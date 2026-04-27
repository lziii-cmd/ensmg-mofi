from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from ..forms import ChangerStatutForm, CohorteForm
from ..models import Certification, Cohorte, OptionCertification


@login_required
def cohorte_ajouter(request, certif_pk=None, option_pk=None):
    """Crée une cohorte pour une certification (sans options) ou pour une option."""
    option = None
    if option_pk:
        option = get_object_or_404(OptionCertification, pk=option_pk)
        certification = option.certification
        titre = f"Ajouter une cohorte — {certification.nom} / {option.nom}"
    elif certif_pk:
        certification = get_object_or_404(Certification, pk=certif_pk)
        titre = f"Ajouter une cohorte — {certification.nom}"
    else:
        messages.error(request, "Paramètres invalides.")
        return redirect("certifications_list")

    if request.method == "POST":
        form = CohorteForm(request.POST)
        if form.is_valid():
            cohorte = form.save(commit=False)
            cohorte.certification = certification
            cohorte.option = option
            cohorte.save()
            messages.success(request, f'Cohorte "{cohorte.nom}" créée avec succès.')
            return redirect("cohorte_detail", pk=cohorte.pk)
    else:
        form = CohorteForm()

    context = {
        "form": form,
        "certification": certification,
        "option": option,
        "titre": titre,
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
        cohorte.inscriptions.select_related("inscrit")
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
