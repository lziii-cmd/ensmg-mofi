import io
import json
import uuid
import unicodedata
import re
from functools import wraps

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Sum, Count, Q
from django.http import JsonResponse, FileResponse, HttpResponse, Http404
from django.utils import timezone
import openpyxl

from .models import Certification, Cohorte, Inscrit, Inscription, Paiement, Attestation, CompteApprenant
from .notifications import (
    notifier_inscription, notifier_paiement,
    notifier_paiement_confirme, notifier_attestation, notifier_changement_statut,
)
from .forms import (
    CertificationForm,
    CohorteForm,
    InscritForm,
    InscriptionForm,
    ChangerStatutForm,
    PaiementForm,
    PaiementInscriptionForm,
    ImportExcelForm,
    UserForm,
)


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------

def admin_required(view_func):
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_superuser:
            messages.error(request, "Accès réservé aux administrateurs.")
            return redirect("dashboard")
        return view_func(request, *args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Filter views
# ---------------------------------------------------------------------------

@login_required
def set_filter(request):
    if request.method == "POST":
        certif_ids = [int(x) for x in request.POST.getlist("certif_ids") if x.isdigit()]
        cohorte_ids = [int(x) for x in request.POST.getlist("cohorte_ids") if x.isdigit()]
        request.session["filter_certif_ids"] = certif_ids
        request.session["filter_cohorte_ids"] = cohorte_ids
    next_url = request.POST.get("next", request.GET.get("next", "/"))
    return redirect(next_url)


@login_required
def clear_filter(request):
    request.session.pop("filter_certif_ids", None)
    request.session.pop("filter_cohorte_ids", None)
    next_url = request.GET.get("next", "/")
    return redirect(next_url)


# ---------------------------------------------------------------------------
# AJAX API
# ---------------------------------------------------------------------------

@login_required
def api_cohortes(request):
    certif_ids = request.GET.getlist("certif_id")
    cohortes = []
    if certif_ids:
        qs = Cohorte.objects.filter(
            certification_id__in=certif_ids
        ).select_related("certification").order_by("nom")
        cohortes = [
            {"id": c.pk, "nom": c.nom, "certification": c.certification.nom}
            for c in qs
        ]
    return JsonResponse({"cohortes": cohortes})


@login_required
def api_search_inscrits(request):
    q = request.GET.get("q", "").strip()
    results = []
    if q:
        inscrits = Inscrit.objects.filter(
            Q(nom__icontains=q) | Q(prenom__icontains=q) | Q(email__icontains=q)
        ).order_by("nom", "prenom")[:20]
        results = [
            {"id": i.pk, "text": f"{i.prenom} {i.nom} ({i.email or i.telephone or 'no contact'})"}
            for i in inscrits
        ]
    return JsonResponse({"results": results})


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@login_required
def dashboard(request):
    filter_certif_ids = request.session.get("filter_certif_ids", [])
    filter_cohorte_ids = request.session.get("filter_cohorte_ids", [])

    inscriptions_qs = Inscription.objects.all()
    paiements_qs = Paiement.objects.all()

    if filter_cohorte_ids:
        inscriptions_qs = inscriptions_qs.filter(cohorte_id__in=filter_cohorte_ids)
        paiements_qs = paiements_qs.filter(inscription__cohorte_id__in=filter_cohorte_ids)
    elif filter_certif_ids:
        inscriptions_qs = inscriptions_qs.filter(cohorte__certification_id__in=filter_certif_ids)
        paiements_qs = paiements_qs.filter(inscription__cohorte__certification_id__in=filter_certif_ids)

    nb_inscrits = inscriptions_qs.values("inscrit").distinct().count()
    nb_certifies = inscriptions_qs.filter(statut="certifie").count()
    total_encaisse = paiements_qs.aggregate(total=Sum("montant"))["total"] or 0
    total_inscriptions = inscriptions_qs.count()
    taux_certification = 0
    if total_inscriptions > 0:
        taux_certification = int((nb_certifies / total_inscriptions) * 100)

    # Stats per certification
    certifications = Certification.objects.prefetch_related(
        "cohortes__inscriptions__paiements"
    ).order_by("-created_at")

    if filter_certif_ids:
        certifications = certifications.filter(pk__in=filter_certif_ids)

    stats_certifications = []
    for cert in certifications:
        cert_inscriptions = Inscription.objects.filter(cohorte__certification=cert)
        if filter_cohorte_ids:
            cert_inscriptions = cert_inscriptions.filter(cohorte_id__in=filter_cohorte_ids)
        nb_cert_inscrits = cert_inscriptions.count()
        nb_cert_certifies = cert_inscriptions.filter(statut="certifie").count()
        taux = 0
        if nb_cert_inscrits > 0:
            taux = int((nb_cert_certifies / nb_cert_inscrits) * 100)
        montant = Paiement.objects.filter(inscription__in=cert_inscriptions).aggregate(
            total=Sum("montant")
        )["total"] or 0
        stats_certifications.append({
            "certification": cert,
            "nb_inscrits": nb_cert_inscrits,
            "nb_certifies": nb_cert_certifies,
            "nb_cohortes": cert.cohortes.count(),
            "taux": taux,
            "montant_encaisse": montant,
        })

    # Recent payments
    paiements_recents = (
        paiements_qs
        .select_related("inscription__inscrit", "inscription__cohorte__certification")
        .order_by("-date_paiement", "-created_at")[:8]
    )

    context = {
        "nb_inscrits": nb_inscrits,
        "nb_certifies": nb_certifies,
        "total_encaisse": total_encaisse,
        "taux_certification": taux_certification,
        "stats_certifications": stats_certifications,
        "paiements_recents": paiements_recents,
        "filter_certif_ids": filter_certif_ids,
        "filter_cohorte_ids": filter_cohorte_ids,
        "active_page": "dashboard",
    }
    return render(request, "inscriptions/dashboard.html", context)


# ---------------------------------------------------------------------------
# Certifications
# ---------------------------------------------------------------------------

@login_required
def certifications_list(request):
    query = request.GET.get("q", "")
    certifications = Certification.objects.prefetch_related(
        "cohortes__inscriptions__paiements"
    )

    if query:
        certifications = certifications.filter(
            Q(nom__icontains=query) | Q(description__icontains=query)
        )

    certifications = certifications.order_by("-created_at")

    context = {
        "certifications": certifications,
        "query": query,
        "active_page": "certifications",
        "nb_certifications": Certification.objects.count(),
    }
    return render(request, "inscriptions/certifications_list.html", context)


@login_required
def certification_detail(request, pk):
    certification = get_object_or_404(Certification, pk=pk)
    cohortes = (
        certification.cohortes
        .prefetch_related("inscriptions__paiements", "inscriptions__inscrit")
        .order_by("nom")
    )

    context = {
        "certification": certification,
        "cohortes": cohortes,
        "active_page": "certifications",
    }
    return render(request, "inscriptions/certification_detail.html", context)


@login_required
def certification_ajouter(request):
    if request.method == "POST":
        form = CertificationForm(request.POST)
        if form.is_valid():
            certification = form.save()
            messages.success(request, f'Certification "{certification.nom}" créée avec succès.')
            return redirect("certification_detail", pk=certification.pk)
    else:
        form = CertificationForm()

    context = {
        "form": form,
        "titre": "Ajouter une certification",
        "action": "Créer",
        "active_page": "certifications",
    }
    return render(request, "inscriptions/certification_form.html", context)


@login_required
def certification_modifier(request, pk):
    certification = get_object_or_404(Certification, pk=pk)
    if request.method == "POST":
        form = CertificationForm(request.POST, instance=certification)
        if form.is_valid():
            form.save()
            messages.success(request, f'Certification "{certification.nom}" modifiée.')
            return redirect("certification_detail", pk=certification.pk)
    else:
        form = CertificationForm(instance=certification)

    context = {
        "form": form,
        "certification": certification,
        "titre": f"Modifier : {certification.nom}",
        "action": "Enregistrer",
        "active_page": "certifications",
    }
    return render(request, "inscriptions/certification_form.html", context)


@login_required
def certification_supprimer(request, pk):
    certification = get_object_or_404(Certification, pk=pk)
    if request.method == "POST":
        nom = certification.nom
        certification.delete()
        messages.success(request, f'Certification "{nom}" supprimée.')
        return redirect("certifications_list")

    context = {
        "certification": certification,
        "active_page": "certifications",
    }
    return render(request, "inscriptions/certification_confirm_delete.html", context)


# ---------------------------------------------------------------------------
# Cohortes
# ---------------------------------------------------------------------------

@login_required
def cohorte_ajouter(request, certif_pk):
    certification = get_object_or_404(Certification, pk=certif_pk)
    if request.method == "POST":
        form = CohorteForm(request.POST)
        if form.is_valid():
            cohorte = form.save(commit=False)
            cohorte.certification = certification
            cohorte.save()
            messages.success(request, f'Cohorte "{cohorte.nom}" créée avec succès.')
            return redirect("cohorte_detail", pk=cohorte.pk)
    else:
        form = CohorteForm()

    context = {
        "form": form,
        "certification": certification,
        "titre": f"Ajouter une cohorte — {certification.nom}",
        "action": "Créer",
        "active_page": "certifications",
    }
    return render(request, "inscriptions/cohorte_form.html", context)


@login_required
def cohorte_modifier(request, pk):
    cohorte = get_object_or_404(Cohorte, pk=pk)
    if request.method == "POST":
        form = CohorteForm(request.POST, instance=cohorte)
        if form.is_valid():
            form.save()
            messages.success(request, f'Cohorte "{cohorte.nom}" modifiée.')
            return redirect("cohorte_detail", pk=cohorte.pk)
    else:
        form = CohorteForm(instance=cohorte)

    context = {
        "form": form,
        "cohorte": cohorte,
        "certification": cohorte.certification,
        "titre": f"Modifier : {cohorte.nom}",
        "action": "Enregistrer",
        "active_page": "certifications",
    }
    return render(request, "inscriptions/cohorte_form.html", context)


@login_required
def cohorte_supprimer(request, pk):
    cohorte = get_object_or_404(Cohorte, pk=pk)
    certif_pk = cohorte.certification.pk
    if request.method == "POST":
        nom = cohorte.nom
        cohorte.delete()
        messages.success(request, f'Cohorte "{nom}" supprimée.')
        return redirect("certification_detail", pk=certif_pk)

    context = {
        "cohorte": cohorte,
        "active_page": "certifications",
    }
    return render(request, "inscriptions/cohorte_confirm_delete.html", context)


@login_required
def cohorte_detail(request, pk):
    cohorte = get_object_or_404(Cohorte, pk=pk)
    inscriptions = (
        cohorte.inscriptions
        .select_related("inscrit")
        .prefetch_related("paiements")
        .order_by("-date_inscription")
    )
    statut_forms = {insc.pk: ChangerStatutForm(instance=insc) for insc in inscriptions}

    context = {
        "cohorte": cohorte,
        "inscriptions": inscriptions,
        "statut_forms": statut_forms,
        "active_page": "certifications",
    }
    return render(request, "inscriptions/cohorte_detail.html", context)


# ---------------------------------------------------------------------------
# Inscrits
# ---------------------------------------------------------------------------

@login_required
def inscrits_list(request):
    query = request.GET.get("q", "")
    activite_filter = request.GET.get("activite", "")
    certification_filter = request.GET.get("certification", "")
    statut_filter = request.GET.get("statut", "")

    inscrits = Inscrit.objects.prefetch_related(
        "inscriptions__cohorte__certification", "inscriptions__paiements"
    ).order_by("-date_inscription")

    if query:
        inscrits = inscrits.filter(
            Q(nom__icontains=query)
            | Q(prenom__icontains=query)
            | Q(email__icontains=query)
            | Q(telephone__icontains=query)
        )

    if activite_filter:
        inscrits = inscrits.filter(activite=activite_filter)

    if certification_filter:
        inscrits = inscrits.filter(
            inscriptions__cohorte__certification__pk=certification_filter
        ).distinct()

    if statut_filter:
        inscrits = inscrits.filter(
            inscriptions__statut=statut_filter
        ).distinct()

    # Apply session filters
    filter_certif_ids = request.session.get("filter_certif_ids", [])
    filter_cohorte_ids = request.session.get("filter_cohorte_ids", [])
    if filter_cohorte_ids:
        inscrits = inscrits.filter(
            inscriptions__cohorte_id__in=filter_cohorte_ids
        ).distinct()
    elif filter_certif_ids:
        inscrits = inscrits.filter(
            inscriptions__cohorte__certification_id__in=filter_certif_ids
        ).distinct()

    certifications_all = Certification.objects.order_by("nom")

    context = {
        "inscrits": inscrits,
        "query": query,
        "activite_filter": activite_filter,
        "certification_filter": certification_filter,
        "statut_filter": statut_filter,
        "certifications_all": certifications_all,
        "statut_choices": Inscription.STATUT_CHOICES,
        "activite_choices": Inscrit.ACTIVITE_CHOICES,
        "active_page": "inscrits",
        "nb_inscrits": Inscrit.objects.count(),
    }
    return render(request, "inscriptions/inscrits_list.html", context)


@login_required
def inscrit_detail(request, pk):
    inscrit = get_object_or_404(Inscrit, pk=pk)
    inscriptions = (
        inscrit.inscriptions
        .select_related("cohorte__certification")
        .prefetch_related("paiements")
        .order_by("-date_inscription")
    )

    statut_forms = {insc.pk: ChangerStatutForm(instance=insc) for insc in inscriptions}
    paiement_forms = {insc.pk: PaiementInscriptionForm(initial={"date_paiement": timezone.now().date()}) for insc in inscriptions}

    context = {
        "inscrit": inscrit,
        "inscriptions": inscriptions,
        "statut_forms": statut_forms,
        "paiement_forms": paiement_forms,
        "active_page": "inscrits",
    }
    return render(request, "inscriptions/inscrit_detail.html", context)


@login_required
def inscrit_ajouter(request):
    if request.method == "POST":
        form = InscritForm(request.POST)
        if form.is_valid():
            inscrit = form.save(commit=False)
            inscrit.source = "manuel"
            inscrit.save()
            messages.success(request, f'Inscrit "{inscrit}" ajouté avec succès.')
            return redirect("inscrit_detail", pk=inscrit.pk)
    else:
        form = InscritForm()

    context = {
        "form": form,
        "titre": "Ajouter un inscrit",
        "action": "Ajouter",
        "active_page": "inscrits",
    }
    return render(request, "inscriptions/inscrit_form.html", context)


@login_required
def inscrit_modifier(request, pk):
    inscrit = get_object_or_404(Inscrit, pk=pk)
    if request.method == "POST":
        form = InscritForm(request.POST, instance=inscrit)
        if form.is_valid():
            form.save()
            messages.success(request, f'Inscrit "{inscrit}" modifié avec succès.')
            return redirect("inscrit_detail", pk=inscrit.pk)
    else:
        form = InscritForm(instance=inscrit)

    context = {
        "form": form,
        "inscrit": inscrit,
        "titre": f"Modifier : {inscrit}",
        "action": "Enregistrer",
        "active_page": "inscrits",
    }
    return render(request, "inscriptions/inscrit_form.html", context)


@login_required
def inscrit_supprimer(request, pk):
    inscrit = get_object_or_404(Inscrit, pk=pk)
    if request.method == "POST":
        nom = str(inscrit)
        inscrit.delete()
        messages.success(request, f'Inscrit "{nom}" supprimé avec succès.')
        return redirect("inscrits_list")

    context = {
        "inscrit": inscrit,
        "active_page": "inscrits",
    }
    return render(request, "inscriptions/inscrit_confirm_delete.html", context)


# ---------------------------------------------------------------------------
# Inscription Wizard
# ---------------------------------------------------------------------------

@login_required
def inscription_wizard(request):
    """
    3-step wizard:
    Step 1: certification → cohorte (AJAX)
    Step 2: find or create inscrit
    Step 3: confirmation with auto-calculated tarif
    """
    certifications = Certification.objects.filter(actif=True).order_by("nom")

    # Build certif_tarifs JSON for JS
    certif_tarifs = {}
    for c in certifications:
        certif_tarifs[c.pk] = {
            "etudiant": float(c.tarif_etudiant),
            "professionnel": float(c.tarif_professionnel),
            "nom": c.nom,
        }

    if request.method == "POST":
        cohorte_id = request.POST.get("cohorte_id")
        inscrit_id = request.POST.get("inscrit_id")
        statut = request.POST.get("statut", "inscrit")
        notes = request.POST.get("notes", "")
        montant_du = request.POST.get("montant_du", "0")

        # Validate cohorte
        cohorte = None
        if cohorte_id:
            try:
                cohorte = Cohorte.objects.select_related("certification").get(pk=cohorte_id)
            except Cohorte.DoesNotExist:
                messages.error(request, "Cohorte invalide.")
                return render(request, "inscriptions/inscription_wizard.html", {
                    "certifications": certifications,
                    "certif_tarifs_json": json.dumps(certif_tarifs),
                    "statut_choices": Inscription.STATUT_CHOICES,
                    "active_page": "inscrits",
                })

        if not cohorte:
            messages.error(request, "Veuillez sélectionner une cohorte.")
            return render(request, "inscriptions/inscription_wizard.html", {
                "certifications": certifications,
                "certif_tarifs_json": json.dumps(certif_tarifs),
                "statut_choices": Inscription.STATUT_CHOICES,
                "active_page": "inscrits",
            })

        # Get or create inscrit
        inscrit = None
        if inscrit_id:
            try:
                inscrit = Inscrit.objects.get(pk=inscrit_id)
            except Inscrit.DoesNotExist:
                messages.error(request, "Participant introuvable.")

        if not inscrit:
            # Create new inscrit
            nom = request.POST.get("nom", "").strip()
            prenom = request.POST.get("prenom", "").strip()
            email = request.POST.get("email", "").strip().lower()
            telephone = request.POST.get("telephone", "").strip()
            activite = request.POST.get("activite", "etudiant")

            if not nom or not prenom:
                messages.error(request, "Nom et prénom requis pour créer un participant.")
                return render(request, "inscriptions/inscription_wizard.html", {
                    "certifications": certifications,
                    "certif_tarifs_json": json.dumps(certif_tarifs),
                    "statut_choices": Inscription.STATUT_CHOICES,
                    "active_page": "inscrits",
                })

            if email:
                inscrit, _ = Inscrit.objects.update_or_create(
                    email=email,
                    defaults={"nom": nom, "prenom": prenom, "telephone": telephone, "activite": activite, "source": "manuel"},
                )
            else:
                inscrit = Inscrit.objects.create(
                    nom=nom, prenom=prenom, email=email,
                    telephone=telephone, activite=activite, source="manuel",
                )

        # Check not already enrolled
        if Inscription.objects.filter(inscrit=inscrit, cohorte=cohorte).exists():
            messages.warning(request, f'"{inscrit}" est déjà inscrit à la cohorte "{cohorte.nom}".')
            return redirect("inscrit_detail", pk=inscrit.pk)

        # Compute montant_du if not provided
        try:
            montant_du_val = float(montant_du) if montant_du else 0
        except (ValueError, TypeError):
            montant_du_val = 0

        if montant_du_val == 0:
            cert = cohorte.certification
            if inscrit.activite == "professionnel":
                montant_du_val = float(cert.tarif_professionnel)
            else:
                montant_du_val = float(cert.tarif_etudiant)

        inscription = Inscription.objects.create(
            inscrit=inscrit,
            cohorte=cohorte,
            statut=statut,
            montant_du=montant_du_val,
            notes=notes,
        )
        notifier_inscription(inscription)
        messages.success(
            request,
            f'"{inscrit}" inscrit à la cohorte "{cohorte.nom}" ({cohorte.certification.nom}).',
        )
        return redirect("inscrit_detail", pk=inscrit.pk)

    context = {
        "certifications": certifications,
        "certif_tarifs_json": json.dumps(certif_tarifs),
        "statut_choices": Inscription.STATUT_CHOICES,
        "activite_choices": Inscrit.ACTIVITE_CHOICES,
        "active_page": "inscrits",
    }
    return render(request, "inscriptions/inscription_wizard.html", context)


# ---------------------------------------------------------------------------
# Inscription actions
# ---------------------------------------------------------------------------

@login_required
def changer_statut(request, pk):
    inscription = get_object_or_404(Inscription, pk=pk)
    next_url = request.POST.get("next") or request.GET.get("next", "")

    if request.method == "POST":
        form = ChangerStatutForm(request.POST, instance=inscription)
        if form.is_valid():
            form.save()
            notifier_changement_statut(inscription)
            messages.success(
                request,
                f'Statut mis à jour : {inscription.get_statut_display()}.',
            )
    if next_url:
        return redirect(next_url)
    return redirect("inscrit_detail", pk=inscription.inscrit.pk)


@login_required
def inscription_supprimer(request, pk):
    inscription = get_object_or_404(Inscription, pk=pk)
    inscrit_pk = inscription.inscrit.pk

    if request.method == "POST":
        cohorte_nom = inscription.cohorte.nom
        inscription.delete()
        messages.success(request, f'Inscription à la cohorte "{cohorte_nom}" supprimée.')
        return redirect("inscrit_detail", pk=inscrit_pk)

    context = {
        "inscription": inscription,
        "active_page": "inscrits",
    }
    return render(request, "inscriptions/inscription_confirm_delete.html", context)


@login_required
def paiement_ajouter_pour_inscription(request, pk):
    inscription = get_object_or_404(Inscription, pk=pk)

    if request.method == "POST":
        form = PaiementInscriptionForm(request.POST)
        if form.is_valid():
            paiement = form.save(commit=False)
            paiement.inscription = inscription
            reste = inscription.reste_a_payer
            if reste <= 0:
                messages.warning(request, "Ce dossier est déjà intégralement réglé.")
            elif paiement.montant > reste:
                messages.error(
                    request,
                    f"Le montant saisi ({paiement.montant} FCFA) dépasse le reste à payer ({reste} FCFA). Veuillez corriger."
                )
            else:
                paiement.save()
                notifier_paiement(paiement)
                messages.success(request, f'Paiement de {paiement.montant} FCFA enregistré.')
        else:
            messages.error(request, "Erreur dans le formulaire de paiement.")
    return redirect("inscrit_detail", pk=inscription.inscrit.pk)


# ---------------------------------------------------------------------------
# Paiements
# ---------------------------------------------------------------------------

@login_required
def paiements_list(request):
    query = request.GET.get("q", "")
    moyen_filter = request.GET.get("moyen", "")

    paiements = Paiement.objects.select_related(
        "inscription__inscrit", "inscription__cohorte__certification"
    ).order_by("-date_paiement", "-created_at")

    if query:
        paiements = paiements.filter(
            Q(inscription__inscrit__nom__icontains=query)
            | Q(inscription__inscrit__prenom__icontains=query)
            | Q(inscription__inscrit__email__icontains=query)
            | Q(inscription__cohorte__certification__nom__icontains=query)
            | Q(inscription__cohorte__nom__icontains=query)
            | Q(reference__icontains=query)
        )

    if moyen_filter:
        paiements = paiements.filter(moyen_paiement=moyen_filter)

    # Apply session filters
    filter_certif_ids = request.session.get("filter_certif_ids", [])
    filter_cohorte_ids = request.session.get("filter_cohorte_ids", [])
    if filter_cohorte_ids:
        paiements = paiements.filter(inscription__cohorte_id__in=filter_cohorte_ids)
    elif filter_certif_ids:
        paiements = paiements.filter(inscription__cohorte__certification_id__in=filter_certif_ids)

    total_filtre = paiements.aggregate(total=Sum("montant"))["total"] or 0

    context = {
        "paiements": paiements,
        "query": query,
        "moyen_filter": moyen_filter,
        "moyen_choices": Paiement.MOYEN_CHOICES,
        "total_filtre": total_filtre,
        "active_page": "paiements",
    }
    return render(request, "inscriptions/paiements_list.html", context)


@login_required
def paiement_ajouter(request):
    if request.method == "POST":
        form = PaiementForm(request.POST)
        if form.is_valid():
            paiement = form.save()
            notifier_paiement(paiement)
            messages.success(request, f"Paiement de {paiement.montant} FCFA enregistré.")
            return redirect("inscrit_detail", pk=paiement.inscription.inscrit.pk)
    else:
        form = PaiementForm(initial={"date_paiement": timezone.now().date()})

    context = {
        "form": form,
        "titre": "Ajouter un paiement",
        "action": "Enregistrer",
        "active_page": "paiements",
    }
    return render(request, "inscriptions/paiement_form.html", context)


@login_required
def paiement_modifier(request, pk):
    paiement = get_object_or_404(Paiement, pk=pk)
    if request.method == "POST":
        form = PaiementForm(request.POST, instance=paiement)
        if form.is_valid():
            form.save()
            messages.success(request, "Paiement modifié avec succès.")
            return redirect("inscrit_detail", pk=paiement.inscription.inscrit.pk)
    else:
        form = PaiementForm(instance=paiement)

    context = {
        "form": form,
        "paiement": paiement,
        "titre": "Modifier le paiement",
        "action": "Enregistrer",
        "active_page": "paiements",
    }
    return render(request, "inscriptions/paiement_form.html", context)


@login_required
def paiement_supprimer(request, pk):
    paiement = get_object_or_404(Paiement, pk=pk)
    inscrit_pk = paiement.inscription.inscrit.pk
    if request.method == "POST":
        montant = paiement.montant
        paiement.delete()
        messages.success(request, f"Paiement de {montant} FCFA supprimé.")
        return redirect("inscrit_detail", pk=inscrit_pk)

    context = {
        "paiement": paiement,
        "active_page": "paiements",
    }
    return render(request, "inscriptions/paiement_confirm_delete.html", context)


# ---------------------------------------------------------------------------
# Import Excel
# ---------------------------------------------------------------------------

COLUMN_ALIASES = {
    "nom": ["nom", "name", "last_name", "lastname", "family_name"],
    "prenom": ["prenom", "prénom", "first_name", "firstname", "given_name"],
    "email": ["email", "e-mail", "mail", "courriel", "adresse_email"],
    "telephone": ["telephone", "téléphone", "tel", "phone", "mobile", "portable"],
    "activite": ["activite", "activité", "formation", "profil"],
}


def _normalize_header(header):
    if header is None:
        return ""
    return str(header).lower().strip().replace(" ", "_").replace("-", "_")


def _map_columns(headers):
    mapping = {}
    normalized = [_normalize_header(h) for h in headers]
    for field, aliases in COLUMN_ALIASES.items():
        for i, norm in enumerate(normalized):
            if norm in aliases:
                mapping[field] = i
                break
    return mapping


@login_required
def import_excel(request):
    if request.method == "POST":
        form = ImportExcelForm(request.POST, request.FILES)
        if form.is_valid():
            fichier = request.FILES["fichier"]
            cohorte = form.cleaned_data.get("cohorte")  # None si pas sélectionné

            try:
                wb = openpyxl.load_workbook(fichier, read_only=True, data_only=True)
                ws = wb.active
                rows = list(ws.iter_rows(values_only=True))

                if not rows:
                    messages.error(request, "Le fichier est vide.")
                    return render(request, "inscriptions/import_excel.html", {
                        "form": form, "active_page": "inscrits",
                        "certifications": Certification.objects.filter(actif=True).order_by("nom"),
                    })

                headers = rows[0]
                col_map = _map_columns(headers)

                required = ["nom", "prenom"]
                missing = [f for f in required if f not in col_map]
                if missing:
                    messages.error(
                        request,
                        f'Colonnes obligatoires manquantes : {", ".join(missing)}. '
                        f'Colonnes trouvées : {", ".join(str(h) for h in headers if h)}',
                    )
                    return render(request, "inscriptions/import_excel.html", {
                        "form": form, "active_page": "inscrits",
                        "certifications": Certification.objects.filter(actif=True).order_by("nom"),
                    })

                created = 0
                updated = 0
                enrolled = 0
                errors = []

                for row_idx, row in enumerate(rows[1:], start=2):
                    try:
                        nom = str(row[col_map["nom"]] or "").strip()
                        prenom = str(row[col_map["prenom"]] or "").strip()

                        if not nom or not prenom:
                            errors.append(f"Ligne {row_idx}: nom ou prénom manquant.")
                            continue

                        email = ""
                        if "email" in col_map and row[col_map["email"]]:
                            email = str(row[col_map["email"]]).strip().lower()

                        telephone = ""
                        if "telephone" in col_map and row[col_map["telephone"]]:
                            telephone = str(row[col_map["telephone"]]).strip()

                        activite_val = "etudiant"
                        if "activite" in col_map and row[col_map["activite"]]:
                            raw = str(row[col_map["activite"]]).strip().lower()
                            if "prof" in raw:
                                activite_val = "professionnel"

                        if email:
                            inscrit, was_created = Inscrit.objects.update_or_create(
                                email=email,
                                defaults={
                                    "nom": nom,
                                    "prenom": prenom,
                                    "telephone": telephone,
                                    "activite": activite_val,
                                    "source": "excel",
                                },
                            )
                        else:
                            inscrit = Inscrit.objects.create(
                                nom=nom,
                                prenom=prenom,
                                telephone=telephone,
                                activite=activite_val,
                                source="excel",
                            )
                            was_created = True

                        if was_created:
                            created += 1
                        else:
                            updated += 1

                        # Inscription à la cohorte uniquement si sélectionnée
                        if cohorte:
                            cert = cohorte.certification
                            montant_du = float(
                                cert.tarif_professionnel if activite_val == "professionnel"
                                else cert.tarif_etudiant
                            )
                            _, ic_created = Inscription.objects.get_or_create(
                                inscrit=inscrit,
                                cohorte=cohorte,
                                defaults={"statut": "inscrit", "montant_du": montant_du},
                            )
                            if ic_created:
                                enrolled += 1

                    except Exception as exc:
                        errors.append(f"Ligne {row_idx}: erreur — {exc}")

                wb.close()

                if created or updated:
                    msg = f"Import terminé : {created} inscrit(s) créé(s), {updated} mis à jour"
                    if cohorte:
                        msg += f", {enrolled} nouvelle(s) inscription(s) à « {cohorte} »."
                    else:
                        msg += "."
                    messages.success(request, msg)
                for err in errors[:10]:
                    messages.warning(request, err)
                if len(errors) > 10:
                    messages.warning(request, f"... et {len(errors) - 10} autres erreurs.")

                return redirect("inscrits_list")

            except Exception as exc:
                messages.error(request, f"Erreur lors de la lecture du fichier : {exc}")
    else:
        form = ImportExcelForm()

    context = {
        "form": form,
        "active_page": "inscrits",
        "certifications": Certification.objects.filter(actif=True).order_by("nom"),
    }
    return render(request, "inscriptions/import_excel.html", context)


# ---------------------------------------------------------------------------
# Users (admin only)
# ---------------------------------------------------------------------------

@admin_required
def users_list(request):
    users = User.objects.prefetch_related("groups").order_by("username")
    context = {
        "users": users,
        "active_page": "utilisateurs",
    }
    return render(request, "inscriptions/users_list.html", context)


@admin_required
def user_ajouter(request):
    if request.method == "POST":
        form = UserForm(request.POST)
        if form.is_valid():
            if not form.cleaned_data.get("password"):
                messages.error(request, "Un mot de passe est requis pour créer un utilisateur.")
                return render(request, "inscriptions/user_form.html", {
                    "form": form, "titre": "Ajouter un utilisateur", "action": "Créer",
                    "active_page": "utilisateurs",
                })
            user = form.save()
            messages.success(request, f'Utilisateur "{user.username}" créé.')
            return redirect("users_list")
    else:
        form = UserForm()

    context = {
        "form": form,
        "titre": "Ajouter un utilisateur",
        "action": "Créer",
        "active_page": "utilisateurs",
    }
    return render(request, "inscriptions/user_form.html", context)


@admin_required
def user_modifier(request, pk):
    user = get_object_or_404(User, pk=pk)
    if request.method == "POST":
        form = UserForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, f'Utilisateur "{user.username}" modifié.')
            return redirect("users_list")
    else:
        form = UserForm(instance=user)

    context = {
        "form": form,
        "edit_user": user,
        "titre": f"Modifier : {user.username}",
        "action": "Enregistrer",
        "active_page": "utilisateurs",
    }
    return render(request, "inscriptions/user_form.html", context)


@admin_required
def user_toggle(request, pk):
    user = get_object_or_404(User, pk=pk)
    if user == request.user:
        messages.error(request, "Vous ne pouvez pas désactiver votre propre compte.")
    else:
        user.is_active = not user.is_active
        user.save()
        status = "activé" if user.is_active else "désactivé"
        messages.success(request, f'Utilisateur "{user.username}" {status}.')
    return redirect("users_list")


# ---------------------------------------------------------------------------
# Certifier — génération d'attestations PDF
# ---------------------------------------------------------------------------

def _generer_qr_image(url):
    """Génère un QR code en mémoire et renvoie un objet reportlab Image."""
    import qrcode
    from reportlab.platypus import Image as RLImage

    qr = qrcode.QRCode(version=2, box_size=4, border=2,
                       error_correction=qrcode.constants.ERROR_CORRECT_H)
    qr.add_data(url)
    qr.make(fit=True)
    pil_img = qr.make_image(fill_color="#1a2340", back_color="white")
    buf = io.BytesIO()
    pil_img.save(buf, format="PNG")
    buf.seek(0)
    return RLImage(buf, width=2.8 * 28.35, height=2.8 * 28.35)   # ~2.8 cm


def _generer_attestation_pdf(inscription, verification_url=""):
    """Génère le PDF d'attestation (certificat formel) et retourne les bytes."""
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import cm, mm
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.utils import ImageReader

    inscrit       = inscription.inscrit
    certification = inscription.cohorte.certification
    cohorte       = inscription.cohorte
    today         = timezone.now().date()

    date_fin_str = cohorte.date_fin.strftime("%d/%m/%Y") if cohorte.date_fin else today.strftime("%d/%m/%Y")

    buffer = io.BytesIO()
    # Paysage A4
    W, H = landscape(A4)  # ~841 x 595 pts

    c = rl_canvas.Canvas(buffer, pagesize=landscape(A4))

    # ── Couleurs ──────────────────────────────────────────────────────────────
    BLACK  = colors.HexColor("#0a0a0a")
    NAVY   = colors.HexColor("#1a2340")
    GOLD   = colors.HexColor("#c9a84c")
    GOLD2  = colors.HexColor("#e8c96a")
    WHITE  = colors.white
    GREY   = colors.HexColor("#555555")
    LGREY  = colors.HexColor("#888888")

    # ── Fond ivoire ───────────────────────────────────────────────────────────
    c.setFillColor(colors.HexColor("#fdfbf5"))
    c.rect(0, 0, W, H, fill=1, stroke=0)

    # ── Bordure extérieure noire épaisse ──────────────────────────────────────
    margin = 18
    c.setStrokeColor(BLACK)
    c.setLineWidth(6)
    c.rect(margin, margin, W - 2*margin, H - 2*margin, fill=0, stroke=1)

    # ── Bordure or fine intérieure ─────────────────────────────────────────────
    gap = 10
    inner = margin + gap
    c.setStrokeColor(GOLD)
    c.setLineWidth(1.5)
    c.rect(inner, inner, W - 2*inner, H - 2*inner, fill=0, stroke=1)

    # ── Coins décoratifs (triangles noirs) ────────────────────────────────────
    cs = 38  # coin size
    for (cx, cy, dx, dy) in [
        (margin, H - margin, 1, -1),   # top-left
        (W - margin, H - margin, -1, -1),  # top-right
        (margin, margin, 1, 1),         # bottom-left
        (W - margin, margin, -1, 1),    # bottom-right
    ]:
        c.setFillColor(BLACK)
        p = c.beginPath()
        p.moveTo(cx, cy)
        p.lineTo(cx + dx * cs, cy)
        p.lineTo(cx, cy + dy * cs)
        p.close()
        c.drawPath(p, fill=1, stroke=0)

    # ── Ligne or décorative sous le header ────────────────────────────────────
    def gold_line(y, x0=None, x1=None, w=1.5):
        x0 = x0 or inner + 10
        x1 = x1 or W - inner - 10
        c.setStrokeColor(GOLD)
        c.setLineWidth(w)
        c.line(x0, y, x1, y)

    # ── En-tête établissement ─────────────────────────────────────────────────
    top_y = H - inner - 18

    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(W / 2, top_y, "ÉCOLE NATIONALE SUPÉRIEURE DE MANAGEMENT ET DE GOUVERNANCE")

    c.setFont("Helvetica", 8.5)
    c.setFillColor(LGREY)
    c.drawCentredString(W / 2, top_y - 14, "ENSMG  ·  Dakar, Sénégal")

    gold_line(top_y - 22, w=2.5)
    gold_line(top_y - 26, w=0.8)

    # ── Médaillon central (cercle doré) ───────────────────────────────────────
    med_x = W / 2
    med_y = H / 2 + 28
    med_r = 36

    c.setFillColor(GOLD)
    c.setStrokeColor(GOLD2)
    c.setLineWidth(2)
    c.circle(med_x, med_y + 68, med_r, fill=1, stroke=1)

    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 22)
    c.drawCentredString(med_x, med_y + 68 - 8, "★")

    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 7.5)
    c.drawCentredString(med_x, med_y + 68 - 20, "ENSMG")

    # ── Titre principal ───────────────────────────────────────────────────────
    title_y = top_y - 60

    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 32)
    c.drawCentredString(W / 2, title_y, "CERTIFICAT DE PARTICIPATION")

    # Ligne décorative sous le titre
    gold_line(title_y - 10, x0=W/2 - 130, x1=W/2 + 130, w=1)

    # ── Sous-titre ────────────────────────────────────────────────────────────
    c.setFillColor(GOLD)
    c.setFont("Helvetica-BoldOblique", 11)
    c.drawCentredString(W / 2, title_y - 26, "ÉCOLE NATIONALE SUPÉRIEURE DE MANAGEMENT ET DE GOUVERNANCE")

    # ── Corps du certificat ───────────────────────────────────────────────────
    body_y = title_y - 56

    c.setFillColor(GREY)
    c.setFont("Helvetica", 11)
    c.drawCentredString(W / 2, body_y, "NOUS CERTIFIONS QUE :")

    # Nom du bénéficiaire (grand, doré)
    body_y -= 30
    c.setFillColor(GOLD)
    c.setFont("Helvetica-Bold", 28)
    c.drawCentredString(W / 2, body_y, inscrit.nom_complet.upper())

    # Soulignement doré sous le nom
    nom_w = c.stringWidth(inscrit.nom_complet.upper(), "Helvetica-Bold", 28)
    line_x0 = W / 2 - nom_w / 2
    line_x1 = W / 2 + nom_w / 2
    gold_line(body_y - 4, x0=line_x0, x1=line_x1, w=1)

    # Texte intermédiaire
    body_y -= 22
    activite_lbl = "Étudiant(e)" if inscrit.activite == "etudiant" else "Professionnel(le)"
    c.setFillColor(GREY)
    c.setFont("Helvetica", 10)
    c.drawCentredString(W / 2, body_y, activite_lbl)

    body_y -= 20
    c.setFont("Helvetica", 11)
    c.setFillColor(NAVY)
    c.drawCentredString(W / 2, body_y, "a suivi avec succès la formation :")

    # Nom de la certification
    body_y -= 22
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 15)
    c.drawCentredString(W / 2, body_y, certification.nom)

    # Cohorte / période
    body_y -= 18
    c.setFillColor(LGREY)
    c.setFont("Helvetica", 9)
    session_txt = f"Session : {cohorte.nom}"
    if cohorte.date_debut:
        session_txt += f"  ·  Du {cohorte.date_debut.strftime('%d/%m/%Y')} au {date_fin_str}"
    c.drawCentredString(W / 2, body_y, session_txt)

    # ── Ligne séparatrice ─────────────────────────────────────────────────────
    gold_line(body_y - 18, w=1.5)

    # ── Zone basse : date + signature + QR ────────────────────────────────────
    footer_y = body_y - 40

    # Date et lieu (gauche)
    sig_x = inner + 50
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(sig_x, footer_y + 8, "Fait à Dakar, le")
    c.setFont("Helvetica-Bold", 10)
    c.drawString(sig_x, footer_y - 6, today.strftime("%d/%m/%Y"))

    # Signature (centre)
    sig_cx = W / 2
    c.setFillColor(LGREY)
    c.setFont("Helvetica", 8)
    c.drawCentredString(sig_cx, footer_y + 8, "Signature & Cachet")
    c.setStrokeColor(LGREY)
    c.setLineWidth(0.6)
    c.line(sig_cx - 60, footer_y - 2, sig_cx + 60, footer_y - 2)
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(sig_cx, footer_y - 14, "Le Directeur Général")
    c.setFont("Helvetica", 8)
    c.setFillColor(LGREY)
    c.drawCentredString(sig_cx, footer_y - 24, "ENSMG")

    # QR code (droite)
    if verification_url:
        import qrcode as _qrcode
        _qr = _qrcode.QRCode(version=2, box_size=4, border=2,
                              error_correction=_qrcode.constants.ERROR_CORRECT_H)
        _qr.add_data(verification_url)
        _qr.make(fit=True)
        _pil = _qr.make_image(fill_color="#1a2340", back_color="white")
        _qr_buf = io.BytesIO()
        _pil.save(_qr_buf, format="PNG")
        _qr_buf.seek(0)
        qr_x = W - inner - 90
        qr_y = footer_y - 28
        c.drawImage(ImageReader(_qr_buf), qr_x, qr_y, width=56, height=56, preserveAspectRatio=True)
        c.setFillColor(LGREY)
        c.setFont("Helvetica", 6.5)
        c.drawCentredString(qr_x + 28, qr_y - 8, "Vérifier l'authenticité")

    # ── Numéro de certificat ──────────────────────────────────────────────────
    ref = f"CERT-{inscription.pk:06d}"
    c.setFillColor(LGREY)
    c.setFont("Helvetica", 7)
    c.drawCentredString(W / 2, inner + 6, f"Réf. : {ref}")

    c.save()
    return buffer.getvalue()


@login_required
def certifier_home(request):
    certifications = Certification.objects.filter(actif=True).order_by("nom")
    return render(request, "inscriptions/certifier_home.html", {
        "certifications": certifications,
        "active_page": "certifier",
    })


@login_required
def certifier_inscrits(request, pk):
    certification = get_object_or_404(Certification, pk=pk)
    inscriptions = (
        Inscription.objects
        .filter(cohorte__certification=certification)
        .exclude(statut="certifie")
        .select_related("inscrit", "cohorte")
        .order_by("inscrit__nom", "inscrit__prenom")
    )
    certifies = (
        Inscription.objects
        .filter(cohorte__certification=certification, statut="certifie")
        .select_related("inscrit", "cohorte")
        .prefetch_related("attestations")
        .order_by("inscrit__nom", "inscrit__prenom")
    )
    return render(request, "inscriptions/certifier_inscrits.html", {
        "certification": certification,
        "inscriptions": inscriptions,
        "certifies": certifies,
        "active_page": "certifier",
    })


@login_required
def certifier_action(request, pk):
    if request.method != "POST":
        return redirect("certifier_inscrits", pk=pk)

    certification = get_object_or_404(Certification, pk=pk)
    inscription_ids = request.POST.getlist("inscription_ids")

    if not inscription_ids:
        messages.warning(request, "Aucun inscrit sélectionné.")
        return redirect("certifier_inscrits", pk=pk)

    inscriptions_qs = Inscription.objects.filter(
        pk__in=inscription_ids,
        cohorte__certification=certification,
    ).select_related("inscrit", "cohorte", "cohorte__certification")

    nb_ok = 0
    for inscription in inscriptions_qs:
        inscription.statut = "certifie"
        inscription.save()

        numero = f"ATT-{certification.pk:04d}-{inscription.pk:06d}-{uuid.uuid4().hex[:6].upper()}"
        verification_url = request.build_absolute_uri(f"/attestations/{numero}/verifier/")
        pdf_bytes = _generer_attestation_pdf(inscription, verification_url=verification_url)

        att = Attestation.objects.create(
            inscription=inscription,
            numero=numero,
            date_delivrance=timezone.now().date(),
            contenu_pdf=pdf_bytes,
        )
        notifier_attestation(att)
        nb_ok += 1

    messages.success(request, f"{nb_ok} attestation(s) générée(s) avec succès.")
    return redirect("certifier_inscrits", pk=pk)


@login_required
def attestation_download(request, pk):
    """Téléchargement du PDF (force download) — servi depuis la base de données."""
    attestation = get_object_or_404(Attestation, pk=pk)
    if not attestation.contenu_pdf:
        messages.error(request, "PDF non disponible. Veuillez re-certifier cet inscrit pour régénérer l'attestation.")
        return redirect(request.META.get("HTTP_REFERER", "certifier_home"))
    nom = attestation.inscription.inscrit.nom_complet.replace(" ", "_")
    response = HttpResponse(bytes(attestation.contenu_pdf), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="attestation_{nom}_{attestation.numero}.pdf"'
    return response


@login_required
def attestation_view(request, pk):
    """Visualisation inline du PDF dans le navigateur — servi depuis la base de données."""
    attestation = get_object_or_404(Attestation, pk=pk)
    if not attestation.contenu_pdf:
        messages.error(request, "PDF non disponible. Veuillez re-certifier cet inscrit pour régénérer l'attestation.")
        return redirect(request.META.get("HTTP_REFERER", "certifier_home"))
    response = HttpResponse(bytes(attestation.contenu_pdf), content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{attestation.numero}.pdf"'
    return response


def attestation_verifier(request, numero):
    """Page publique de vérification d'authenticité (accessible sans connexion)."""
    try:
        attestation = (
            Attestation.objects
            .select_related("inscription__inscrit", "inscription__cohorte__certification")
            .get(numero=numero)
        )
        valide = True
    except Attestation.DoesNotExist:
        attestation = None
        valide = False
    return render(request, "inscriptions/attestation_verifier.html", {
        "attestation": attestation,
        "numero": numero,
        "valide": valide,
    })


# ---------------------------------------------------------------------------
# Custom login (redirects by user type)
# ---------------------------------------------------------------------------

def custom_login(request):
    """Login page that redirects apprenants to their space and admins to dashboard."""
    from django.contrib.auth import authenticate, login as auth_login
    from django.contrib.auth.views import LoginView

    if request.user.is_authenticated:
        try:
            _ = request.user.compte_apprenant
            return redirect('espace_apprenant')
        except Exception:
            pass
        return redirect('dashboard')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        # Accepter email ou username
        if '@' in username:
            try:
                username = User.objects.get(email__iexact=username).username
            except User.DoesNotExist:
                pass
        user = authenticate(request, username=username, password=password)
        if user is not None:
            if user.is_active:
                auth_login(request, user)
                next_url = request.POST.get('next', request.GET.get('next', ''))
                if next_url:
                    return redirect(next_url)
                try:
                    _ = user.compte_apprenant
                    return redirect('espace_apprenant')
                except Exception:
                    pass
                return redirect('dashboard')
            else:
                messages.error(request, "Ce compte est désactivé.")
        else:
            messages.error(request, "Identifiant ou mot de passe incorrect.")

    return render(request, 'inscriptions/login.html', {
        'next': request.GET.get('next', ''),
    })


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _slugify_name(text):
    """
    Convert a name (possibly compound) to a lowercase ASCII slug without separators.
    'Mamadou Fole' -> 'mamadoufole'   'Ba' -> 'ba'
    """
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    text = text.lower().strip()
    # Supprimer tout ce qui n'est pas lettre/chiffre (espaces inclus → pas de point interne)
    text = re.sub(r'[^a-z0-9]', '', text)
    return text


def _creer_compte_apprenant(inscrit):
    """Create Django User + CompteApprenant for a new portal registrant. Returns (user, compte)."""
    base_username = f"{_slugify_name(inscrit.prenom)}.{_slugify_name(inscrit.nom)}@ensmg.sn"
    username = base_username
    counter = 2
    while User.objects.filter(username=username).exists():
        name_part = base_username.replace('@ensmg.sn', '')
        username = f"{name_part}{counter}@ensmg.sn"
        counter += 1

    user = User.objects.create_user(
        username=username,
        email=username,
        password='passer01',
        first_name=inscrit.prenom,
        last_name=inscrit.nom,
    )
    compte = CompteApprenant.objects.create(user=user, inscrit=inscrit, mdp_change=False)
    return user, compte


# ---------------------------------------------------------------------------
# Portail public
# ---------------------------------------------------------------------------

def portail_accueil(request):
    """Public landing page — redirect to dashboard if admin/staff, to espace if apprenant."""
    if request.user.is_authenticated:
        try:
            _ = request.user.compte_apprenant
            return redirect('espace_apprenant')
        except Exception:
            if request.user.is_staff or request.user.is_superuser:
                return redirect('dashboard')
    certifications = Certification.objects.filter(actif=True).order_by('nom')
    return render(request, 'inscriptions/portail_accueil.html', {
        'certifications': certifications,
    })


def portail_wizard(request):
    """4-step session-based wizard for public registration."""
    step = int(request.GET.get('step', request.POST.get('step', 1)))

    if request.method == 'POST':
        if step == 1:
            from .forms import WizardStep1Form
            form = WizardStep1Form(request.POST)
            if form.is_valid():
                request.session['wizard_step1'] = form.cleaned_data
                return redirect('/portail/inscription/?step=2')
            return render(request, 'inscriptions/portail_wizard.html', {
                'step': 1, 'form': form,
                'certifications': Certification.objects.filter(actif=True).order_by('nom'),
            })

        elif step == 2:
            from .forms import WizardStep2Form
            form = WizardStep2Form(request.POST)
            if form.is_valid():
                request.session['wizard_step2'] = form.cleaned_data
                return redirect('/portail/inscription/?step=3')
            step1 = request.session.get('wizard_step1')
            if not step1:
                return redirect('/portail/inscription/?step=1')
            return render(request, 'inscriptions/portail_wizard.html', {
                'step': 2, 'form': form,
                'certifications': Certification.objects.filter(actif=True).order_by('nom'),
            })

        elif step == 3:
            from .forms import WizardStep3Form
            form = WizardStep3Form(request.POST)
            if form.is_valid():
                cohorte = form.cleaned_data['cohorte']
                request.session['wizard_step3'] = {'cohorte_id': cohorte.pk}
                return redirect('/portail/inscription/?step=4')
            step1 = request.session.get('wizard_step1')
            if not step1:
                return redirect('/portail/inscription/?step=1')
            certifications = Certification.objects.filter(actif=True).order_by('nom')
            certif_tarifs = {
                c.pk: {'etudiant': float(c.tarif_etudiant), 'professionnel': float(c.tarif_professionnel), 'nom': c.nom}
                for c in certifications
            }
            return render(request, 'inscriptions/portail_wizard.html', {
                'step': 3, 'form': form, 'certifications': certifications,
                'certif_tarifs_json': json.dumps(certif_tarifs),
            })

        elif step == 4:
            step1 = request.session.get('wizard_step1')
            step2 = request.session.get('wizard_step2')
            step3 = request.session.get('wizard_step3')
            if not all([step1, step2, step3]):
                return redirect('/portail/inscription/?step=1')

            try:
                cohorte = Cohorte.objects.select_related('certification').get(pk=step3['cohorte_id'])
            except Cohorte.DoesNotExist:
                messages.error(request, "Cohorte invalide.")
                return redirect('/portail/inscription/?step=3')

            email = step1['email'].lower()
            activite = step2['activite']

            if Inscrit.objects.filter(email=email).exists():
                inscrit = Inscrit.objects.get(email=email)
                inscrit.nom = step1['nom']
                inscrit.prenom = step1['prenom']
                inscrit.telephone = step1['telephone']
                inscrit.adresse = step1.get('adresse', '')
                inscrit.activite = activite
                inscrit.universite = step2.get('universite', '')
                inscrit.entreprise = step2.get('entreprise', '')
                inscrit.save()
            else:
                inscrit = Inscrit.objects.create(
                    nom=step1['nom'],
                    prenom=step1['prenom'],
                    email=email,
                    telephone=step1['telephone'],
                    adresse=step1.get('adresse', ''),
                    activite=activite,
                    source='portail',
                    universite=step2.get('universite', ''),
                    entreprise=step2.get('entreprise', ''),
                )

            cert = cohorte.certification
            montant_du = float(
                cert.tarif_professionnel if activite == 'professionnel' else cert.tarif_etudiant
            )
            inscription, created = Inscription.objects.get_or_create(
                inscrit=inscrit, cohorte=cohorte,
                defaults={'statut': 'inscrit', 'montant_du': montant_du},
            )
            if created:
                notifier_inscription(inscription)

            if not CompteApprenant.objects.filter(inscrit=inscrit).exists():
                user, compte = _creer_compte_apprenant(inscrit)
            else:
                compte = inscrit.compte_apprenant
                user = compte.user

            for k in ['wizard_step1', 'wizard_step2', 'wizard_step3']:
                request.session.pop(k, None)

            request.session['pending_inscription_id'] = inscription.pk
            request.session['new_compte_username'] = user.username

            return redirect('portail_paiement', pk=inscription.pk)

    # GET requests
    certifications = Certification.objects.filter(actif=True).order_by('nom')
    certif_tarifs = {
        c.pk: {'etudiant': float(c.tarif_etudiant), 'professionnel': float(c.tarif_professionnel), 'nom': c.nom}
        for c in certifications
    }

    if step == 1:
        from .forms import WizardStep1Form
        initial = request.session.get('wizard_step1', {})
        form = WizardStep1Form(initial=initial)
        return render(request, 'inscriptions/portail_wizard.html', {
            'step': 1, 'form': form, 'certifications': certifications,
        })
    elif step == 2:
        if not request.session.get('wizard_step1'):
            return redirect('/portail/inscription/?step=1')
        from .forms import WizardStep2Form
        initial = request.session.get('wizard_step2', {})
        form = WizardStep2Form(initial=initial)
        return render(request, 'inscriptions/portail_wizard.html', {
            'step': 2, 'form': form, 'certifications': certifications,
        })
    elif step == 3:
        if not request.session.get('wizard_step2'):
            return redirect('/portail/inscription/?step=1')
        from .forms import WizardStep3Form
        form = WizardStep3Form()
        return render(request, 'inscriptions/portail_wizard.html', {
            'step': 3, 'form': form, 'certifications': certifications,
            'certif_tarifs_json': json.dumps(certif_tarifs),
        })
    elif step == 4:
        step1 = request.session.get('wizard_step1', {})
        step2 = request.session.get('wizard_step2', {})
        step3_data = request.session.get('wizard_step3', {})
        cohorte = None
        if step3_data.get('cohorte_id'):
            try:
                cohorte = Cohorte.objects.select_related('certification').get(pk=step3_data['cohorte_id'])
            except Cohorte.DoesNotExist:
                pass
        if not all([step1, step2, cohorte]):
            return redirect('/portail/inscription/?step=1')
        activite = step2.get('activite', 'etudiant')
        tarif = float(
            cohorte.certification.tarif_professionnel if activite == 'professionnel'
            else cohorte.certification.tarif_etudiant
        )
        return render(request, 'inscriptions/portail_wizard.html', {
            'step': 4, 'step1': step1, 'step2': step2, 'cohorte': cohorte, 'tarif': tarif,
            'certifications': certifications,
        })

    return redirect('/portail/inscription/?step=1')


def portail_inscrire(request, certif_pk):
    """
    Formulaire d'inscription en une seule page pré-lié à une certification.
    Assigne automatiquement la première cohorte active de cette certification.
    """
    certification = get_object_or_404(Certification, pk=certif_pk, actif=True)

    # Chercher la prochaine cohorte active
    cohorte = Cohorte.objects.filter(
        certification=certification, actif=True
    ).order_by("date_debut").first()

    errors = {}
    form_data = {}

    if request.method == "POST":
        nom = request.POST.get("nom", "").strip()
        prenom = request.POST.get("prenom", "").strip()
        email = request.POST.get("email", "").strip().lower()
        telephone = request.POST.get("telephone", "").strip()
        activite = request.POST.get("activite", "etudiant")
        adresse = request.POST.get("adresse", "").strip()
        universite = request.POST.get("universite", "").strip()
        entreprise = request.POST.get("entreprise", "").strip()

        form_data = {
            "nom": nom, "prenom": prenom, "email": email,
            "telephone": telephone, "activite": activite,
            "adresse": adresse, "universite": universite, "entreprise": entreprise,
        }

        if not nom:
            errors["nom"] = "Le nom est requis."
        if not prenom:
            errors["prenom"] = "Le prénom est requis."
        if not email:
            errors["email"] = "L'email est requis."
        if not cohorte:
            errors["cohorte"] = "Aucune session disponible pour cette certification pour le moment."

        if not errors:
            # Créer ou récupérer l'inscrit
            if Inscrit.objects.filter(email=email).exists():
                inscrit = Inscrit.objects.get(email=email)
                inscrit.nom = nom
                inscrit.prenom = prenom
                inscrit.telephone = telephone
                inscrit.adresse = adresse
                inscrit.activite = activite
                inscrit.universite = universite
                inscrit.entreprise = entreprise
                inscrit.save()
            else:
                inscrit = Inscrit.objects.create(
                    nom=nom, prenom=prenom, email=email,
                    telephone=telephone, adresse=adresse,
                    activite=activite, source="portail",
                    universite=universite, entreprise=entreprise,
                )

            # Calculer le montant
            montant_du = float(
                certification.tarif_professionnel if activite == "professionnel"
                else certification.tarif_etudiant
            )

            # Créer l'inscription (ou récupérer si déjà inscrit à cette cohorte)
            inscription, created = Inscription.objects.get_or_create(
                inscrit=inscrit, cohorte=cohorte,
                defaults={"statut": "inscrit", "montant_du": montant_du},
            )
            if created:
                notifier_inscription(inscription)

            # Créer le compte apprenant si nécessaire
            if not CompteApprenant.objects.filter(inscrit=inscrit).exists():
                user, _ = _creer_compte_apprenant(inscrit)
            else:
                user = inscrit.compte_apprenant.user

            # Auto-login : connecter directement l'apprenant
            from django.contrib.auth import login as auth_login
            user.backend = "django.contrib.auth.backends.ModelBackend"
            auth_login(request, user)

            request.session["new_compte_username"] = user.username
            return redirect("portail_paiement", pk=inscription.pk)

    return render(request, "inscriptions/portail_inscrire.html", {
        "certification": certification,
        "cohorte": cohorte,
        "errors": errors,
        "form_data": form_data,
    })


def portail_paiement(request, pk):
    """Payment choice page after wizard completion."""
    inscription = get_object_or_404(Inscription, pk=pk)
    username = request.session.get('new_compte_username', '')

    if request.method == 'POST':
        # Skip paiement — l'apprenant paiera plus tard
        if request.POST.get('skip_paiement'):
            skip_redirect = request.session.pop('paiement_skip_redirect', None)
            request.session.pop('pending_inscription_id', None)
            if skip_redirect == 'espace_apprenant':
                return redirect('espace_apprenant')
            return render(request, 'inscriptions/portail_confirmation.html', {
                'inscription': inscription,
                'username': request.session.get('new_compte_username', ''),
                'moyen': 'plus_tard',
            })

        moyen = request.POST.get('moyen_paiement', '')
        reference = request.POST.get('reference_virement', '').strip()

        if moyen in ['wave', 'orange_money', 'carte']:
            ref = request.POST.get('numero_mobile', '') or f"SIM-{uuid.uuid4().hex[:8].upper()}"
            Paiement.objects.create(
                inscription=inscription,
                montant=inscription.montant_du,
                date_paiement=timezone.now().date(),
                moyen_paiement=moyen,
                reference=ref,
                statut='en_attente',
                notes="Initié depuis le portail — en attente de confirmation",
            )
            messages.success(request, "Votre demande de paiement a été enregistrée. En attente de confirmation.")
        elif moyen == 'virement':
            Paiement.objects.create(
                inscription=inscription,
                montant=inscription.montant_du,
                date_paiement=timezone.now().date(),
                moyen_paiement='virement',
                reference=reference or f"VIR-{uuid.uuid4().hex[:8].upper()}",
                statut='en_attente',
                notes="Virement bancaire déclaré depuis le portail",
            )
            messages.success(request, "Votre virement a été déclaré. L'administration vérifiera et confirmera votre inscription.")

        request.session.pop('pending_inscription_id', None)

        return render(request, 'inscriptions/portail_confirmation.html', {
            'inscription': inscription,
            'username': username,
            'moyen': moyen,
        })

    rib_info = {
        'banque': "Banque de l'Habitat du Sénégal (BHS)",
        'titulaire': 'ENSMG — École Nationale Supérieure de Management et de Gouvernance',
        'iban': 'SN38 SN010 10100 20030050001 23',
        'swift': 'BHSASNDA',
        'reference': f"INS-{inscription.pk:06d}-{inscription.inscrit.nom.upper()[:6]}",
    }

    return render(request, 'inscriptions/portail_paiement.html', {
        'inscription': inscription,
        'rib_info': rib_info,
        'username': username,
    })


# ---------------------------------------------------------------------------
# Espace Apprenant
# ---------------------------------------------------------------------------

def _apprenant_required(view_func):
    """Decorator: must be logged in as apprenant (has compte_apprenant)."""
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        try:
            _ = request.user.compte_apprenant
        except Exception:
            messages.error(request, "Accès réservé aux apprenants.")
            return redirect('dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper


@_apprenant_required
def espace_apprenant(request):
    """Learner personal dashboard."""
    compte = request.user.compte_apprenant
    inscrit = compte.inscrit

    inscriptions = (
        inscrit.inscriptions
        .select_related('cohorte__certification')
        .prefetch_related('paiements', 'attestations')
        .order_by('-date_inscription')
    )

    total_du = sum(i.montant_du for i in inscriptions)
    total_paye = sum(i.total_paye for i in inscriptions)
    total_restant = max(total_du - total_paye, 0)

    context = {
        'compte': compte,
        'inscrit': inscrit,
        'inscriptions': inscriptions,
        'total_du': total_du,
        'total_paye': total_paye,
        'total_restant': total_restant,
        'active_page': 'espace',
    }
    return render(request, 'inscriptions/apprenant_dashboard.html', context)


def apprenant_changer_mdp(request):
    """Forced password change on first login."""
    if not request.user.is_authenticated:
        return redirect('login')

    try:
        compte = request.user.compte_apprenant
    except Exception:
        return redirect('dashboard')

    if request.method == 'POST':
        from .forms import ChangerMdpApprenantForm
        form = ChangerMdpApprenantForm(request.POST)
        if form.is_valid():
            request.user.set_password(form.cleaned_data['nouveau_mdp'])
            request.user.save()
            compte.mdp_change = True
            compte.save()
            from django.contrib.auth import update_session_auth_hash
            update_session_auth_hash(request, request.user)
            messages.success(request, "Mot de passe changé avec succès. Bienvenue !")
            return redirect('espace_apprenant')
    else:
        from .forms import ChangerMdpApprenantForm
        form = ChangerMdpApprenantForm()

    return render(request, 'inscriptions/apprenant_changer_mdp.html', {'form': form})


@_apprenant_required
def apprenant_profil(request):
    """View and edit learner profile."""
    compte = request.user.compte_apprenant
    inscrit = compte.inscrit

    if request.method == 'POST':
        from .forms import ProfilApprenantForm
        form = ProfilApprenantForm(request.POST, instance=inscrit)
        if form.is_valid():
            form.save()
            messages.success(request, "Profil mis à jour avec succès.")
            return redirect('apprenant_profil')
    else:
        from .forms import ProfilApprenantForm
        form = ProfilApprenantForm(instance=inscrit)

    return render(request, 'inscriptions/apprenant_profil.html', {
        'form': form, 'inscrit': inscrit, 'compte': compte, 'active_page': 'profil',
    })


@_apprenant_required
def apprenant_payer(request, inscription_pk):
    """Learner initiates a new payment from their space."""
    compte = request.user.compte_apprenant
    inscription = get_object_or_404(Inscription, pk=inscription_pk, inscrit=compte.inscrit)
    request.session['pending_inscription_id'] = inscription.pk
    request.session['paiement_skip_redirect'] = 'espace_apprenant'
    request.session.pop('new_compte_username', None)
    return redirect('portail_paiement', pk=inscription.pk)


# ---------------------------------------------------------------------------
# Admin: confirm pending payments
# ---------------------------------------------------------------------------

@login_required
def admin_confirmer_paiement(request, pk):
    """Admin confirms a pending (virement/wave/om) payment."""
    paiement = get_object_or_404(Paiement, pk=pk)
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard')
    if request.method == 'POST':
        paiement.statut = 'confirme'
        paiement.save()
        notifier_paiement_confirme(paiement)
        messages.success(request, f"Paiement de {paiement.montant} FCFA confirmé.")
        return redirect('inscrit_detail', pk=paiement.inscription.inscrit.pk)
    return render(request, 'inscriptions/confirmer_paiement.html', {'paiement': paiement})


# ---------------------------------------------------------------------------
# Reçu de paiement PDF
# ---------------------------------------------------------------------------

def _generer_recu_pdf(paiement, request=None):
    """Generate a payment receipt PDF and return bytes."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=2.5 * cm, rightMargin=2.5 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
    )

    navy   = colors.HexColor("#1a2340")
    accent = colors.HexColor("#4f6ef7")
    gold   = colors.HexColor("#d4a017")
    grey   = colors.HexColor("#718096")
    green  = colors.HexColor("#38a169")

    styles = getSampleStyleSheet()

    def ms(name, **kw):
        return ParagraphStyle(name, parent=styles["Normal"], **kw)

    s_title  = ms("t",  fontSize=22, textColor=navy,   alignment=TA_CENTER, fontName="Helvetica-Bold", leading=28, spaceAfter=4)
    s_sub    = ms("s",  fontSize=10, textColor=accent, alignment=TA_CENTER, leading=14)
    s_label  = ms("l",  fontSize=9,  textColor=grey,   leading=13)
    s_value  = ms("v",  fontSize=11, textColor=navy,   fontName="Helvetica-Bold", leading=16)
    s_big    = ms("b",  fontSize=18, textColor=green,  fontName="Helvetica-Bold", alignment=TA_CENTER, leading=24)
    s_footer = ms("f",  fontSize=8,  textColor=grey,   alignment=TA_CENTER, leading=11)

    inscrit = paiement.inscription.inscrit
    certification = paiement.inscription.cohorte.certification
    moyen_map = dict(Paiement.MOYEN_CHOICES)
    moyen_label = moyen_map.get(paiement.moyen_paiement, paiement.moyen_paiement)

    story = []
    story.append(Paragraph("ÉCOLE NATIONALE SUPÉRIEURE DE MANAGEMENT ET DE GOUVERNANCE", s_title))
    story.append(Paragraph("ENSMG — Dakar, Sénégal", s_sub))
    story.append(Spacer(1, 0.3 * cm))
    story.append(HRFlowable(width="100%", thickness=3, color=accent, spaceAfter=3))
    story.append(HRFlowable(width="100%", thickness=1, color=gold,   spaceAfter=10))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph("REÇU DE PAIEMENT", ms("rp", fontSize=26, textColor=navy, alignment=TA_CENTER, fontName="Helvetica-Bold", leading=32, spaceAfter=6)))
    story.append(Paragraph(f"N° {paiement.reference or paiement.pk}", ms("ref", fontSize=11, textColor=grey, alignment=TA_CENTER, leading=14)))
    story.append(Spacer(1, 0.5 * cm))

    data = [
        [Paragraph("Bénéficiaire", s_label), Paragraph(f"{inscrit.prenom} {inscrit.nom}", s_value)],
        [Paragraph("Certification", s_label), Paragraph(certification.nom, s_value)],
        [Paragraph("Cohorte",       s_label), Paragraph(paiement.inscription.cohorte.nom, s_value)],
        [Paragraph("Date",          s_label), Paragraph(paiement.date_paiement.strftime("%d/%m/%Y"), s_value)],
        [Paragraph("Moyen",         s_label), Paragraph(moyen_label, s_value)],
    ]
    if paiement.reference:
        data.append([Paragraph("Référence", s_label), Paragraph(paiement.reference, s_value)])

    t = Table(data, colWidths=[5 * cm, 12 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f0f2f8")),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#f8f9ff")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("PADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.6 * cm))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e2e8f0"), spaceAfter=10))
    story.append(Paragraph(f"{int(paiement.montant):,} FCFA".replace(",", " "), s_big))
    story.append(Spacer(1, 0.4 * cm))
    story.append(HRFlowable(width="100%", thickness=1, color=accent, spaceAfter=4))
    story.append(HRFlowable(width="100%", thickness=3, color=navy,   spaceAfter=6))
    story.append(Paragraph("Ce document atteste du paiement effectué auprès de l'ENSMG.", s_footer))
    story.append(Paragraph("ENSMG — Dakar, Sénégal — www.ensmg.sn", s_footer))

    doc.build(story)
    return buffer.getvalue()


@login_required
def recu_download(request, pk):
    """Download or generate payment receipt PDF."""
    paiement = get_object_or_404(Paiement, pk=pk)
    # Check permission: admin/staff OR the apprenant themselves
    is_owner = False
    try:
        compte = request.user.compte_apprenant
        if paiement.inscription.inscrit == compte.inscrit:
            is_owner = True
    except Exception:
        pass

    if not is_owner and not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard')

    if not paiement.recu_pdf:
        pdf_bytes = _generer_recu_pdf(paiement, request)
        paiement.recu_pdf = pdf_bytes
        paiement.save(update_fields=['recu_pdf'])

    nom = paiement.inscription.inscrit.nom_complet.replace(" ", "_")
    response = HttpResponse(bytes(paiement.recu_pdf), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="recu_{nom}_{paiement.pk}.pdf"'
    return response


# ---------------------------------------------------------------------------
# Dashboard financier avancé
# ---------------------------------------------------------------------------

@login_required
def dashboard_financier(request):
    """Advanced financial dashboard with charts data."""
    from django.db.models.functions import TruncMonth
    from datetime import date, timedelta

    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "Accès réservé aux administrateurs.")
        return redirect('dashboard')

    today = timezone.now().date()
    twelve_months_ago = today - timedelta(days=365)

    monthly_data = (
        Paiement.objects.filter(statut='confirme', date_paiement__gte=twelve_months_ago)
        .annotate(mois=TruncMonth('date_paiement'))
        .values('mois')
        .annotate(total=Sum('montant'))
        .order_by('mois')
    )

    months_labels = []
    months_values = []
    for entry in monthly_data:
        mois = entry['mois']
        months_labels.append(mois.strftime('%b %Y'))
        months_values.append(float(entry['total']))

    total_encaisse = Paiement.objects.filter(statut='confirme').aggregate(t=Sum('montant'))['t'] or 0
    total_en_attente = Paiement.objects.filter(statut='en_attente').aggregate(t=Sum('montant'))['t'] or 0
    total_inscrits = Inscription.objects.count()
    total_certifies = Inscription.objects.filter(statut='certifie').count()
    taux_certif = int((total_certifies / total_inscrits * 100)) if total_inscrits else 0

    moyen_data = (
        Paiement.objects.filter(statut='confirme')
        .values('moyen_paiement')
        .annotate(total=Sum('montant'), count=Count('id'))
        .order_by('-total')
    )
    moyen_labels = []
    moyen_values = []
    moyen_map = dict(Paiement.MOYEN_CHOICES)
    for m in moyen_data:
        moyen_labels.append(moyen_map.get(m['moyen_paiement'], m['moyen_paiement']))
        moyen_values.append(float(m['total']))

    stats_certifs = []
    for cert in Certification.objects.order_by('nom'):
        nb_i = Inscription.objects.filter(cohorte__certification=cert).count()
        nb_c = Inscription.objects.filter(cohorte__certification=cert, statut='certifie').count()
        enc = Paiement.objects.filter(
            inscription__cohorte__certification=cert, statut='confirme'
        ).aggregate(t=Sum('montant'))['t'] or 0
        taux = int(nb_c / nb_i * 100) if nb_i else 0
        stats_certifs.append({
            'cert': cert, 'nb_inscrits': nb_i, 'nb_certifies': nb_c,
            'encaisse': enc, 'taux': taux,
        })

    paiements_en_attente = (
        Paiement.objects.filter(statut='en_attente')
        .select_related('inscription__inscrit', 'inscription__cohorte__certification')
        .order_by('-created_at')[:20]
    )

    context = {
        'total_encaisse': total_encaisse,
        'total_en_attente': total_en_attente,
        'total_inscrits': total_inscrits,
        'total_certifies': total_certifies,
        'taux_certif': taux_certif,
        'months_labels_json': json.dumps(months_labels),
        'months_values_json': json.dumps(months_values),
        'moyen_labels_json': json.dumps(moyen_labels),
        'moyen_values_json': json.dumps(moyen_values),
        'stats_certifs': stats_certifs,
        'paiements_en_attente': paiements_en_attente,
        'active_page': 'dashboard_financier',
    }
    return render(request, 'inscriptions/dashboard_financier.html', context)
