import io
import json
import uuid
import unicodedata
import re
from functools import wraps

from django.conf import settings
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Sum, Count, Q
from django.http import JsonResponse, FileResponse, HttpResponse, Http404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
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
# Helpers de rôle
# ---------------------------------------------------------------------------

def _get_user_role(user):
    """Retourne le rôle string d'un utilisateur staff authentifié."""
    if user.is_superuser:
        return 'super_utilisateur'
    groups = set(user.groups.values_list('name', flat=True))
    if 'Responsable Scolarité' in groups:
        return 'responsable_scolarite'
    if 'Admin' in groups:
        return 'admin'
    if 'Personnel Utilisateur' in groups:
        return 'personnel_utilisateur'
    return 'super_utilisateur'


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------

def admin_required(view_func):
    """Réservé aux Super Utilisateurs uniquement."""
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_superuser:
            messages.error(request, "Accès réservé aux super utilisateurs.")
            return redirect("dashboard")
        return view_func(request, *args, **kwargs)
    return wrapper


def users_required(view_func):
    """Gestion des utilisateurs : Super Utilisateur + Admin."""
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        role = _get_user_role(request.user)
        if role not in ('super_utilisateur', 'admin'):
            messages.error(request, "Accès réservé aux administrateurs système.")
            return redirect("dashboard")
        return view_func(request, *args, **kwargs)
    return wrapper


def write_required(view_func):
    """Opérations d'écriture : Super Utilisateur + Responsable Scolarité uniquement."""
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        role = _get_user_role(request.user)
        if role in ('admin', 'personnel_utilisateur'):
            messages.warning(request, "Vous avez un accès en lecture seule.")
            return redirect(request.META.get("HTTP_REFERER", "dashboard"))
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
# Auto-transitions de statut selon les dates de cohorte
# ---------------------------------------------------------------------------

def _auto_transition_statuts():
    """
    Parcourt les inscriptions et met à jour automatiquement le statut selon
    les dates de la cohorte :
      - statut = 'inscrit' + cohorte.date_debut <= today + reste_a_payer == 0 → 'en_formation'
      - statut = 'en_formation' + cohorte.date_fin <= today → 'formation_terminee'
    Les pré-inscrits (sans paiement confirmé) ne sont PAS promus.
    """
    today = timezone.now().date()

    # inscrit (paiement soldé) + formation démarrée → en formation
    candidates = Inscription.objects.filter(
        statut='inscrit',
        cohorte__date_debut__lte=today,
        cohorte__date_fin__gte=today,
    ).prefetch_related('paiements')

    to_promote = [
        ic.pk for ic in candidates
        if sum(p.montant for p in ic.paiements.all() if p.statut == 'confirme') >= ic.montant_du
    ]
    if to_promote:
        Inscription.objects.filter(pk__in=to_promote).update(statut='en_formation')

    # en_formation + formation terminée → formation_terminee
    Inscription.objects.filter(
        statut='en_formation',
        cohorte__date_fin__lt=today,
    ).update(statut='formation_terminee')


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@login_required
def dashboard(request):
    _auto_transition_statuts()
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

    # Répartition par statut
    from django.db.models import Count
    stats_statut_qs = inscriptions_qs.values('statut').annotate(nb=Count('id'))
    stats_statut_dict = {s['statut']: s['nb'] for s in stats_statut_qs}

    # Inscrits récents
    inscrits_recents = (
        Inscrit.objects.prefetch_related('inscriptions')
        .order_by('-date_inscription')[:8]
    )

    context = {
        "nb_certifications": Certification.objects.count(),
        "nb_inscrits": nb_inscrits,
        "nb_certifies": nb_certifies,
        "total_encaisse": total_encaisse,
        "taux_certification": taux_certification,
        "stats_certifications": stats_certifications,
        "stats_statut_dict": stats_statut_dict,
        "paiements_recents": paiements_recents,
        "inscrits_recents": inscrits_recents,
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
    query = request.GET.get("q", "").strip()
    certifications = Certification.objects.prefetch_related(
        "cohortes__inscriptions__paiements"
    )

    if query:
        for mot in query.split():
            certifications = certifications.filter(
                Q(nom__icontains=mot) | Q(description__icontains=mot)
            )

    certifications = certifications.order_by("-created_at")

    paginator = Paginator(certifications, 25)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    context = {
        "certifications": page_obj,
        "page_obj": page_obj,
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
        form = CertificationForm(request.POST, request.FILES)
        if form.is_valid():
            certification = form.save()
            messages.success(request, f'Certification "{certification.nom}" créée avec succès.')
            # Notify all apprenants of new certification
            from .models import Notification
            for compte in CompteApprenant.objects.all():
                Notification.objects.create(
                    destinataire=compte,
                    type_notif='nouvelle_certification',
                    message=f"Nouvelle certification disponible : « {certification.nom} ». Inscrivez-vous dès maintenant !",
                    lien='/apprenant/certifications/',
                )
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
        form = CertificationForm(request.POST, request.FILES, instance=certification)
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
    query = request.GET.get("q", "").strip()
    activite_filter = request.GET.get("activite", "")
    certification_filter = request.GET.get("certification", "")
    statut_filter = request.GET.get("statut", "")

    inscrits = Inscrit.objects.prefetch_related(
        "inscriptions__cohorte__certification", "inscriptions__paiements"
    ).order_by("-date_inscription")

    if query:
        for mot in query.split():
            inscrits = inscrits.filter(
                Q(nom__icontains=mot)
                | Q(prenom__icontains=mot)
                | Q(email__icontains=mot)
                | Q(telephone__icontains=mot)
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

    # Stats for cards
    nb_total = Inscrit.objects.count()

    # All inscrits who have a CompteApprenant (registered via portail)
    from django.db.models import Prefetch
    inscrits_avec_compte = list(
        Inscrit.objects.filter(
            compte_apprenant__isnull=False
        ).prefetch_related(
            Prefetch(
                'inscriptions',
                queryset=Inscription.objects.select_related('cohorte__certification').prefetch_related(
                    'paiements'
                )
            )
        ).order_by('nom', 'prenom')
    )

    # Classify each inscrit with a compte
    list_inscrits_actifs = []      # inscription active + paiement soldé
    list_sans_inscription = []     # compte mais aucune inscription
    list_non_paye = []             # inscription pre_inscrit (pas encore payé)
    list_paiement_attente = []     # paiement en attente de confirmation
    inscrits_actifs_pks = set()

    for ins in inscrits_avec_compte:
        inscriptions = list(ins.inscriptions.all())
        if not inscriptions:
            list_sans_inscription.append(ins)
            continue

        is_actif = False
        has_attente = False
        has_non_paye = False

        for ic in inscriptions:
            paiements = list(ic.paiements.all())
            total_confirme = sum(p.montant for p in paiements if p.statut == 'confirme')
            has_attente_paiement = any(p.statut == 'en_attente' for p in paiements)

            if ic.statut in ('inscrit', 'en_formation', 'formation_terminee', 'certifie') and total_confirme >= ic.montant_du:
                is_actif = True
                inscrits_actifs_pks.add(ins.pk)
                break
            if has_attente_paiement:
                has_attente = True
            elif ic.statut == 'pre_inscrit':
                has_non_paye = True

        if is_actif:
            list_inscrits_actifs.append(ins)
        elif has_attente:
            list_paiement_attente.append(ins)
        elif has_non_paye:
            list_non_paye.append(ins)
        else:
            list_sans_inscription.append(ins)

    # Pre-inscrits = sans inscription active soldée (toutes sous-catégories)
    list_pre_inscrits = list_sans_inscription + list_non_paye + list_paiement_attente
    nb_pre_inscrits = len(list_pre_inscrits)
    nb_avec_certif = len(list_inscrits_actifs)

    paginator = Paginator(inscrits, 25)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    context = {
        "inscrits": page_obj,
        "page_obj": page_obj,
        "query": query,
        "activite_filter": activite_filter,
        "certification_filter": certification_filter,
        "statut_filter": statut_filter,
        "certifications_all": certifications_all,
        "statut_choices": Inscription.STATUT_CHOICES,
        "activite_choices": Inscrit.ACTIVITE_CHOICES,
        "active_page": "inscrits",
        "nb_inscrits": nb_total,
        "nb_pre_inscrits": nb_pre_inscrits,
        "nb_avec_certif": nb_avec_certif,
        "list_pre_inscrits": list_pre_inscrits,
        "list_inscrits_actifs": list_inscrits_actifs,
        # Sub-categories for pre-inscrit panel
        "list_sans_inscription": list_sans_inscription,
        "list_non_paye": list_non_paye,
        "list_paiement_attente": list_paiement_attente,
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

    try:
        compte = inscrit.compte_apprenant
    except Exception:
        compte = None

    context = {
        "inscrit": inscrit,
        "inscriptions": inscriptions,
        "statut_forms": statut_forms,
        "paiement_forms": paiement_forms,
        "compte": compte,
        "active_page": "inscrits",
    }
    return render(request, "inscriptions/inscrit_detail.html", context)


@login_required
def admin_certifications_pour_inscrit(request, pk):
    """Admin: choose which certification to enroll an inscrit in."""
    inscrit = get_object_or_404(Inscrit, pk=pk)
    certifs_actives = Certification.objects.filter(actif=True).order_by('nom')
    certifs_inactives = Certification.objects.filter(actif=False).order_by('nom')
    return render(request, 'inscriptions/admin_certifications_pour_inscrit.html', {
        'inscrit': inscrit,
        'certifs_actives': certifs_actives,
        'certifs_inactives': certifs_inactives,
        'active_page': 'inscrits',
    })


@login_required
def admin_inscription_directe(request, pk, certif_pk):
    """Admin: enroll an inscrit in a specific certification (choose cohorte)."""
    inscrit = get_object_or_404(Inscrit, pk=pk)
    certification = get_object_or_404(Certification, pk=certif_pk)
    cohortes = Cohorte.objects.filter(certification=certification, actif=True).order_by('nom')

    errors = {}

    if request.method == 'POST':
        cohorte_id = request.POST.get('cohorte_id', '').strip()
        action = request.POST.get('action', 'payer')
        cohorte = None

        if cohorte_id:
            try:
                cohorte = Cohorte.objects.get(pk=cohorte_id, certification=certification, actif=True)
            except Cohorte.DoesNotExist:
                errors['cohorte'] = "Cohorte invalide."
        if not cohorte:
            errors['cohorte'] = "Veuillez sélectionner une session valide."

        if not errors:
            montant_du = float(
                certification.tarif_professionnel if inscrit.activite == 'professionnel'
                else certification.tarif_etudiant
            )
            inscription, created = Inscription.objects.get_or_create(
                inscrit=inscrit,
                cohorte=cohorte,
                defaults={'statut': 'pre_inscrit', 'montant_du': montant_du},
            )
            if created:
                notifier_inscription(inscription)

            if action == 'sans_payer':
                messages.success(request, f"{inscrit.nom_complet} inscrit(e) à « {certification.nom} » (paiement différé).")
                return redirect('inscrit_detail', pk=inscrit.pk)
            else:
                request.session['pending_inscription_id'] = inscription.pk
                return redirect('portail_paiement', pk=inscription.pk)

    return render(request, 'inscriptions/admin_inscription_directe.html', {
        'inscrit': inscrit,
        'certification': certification,
        'cohortes': cohortes,
        'errors': errors,
        'active_page': 'inscrits',
    })


@login_required
def inscrit_ajouter(request):
    if request.method == "POST":
        form = InscritForm(request.POST)
        if form.is_valid():
            inscrit = form.save(commit=False)
            inscrit.source = "manuel"
            inscrit.save()
            # Auto-create portal account for every new inscrit
            try:
                if not hasattr(inscrit, 'compte_apprenant'):
                    _, compte = _creer_compte_apprenant(inscrit)
                    messages.success(
                        request,
                        f'Inscrit "{inscrit}" ajouté. Compte portail créé — identifiant : {compte.user.username} — mot de passe provisoire : passer01'
                    )
                else:
                    messages.success(request, f'Inscrit "{inscrit}" ajouté avec succès.')
            except Exception:
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
def admin_creer_compte_inscrit(request, pk):
    """Create a portal account (User + CompteApprenant) for an existing inscrit who doesn't have one."""
    inscrit = get_object_or_404(Inscrit, pk=pk)
    try:
        _ = inscrit.compte_apprenant
        messages.info(request, f"Un compte portail existe déjà pour {inscrit.nom_complet}.")
        return redirect("inscrit_detail", pk=pk)
    except Exception:
        pass
    _, compte = _creer_compte_apprenant(inscrit)
    messages.success(
        request,
        f"Compte portail créé pour {inscrit.nom_complet} — identifiant : {compte.user.username} — mot de passe provisoire : passer01"
    )
    return redirect("inscrit_detail", pk=pk)


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
    query = request.GET.get("q", "").strip()
    moyen_filter = request.GET.get("moyen", "")

    paiements = Paiement.objects.select_related(
        "inscription__inscrit", "inscription__cohorte__certification"
    ).order_by("-date_paiement", "-created_at")

    if query:
        for mot in query.split():
            paiements = paiements.filter(
                Q(inscription__inscrit__nom__icontains=mot)
                | Q(inscription__inscrit__prenom__icontains=mot)
                | Q(inscription__inscrit__email__icontains=mot)
                | Q(inscription__cohorte__certification__nom__icontains=mot)
                | Q(inscription__cohorte__nom__icontains=mot)
                | Q(reference__icontains=mot)
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

    # Pending payments (en_attente) — always shown regardless of filters
    paiements_en_attente = Paiement.objects.filter(statut='en_attente').select_related(
        "inscription__inscrit", "inscription__cohorte__certification"
    ).order_by("-created_at")

    paginator = Paginator(paiements, 25)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    context = {
        "paiements": page_obj,
        "page_obj": page_obj,
        "paiements_en_attente": paiements_en_attente,
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
                paid = 0
                errors = []
                paiement_solde = form.cleaned_data.get("paiement_solde", False)
                moyen_paiement = form.cleaned_data.get("moyen_paiement", "especes")

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
                            # Auto-create portal account for newly imported inscrits
                            try:
                                if not hasattr(inscrit, 'compte_apprenant'):
                                    _creer_compte_apprenant(inscrit)
                            except Exception:
                                pass
                        else:
                            updated += 1

                        # Inscription à la cohorte uniquement si sélectionnée
                        if cohorte:
                            cert = cohorte.certification
                            montant_du = float(
                                cert.tarif_professionnel if activite_val == "professionnel"
                                else cert.tarif_etudiant
                            )
                            inscription, ic_created = Inscription.objects.get_or_create(
                                inscrit=inscrit,
                                cohorte=cohorte,
                                defaults={"statut": "inscrit", "montant_du": montant_du},
                            )
                            if ic_created:
                                enrolled += 1

                            # Enregistrer le paiement intégral si demandé
                            if paiement_solde and montant_du > 0:
                                from django.utils import timezone as tz
                                Paiement.objects.get_or_create(
                                    inscription=inscription,
                                    montant=montant_du,
                                    moyen_paiement=moyen_paiement,
                                    statut="confirme",
                                    defaults={"date_paiement": tz.now().date()},
                                )
                                paid += 1

                    except Exception as exc:
                        errors.append(f"Ligne {row_idx}: erreur — {exc}")

                wb.close()

                if created or updated:
                    msg = f"Import terminé : {created} inscrit(s) créé(s), {updated} mis à jour"
                    if cohorte:
                        msg += f", {enrolled} nouvelle(s) inscription(s) à « {cohorte} »"
                    if paid:
                        msg += f", {paid} paiement(s) enregistré(s)"
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

def _get_active_session_data():
    """
    Retourne un dict {user_id: session_info} pour toutes les sessions non expirées.
    session_info = {'expire_date': datetime, 'session_key': str}
    """
    from django.contrib.sessions.models import Session
    active = {}
    for session in Session.objects.filter(expire_date__gte=timezone.now()):
        try:
            data = session.get_decoded()
            uid = data.get('_auth_user_id')
            if uid:
                uid = int(uid)
                # Garder la session la plus récente si plusieurs
                if uid not in active or session.expire_date > active[uid]['expire_date']:
                    active[uid] = {
                        'expire_date': session.expire_date,
                        'session_key': session.session_key,
                    }
        except Exception:
            pass
    return active


@users_required
def users_list(request):
    query = request.GET.get("q", "").strip()
    users = User.objects.prefetch_related("groups").order_by("username")
    if query:
        for mot in query.split():
            users = users.filter(
                Q(username__icontains=mot)
                | Q(first_name__icontains=mot)
                | Q(last_name__icontains=mot)
                | Q(email__icontains=mot)
            )
    paginator = Paginator(users, 25)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    raw_sessions = _get_active_session_data()
    # Build simple sets/dicts usable in template without custom filters
    active_user_ids = set(raw_sessions.keys())
    active_expire_labels = {
        uid: info['expire_date'].strftime("%d/%m %H:%M")
        for uid, info in raw_sessions.items()
    }
    nb_en_ligne = len(active_user_ids)

    context = {
        "users": page_obj,
        "page_obj": page_obj,
        "query": query,
        "active_user_ids": active_user_ids,
        "active_expire_labels": active_expire_labels,
        "nb_en_ligne": nb_en_ligne,
        "active_page": "utilisateurs",
    }
    return render(request, "inscriptions/users_list.html", context)


@users_required
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


@users_required
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


@users_required
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


def _generer_attestation_pdf(inscription, verification_url="", partenaire_logo_path=None, partenaire_nom=None, partenaire_titre_signataire=None):
    """Génère le PDF d'attestation via WeasyPrint (template PNG + overlay CSS)."""
    import os, base64
    from django.conf import settings
    from django.template.loader import render_to_string

    from PIL import Image, ImageDraw, ImageFont
    from django.conf import settings

    inscrit       = inscription.inscrit
    certification = inscription.cohorte.certification
    cohorte       = inscription.cohorte
    today         = timezone.now().date()

    STATIC   = os.path.join(settings.BASE_DIR, 'inscriptions', 'static', 'inscriptions')
    IMG_DIR  = os.path.join(STATIC, 'img')
    FONT_DIR = os.path.join(STATIC, 'fonts')
    NAVY = (13, 36, 97)
    GREY = (68, 68, 68)
    DPI  = 150

    # ── A4 landscape en pixels à DPI ─────────────────────────────────────────
    A4W = int(297 * DPI / 25.4)   # 1748 px
    A4H = int(210 * DPI / 25.4)   # 1240 px

    # Charger le template et le redimensionner exactement en A4
    tmpl = Image.open(os.path.join(IMG_DIR, 'cert_template.png')).convert('RGB')
    img  = tmpl.resize((A4W, A4H), Image.LANCZOS)
    W, H = A4W, A4H
    draw = ImageDraw.Draw(img)

    # ── Helpers ───────────────────────────────────────────────────────────────
    def px(x_mm, y_mm):
        """mm → pixels dans l'image A4."""
        return int(x_mm * W / 297), int(y_mm * H / 210)

    def white_box(x1_mm, y1_mm, x2_mm, y2_mm):
        x1, y1 = px(x1_mm, y1_mm)
        x2, y2 = px(x2_mm, y2_mm)
        draw.rectangle([x1, y1, x2, y2], fill='white')

    def pt(size_mm):
        """Taille de police en px (1mm ≈ 2.83pt, 1pt ≈ 1.33px à 96dpi → adaptée au DPI)."""
        return max(10, int(size_mm * DPI / 25.4))

    def load_font(name, size_mm):
        try:
            return ImageFont.truetype(os.path.join(FONT_DIR, name), pt(size_mm))
        except Exception:
            return ImageFont.load_default()

    def load_sys_font(name, size_mm):
        for path in [f'C:/Windows/Fonts/{name}', f'/usr/share/fonts/truetype/liberation/{name}',
                     f'/usr/share/fonts/{name}']:
            try:
                return ImageFont.truetype(path, pt(size_mm))
            except Exception:
                continue
        return ImageFont.load_default()

    def draw_centered(text, y_mm, font, color=NAVY):
        _, y = px(0, y_mm)
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        draw.text(((W - tw) // 2, y), text, font=font, fill=color)

    def draw_right(text, x_right_mm, y_mm, font, color=NAVY):
        xr, y = px(x_right_mm, y_mm)
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        draw.text((xr - tw, y), text, font=font, fill=color)

    # ── Fontes ────────────────────────────────────────────────────────────────
    font_script = load_font('DancingScript-Bold.ttf', 14)   # ~14mm = 53pt
    font_bold   = load_sys_font('arialbd.ttf', 5.5)         # ~5.5mm = 23pt bold
    font_reg    = load_sys_font('arial.ttf',   4.5)         # ~4.5mm = 19pt
    font_sm     = load_sys_font('arial.ttf',   3.5)         # ~3.5mm = 15pt
    font_tiny   = load_sys_font('arial.ttf',   2.8)         # ~2.8mm = 12pt

    # ══════════════════════════════════════════════════════════════════════════
    # OVERLAYS
    # ══════════════════════════════════════════════════════════════════════════

    # 1. Supprimer le logo central en haut (mm: 127.2,3.2 → 170.8,25.1)
    white_box(125, 0, 173, 27)

    # 2. Numéro de certificat (box template: mm 5.9,8.6 → 46.8,13.5)
    cert_num = f"ENSMG-{today.year}-{inscription.pk:04d}"
    white_box(5.5, 8.2, 48, 14)
    x1, y1 = px(5.5, 8.2)
    x2, y2 = px(48,  14)
    draw.rounded_rectangle([x1, y1, x2, y2], radius=6, outline=NAVY, width=2)
    cert_txt = f"Certificat N° : {cert_num}"
    bbox = draw.textbbox((0, 0), cert_txt, font=font_tiny)
    tw = bbox[2] - bbox[0]; th = bbox[3] - bbox[1]
    draw.text((x1 + 8, (y1 + y2) // 2 - th // 2), cert_txt, font=font_tiny, fill=GREY)

    # 3. Nom du bénéficiaire (zone template: mm 21.7,101.1 → 274.1,118.9)
    white_box(2, 100, 295, 120)
    nom_txt = f"{inscrit.prenom} {inscrit.nom}"
    fn = font_script
    bbox_n = draw.textbbox((0, 0), nom_txt, font=fn)
    while (bbox_n[2] - bbox_n[0]) > int(0.85 * W) and fn.size > pt(7):
        fn = ImageFont.truetype(os.path.join(FONT_DIR, 'DancingScript-Bold.ttf'), fn.size - 4)
        bbox_n = draw.textbbox((0, 0), nom_txt, font=fn)
    _, y_top = px(0, 100); _, y_bot = px(0, 120)
    th_n = bbox_n[3] - bbox_n[1]
    y_name = y_top + (y_bot - y_top - th_n) // 2
    draw.text(((W - (bbox_n[2] - bbox_n[0])) // 2, y_name), nom_txt, font=fn, fill=NAVY)

    # 4. Formation + description (zone template: mm 21.7,120.2 → 274.1,142.1)
    white_box(2, 119, 295, 160)
    nom_cert = certification.nom
    bbox_f = draw.textbbox((0, 0), nom_cert, font=font_bold)
    if (bbox_f[2] - bbox_f[0]) > int(0.82 * W):
        words = nom_cert.split()
        mid   = len(words) // 2
        draw_centered(' '.join(words[:mid]), 123, font_bold, NAVY)
        draw_centered(' '.join(words[mid:]), 132, font_bold, NAVY)
        desc_y = 143
    else:
        draw_centered(nom_cert, 127, font_bold, NAVY)
        desc_y = 139

    desc = certification.description.strip() if certification.description else ''
    if desc:
        desc_txt = f"({desc})" if not desc.startswith('(') else desc
        draw_centered(desc_txt, desc_y, font_reg, GREY)

    # 5. QR code (zone template: mm 7.5,144.8 → 44.6,183.1)
    white_box(6, 143, 46, 184)
    if verification_url:
        try:
            import qrcode as _qrcode
            _qr = _qrcode.QRCode(version=2, box_size=8, border=2,
                                  error_correction=_qrcode.constants.ERROR_CORRECT_H)
            _qr.add_data(verification_url)
            _qr.make(fit=True)
            qr_img = _qr.make_image(fill_color=(13, 36, 97), back_color='white').convert('RGB')
            qr_px  = int(38 * W / 297)
            qr_img = qr_img.resize((qr_px, qr_px), Image.LANCZOS)
            qx, qy = px(7.5, 144.8)
            img.paste(qr_img, (qx, qy))
        except Exception:
            pass

    # 6. Partenaire signataire (zone template: mm 171.8,162.6 → 239.2,169.5)
    part_nom = partenaire_nom or certification.partenaire_nom or ''
    if part_nom:
        white_box(170, 162, 241, 170)
        _, y_p  = px(0, 163.5)
        cx_p    = (px(170, 0)[0] + px(241, 0)[0]) // 2
        bbox_p  = draw.textbbox((0, 0), part_nom, font=font_sm)
        tw_p    = bbox_p[2] - bbox_p[0]
        draw.text((cx_p - tw_p // 2, y_p), part_nom, font=font_sm, fill=GREY)

    # 7. Date (zone template: mm 221.8,194.1 → 291.4,203.6)
    white_box(220, 193, 293, 204)
    date_str  = f"Fait à Dakar, le {today.day:02d} / {today.month:02d} / {today.year}"
    _, y_date = px(0, 196)
    bbox_d    = draw.textbbox((0, 0), date_str, font=font_sm)
    tw_d      = bbox_d[2] - bbox_d[0]
    draw.text((W - px(8, 0)[0] - tw_d, y_date), date_str, font=font_sm, fill=NAVY)

    # ── Export PDF A4 à DPI ───────────────────────────────────────────────────
    buf = io.BytesIO()
    img.save(buf, format='PDF', resolution=DPI)
    return buf.getvalue()


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
        # Éviter les doublons si déjà certifié
        if inscription.attestations.exists():
            continue

        inscription.statut = "certifie"
        inscription.save()

        # Numéro séquentiel : CERT/ENSMG/{CERT}/{ANNÉE}/{SEQ:03d}
        annee = timezone.now().year
        abbrev = "".join(c for c in certification.nom.upper() if c.isalpha())[:6]
        seq = Attestation.objects.filter(
            inscription__cohorte__certification=certification,
            date_delivrance__year=annee,
        ).count() + 1
        numero = f"CERT-ENSMG-{abbrev}-{annee}-{seq:03d}"
        # Garantir l'unicité en cas de collision
        while Attestation.objects.filter(numero=numero).exists():
            seq += 1
            numero = f"CERT-ENSMG-{abbrev}-{annee}-{seq:03d}"

        # Créer l'attestation sans PDF — le PDF sera chargé manuellement
        Attestation.objects.create(
            inscription=inscription,
            numero=numero,
            date_delivrance=timezone.now().date(),
            contenu_pdf=None,
        )
        nb_ok += 1

    if nb_ok:
        messages.success(
            request,
            f"{nb_ok} apprenant(s) certifié(s). "
            "Téléchargez les QR codes, apposez-les sur vos documents, "
            "puis chargez les attestations PDF ci-dessous."
        )
    else:
        messages.info(request, "Tous les inscrits sélectionnés ont déjà une attestation.")
    return redirect("certifier_inscrits", pk=pk)


@login_required
def attestation_qr_download(request, pk):
    """Génère et télécharge le QR code de vérification d'une attestation (PNG)."""
    attestation = get_object_or_404(Attestation, pk=pk)
    verification_url = request.build_absolute_uri(
        f"/attestations/{attestation.numero}/verifier/"
    )
    try:
        import qrcode as _qrcode
        from PIL import Image as _PilImage

        qr = _qrcode.QRCode(
            version=2, box_size=12, border=4,
            error_correction=_qrcode.constants.ERROR_CORRECT_H,
        )
        qr.add_data(verification_url)
        qr.make(fit=True)

        # Générer en RGBA avec fond transparent et modules navy ENSMG
        # On passe par un masque : canal R de l'image N&B = masque d'opacité inversé
        qr_bw = qr.make_image(fill_color="black", back_color="white").convert("L")
        w, h = qr_bw.size
        # Canal alpha : 255 là où c'est foncé (module QR), 0 là où c'est blanc (fond)
        from PIL import ImageOps as _ops
        alpha = _ops.invert(qr_bw)           # blanc→noir (0), noir→blanc (255)
        alpha = alpha.point(lambda x: 0 if x < 128 else 255)  # seuillage propre

        qr_rgba = _PilImage.new("RGBA", (w, h), (13, 36, 97, 255))  # tout en navy
        qr_rgba.putalpha(alpha)                                        # fond transparent

        buf = io.BytesIO()
        qr_rgba.save(buf, format="PNG")
        buf.seek(0)
        nom = attestation.inscription.inscrit.nom_complet.replace(" ", "_")
        response = HttpResponse(buf.getvalue(), content_type="image/png")
        response["Content-Disposition"] = (
            f'attachment; filename="QR_{nom}_{attestation.numero}.png"'
        )
        return response
    except Exception as e:
        messages.error(request, f"Erreur QR : {e}")
        return redirect(request.META.get("HTTP_REFERER", "certifier_home"))


@login_required
def attestation_upload_pdf(request, pk):
    """Charge (ou remplace) le PDF d'une attestation existante."""
    attestation = get_object_or_404(Attestation, pk=pk)
    certif_pk = attestation.inscription.cohorte.certification.pk

    if request.method == "POST":
        pdf_file = request.FILES.get("pdf_file")
        if not pdf_file:
            messages.error(request, "Aucun fichier sélectionné.")
        elif not pdf_file.name.lower().endswith(".pdf"):
            messages.error(request, "Le fichier doit être au format PDF.")
        elif pdf_file.size > 20 * 1024 * 1024:
            messages.error(request, "Fichier trop volumineux (max 20 Mo).")
        else:
            attestation.contenu_pdf = pdf_file.read()
            attestation.save()

            # Notifier l'apprenant
            notifier_attestation(attestation)
            try:
                from .models import Notification
                inscrit = attestation.inscription.inscrit
                if hasattr(inscrit, "compte_apprenant"):
                    Notification.objects.create(
                        destinataire=inscrit.compte_apprenant,
                        type_notif="attestation_generee",
                        message=(
                            f"Votre attestation pour « {attestation.inscription.cohorte.certification.nom} » "
                            "est maintenant disponible en téléchargement."
                        ),
                        lien="/apprenant/attestations/",
                    )
            except Exception:
                pass
            _send_email_apprenant(
                attestation.inscription.inscrit,
                subject=(
                    f"[ENSMG] Votre attestation est disponible — "
                    f"{attestation.inscription.cohorte.certification.nom}"
                ),
                body=(
                    f"Bonjour {attestation.inscription.inscrit.prenom},\n\n"
                    f"Félicitations ! Votre attestation pour la certification "
                    f"« {attestation.inscription.cohorte.certification.nom} » "
                    f"est maintenant disponible en téléchargement.\n\n"
                    f"Connectez-vous à votre espace apprenant : "
                    f"https://ensmg.sn/apprenant/attestations/\n\n"
                    f"Numéro d'attestation : {attestation.numero}\n\n"
                    f"Cordialement,\nL'équipe ENSMG"
                ),
            )
            messages.success(
                request,
                f"PDF chargé avec succès pour {attestation.inscription.inscrit.nom_complet}."
            )

    return redirect("certifier_inscrits", pk=certif_pk)


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

def custom_logout(request):
    """Logout — accepts GET and POST, redirects to homepage."""
    from django.contrib.auth import logout as auth_logout
    auth_logout(request)
    return redirect('portail_accueil_home')


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
    # Username : prenom.nom@ensmg.sn (identifiant de connexion ENSMG)
    base_username = f"{_slugify_name(inscrit.prenom)}.{_slugify_name(inscrit.nom)}@ensmg.sn"
    username = base_username
    counter = 2
    while User.objects.filter(username=username).exists():
        name_part = base_username.replace('@ensmg.sn', '')
        username = f"{name_part}{counter}@ensmg.sn"
        counter += 1

    user = User.objects.create_user(
        username=username,
        email=inscrit.email or username,   # email personnel pour les notifications
        password='passer01',
        first_name=inscrit.prenom,
        last_name=inscrit.nom,
    )
    compte = CompteApprenant.objects.create(user=user, inscrit=inscrit, mdp_change=False)

    # Envoyer les identifiants par email si l'apprenant a une adresse email personnelle
    if inscrit.email:
        _send_email_apprenant(
            inscrit,
            subject="[ENSMG] Vos identifiants de connexion au portail",
            body=(
                f"Bonjour {inscrit.prenom},\n\n"
                f"Un compte a été créé pour vous sur le portail ENSMG.\n\n"
                f"Vos identifiants de connexion :\n"
                f"  Identifiant : {username}\n"
                f"  Mot de passe provisoire : passer01\n\n"
                f"Connectez-vous sur : https://ensmg.sn/login/\n"
                f"Vous serez invité(e) à changer votre mot de passe à la première connexion.\n\n"
                f"Cordialement,\nL'équipe ENSMG"
            ),
        )
    return user, compte


# ---------------------------------------------------------------------------
# Email utility
# ---------------------------------------------------------------------------

def _send_email_apprenant(inscrit, subject, body):
    """Send an email to an apprenant. Silently ignores errors (no email configured)."""
    if not inscrit.email:
        return
    try:
        from django.core.mail import send_mail
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[inscrit.email],
            fail_silently=True,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Portail public
# ---------------------------------------------------------------------------

def register_admin(request, key=""):
    """Page de création de compte admin — protégée par clé dans l'URL."""
    from django.conf import settings as _s
    from django.http import Http404
    register_key = _s.REGISTER_KEY
    if not register_key or key != register_key:
        raise Http404

    errors = {}
    form_data = {}

    if request.method == 'POST':
        prenom   = request.POST.get('prenom', '').strip()
        nom      = request.POST.get('nom', '').strip()
        email    = request.POST.get('email', '').strip().lower()
        password  = request.POST.get('password', '')
        password2 = request.POST.get('password2', '')
        form_data = {'prenom': prenom, 'nom': nom, 'email': email}

        if not prenom:
            errors['prenom'] = "Le prénom est obligatoire."
        if not nom:
            errors['nom'] = "Le nom est obligatoire."
        if not email:
            errors['email'] = "L'adresse email est obligatoire."
        elif User.objects.filter(username__iexact=email).exists() or User.objects.filter(email__iexact=email).exists():
            errors['email'] = "Un compte avec cet email existe déjà."
        if not password:
            errors['password'] = "Le mot de passe est obligatoire."
        elif len(password) < 6:
            errors['password'] = "Le mot de passe doit contenir au moins 6 caractères."
        if password and password != password2:
            errors['password2'] = "Les mots de passe ne correspondent pas."

        if not errors:
            user = User.objects.create_user(
                username=email,
                email=email,
                password=password,
                first_name=prenom,
                last_name=nom,
                is_staff=True,
                is_superuser=True,
            )
            messages.success(request, f"Compte créé avec succès ! Connectez-vous avec {email}.")
            return redirect('login')

    return render(request, 'inscriptions/register_admin.html', {
        'errors': errors,
        'form_data': form_data,
    })


def bootstrap_admin(request):
    """
    One-time bootstrap: creates admin account if it doesn't exist.
    Protected by BOOTSTRAP_KEY env var.
    Access: /bootstrap/?key=<BOOTSTRAP_KEY>
    Remove BOOTSTRAP_KEY env var after first use.
    """
    import os
    secret = os.environ.get('BOOTSTRAP_KEY', '')
    provided = request.GET.get('key', '')
    if not secret or provided != secret:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("Accès refusé.")

    username = 'admin@ensmg.sn'
    password = 'password'
    if User.objects.filter(username=username).exists():
        msg = f"✅ Compte déjà existant : {username}"
    else:
        User.objects.create_superuser(
            username=username, email=username, password=password,
            first_name='Admin', last_name='ENSMG',
        )
        msg = f"✅ Compte créé : {username} / {password}"
    from django.http import HttpResponse
    return HttpResponse(msg)


def portail_accueil(request):
    """Public landing page — redirect authenticated users to their space."""
    if request.user.is_authenticated:
        try:
            _ = request.user.compte_apprenant
            return redirect('espace_apprenant')
        except Exception:
            pass
        if request.user.is_staff or request.user.is_superuser:
            return redirect('dashboard')
    certifications = Certification.objects.filter(actif=True).order_by('nom')
    return render(request, 'inscriptions/portail_accueil.html', {
        'certifications': certifications,
    })


def portail_rejoindre(request, certif_pk):
    """
    Page d'inscription à une certification spécifique.
    Étape 0 : choix "J'ai un compte" / "Je suis nouveau"
    Étapes 1-4 : wizard inline (4 étapes de création de compte + inscription)
    """
    from .forms import WizardStep1Form, WizardStep2Form
    certification = get_object_or_404(Certification, pk=certif_pk, actif=True)

    # If already authenticated apprenant, redirect directly to inscription directe
    if request.user.is_authenticated:
        try:
            _ = request.user.compte_apprenant
            return redirect('apprenant_inscription_directe', certif_pk=certif_pk)
        except Exception:
            return redirect('dashboard')

    # Store certif in session for multi-step navigation
    request.session['rejoindre_certif_id'] = certif_pk
    cohortes = Cohorte.objects.filter(certification=certification, actif=True).order_by('nom')

    # ------------------------------------------------------------------
    # POST handlers
    # ------------------------------------------------------------------
    if request.method == 'POST':
        action = request.POST.get('action', '')

        # ---- Login ----
        if action == 'login':
            from django.contrib.auth import authenticate, login as auth_login
            username = request.POST.get('username', '').strip()
            password = request.POST.get('password', '').strip()
            # Support email OR username
            if '@' in username:
                try:
                    username = User.objects.get(email__iexact=username).username
                except User.DoesNotExist:
                    pass
            user = authenticate(request, username=username, password=password)
            if user and user.is_active:
                auth_login(request, user)
                try:
                    _ = user.compte_apprenant
                    return redirect('apprenant_inscription_directe', certif_pk=certif_pk)
                except Exception:
                    return redirect('dashboard')
            # Login failed
            return render(request, 'inscriptions/portail_rejoindre.html', {
                'certification': certification,
                'cohortes': cohortes,
                'panel': 'login',
                'error_login': True,
            })

        # ---- Wizard step 1 ----
        elif action == 'wizard_step1':
            form = WizardStep1Form(request.POST)
            if form.is_valid():
                request.session['wizard_step1'] = form.cleaned_data
                return redirect(f'/portail/rejoindre/{certif_pk}/?step=2')
            return render(request, 'inscriptions/portail_rejoindre.html', {
                'certification': certification,
                'cohortes': cohortes,
                'panel': 'wizard',
                'wizard_step': 1,
                'form_step1': form,
            })

        # ---- Wizard step 2 ----
        elif action == 'wizard_step2':
            if not request.session.get('wizard_step1'):
                return redirect(f'/portail/rejoindre/{certif_pk}/?step=1')
            form = WizardStep2Form(request.POST)
            if form.is_valid():
                request.session['wizard_step2'] = form.cleaned_data
                return redirect(f'/portail/rejoindre/{certif_pk}/?step=3')
            return render(request, 'inscriptions/portail_rejoindre.html', {
                'certification': certification,
                'cohortes': cohortes,
                'panel': 'wizard',
                'wizard_step': 2,
                'form_step2': form,
            })

        # ---- Wizard step 3 ----
        elif action == 'wizard_step3':
            if not request.session.get('wizard_step2'):
                return redirect(f'/portail/rejoindre/{certif_pk}/?step=1')
            cohorte_id = request.POST.get('cohorte_id', '').strip()
            cohorte_sel = None
            if cohorte_id:
                try:
                    cohorte_sel = Cohorte.objects.get(pk=cohorte_id, certification=certification, actif=True)
                except Cohorte.DoesNotExist:
                    pass
            if cohorte_sel:
                request.session['wizard_step3'] = {'cohorte_id': cohorte_sel.pk}
                return redirect(f'/portail/rejoindre/{certif_pk}/?step=4')
            return render(request, 'inscriptions/portail_rejoindre.html', {
                'certification': certification,
                'cohortes': cohortes,
                'panel': 'wizard',
                'wizard_step': 3,
                'cohorte_error': "Veuillez sélectionner une session disponible.",
            })

        # ---- Wizard step 4 (final) ----
        elif action == 'wizard_step4':
            step1 = request.session.get('wizard_step1')
            step2 = request.session.get('wizard_step2')
            step3_data = request.session.get('wizard_step3')
            if not all([step1, step2, step3_data]):
                return redirect(f'/portail/rejoindre/{certif_pk}/?step=1')
            try:
                cohorte_obj = Cohorte.objects.select_related('certification').get(pk=step3_data['cohorte_id'])
            except Cohorte.DoesNotExist:
                return redirect(f'/portail/rejoindre/{certif_pk}/?step=3')

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
                    nom=step1['nom'], prenom=step1['prenom'],
                    email=email, telephone=step1['telephone'],
                    adresse=step1.get('adresse', ''), activite=activite,
                    source='portail', universite=step2.get('universite', ''),
                    entreprise=step2.get('entreprise', ''),
                )

            montant_du = float(
                cohorte_obj.certification.tarif_professionnel if activite == 'professionnel'
                else cohorte_obj.certification.tarif_etudiant
            )
            inscription, created = Inscription.objects.get_or_create(
                inscrit=inscrit, cohorte=cohorte_obj,
                defaults={'statut': 'pre_inscrit', 'montant_du': montant_du},
            )
            if created:
                notifier_inscription(inscription)

            if not CompteApprenant.objects.filter(inscrit=inscrit).exists():
                user, compte = _creer_compte_apprenant(inscrit)
            else:
                compte = inscrit.compte_apprenant
                user = compte.user

            from django.contrib.auth import login as auth_login
            user.backend = 'django.contrib.auth.backends.ModelBackend'
            auth_login(request, user)

            for k in ['wizard_step1', 'wizard_step2', 'wizard_step3', 'rejoindre_certif_id']:
                request.session.pop(k, None)

            request.session['pending_inscription_id'] = inscription.pk
            request.session['new_compte_username'] = user.username
            return redirect('portail_paiement', pk=inscription.pk)

    # ------------------------------------------------------------------
    # GET handlers
    # ------------------------------------------------------------------
    step = int(request.GET.get('step', 0))
    panel = request.GET.get('panel', '')  # 'login' | 'wizard' | ''

    if step == 1 or panel == 'wizard':
        from .forms import WizardStep1Form
        initial = request.session.get('wizard_step1', {})
        return render(request, 'inscriptions/portail_rejoindre.html', {
            'certification': certification, 'cohortes': cohortes,
            'panel': 'wizard', 'wizard_step': 1,
            'form_step1': WizardStep1Form(initial=initial),
        })
    elif step == 2:
        if not request.session.get('wizard_step1'):
            return redirect(f'/portail/rejoindre/{certif_pk}/?step=1')
        from .forms import WizardStep2Form
        initial = request.session.get('wizard_step2', {})
        return render(request, 'inscriptions/portail_rejoindre.html', {
            'certification': certification, 'cohortes': cohortes,
            'panel': 'wizard', 'wizard_step': 2,
            'form_step2': WizardStep2Form(initial=initial),
        })
    elif step == 3:
        if not request.session.get('wizard_step2'):
            return redirect(f'/portail/rejoindre/{certif_pk}/?step=1')
        return render(request, 'inscriptions/portail_rejoindre.html', {
            'certification': certification, 'cohortes': cohortes,
            'panel': 'wizard', 'wizard_step': 3,
        })
    elif step == 4:
        step1 = request.session.get('wizard_step1', {})
        step2 = request.session.get('wizard_step2', {})
        step3_data = request.session.get('wizard_step3', {})
        if not all([step1, step2, step3_data]):
            return redirect(f'/portail/rejoindre/{certif_pk}/?step=1')
        try:
            cohorte_obj = Cohorte.objects.select_related('certification').get(pk=step3_data['cohorte_id'])
        except Cohorte.DoesNotExist:
            return redirect(f'/portail/rejoindre/{certif_pk}/?step=3')
        activite = step2.get('activite', 'etudiant')
        tarif = float(
            cohorte_obj.certification.tarif_professionnel if activite == 'professionnel'
            else cohorte_obj.certification.tarif_etudiant
        )
        return render(request, 'inscriptions/portail_rejoindre.html', {
            'certification': certification, 'cohortes': cohortes,
            'panel': 'wizard', 'wizard_step': 4,
            'step1': step1, 'step2': step2, 'cohorte': cohorte_obj, 'tarif': tarif,
        })

    # Default: choice page
    from .forms import WizardStep1Form
    return render(request, 'inscriptions/portail_rejoindre.html', {
        'certification': certification,
        'cohortes': cohortes,
        'panel': 'login' if panel == 'login' else '',
        'wizard_step': 0,
        'form_step1': WizardStep1Form(),
        'error_login': False,
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
                defaults={'statut': 'pre_inscrit', 'montant_du': montant_du},
            )
            if created:
                notifier_inscription(inscription)

            if not CompteApprenant.objects.filter(inscrit=inscrit).exists():
                user, compte = _creer_compte_apprenant(inscrit)
            else:
                compte = inscrit.compte_apprenant
                user = compte.user

            # Détecter si c'est un staff qui enregistre l'apprenant
            is_staff_registrant = request.user.is_authenticated and (
                request.user.is_staff or request.user.is_superuser
            )
            if is_staff_registrant:
                # Staff : on note en session pour adapter la page finale
                request.session['wizard_by_staff'] = True
            else:
                # Auto-login : connecte l'apprenant automatiquement
                from django.contrib.auth import login as auth_login
                user.backend = 'django.contrib.auth.backends.ModelBackend'
                auth_login(request, user)

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
        cohortes_data = [
            {'id': co.pk, 'nom': co.nom, 'certif_id': co.certification_id,
             'certif_nom': co.certification.nom}
            for co in Cohorte.objects.select_related('certification')
                                     .filter(certification__actif=True)
                                     .order_by('certification__nom', 'nom')
        ]
        return render(request, 'inscriptions/portail_wizard.html', {
            'step': 3, 'form': form, 'certifications': certifications,
            'certif_tarifs_json': json.dumps(certif_tarifs),
            'cohortes_json': json.dumps(cohortes_data),
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
                defaults={"statut": "pre_inscrit", "montant_du": montant_du},
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
            is_staff_reg = request.session.pop('wizard_by_staff', False)
            skip_redirect = request.session.pop('paiement_skip_redirect', None)
            request.session.pop('pending_inscription_id', None)
            if not is_staff_reg and skip_redirect == 'espace_apprenant':
                return redirect('espace_apprenant')
            return render(request, 'inscriptions/portail_confirmation.html', {
                'inscription': inscription,
                'username': request.session.get('new_compte_username', ''),
                'moyen': 'plus_tard',
                'is_staff_reg': is_staff_reg,
            })

        moyen = request.POST.get('moyen_paiement', '')
        reference = request.POST.get('reference_virement', '').strip()

        # ── WAVE : vrai checkout via l'API Wave Business ──────────────────
        if moyen == 'wave':
            import requests as http_requests
            wave_api_key = getattr(settings, 'WAVE_API_KEY', '')
            if not wave_api_key:
                messages.error(request, "Paiement Wave non configuré. Contactez l'administration.")
                return redirect('portail_paiement', pk=inscription.pk)

            client_ref = f"INS-{inscription.pk:06d}-{uuid.uuid4().hex[:6].upper()}"
            success_url = request.build_absolute_uri(f'/portail/paiement/{inscription.pk}/wave-retour/?ref={client_ref}&statut=succes')
            error_url   = request.build_absolute_uri(f'/portail/paiement/{inscription.pk}/wave-retour/?ref={client_ref}&statut=echec')

            try:
                resp = http_requests.post(
                    'https://api.wave.com/v1/checkout/sessions',
                    headers={
                        'Authorization': f'Bearer {wave_api_key}',
                        'Content-Type': 'application/json',
                    },
                    json={
                        'amount': str(int(inscription.montant_du)),
                        'currency': 'XOF',
                        'client_reference': client_ref,
                        'success_url': success_url,
                        'error_url': error_url,
                    },
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
                wave_url = data.get('wave_launch_url') or data.get('checkout_url')
                if not wave_url:
                    raise ValueError("Pas d'URL de paiement dans la réponse Wave.")
                # Enregistrer la session en attente
                Paiement.objects.create(
                    inscription=inscription,
                    montant=inscription.montant_du,
                    date_paiement=timezone.now().date(),
                    moyen_paiement='wave',
                    reference=client_ref,
                    statut='en_attente',
                    notes=f"Session Wave: {data.get('id', '')}",
                )
                return redirect(wave_url)
            except Exception as e:
                messages.error(request, f"Erreur lors de l'initiation du paiement Wave : {e}")
                return redirect('portail_paiement', pk=inscription.pk)

        # ── ORANGE MONEY : déclaration de transaction réelle ──────────────
        elif moyen == 'orange_money':
            txn_id = request.POST.get('txn_id', '').strip()
            numero = request.POST.get('numero_mobile', '').strip()
            if not txn_id:
                messages.error(request, "Veuillez saisir l'identifiant de transaction Orange Money.")
                return redirect('portail_paiement', pk=inscription.pk)
            Paiement.objects.create(
                inscription=inscription,
                montant=inscription.montant_du,
                date_paiement=timezone.now().date(),
                moyen_paiement='orange_money',
                reference=txn_id,
                statut='en_attente',
                notes=f"N° Orange Money : {numero} — Réf. transaction : {txn_id}",
            )
            messages.success(request, "Transaction Orange Money déclarée. L'administration vérifiera et confirmera votre inscription.")

        # ── INTOUCH : checkout hébergé ────────────────────────────────────
        elif moyen == 'intouch':
            import requests as http_requests
            paytech_key    = getattr(settings, 'PAYTECH_API_KEY', '')
            paytech_secret = getattr(settings, 'PAYTECH_API_SECRET', '')
            if not paytech_key or not paytech_secret:
                messages.error(request, "Paiement InTouch non configuré. Contactez l'administration.")
                return redirect('portail_paiement', pk=inscription.pk)

            client_ref  = f"INS-{inscription.pk:06d}-{uuid.uuid4().hex[:6].upper()}"
            success_url = request.build_absolute_uri(
                f'/portail/paiement/{inscription.pk}/intouch-retour/?ref={client_ref}&statut=succes')
            cancel_url  = request.build_absolute_uri(
                f'/portail/paiement/{inscription.pk}/intouch-retour/?ref={client_ref}&statut=echec')
            ipn_url     = request.build_absolute_uri(
                f'/portail/paiement/{inscription.pk}/intouch-ipn/')

            try:
                resp = http_requests.post(
                    'https://paytech.sn/api/payment/request-payment',
                    headers={
                        'API_KEY':    paytech_key,
                        'API_SECRET': paytech_secret,
                        'Content-Type': 'application/json',
                    },
                    json={
                        'item_name':    f"Inscription {inscription.cohorte.certification.nom}",
                        'item_price':   int(inscription.montant_du),
                        'ref_command':  client_ref,
                        'command_name': f"Inscription ENSMG — {inscription.cohorte.nom}",
                        'currency':     'XOF',
                        'env':          'prod',
                        'ipn_url':      ipn_url,
                        'success_url':  success_url,
                        'cancel_url':   cancel_url,
                    },
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
                redirect_url = data.get('redirect_url')
                token        = data.get('token', '')
                if not redirect_url:
                    raise ValueError("Pas d'URL de paiement dans la réponse InTouch.")
                Paiement.objects.create(
                    inscription=inscription,
                    montant=inscription.montant_du,
                    date_paiement=timezone.now().date(),
                    moyen_paiement='intouch',
                    reference=client_ref,
                    statut='en_attente',
                    notes=f"Token InTouch: {token}",
                )
                return redirect(redirect_url)
            except Exception as e:
                messages.error(request, f"Erreur lors de l'initiation du paiement InTouch : {e}")
                return redirect('portail_paiement', pk=inscription.pk)

        # ── VIREMENT bancaire ─────────────────────────────────────────────
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
            messages.success(request, "Virement déclaré. L'administration le vérifiera et confirmera votre inscription.")

        is_staff_reg = request.session.pop('wizard_by_staff', False)
        request.session.pop('pending_inscription_id', None)

        return render(request, 'inscriptions/portail_confirmation.html', {
            'inscription': inscription,
            'username': username,
            'moyen': moyen,
            'is_staff_reg': is_staff_reg,
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
        'wave_configured':    bool(getattr(settings, 'WAVE_API_KEY', '')),
        'intouch_configured': bool(getattr(settings, 'PAYTECH_API_KEY', '') and
                                   getattr(settings, 'PAYTECH_API_SECRET', '')),
    })


def portail_wave_retour(request, pk):
    """Page de retour après paiement Wave (success_url / error_url)."""
    inscription = get_object_or_404(Inscription, pk=pk)
    statut = request.GET.get('statut', 'echec')
    ref    = request.GET.get('ref', '')

    if statut == 'succes':
        # Marquer le paiement Wave en_attente comme confirmé (le webhook
        # confirmera définitivement, mais on peut pré-confirmer ici)
        paiement = Paiement.objects.filter(
            inscription=inscription,
            reference=ref,
            moyen_paiement='wave',
        ).first()
        if paiement and paiement.statut == 'en_attente':
            paiement.statut = 'confirme'
            paiement.save(update_fields=['statut'])
            if inscription.statut == 'pre_inscrit':
                inscription.statut = 'inscrit'
                inscription.save(update_fields=['statut'])
            notifier_paiement_confirme(paiement)
        messages.success(request, "Paiement Wave confirmé ! Votre inscription est validée.")
    else:
        messages.error(request, "Le paiement Wave a échoué ou a été annulé.")

    username = request.session.get('new_compte_username', '')
    is_staff_reg = request.session.pop('wizard_by_staff', False)
    return render(request, 'inscriptions/portail_confirmation.html', {
        'inscription': inscription,
        'username': username,
        'moyen': 'wave',
        'wave_succes': statut == 'succes',
        'is_staff_reg': is_staff_reg,
    })


def portail_intouch_retour(request, pk):
    """Retour navigateur après paiement InTouch (success_url / cancel_url)."""
    inscription = get_object_or_404(Inscription, pk=pk)
    statut = request.GET.get('statut', 'echec')
    ref    = request.GET.get('ref', '')

    if statut == 'succes':
        paiement = Paiement.objects.filter(
            inscription=inscription,
            reference=ref,
            moyen_paiement='intouch',
        ).first()
        if paiement and paiement.statut == 'en_attente':
            paiement.statut = 'confirme'
            paiement.save(update_fields=['statut'])
            if inscription.statut == 'pre_inscrit':
                inscription.statut = 'inscrit'
                inscription.save(update_fields=['statut'])
            notifier_paiement_confirme(paiement)
        messages.success(request, "Paiement InTouch confirmé ! Votre inscription est validée.")
    else:
        messages.error(request, "Le paiement a été annulé ou a échoué.")

    username = request.session.get('new_compte_username', '')
    is_staff_reg = request.session.pop('wizard_by_staff', False)
    return render(request, 'inscriptions/portail_confirmation.html', {
        'inscription': inscription,
        'username': username,
        'moyen': 'intouch',
        'intouch_succes': statut == 'succes',
        'is_staff_reg': is_staff_reg,
    })


# Keep backward-compatible alias
portail_paytech_retour = portail_intouch_retour


@csrf_exempt
def portail_intouch_ipn(request, pk):
    """Webhook IPN InTouch — confirmation serveur-à-serveur."""
    if request.method != 'POST':
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(['POST'])

    inscription = get_object_or_404(Inscription, pk=pk)
    ref_command = request.POST.get('ref_command', '')
    type_event  = request.POST.get('type_event', '')

    if type_event == 'sale_complete' and ref_command:
        paiement = Paiement.objects.filter(
            inscription=inscription,
            reference=ref_command,
            moyen_paiement='intouch',
        ).first()
        if paiement and paiement.statut == 'en_attente':
            paiement.statut = 'confirme'
            paiement.save(update_fields=['statut'])
            if inscription.statut == 'pre_inscrit':
                inscription.statut = 'inscrit'
                inscription.save(update_fields=['statut'])
            notifier_paiement_confirme(paiement)

    from django.http import JsonResponse
    return JsonResponse({'status': 'ok'})


# Keep backward-compatible alias
portail_paytech_ipn = portail_intouch_ipn


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
    _auto_transition_statuts()
    compte = request.user.compte_apprenant
    inscrit = compte.inscrit

    inscriptions = list(
        inscrit.inscriptions
        .select_related('cohorte__certification')
        .prefetch_related('paiements', 'attestations')
        .order_by('-date_inscription')
    )

    total_du = sum(i.montant_du for i in inscriptions)
    total_paye = sum(i.total_paye for i in inscriptions)
    total_restant = max(total_du - total_paye, 0)
    nb_certifies = sum(1 for i in inscriptions if i.statut == 'certifie')

    # Collect all payments sorted by date desc
    all_paiements = []
    for ins in inscriptions:
        for p in ins.paiements.all():
            all_paiements.append(p)
    all_paiements.sort(key=lambda p: p.date_paiement, reverse=True)
    recent_paiements = all_paiements[:5]

    # Pending payments
    paiements_en_attente = [p for p in all_paiements if p.statut == 'en_attente']

    from .models import Notification
    notifications_recentes = Notification.objects.filter(
        destinataire=compte
    ).order_by('-date_creation')[:5]
    nb_notifs_non_lues = Notification.objects.filter(
        destinataire=compte, lu=False
    ).count()

    # Available certifications (exclude only those where already certified)
    certif_ids_certifiees = set(
        i.cohorte.certification_id for i in inscriptions if i.statut == 'certifie'
    )
    certifs_disponibles = Certification.objects.filter(
        actif=True
    ).exclude(pk__in=certif_ids_certifiees).count()

    # Inscriptions with balance due
    inscriptions_a_payer = [i for i in inscriptions if i.reste_a_payer > 0]

    context = {
        'compte': compte,
        'inscrit': inscrit,
        'inscriptions': inscriptions,
        'total_du': total_du,
        'total_paye': total_paye,
        'total_restant': total_restant,
        'nb_certifies': nb_certifies,
        'recent_paiements': recent_paiements,
        'paiements_en_attente': paiements_en_attente,
        'notifications_recentes': notifications_recentes,
        'nb_notifs_non_lues': nb_notifs_non_lues,
        'certifs_disponibles': certifs_disponibles,
        'inscriptions_a_payer': inscriptions_a_payer,
        'active_page': 'espace',
    }
    return render(request, 'inscriptions/apprenant_dashboard.html', context)


@_apprenant_required
def apprenant_paiements(request):
    """Dedicated paiements list page for the apprenant."""
    compte = request.user.compte_apprenant
    inscrit = compte.inscrit
    inscriptions = (
        inscrit.inscriptions
        .select_related('cohorte__certification')
        .prefetch_related('paiements')
        .order_by('-date_inscription')
    )
    paiements = []
    for ins in inscriptions:
        for p in ins.paiements.all():
            paiements.append({'paiement': p, 'inscription': ins})
    return render(request, 'inscriptions/apprenant_paiements.html', {
        'compte': compte,
        'inscrit': inscrit,
        'paiements': paiements,
        'active_page': 'paiements',
    })


@_apprenant_required
def apprenant_attestations(request):
    """Dedicated attestations list page for the apprenant."""
    compte = request.user.compte_apprenant
    inscrit = compte.inscrit
    inscriptions = (
        inscrit.inscriptions
        .select_related('cohorte__certification')
        .prefetch_related('attestations')
        .order_by('-date_inscription')
    )
    attestations = []
    for ins in inscriptions:
        for att in ins.attestations.all():
            attestations.append({'attestation': att, 'inscription': ins})
    return render(request, 'inscriptions/apprenant_attestations.html', {
        'compte': compte,
        'inscrit': inscrit,
        'attestations': attestations,
        'active_page': 'attestations',
    })


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
            # Logout so user must login with new password
            from django.contrib.auth import logout as auth_logout
            auth_logout(request)
            messages.success(request, "Mot de passe changé avec succès. Veuillez vous reconnecter.")
            return redirect('login')
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


def apprenant_certifications(request):
    """Liste des certifications disponibles pour l'apprenant."""
    _auto_transition_statuts()
    try:
        compte = request.user.compte_apprenant
        inscrit = compte.inscrit
    except Exception:
        return redirect('login')

    from .models import Notification
    nb_notifs_non_lues = Notification.objects.filter(
        destinataire=compte, lu=False
    ).count()

    # Exclure les certifications pour lesquelles l'apprenant a déjà le statut certifie
    certif_ids_obtenues = Inscription.objects.filter(
        inscrit=inscrit, statut='certifie'
    ).values_list('cohorte__certification_id', flat=True)

    certifs_actives = Certification.objects.filter(actif=True).exclude(
        pk__in=certif_ids_obtenues
    ).order_by('nom')
    certifs_inactives = Certification.objects.filter(actif=False).exclude(
        pk__in=certif_ids_obtenues
    ).order_by('nom')

    return render(request, 'inscriptions/apprenant_certifications.html', {
        'compte': compte,
        'inscrit': inscrit,
        'certifs_actives': certifs_actives,
        'certifs_inactives': certifs_inactives,
        'active_page': 'certifications',
        'nb_notifs_non_lues': nb_notifs_non_lues,
    })


def apprenant_inscription_directe(request, certif_pk):
    """Authenticated apprenant registers directly for a certification (skips portail wizard)."""
    try:
        compte = request.user.compte_apprenant
        inscrit = compte.inscrit
    except Exception:
        return redirect('login')

    certification = get_object_or_404(Certification, pk=certif_pk, actif=True)

    # Find the first active cohorte for this certification
    cohorte = Cohorte.objects.filter(
        certification=certification, actif=True
    ).order_by('date_debut').first()

    from .models import Notification
    nb_notifs_non_lues = Notification.objects.filter(
        destinataire=compte, lu=False
    ).count()

    errors = {}

    if request.method == 'POST':
        cohorte_id = request.POST.get('cohorte_id', '').strip()
        if cohorte_id:
            try:
                cohorte = Cohorte.objects.get(pk=cohorte_id, certification=certification, actif=True)
            except Cohorte.DoesNotExist:
                errors['cohorte'] = "Cohorte invalide."
        if not cohorte:
            errors['cohorte'] = "Aucune session disponible pour cette certification."

        if not errors:
            activite = inscrit.activite
            montant_du = float(
                certification.tarif_professionnel if activite == 'professionnel'
                else certification.tarif_etudiant
            )
            inscription, created = Inscription.objects.get_or_create(
                inscrit=inscrit,
                cohorte=cohorte,
                defaults={'statut': 'pre_inscrit', 'montant_du': montant_du},
            )
            if created:
                notifier_inscription(inscription)

            action = request.POST.get('action', 'payer')
            if action == 'sans_payer':
                messages.success(request, f"Inscription à « {certification.nom} » confirmée. Vous pourrez payer plus tard depuis votre espace.")
                return redirect('espace_apprenant')

            request.session['pending_inscription_id'] = inscription.pk
            request.session['paiement_skip_redirect'] = 'espace_apprenant'
            request.session.pop('new_compte_username', None)
            return redirect('portail_paiement', pk=inscription.pk)

    cohortes = Cohorte.objects.filter(certification=certification, actif=True).order_by('nom')

    return render(request, 'inscriptions/apprenant_inscription_directe.html', {
        'compte': compte,
        'inscrit': inscrit,
        'certification': certification,
        'cohorte': cohorte,
        'cohortes': cohortes,
        'errors': errors,
        'active_page': 'certifications',
        'nb_notifs_non_lues': nb_notifs_non_lues,
    })


def apprenant_notifications(request):
    """Liste et gestion des notifications de l'apprenant."""
    try:
        compte = request.user.compte_apprenant
        inscrit = compte.inscrit
    except Exception:
        return redirect('login')

    from .models import Notification

    if request.method == 'POST' and request.POST.get('marquer_tout_lu'):
        Notification.objects.filter(destinataire=compte, lu=False).update(lu=True)
        messages.success(request, "Toutes les notifications marquées comme lues.")
        return redirect('apprenant_notifications')

    notifs = Notification.objects.filter(destinataire=compte).order_by('-date_creation')
    nb_notifs_non_lues = notifs.filter(lu=False).count()

    # Marquer comme lues les notifications affichées
    notifs.filter(lu=False).update(lu=True)

    return render(request, 'inscriptions/apprenant_notifications.html', {
        'compte': compte,
        'inscrit': inscrit,
        'notifs': notifs,
        'active_page': 'notifications',
        'nb_notifs_non_lues': 0,
    })


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
        # Pré-inscrit ayant confirmé son paiement → passe en "Inscrit"
        inscription = paiement.inscription
        if inscription.statut == 'pre_inscrit':
            inscription.statut = 'inscrit'
            inscription.save(update_fields=['statut'])
        notifier_paiement_confirme(paiement)
        # Send notification + email to apprenant
        try:
            from .models import Notification
            if hasattr(inscription.inscrit, 'compte_apprenant'):
                Notification.objects.create(
                    destinataire=inscription.inscrit.compte_apprenant,
                    type_notif='paiement_confirme',
                    message=f"Votre paiement de {paiement.montant} FCFA pour « {inscription.cohorte.certification.nom} » a été confirmé. Votre inscription est validée.",
                    lien='/apprenant/paiements/',
                )
        except Exception:
            pass
        _send_email_apprenant(
            inscription.inscrit,
            subject=f"[ENSMG] Paiement confirmé — {inscription.cohorte.certification.nom}",
            body=(
                f"Bonjour {inscription.inscrit.prenom},\n\n"
                f"Votre paiement de {paiement.montant} FCFA pour la certification "
                f"« {inscription.cohorte.certification.nom} » a été confirmé.\n\n"
                f"Votre inscription est maintenant validée. Vous pouvez accéder à votre espace apprenant : "
                f"https://ensmg.sn/apprenant/\n\n"
                f"Cordialement,\nL'équipe ENSMG"
            ),
        )
        messages.success(request, f"Paiement de {paiement.montant} FCFA confirmé. Statut mis à jour : Inscrit.")
        return redirect('paiements_list')
    return render(request, 'inscriptions/confirmer_paiement.html', {'paiement': paiement})


@login_required
def admin_annuler_paiement(request, pk):
    """Admin cancels/rejects a pending payment."""
    paiement = get_object_or_404(Paiement, pk=pk)
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "Accès refusé.")
        return redirect('dashboard')
    if request.method == 'POST':
        motif = request.POST.get('motif', '').strip()
        paiement.statut = 'annule'
        paiement.notes = (paiement.notes or '') + f"\n[Annulé par admin: {motif}]"
        paiement.save()
        inscription = paiement.inscription
        # Send notification + email
        try:
            from .models import Notification
            if hasattr(inscription.inscrit, 'compte_apprenant'):
                Notification.objects.create(
                    destinataire=inscription.inscrit.compte_apprenant,
                    type_notif='paiement_annule',
                    message=f"Votre paiement de {paiement.montant} FCFA pour « {inscription.cohorte.certification.nom} » a été annulé.{' Motif : ' + motif if motif else ''}",
                    lien='/apprenant/paiements/',
                )
        except Exception:
            pass
        _send_email_apprenant(
            inscription.inscrit,
            subject=f"[ENSMG] Paiement annulé — {inscription.cohorte.certification.nom}",
            body=(
                f"Bonjour {inscription.inscrit.prenom},\n\n"
                f"Votre paiement de {paiement.montant} FCFA pour la certification "
                f"« {inscription.cohorte.certification.nom} » a été annulé par l'administration.\n\n"
                f"{'Motif : ' + motif + chr(10) + chr(10) if motif else ''}"
                f"Pour toute question, contactez-nous à admin@ensmg.sn\n\n"
                f"Cordialement,\nL'équipe ENSMG"
            ),
        )
        messages.warning(request, f"Paiement de {paiement.montant} FCFA annulé.")
        return redirect('paiements_list')
    return render(request, 'inscriptions/annuler_paiement.html', {'paiement': paiement})


@login_required
def api_inscription_solde(request):
    """Returns reste_a_payer for a given inscription pk (used in paiement form)."""
    pk = request.GET.get('pk')
    if not pk:
        from django.http import JsonResponse
        return JsonResponse({'error': 'missing pk'}, status=400)
    try:
        ic = Inscription.objects.select_related(
            'cohorte__certification', 'inscrit'
        ).prefetch_related('paiements').get(pk=pk)
        from django.http import JsonResponse
        return JsonResponse({
            'reste_a_payer': float(ic.reste_a_payer),
            'montant_du': float(ic.montant_du),
            'total_paye': float(ic.total_paye),
            'nom_inscrit': ic.inscrit.nom_complet,
            'activite': ic.inscrit.activite,
        })
    except Inscription.DoesNotExist:
        from django.http import JsonResponse
        return JsonResponse({'error': 'not found'}, status=404)


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
    story.append(Paragraph("ÉCOLE NATIONALE SUPÉRIEURE DES MINES ET DE LA GÉOLOGIE", s_title))
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
    story.append(Paragraph("Ce document atteste du paiement effectué auprès de l'École Nationale Supérieure des Mines et de la Géologie.", s_footer))
    story.append(Paragraph("ENSMG — École Nationale Supérieure des Mines et de la Géologie — Dakar, Sénégal — www.ensmg.sn", s_footer))

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


@login_required
def recu_view(request, pk):
    """View payment receipt PDF inline in the browser."""
    paiement = get_object_or_404(Paiement, pk=pk)
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
    response["Content-Disposition"] = f'inline; filename="recu_{nom}_{paiement.pk}.pdf"'
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
    total_du = Inscription.objects.aggregate(t=Sum('montant_du'))['t'] or 0
    total_inscrits = Inscription.objects.count()
    total_certifies = Inscription.objects.filter(statut='certifie').count()
    taux_certif = int((total_certifies / total_inscrits * 100)) if total_inscrits else 0
    taux_recouvrement = int((float(total_encaisse) / float(total_du) * 100)) if total_du else 0
    nb_paiements_confirmes = Paiement.objects.filter(statut='confirme').count()
    montant_moyen = int(float(total_encaisse) / nb_paiements_confirmes) if nb_paiements_confirmes else 0

    # Current month vs last month
    from datetime import date
    first_day_this_month = today.replace(day=1)
    last_month_end = first_day_this_month - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    revenue_this_month = Paiement.objects.filter(
        statut='confirme', date_paiement__gte=first_day_this_month
    ).aggregate(t=Sum('montant'))['t'] or 0
    revenue_last_month = Paiement.objects.filter(
        statut='confirme',
        date_paiement__gte=last_month_start,
        date_paiement__lte=last_month_end,
    ).aggregate(t=Sum('montant'))['t'] or 0
    growth_pct = 0
    if revenue_last_month:
        growth_pct = int(((float(revenue_this_month) - float(revenue_last_month)) / float(revenue_last_month)) * 100)

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
        'total_du': total_du,
        'total_inscrits': total_inscrits,
        'total_certifies': total_certifies,
        'taux_certif': taux_certif,
        'taux_recouvrement': taux_recouvrement,
        'nb_paiements_confirmes': nb_paiements_confirmes,
        'montant_moyen': montant_moyen,
        'revenue_this_month': revenue_this_month,
        'revenue_last_month': revenue_last_month,
        'growth_pct': growth_pct,
        'months_labels_json': json.dumps(months_labels),
        'months_values_json': json.dumps(months_values),
        'moyen_labels_json': json.dumps(moyen_labels),
        'moyen_values_json': json.dumps(moyen_values),
        'stats_certifs': stats_certifs,
        'paiements_en_attente': paiements_en_attente,
        'active_page': 'dashboard_financier',
    }
    return render(request, 'inscriptions/dashboard_financier.html', context)
