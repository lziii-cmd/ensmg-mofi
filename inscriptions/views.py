from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.db.models import Sum, Count, Q
from django.utils import timezone
import openpyxl

from .models import Certification, Inscrit, InscriptionCertification, Paiement
from .forms import (
    CertificationForm,
    InscritForm,
    InscriptionCertificationForm,
    ChangerStatutForm,
    PaiementForm,
    PaiementInscriptionForm,
    ImportExcelForm,
)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def dashboard(request):
    nb_certifications = Certification.objects.count()
    nb_inscrits = Inscrit.objects.count()
    total_encaisse = Paiement.objects.aggregate(total=Sum("montant"))["total"] or 0

    nb_certifies = InscriptionCertification.objects.filter(statut="certifie").count()
    taux_certification = 0
    total_inscriptions = InscriptionCertification.objects.count()
    if total_inscriptions > 0:
        taux_certification = int((nb_certifies / total_inscriptions) * 100)

    # Stats per status
    stats_statut = (
        InscriptionCertification.objects
        .values("statut")
        .annotate(count=Count("id"))
        .order_by("statut")
    )
    stats_statut_dict = {s["statut"]: s["count"] for s in stats_statut}

    # Stats per certification
    certifications = Certification.objects.prefetch_related(
        "inscriptions__paiements"
    ).order_by("-created_at")

    stats_certifications = []
    for cert in certifications:
        stats_certifications.append({
            "certification": cert,
            "nb_inscrits": cert.nb_inscrits,
            "nb_en_formation": cert.nb_en_formation,
            "nb_certifies": cert.nb_certifies,
            "montant_encaisse": cert.montant_encaisse,
        })

    # Recent payments
    paiements_recents = (
        Paiement.objects
        .select_related("inscription__inscrit", "inscription__certification")
        .order_by("-date_paiement", "-created_at")[:8]
    )

    # Recent inscrits
    inscrits_recents = Inscrit.objects.order_by("-date_inscription")[:5]

    context = {
        "nb_certifications": nb_certifications,
        "nb_inscrits": nb_inscrits,
        "total_encaisse": total_encaisse,
        "taux_certification": taux_certification,
        "stats_statut_dict": stats_statut_dict,
        "stats_certifications": stats_certifications,
        "paiements_recents": paiements_recents,
        "inscrits_recents": inscrits_recents,
        "active_page": "dashboard",
    }
    return render(request, "inscriptions/dashboard.html", context)


# ---------------------------------------------------------------------------
# Certifications
# ---------------------------------------------------------------------------

def certifications_list(request):
    query = request.GET.get("q", "")
    certifications = Certification.objects.prefetch_related("inscriptions__paiements")

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


def certification_detail(request, pk):
    certification = get_object_or_404(Certification, pk=pk)
    inscriptions = (
        certification.inscriptions
        .select_related("inscrit")
        .prefetch_related("paiements")
        .order_by("-date_inscription")
    )

    # Build changer statut forms per inscription
    statut_forms = {ic.pk: ChangerStatutForm(instance=ic) for ic in inscriptions}

    context = {
        "certification": certification,
        "inscriptions": inscriptions,
        "statut_forms": statut_forms,
        "active_page": "certifications",
    }
    return render(request, "inscriptions/certification_detail.html", context)


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
# Inscrits
# ---------------------------------------------------------------------------

def inscrits_list(request):
    query = request.GET.get("q", "")
    activite_filter = request.GET.get("activite", "")
    certification_filter = request.GET.get("certification", "")
    statut_filter = request.GET.get("statut", "")

    inscrits = Inscrit.objects.prefetch_related(
        "inscriptions__certification", "inscriptions__paiements"
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
            inscriptions__certification__pk=certification_filter
        ).distinct()

    if statut_filter:
        inscrits = inscrits.filter(
            inscriptions__statut=statut_filter
        ).distinct()

    certifications_all = Certification.objects.order_by("nom")

    context = {
        "inscrits": inscrits,
        "query": query,
        "activite_filter": activite_filter,
        "certification_filter": certification_filter,
        "statut_filter": statut_filter,
        "certifications_all": certifications_all,
        "statut_choices": InscriptionCertification.STATUT_CHOICES,
        "activite_choices": Inscrit.ACTIVITE_CHOICES,
        "active_page": "inscrits",
        "nb_inscrits": Inscrit.objects.count(),
    }
    return render(request, "inscriptions/inscrits_list.html", context)


def inscrit_detail(request, pk):
    inscrit = get_object_or_404(Inscrit, pk=pk)
    inscriptions = (
        inscrit.inscriptions
        .select_related("certification")
        .prefetch_related("paiements")
        .order_by("-date_inscription")
    )

    statut_forms = {ic.pk: ChangerStatutForm(instance=ic) for ic in inscriptions}

    context = {
        "inscrit": inscrit,
        "inscriptions": inscriptions,
        "statut_forms": statut_forms,
        "active_page": "inscrits",
    }
    return render(request, "inscriptions/inscrit_detail.html", context)


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


def inscrire_a_certification(request, pk):
    """Enroll an inscrit in a certification."""
    inscrit = get_object_or_404(Inscrit, pk=pk)

    if request.method == "POST":
        form = InscriptionCertificationForm(request.POST, inscrit=inscrit)
        if form.is_valid():
            inscription = form.save(commit=False)
            inscription.inscrit = inscrit
            inscription.save()
            messages.success(
                request,
                f'"{inscrit}" inscrit à la certification "{inscription.certification.nom}".',
            )
            return redirect("inscrit_detail", pk=inscrit.pk)
    else:
        form = InscriptionCertificationForm(inscrit=inscrit)

    context = {
        "form": form,
        "inscrit": inscrit,
        "titre": f"Inscrire {inscrit} à une certification",
        "active_page": "inscrits",
    }
    return render(request, "inscriptions/inscription_form.html", context)


# ---------------------------------------------------------------------------
# InscriptionCertification actions
# ---------------------------------------------------------------------------

def changer_statut(request, pk):
    inscription = get_object_or_404(InscriptionCertification, pk=pk)
    next_url = request.POST.get("next") or request.GET.get("next", "")

    if request.method == "POST":
        form = ChangerStatutForm(request.POST, instance=inscription)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                f'Statut mis à jour : {inscription.get_statut_display()}.',
            )
    if next_url:
        return redirect(next_url)
    return redirect("inscrit_detail", pk=inscription.inscrit.pk)


def inscription_supprimer(request, pk):
    inscription = get_object_or_404(InscriptionCertification, pk=pk)
    inscrit_pk = inscription.inscrit.pk

    if request.method == "POST":
        cert_nom = inscription.certification.nom
        inscription.delete()
        messages.success(request, f'Inscription à "{cert_nom}" supprimée.')
        return redirect("inscrit_detail", pk=inscrit_pk)

    context = {
        "inscription": inscription,
        "active_page": "inscrits",
    }
    return render(request, "inscriptions/inscription_confirm_delete.html", context)


def paiement_ajouter_pour_inscription(request, pk):
    """Add a payment linked to a specific InscriptionCertification."""
    inscription = get_object_or_404(InscriptionCertification, pk=pk)

    if request.method == "POST":
        form = PaiementInscriptionForm(request.POST)
        if form.is_valid():
            paiement = form.save(commit=False)
            paiement.inscription = inscription
            paiement.save()
            messages.success(
                request,
                f'Paiement de {paiement.montant} FCFA enregistré.',
            )
        else:
            messages.error(request, "Erreur dans le formulaire de paiement.")
    return redirect("inscrit_detail", pk=inscription.inscrit.pk)


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


def import_excel(request):
    if request.method == "POST":
        form = ImportExcelForm(request.POST, request.FILES)
        if form.is_valid():
            fichier = request.FILES["fichier"]
            certification = form.cleaned_data["certification"]

            try:
                wb = openpyxl.load_workbook(fichier, read_only=True, data_only=True)
                ws = wb.active
                rows = list(ws.iter_rows(values_only=True))

                if not rows:
                    messages.error(request, "Le fichier est vide.")
                    return render(
                        request,
                        "inscriptions/import_excel.html",
                        {"form": form, "active_page": "inscrits"},
                    )

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
                    return render(
                        request,
                        "inscriptions/import_excel.html",
                        {"form": form, "active_page": "inscrits"},
                    )

                created = 0
                updated = 0
                enrolled = 0
                errors = []

                for row_idx, row in enumerate(rows[1:], start=2):
                    try:
                        nom = str(row[col_map["nom"]] or "").strip()
                        prenom = str(row[col_map["prenom"]] or "").strip()

                        if not nom or not prenom:
                            errors.append(
                                f"Ligne {row_idx}: nom ou prénom manquant."
                            )
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

                        # Enroll in selected certification
                        _, ic_created = InscriptionCertification.objects.get_or_create(
                            inscrit=inscrit,
                            certification=certification,
                            defaults={"statut": "inscrit"},
                        )
                        if ic_created:
                            enrolled += 1

                    except Exception as exc:
                        errors.append(f"Ligne {row_idx}: erreur — {exc}")

                wb.close()

                if created or updated:
                    messages.success(
                        request,
                        f"Import terminé : {created} inscrit(s) créé(s), {updated} mis à jour, "
                        f"{enrolled} nouvelle(s) inscription(s) à « {certification.nom} ».",
                    )
                for err in errors[:10]:
                    messages.warning(request, err)
                if len(errors) > 10:
                    messages.warning(
                        request, f"... et {len(errors) - 10} autres erreurs."
                    )

                return redirect("inscrits_list")

            except Exception as exc:
                messages.error(request, f"Erreur lors de la lecture du fichier : {exc}")
    else:
        form = ImportExcelForm()

    context = {
        "form": form,
        "active_page": "inscrits",
    }
    return render(request, "inscriptions/import_excel.html", context)


# ---------------------------------------------------------------------------
# Paiements
# ---------------------------------------------------------------------------

def paiements_list(request):
    query = request.GET.get("q", "")
    moyen_filter = request.GET.get("moyen", "")

    paiements = Paiement.objects.select_related(
        "inscription__inscrit", "inscription__certification"
    ).order_by("-date_paiement", "-created_at")

    if query:
        paiements = paiements.filter(
            Q(inscription__inscrit__nom__icontains=query)
            | Q(inscription__inscrit__prenom__icontains=query)
            | Q(inscription__inscrit__email__icontains=query)
            | Q(inscription__certification__nom__icontains=query)
            | Q(reference__icontains=query)
        )

    if moyen_filter:
        paiements = paiements.filter(moyen_paiement=moyen_filter)

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


def paiement_ajouter(request):
    if request.method == "POST":
        form = PaiementForm(request.POST)
        if form.is_valid():
            paiement = form.save()
            messages.success(request, f"Paiement de {paiement.montant} FCFA enregistré.")
            return redirect(
                "inscrit_detail", pk=paiement.inscription.inscrit.pk
            )
    else:
        form = PaiementForm(initial={"date_paiement": timezone.now().date()})

    context = {
        "form": form,
        "titre": "Ajouter un paiement",
        "action": "Enregistrer",
        "active_page": "paiements",
    }
    return render(request, "inscriptions/paiement_form.html", context)


def paiement_modifier(request, pk):
    paiement = get_object_or_404(Paiement, pk=pk)
    if request.method == "POST":
        form = PaiementForm(request.POST, instance=paiement)
        if form.is_valid():
            form.save()
            messages.success(request, "Paiement modifié avec succès.")
            return redirect(
                "inscrit_detail", pk=paiement.inscription.inscrit.pk
            )
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
