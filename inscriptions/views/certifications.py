from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from ..forms import CertificationForm, OptionCertificationForm, TypeTarifForm
from ..models import (
    Certification,
    CompteApprenant,
    NomTypeTarif,
    Notification,
    OptionCertification,
    TypeTarif,
)


@login_required
def certifications_list(request):
    query = request.GET.get("q", "").strip()
    certifications = Certification.objects.prefetch_related("cohortes__inscriptions__paiements")

    if query:
        for mot in query.split():
            certifications = certifications.filter(
                Q(nom__icontains=mot) | Q(description__icontains=mot)
            )

    certifications = certifications.order_by("-created_at")

    paginator = Paginator(certifications, 25)
    page_number = request.GET.get("page", 1)
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

    if certification.a_options:
        # Charger options avec leurs types_tarif et cohortes
        options = certification.options.prefetch_related(
            "types_tarif",
            "cohortes__inscriptions__paiements",
            "cohortes__inscriptions__inscrit",
        ).order_by("nom")
        cohortes = None
        types_tarif = None
    else:
        options = None
        cohortes = (
            certification.cohortes.prefetch_related(
                "inscriptions__paiements", "inscriptions__inscrit"
            )
            .filter(option__isnull=True)
            .order_by("nom")
        )
        types_tarif = certification.types_tarif.filter(actif=True).order_by("nom")

    context = {
        "certification": certification,
        "options": options,
        "cohortes": cohortes,
        "types_tarif": types_tarif,
        "noms_catalogue": NomTypeTarif.objects.filter(actif=True).order_by("nom"),
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
            for compte in CompteApprenant.objects.all():
                Notification.objects.create(
                    destinataire=compte,
                    type_notif="nouvelle_certification",
                    message=(
                        f"Nouvelle certification disponible : « {certification.nom} »."
                        " Inscrivez-vous dès maintenant !"
                    ),
                    lien="/apprenant/certifications/",
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


# ── Options de certification ─────────────────────────────────────────────────


@login_required
def option_ajouter(request, certif_pk):
    certification = get_object_or_404(Certification, pk=certif_pk)
    if request.method == "POST":
        form = OptionCertificationForm(request.POST)
        if form.is_valid():
            option = form.save(commit=False)
            option.certification = certification
            option.save()
            messages.success(request, f'Option "{option.nom}" créée.')
            return redirect("certification_detail", pk=certification.pk)
    else:
        form = OptionCertificationForm()

    context = {
        "form": form,
        "certification": certification,
        "titre": f"Ajouter une option — {certification.nom}",
        "action": "Créer",
        "active_page": "certifications",
    }
    return render(request, "inscriptions/option_form.html", context)


@login_required
def option_modifier(request, pk):
    option = get_object_or_404(OptionCertification, pk=pk)
    if request.method == "POST":
        form = OptionCertificationForm(request.POST, instance=option)
        if form.is_valid():
            form.save()
            messages.success(request, f'Option "{option.nom}" modifiée.')
            return redirect("certification_detail", pk=option.certification.pk)
    else:
        form = OptionCertificationForm(instance=option)

    context = {
        "form": form,
        "option": option,
        "certification": option.certification,
        "titre": f"Modifier l'option : {option.nom}",
        "action": "Enregistrer",
        "active_page": "certifications",
    }
    return render(request, "inscriptions/option_form.html", context)


@login_required
def option_supprimer(request, pk):
    option = get_object_or_404(OptionCertification, pk=pk)
    certif_pk = option.certification.pk
    if request.method == "POST":
        nom = option.nom
        option.delete()
        messages.success(request, f'Option "{nom}" supprimée.')
        return redirect("certification_detail", pk=certif_pk)

    context = {
        "option": option,
        "certification": option.certification,
        "active_page": "certifications",
    }
    return render(request, "inscriptions/option_confirm_delete.html", context)


# ── Types de tarif ───────────────────────────────────────────────────────────


@login_required
def type_tarif_ajouter(request, certif_pk=None, option_pk=None):
    """Ajoute un type de tarif à une certification (sans options) ou à une option."""
    certification = None
    option = None

    if certif_pk:
        certification = get_object_or_404(Certification, pk=certif_pk)
        parent_label = certification.nom
        back_url = "certification_detail"
        back_pk = certif_pk
    elif option_pk:
        option = get_object_or_404(OptionCertification, pk=option_pk)
        certification = option.certification
        parent_label = f"{certification.nom} — {option.nom}"
        back_url = "certification_detail"
        back_pk = certification.pk
    else:
        messages.error(request, "Paramètres invalides.")
        return redirect("certifications_list")

    if request.method == "POST":
        form = TypeTarifForm(request.POST)
        if form.is_valid():
            tarif = form.save(commit=False)
            tarif.certification = certification if not option else None
            tarif.option = option
            tarif.save()
            messages.success(request, f'Tarif "{tarif.nom}" créé.')
            return redirect(back_url, pk=back_pk)
    else:
        form = TypeTarifForm()

    context = {
        "form": form,
        "certification": certification,
        "option": option,
        "titre": f"Ajouter un tarif — {parent_label}",
        "action": "Créer",
        "active_page": "certifications",
    }
    return render(request, "inscriptions/type_tarif_form.html", context)


@login_required
def type_tarif_modifier(request, pk):
    tarif = get_object_or_404(TypeTarif, pk=pk)
    if request.method == "POST":
        form = TypeTarifForm(request.POST, instance=tarif)
        if form.is_valid():
            form.save()
            messages.success(request, f'Tarif "{tarif.nom}" modifié.')
            certif_pk = (
                tarif.certification.pk if tarif.certification else tarif.option.certification.pk
            )
            return redirect("certification_detail", pk=certif_pk)
    else:
        form = TypeTarifForm(instance=tarif)

    certification = tarif.certification or tarif.option.certification
    context = {
        "form": form,
        "tarif": tarif,
        "certification": certification,
        "option": tarif.option,
        "titre": f"Modifier le tarif : {tarif.nom}",
        "action": "Enregistrer",
        "active_page": "certifications",
    }
    return render(request, "inscriptions/type_tarif_form.html", context)


@login_required
def type_tarif_supprimer(request, pk):
    tarif = get_object_or_404(TypeTarif, pk=pk)
    certif_pk = tarif.certification.pk if tarif.certification else tarif.option.certification.pk
    if request.method == "POST":
        nom = tarif.nom
        tarif.delete()
        messages.success(request, f'Tarif "{nom}" supprimé.')
        return redirect("certification_detail", pk=certif_pk)

    certification = tarif.certification or tarif.option.certification
    context = {
        "tarif": tarif,
        "certification": certification,
        "active_page": "certifications",
    }
    return render(request, "inscriptions/type_tarif_confirm_delete.html", context)


# ── Catalogue NomTypeTarif ───────────────────────────────────────────────────


@login_required
def nom_tarif_creer_ajax(request):
    """POST AJAX : ajoute un nom au catalogue NomTypeTarif. Retourne {id, nom}."""
    if request.method != "POST":
        return JsonResponse({"error": "Méthode non autorisée."}, status=405)
    nom = request.POST.get("nom", "").strip()
    if not nom:
        return JsonResponse({"error": "Le nom est obligatoire."}, status=400)
    obj, created = NomTypeTarif.objects.get_or_create(nom=nom)
    return JsonResponse({"id": obj.pk, "nom": obj.nom, "created": created})


@login_required
def tarifs_bulk_ajouter(request, certif_pk=None, option_pk=None):
    """POST : crée plusieurs TypeTarif en une fois depuis le catalogue multi-sélection."""
    if request.method != "POST":
        return JsonResponse({"error": "Méthode non autorisée."}, status=405)

    certification = None
    option = None

    if option_pk:
        option = get_object_or_404(OptionCertification, pk=option_pk)
        certification = option.certification
        back_pk = certification.pk
    elif certif_pk:
        certification = get_object_or_404(Certification, pk=certif_pk)
        back_pk = certif_pk
    else:
        messages.error(request, "Paramètres invalides.")
        return redirect("certifications_list")

    noms_ids = request.POST.getlist("noms_ids")
    crees = 0
    for nom_id in noms_ids:
        montant_raw = request.POST.get(f"montant_{nom_id}", "").strip()
        if not montant_raw:
            continue
        try:
            montant = float(montant_raw)
        except ValueError:
            continue
        nom_obj = NomTypeTarif.objects.filter(pk=nom_id).first()
        if not nom_obj:
            continue
        # Évite les doublons : ne crée pas si un tarif avec ce nom existe déjà
        existe = TypeTarif.objects.filter(
            nom=nom_obj.nom,
            certification=certification if not option else None,
            option=option,
        ).exists()
        if not existe:
            TypeTarif.objects.create(
                nom=nom_obj.nom,
                montant=montant,
                certification=certification if not option else None,
                option=option,
            )
            crees += 1

    if crees:
        messages.success(request, f"{crees} tarif(s) ajouté(s) avec succès.")
    else:
        messages.warning(request, "Aucun tarif ajouté (déjà existants ou montants manquants).")

    return redirect("certification_detail", pk=back_pk)


# ── AJAX ─────────────────────────────────────────────────────────────────────


@login_required
def api_types_tarif(request):
    """Retourne les types de tarif pour une certification ou une option (AJAX)."""
    certif_id = request.GET.get("certif_id")
    option_id = request.GET.get("option_id")
    cohorte_id = request.GET.get("cohorte_id")

    from ..models import Cohorte

    if cohorte_id:
        try:
            cohorte = Cohorte.objects.select_related("certification", "option").get(pk=cohorte_id)
        except Cohorte.DoesNotExist:
            return JsonResponse({"tarifs": []})

        if cohorte.option:
            qs = TypeTarif.objects.filter(option=cohorte.option, actif=True)
        else:
            qs = TypeTarif.objects.filter(certification=cohorte.certification, actif=True)
    elif option_id:
        qs = TypeTarif.objects.filter(option_id=option_id, actif=True)
    elif certif_id:
        qs = TypeTarif.objects.filter(certification_id=certif_id, actif=True)
    else:
        return JsonResponse({"tarifs": []})

    tarifs = [{"id": t.pk, "nom": t.nom, "montant": float(t.montant)} for t in qs.order_by("nom")]
    return JsonResponse({"tarifs": tarifs})
