"""
CRUD pour le modèle Session.
Session = dimension temporelle (quand la formation a lieu).
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from ..forms import CohorteForm, SessionForm
from ..models import Certification, Cohorte, OptionCertification, Session


@login_required
def session_ajouter(request, certif_pk=None, option_pk=None):
    """Crée une session pour une certification (sans options) ou pour une option."""
    option = None
    if option_pk:
        option = get_object_or_404(OptionCertification, pk=option_pk)
        certification = option.certification
        titre = f"Ajouter une session — {certification.nom} / {option.nom}"
    elif certif_pk:
        certification = get_object_or_404(Certification, pk=certif_pk)
        titre = f"Ajouter une session — {certification.nom}"
    else:
        messages.error(request, "Paramètres invalides.")
        return redirect("certifications_list")

    if request.method == "POST":
        form = SessionForm(request.POST)
        if form.is_valid():
            session = form.save(commit=False)
            session.certification = certification
            session.option = option
            # Générer un nom automatique si non fourni
            if not session.nom and session.date_debut:
                session.nom = Session.nom_auto(session.date_debut)
            session.save()
            # Créer automatiquement une première cohorte "Cohorte A"
            Cohorte.objects.create(session=session, nom="Cohorte A", actif=True)
            messages.success(
                request,
                f'Session "{session.nom}" créée avec Cohorte A. '
                f"Vous pouvez ajouter d'autres cohortes si nécessaire.",
            )
            return redirect("session_detail", pk=session.pk)
    else:
        form = SessionForm()

    context = {
        "form": form,
        "certification": certification,
        "option": option,
        "titre": titre,
        "action": "Créer",
        "active_page": "certifications",
    }
    return render(request, "inscriptions/session_form.html", context)


@login_required
def session_modifier(request, pk):
    session = get_object_or_404(Session, pk=pk)
    if request.method == "POST":
        form = SessionForm(request.POST, instance=session)
        if form.is_valid():
            form.save()
            messages.success(request, f'Session "{session.nom}" modifiée.')
            return redirect("session_detail", pk=session.pk)
    else:
        form = SessionForm(instance=session)

    context = {
        "form": form,
        "session": session,
        "certification": session.certification,
        "titre": f"Modifier : {session.nom}",
        "action": "Enregistrer",
        "active_page": "certifications",
    }
    return render(request, "inscriptions/session_form.html", context)


@login_required
def session_supprimer(request, pk):
    session = get_object_or_404(Session, pk=pk)
    certif_pk = session.certification.pk
    if request.method == "POST":
        nom = session.nom
        session.delete()
        messages.success(request, f'Session "{nom}" supprimée.')
        return redirect("certification_detail", pk=certif_pk)

    context = {
        "session": session,
        "active_page": "certifications",
    }
    return render(request, "inscriptions/session_confirm_delete.html", context)


@login_required
def session_detail(request, pk):
    session = get_object_or_404(Session, pk=pk)
    cohortes = session.cohortes.prefetch_related(
        "inscriptions__inscrit", "inscriptions__paiements"
    ).order_by("nom")

    context = {
        "session": session,
        "cohortes": cohortes,
        "active_page": "certifications",
    }
    return render(request, "inscriptions/session_detail.html", context)


# ── Cohortes dans une session ────────────────────────────────────────────────


@login_required
def cohorte_ajouter_dans_session(request, session_pk):
    """Ajoute une cohorte à une session existante."""
    session = get_object_or_404(Session, pk=session_pk)

    if request.method == "POST":
        form = CohorteForm(request.POST)
        if form.is_valid():
            cohorte = form.save(commit=False)
            cohorte.session = session
            cohorte.save()
            messages.success(request, f'Cohorte "{cohorte.nom}" ajoutée à {session.nom}.')
            return redirect("session_detail", pk=session.pk)
    else:
        form = CohorteForm()

    context = {
        "form": form,
        "session": session,
        "certification": session.certification,
        "titre": f"Ajouter une cohorte — {session.nom}",
        "action": "Créer",
        "active_page": "certifications",
    }
    return render(request, "inscriptions/cohorte_form.html", context)
