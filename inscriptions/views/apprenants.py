from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from ..models import Certification, Cohorte, Inscription, Notification, TypeTarif
from ..notifications import notifier_inscription
from ._base import _auto_transition_statuts


def _apprenant_required(view_func):
    """Decorator: must be logged in as apprenant (has compte_apprenant)."""

    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        try:
            _ = request.user.compte_apprenant
        except Exception:
            messages.error(request, "Accès réservé aux apprenants.")
            return redirect("dashboard")
        return view_func(request, *args, **kwargs)

    return wrapper


@_apprenant_required
def espace_apprenant(request):
    """Learner personal dashboard."""
    _auto_transition_statuts()
    compte = request.user.compte_apprenant
    inscrit = compte.inscrit

    inscriptions = list(
        inscrit.inscriptions.select_related("cohorte__certification")
        .prefetch_related("paiements", "attestations")
        .order_by("-date_inscription")
    )

    total_du = sum(i.montant_du for i in inscriptions)
    total_paye = sum(i.total_paye for i in inscriptions)
    total_restant = max(total_du - total_paye, 0)
    nb_certifies = sum(1 for i in inscriptions if i.statut == "certifie")

    all_paiements = []
    for ins in inscriptions:
        for p in ins.paiements.all():
            all_paiements.append(p)
    all_paiements.sort(key=lambda p: p.date_paiement, reverse=True)
    recent_paiements = all_paiements[:5]

    paiements_en_attente = [p for p in all_paiements if p.statut == "en_attente"]

    notifications_recentes = Notification.objects.filter(destinataire=compte).order_by(
        "-date_creation"
    )[:5]
    nb_notifs_non_lues = Notification.objects.filter(destinataire=compte, lu=False).count()

    certif_ids_certifiees = set(
        i.cohorte.certification_id for i in inscriptions if i.statut == "certifie"
    )
    certifs_disponibles = (
        Certification.objects.filter(actif=True).exclude(pk__in=certif_ids_certifiees).count()
    )

    inscriptions_a_payer = [i for i in inscriptions if i.reste_a_payer > 0]

    context = {
        "compte": compte,
        "inscrit": inscrit,
        "inscriptions": inscriptions,
        "total_du": total_du,
        "total_paye": total_paye,
        "total_restant": total_restant,
        "nb_certifies": nb_certifies,
        "recent_paiements": recent_paiements,
        "paiements_en_attente": paiements_en_attente,
        "notifications_recentes": notifications_recentes,
        "nb_notifs_non_lues": nb_notifs_non_lues,
        "certifs_disponibles": certifs_disponibles,
        "inscriptions_a_payer": inscriptions_a_payer,
        "active_page": "espace",
    }
    return render(request, "inscriptions/apprenant_dashboard.html", context)


@_apprenant_required
def apprenant_paiements(request):
    """Dedicated paiements list page for the apprenant."""
    compte = request.user.compte_apprenant
    inscrit = compte.inscrit
    inscriptions = (
        inscrit.inscriptions.select_related("cohorte__certification")
        .prefetch_related("paiements")
        .order_by("-date_inscription")
    )
    paiements = []
    for ins in inscriptions:
        for p in ins.paiements.all():
            paiements.append({"paiement": p, "inscription": ins})
    return render(
        request,
        "inscriptions/apprenant_paiements.html",
        {
            "compte": compte,
            "inscrit": inscrit,
            "paiements": paiements,
            "active_page": "paiements",
        },
    )


@_apprenant_required
def apprenant_attestations(request):
    """Dedicated attestations list page for the apprenant."""
    compte = request.user.compte_apprenant
    inscrit = compte.inscrit
    inscriptions = (
        inscrit.inscriptions.select_related("cohorte__certification")
        .prefetch_related("attestations")
        .order_by("-date_inscription")
    )
    attestations = []
    for ins in inscriptions:
        for att in ins.attestations.all():
            attestations.append({"attestation": att, "inscription": ins})
    return render(
        request,
        "inscriptions/apprenant_attestations.html",
        {
            "compte": compte,
            "inscrit": inscrit,
            "attestations": attestations,
            "active_page": "attestations",
        },
    )


def apprenant_changer_mdp(request):
    """Forced password change on first login."""
    if not request.user.is_authenticated:
        return redirect("login")

    try:
        compte = request.user.compte_apprenant
    except Exception:
        return redirect("dashboard")

    if request.method == "POST":
        from ..forms import ChangerMdpApprenantForm

        form = ChangerMdpApprenantForm(request.POST)
        if form.is_valid():
            request.user.set_password(form.cleaned_data["nouveau_mdp"])
            request.user.save()
            compte.mdp_change = True
            compte.save()
            from django.contrib.auth import logout as auth_logout

            auth_logout(request)
            messages.success(request, "Mot de passe changé avec succès. Veuillez vous reconnecter.")
            return redirect("login")
    else:
        from ..forms import ChangerMdpApprenantForm

        form = ChangerMdpApprenantForm()

    return render(request, "inscriptions/apprenant_changer_mdp.html", {"form": form})


@_apprenant_required
def apprenant_profil(request):
    """View and edit learner profile."""
    compte = request.user.compte_apprenant
    inscrit = compte.inscrit

    if request.method == "POST":
        from ..forms import ProfilApprenantForm

        form = ProfilApprenantForm(request.POST, instance=inscrit)
        if form.is_valid():
            form.save()
            messages.success(request, "Profil mis à jour avec succès.")
            return redirect("apprenant_profil")
    else:
        from ..forms import ProfilApprenantForm

        form = ProfilApprenantForm(instance=inscrit)

    return render(
        request,
        "inscriptions/apprenant_profil.html",
        {"form": form, "inscrit": inscrit, "compte": compte, "active_page": "profil"},
    )


@_apprenant_required
def apprenant_payer(request, inscription_pk):
    """Learner initiates a new payment from their space."""
    compte = request.user.compte_apprenant
    inscription = get_object_or_404(Inscription, pk=inscription_pk, inscrit=compte.inscrit)
    request.session["pending_inscription_id"] = inscription.pk
    request.session["paiement_skip_redirect"] = "espace_apprenant"
    request.session.pop("new_compte_username", None)
    return redirect("portail_paiement", pk=inscription.pk)


def apprenant_certifications(request):
    """Liste des certifications disponibles pour l'apprenant."""
    _auto_transition_statuts()
    try:
        compte = request.user.compte_apprenant
        inscrit = compte.inscrit
    except Exception:
        return redirect("login")

    nb_notifs_non_lues = Notification.objects.filter(destinataire=compte, lu=False).count()

    certif_ids_obtenues = Inscription.objects.filter(
        inscrit=inscrit, statut="certifie"
    ).values_list("cohorte__certification_id", flat=True)

    certifs_actives = (
        Certification.objects.filter(actif=True).exclude(pk__in=certif_ids_obtenues).order_by("nom")
    )
    certifs_inactives = (
        Certification.objects.filter(actif=False)
        .exclude(pk__in=certif_ids_obtenues)
        .order_by("nom")
    )

    return render(
        request,
        "inscriptions/apprenant_certifications.html",
        {
            "compte": compte,
            "inscrit": inscrit,
            "certifs_actives": certifs_actives,
            "certifs_inactives": certifs_inactives,
            "active_page": "certifications",
            "nb_notifs_non_lues": nb_notifs_non_lues,
        },
    )


def apprenant_inscription_directe(request, certif_pk):
    """Authenticated apprenant registers directly for a certification (skips portail wizard)."""
    try:
        compte = request.user.compte_apprenant
        inscrit = compte.inscrit
    except Exception:
        return redirect("login")

    certification = get_object_or_404(Certification, pk=certif_pk, actif=True)

    cohorte = (
        Cohorte.objects.filter(certification=certification, actif=True)
        .order_by("date_debut")
        .first()
    )

    nb_notifs_non_lues = Notification.objects.filter(destinataire=compte, lu=False).count()

    errors = {}

    if request.method == "POST":
        cohorte_id = request.POST.get("cohorte_id", "").strip()
        if cohorte_id:
            try:
                cohorte = Cohorte.objects.get(
                    pk=cohorte_id, certification=certification, actif=True
                )
            except Cohorte.DoesNotExist:
                errors["cohorte"] = "Cohorte invalide."
        if not cohorte:
            errors["cohorte"] = "Aucune session disponible pour cette certification."

        if not errors:
            # Choisir le premier type de tarif actif disponible
            type_tarif = None
            if cohorte.option:
                type_tarif = TypeTarif.objects.filter(option=cohorte.option, actif=True).first()
            if type_tarif is None:
                type_tarif = TypeTarif.objects.filter(
                    certification=certification, actif=True
                ).first()
            montant_du = float(type_tarif.montant) if type_tarif else 0
            inscription, created = Inscription.objects.get_or_create(
                inscrit=inscrit,
                cohorte=cohorte,
                defaults={
                    "statut": "pre_inscrit",
                    "type_tarif": type_tarif,
                    "montant_du": montant_du,
                },
            )
            if created:
                notifier_inscription(inscription)

            action = request.POST.get("action", "payer")
            if action == "sans_payer":
                messages.success(
                    request,
                    f"Inscription à « {certification.nom} » confirmée. "
                    "Vous pourrez payer plus tard depuis votre espace.",
                )
                return redirect("espace_apprenant")

            request.session["pending_inscription_id"] = inscription.pk
            request.session["paiement_skip_redirect"] = "espace_apprenant"
            request.session.pop("new_compte_username", None)
            return redirect("portail_paiement", pk=inscription.pk)

    cohortes = Cohorte.objects.filter(certification=certification, actif=True).order_by("nom")

    return render(
        request,
        "inscriptions/apprenant_inscription_directe.html",
        {
            "compte": compte,
            "inscrit": inscrit,
            "certification": certification,
            "cohorte": cohorte,
            "cohortes": cohortes,
            "errors": errors,
            "active_page": "certifications",
            "nb_notifs_non_lues": nb_notifs_non_lues,
        },
    )


def apprenant_notifications(request):
    """Liste et gestion des notifications de l'apprenant."""
    try:
        compte = request.user.compte_apprenant
        inscrit = compte.inscrit
    except Exception:
        return redirect("login")

    if request.method == "POST" and request.POST.get("marquer_tout_lu"):
        Notification.objects.filter(destinataire=compte, lu=False).update(lu=True)
        messages.success(request, "Toutes les notifications marquées comme lues.")
        return redirect("apprenant_notifications")

    notifs = Notification.objects.filter(destinataire=compte).order_by("-date_creation")

    notifs.filter(lu=False).update(lu=True)

    return render(
        request,
        "inscriptions/apprenant_notifications.html",
        {
            "compte": compte,
            "inscrit": inscrit,
            "notifs": notifs,
            "active_page": "notifications",
            "nb_notifs_non_lues": 0,
        },
    )
