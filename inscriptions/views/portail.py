import json
import uuid

from django.conf import settings
from django.contrib import messages
from django.http import HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from ..models import (
    Certification,
    Cohorte,
    CompteApprenant,
    Inscription,
    Inscrit,
    Paiement,
    TypeTarif,
)
from ..notifications import notifier_inscription, notifier_paiement_confirme
from ._base import _creer_compte_apprenant


def _premier_type_tarif(cohorte):
    """Retourne le premier TypeTarif actif d'une cohorte (option ou certification)."""
    if cohorte.option:
        tt = TypeTarif.objects.filter(option=cohorte.option, actif=True).order_by("montant").first()
        if tt:
            return tt
    return (
        TypeTarif.objects.filter(certification=cohorte.certification, actif=True)
        .order_by("montant")
        .first()
    )


def _build_step3_context(certification, cohortes, error_msg=None):
    """
    Construit le contexte pour l'étape 3 du wizard (choix option/cohorte/tarif).
    Structure passée au template :
      - has_options : bool
      - options_data : liste d'options avec leurs cohortes + tarifs (si has_options)
      - cohortes_data / tarifs_data : si pas d'options
    """
    from ..models import OptionCertification

    ctx = {
        "certification": certification,
        "cohortes": cohortes,
        "panel": "wizard",
        "wizard_step": 3,
        "cohorte_error": error_msg,
    }

    if certification.a_options:
        options_qs = (
            OptionCertification.objects.filter(certification=certification, actif=True)
            .prefetch_related("cohortes", "types_tarif")
            .order_by("nom")
        )

        options_data = []
        for opt in options_qs:
            opt_cohortes = [c for c in opt.cohortes.all() if c.actif]
            opt_tarifs = [t for t in opt.types_tarif.all() if t.actif]
            options_data.append(
                {
                    "id": opt.pk,
                    "nom": opt.nom,
                    "cohortes": opt_cohortes,
                    "tarifs": sorted(opt_tarifs, key=lambda x: x.montant),
                }
            )
        ctx["has_options"] = True
        ctx["options_data"] = options_data
    else:
        ctx["has_options"] = False
        ctx["tarifs_data"] = list(
            TypeTarif.objects.filter(certification=certification, actif=True).order_by("montant")
        )
    return ctx


def portail_accueil(request):
    """Public landing page — redirect authenticated users to their space."""
    if request.user.is_authenticated:
        try:
            _ = request.user.compte_apprenant
            return redirect("espace_apprenant")
        except Exception:
            pass
        if request.user.is_staff or request.user.is_superuser:
            return redirect("dashboard")
    certifications = Certification.objects.filter(actif=True).order_by("nom")
    return render(
        request,
        "inscriptions/portail_accueil.html",
        {"certifications": certifications},
    )


def portail_rejoindre(request, certif_pk):
    """
    Page d'inscription à une certification spécifique.
    Étape 0 : choix "J'ai un compte" / "Je suis nouveau"
    Étapes 1-4 : wizard inline (4 étapes de création de compte + inscription)
    """
    from ..forms import WizardStep1Form

    certification = get_object_or_404(Certification, pk=certif_pk, actif=True)

    if request.user.is_authenticated:
        try:
            _ = request.user.compte_apprenant
            return redirect("apprenant_inscription_directe", certif_pk=certif_pk)
        except Exception:
            return redirect("dashboard")

    request.session["rejoindre_certif_id"] = certif_pk
    cohortes = Cohorte.objects.filter(certification=certification, actif=True).order_by("nom")

    if request.method == "POST":
        action = request.POST.get("action", "")

        if action == "login":
            from django.contrib.auth import authenticate
            from django.contrib.auth import login as auth_login
            from django.contrib.auth.models import User

            username = request.POST.get("username", "").strip()
            password = request.POST.get("password", "").strip()
            if "@" in username:
                try:
                    username = User.objects.get(email__iexact=username).username
                except User.DoesNotExist:
                    pass
            user = authenticate(request, username=username, password=password)
            if user and user.is_active:
                auth_login(request, user)
                try:
                    _ = user.compte_apprenant
                    return redirect("apprenant_inscription_directe", certif_pk=certif_pk)
                except Exception:
                    return redirect("dashboard")
            return render(
                request,
                "inscriptions/portail_rejoindre.html",
                {
                    "certification": certification,
                    "cohortes": cohortes,
                    "panel": "login",
                    "error_login": True,
                },
            )

        elif action == "wizard_step1":
            form = WizardStep1Form(request.POST)
            if form.is_valid():
                # Séparer identité et profil pour compat avec la suite du code
                data = form.cleaned_data
                request.session["wizard_step1"] = {
                    "nom": data["nom"],
                    "prenom": data["prenom"],
                    "email": data["email"],
                    "telephone": data["telephone"],
                    "adresse": data.get("adresse", ""),
                }
                request.session["wizard_step2"] = {
                    "activite": data["activite"],
                    "universite": data.get("universite", ""),
                    "entreprise": data.get("entreprise", ""),
                }
                return redirect(f"/portail/rejoindre/{certif_pk}/?step=2")
            return render(
                request,
                "inscriptions/portail_rejoindre.html",
                {
                    "certification": certification,
                    "cohortes": cohortes,
                    "panel": "wizard",
                    "wizard_step": 1,
                    "form_step1": form,
                },
            )

        elif action == "wizard_step2":
            if not request.session.get("wizard_step1"):
                return redirect(f"/portail/rejoindre/{certif_pk}/?step=1")
            cohorte_id = request.POST.get("cohorte_id", "").strip()
            type_tarif_id = request.POST.get("type_tarif_id", "").strip()

            # Valider la cohorte (doit appartenir à cette certification)
            cohorte_sel = None
            if cohorte_id:
                try:
                    cohorte_sel = Cohorte.objects.select_related("option").get(
                        pk=cohorte_id, certification=certification, actif=True
                    )
                except Cohorte.DoesNotExist:
                    pass

            # Valider le tarif (doit appartenir à l'option de la cohorte, ou à la certification)
            type_tarif_sel = None
            if type_tarif_id and cohorte_sel:
                try:
                    tt = TypeTarif.objects.get(pk=type_tarif_id, actif=True)
                    if cohorte_sel.option:
                        if tt.option_id == cohorte_sel.option_id:
                            type_tarif_sel = tt
                    else:
                        if tt.certification_id == cohorte_sel.certification_id:
                            type_tarif_sel = tt
                except TypeTarif.DoesNotExist:
                    pass

            if cohorte_sel and type_tarif_sel:
                request.session["wizard_step3"] = {
                    "cohorte_id": cohorte_sel.pk,
                    "type_tarif_id": type_tarif_sel.pk,
                }
                return redirect(f"/portail/rejoindre/{certif_pk}/?step=3")

            # Erreur — re-render avec le message approprié
            if not cohorte_sel:
                error_msg = "Veuillez sélectionner une session disponible."
            else:
                error_msg = "Veuillez sélectionner un tarif."

            return render(
                request,
                "inscriptions/portail_rejoindre.html",
                _build_step3_context(certification, cohortes, error_msg),
            )

        elif action == "wizard_step3":
            step1 = request.session.get("wizard_step1")
            step2 = request.session.get("wizard_step2")
            step3_data = request.session.get("wizard_step3")
            if not all([step1, step2, step3_data]):
                return redirect(f"/portail/rejoindre/{certif_pk}/?step=1")
            try:
                cohorte_obj = Cohorte.objects.select_related("certification", "option").get(
                    pk=step3_data["cohorte_id"]
                )
            except Cohorte.DoesNotExist:
                return redirect(f"/portail/rejoindre/{certif_pk}/?step=2")

            email = step1["email"].lower()
            activite = step2["activite"]

            if Inscrit.objects.filter(email=email).exists():
                inscrit = Inscrit.objects.get(email=email)
                inscrit.nom = step1["nom"]
                inscrit.prenom = step1["prenom"]
                inscrit.telephone = step1["telephone"]
                inscrit.adresse = step1.get("adresse", "")
                inscrit.activite = activite
                inscrit.universite = step2.get("universite", "")
                inscrit.entreprise = step2.get("entreprise", "")
                inscrit.save()
            else:
                inscrit = Inscrit.objects.create(
                    nom=step1["nom"],
                    prenom=step1["prenom"],
                    email=email,
                    telephone=step1["telephone"],
                    adresse=step1.get("adresse", ""),
                    activite=activite,
                    source="portail",
                    universite=step2.get("universite", ""),
                    entreprise=step2.get("entreprise", ""),
                )

            # Récupérer le tarif choisi (pas le premier par défaut)
            type_tarif = None
            if step3_data.get("type_tarif_id"):
                try:
                    type_tarif = TypeTarif.objects.get(pk=step3_data["type_tarif_id"])
                except TypeTarif.DoesNotExist:
                    pass
            if type_tarif is None:
                type_tarif = _premier_type_tarif(cohorte_obj)
            montant_du = float(type_tarif.montant) if type_tarif else 0
            inscription, created = Inscription.objects.get_or_create(
                inscrit=inscrit,
                cohorte=cohorte_obj,
                defaults={
                    "statut": "pre_inscrit",
                    "type_tarif": type_tarif,
                    "montant_du": montant_du,
                },
            )
            if created:
                notifier_inscription(inscription)

            if not CompteApprenant.objects.filter(inscrit=inscrit).exists():
                user, compte = _creer_compte_apprenant(inscrit)
            else:
                compte = inscrit.compte_apprenant
                user = compte.user

            from django.contrib.auth import login as auth_login

            user.backend = "django.contrib.auth.backends.ModelBackend"
            auth_login(request, user)

            for k in ["wizard_step1", "wizard_step2", "wizard_step3", "rejoindre_certif_id"]:
                request.session.pop(k, None)

            request.session["pending_inscription_id"] = inscription.pk
            request.session["new_compte_username"] = user.username
            return redirect("portail_paiement", pk=inscription.pk)

    # GET handlers
    step = int(request.GET.get("step", 0))
    panel = request.GET.get("panel", "")

    if step == 1 or panel == "wizard":
        # Pré-remplir depuis les 2 anciennes clés (identité + profil) fusionnées
        initial = {}
        initial.update(request.session.get("wizard_step1", {}))
        initial.update(request.session.get("wizard_step2", {}))
        return render(
            request,
            "inscriptions/portail_rejoindre.html",
            {
                "certification": certification,
                "cohortes": cohortes,
                "panel": "wizard",
                "wizard_step": 1,
                "form_step1": WizardStep1Form(initial=initial),
            },
        )
    elif step == 2:
        if not request.session.get("wizard_step1"):
            return redirect(f"/portail/rejoindre/{certif_pk}/?step=1")
        return render(
            request,
            "inscriptions/portail_rejoindre.html",
            _build_step3_context(certification, cohortes),
        )
    elif step == 3:
        step1 = request.session.get("wizard_step1", {})
        step2 = request.session.get("wizard_step2", {})
        step3_data = request.session.get("wizard_step3", {})
        if not all([step1, step2, step3_data]):
            return redirect(f"/portail/rejoindre/{certif_pk}/?step=1")
        try:
            cohorte_obj = Cohorte.objects.select_related("certification", "option").get(
                pk=step3_data["cohorte_id"]
            )
        except Cohorte.DoesNotExist:
            return redirect(f"/portail/rejoindre/{certif_pk}/?step=2")

        # Récupérer le tarif choisi par l'utilisateur (pas le premier par défaut)
        type_tarif = None
        if step3_data.get("type_tarif_id"):
            try:
                type_tarif = TypeTarif.objects.get(pk=step3_data["type_tarif_id"])
            except TypeTarif.DoesNotExist:
                pass
        if type_tarif is None:
            type_tarif = _premier_type_tarif(cohorte_obj)
        tarif = float(type_tarif.montant) if type_tarif else 0
        return render(
            request,
            "inscriptions/portail_rejoindre.html",
            {
                "certification": certification,
                "cohortes": cohortes,
                "panel": "wizard",
                "wizard_step": 3,
                "step1": step1,
                "step2": step2,
                "cohorte": cohorte_obj,
                "type_tarif": type_tarif,
                "tarif": tarif,
            },
        )

    return render(
        request,
        "inscriptions/portail_rejoindre.html",
        {
            "certification": certification,
            "cohortes": cohortes,
            "panel": "login" if panel == "login" else "",
            "wizard_step": 0,
            "form_step1": WizardStep1Form(),
            "error_login": False,
        },
    )


def portail_wizard(request):
    """4-step session-based wizard for public registration."""
    step = int(request.GET.get("step", request.POST.get("step", 1)))

    if request.method == "POST":
        if step == 1:
            from ..forms import WizardStep1Form

            form = WizardStep1Form(request.POST)
            if form.is_valid():
                data = form.cleaned_data
                request.session["wizard_step1"] = {
                    "nom": data["nom"],
                    "prenom": data["prenom"],
                    "email": data["email"],
                    "telephone": data["telephone"],
                    "adresse": data.get("adresse", ""),
                }
                request.session["wizard_step2"] = {
                    "activite": data["activite"],
                    "universite": data.get("universite", ""),
                    "entreprise": data.get("entreprise", ""),
                }
                return redirect("/portail/inscription/?step=2")
            return render(
                request,
                "inscriptions/portail_wizard.html",
                {
                    "step": 1,
                    "form": form,
                    "certifications": Certification.objects.filter(actif=True).order_by("nom"),
                },
            )

        elif step == 2:
            from ..forms import WizardStep3Form

            form = WizardStep3Form(request.POST)
            if form.is_valid():
                cohorte = form.cleaned_data["cohorte"]
                type_tarif_id = request.POST.get("type_tarif_id", "").strip()
                request.session["wizard_step3"] = {
                    "cohorte_id": cohorte.pk,
                    "type_tarif_id": type_tarif_id or None,
                }
                return redirect("/portail/inscription/?step=3")
            step1 = request.session.get("wizard_step1")
            if not step1:
                return redirect("/portail/inscription/?step=1")
            certifications = Certification.objects.filter(actif=True).order_by("nom")
            return render(
                request,
                "inscriptions/portail_wizard.html",
                {
                    "step": 2,
                    "form": form,
                    "certifications": certifications,
                },
            )

        elif step == 3:
            step1 = request.session.get("wizard_step1")
            step2 = request.session.get("wizard_step2")
            step3 = request.session.get("wizard_step3")
            if not all([step1, step2, step3]):
                return redirect("/portail/inscription/?step=1")

            try:
                cohorte = Cohorte.objects.select_related("certification", "option").get(
                    pk=step3["cohorte_id"]
                )
            except Cohorte.DoesNotExist:
                messages.error(request, "Cohorte invalide.")
                return redirect("/portail/inscription/?step=2")

            email = step1["email"].lower()
            activite = step2["activite"]

            if Inscrit.objects.filter(email=email).exists():
                inscrit = Inscrit.objects.get(email=email)
                inscrit.nom = step1["nom"]
                inscrit.prenom = step1["prenom"]
                inscrit.telephone = step1["telephone"]
                inscrit.adresse = step1.get("adresse", "")
                inscrit.activite = activite
                inscrit.universite = step2.get("universite", "")
                inscrit.entreprise = step2.get("entreprise", "")
                inscrit.save()
            else:
                inscrit = Inscrit.objects.create(
                    nom=step1["nom"],
                    prenom=step1["prenom"],
                    email=email,
                    telephone=step1["telephone"],
                    adresse=step1.get("adresse", ""),
                    activite=activite,
                    source="portail",
                    universite=step2.get("universite", ""),
                    entreprise=step2.get("entreprise", ""),
                )

            # Utiliser le tarif choisi par l'utilisateur si présent, sinon fallback
            type_tarif = None
            if step3.get("type_tarif_id"):
                try:
                    type_tarif = TypeTarif.objects.get(pk=step3["type_tarif_id"])
                except TypeTarif.DoesNotExist:
                    pass
            if type_tarif is None:
                type_tarif = _premier_type_tarif(cohorte)
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

            if not CompteApprenant.objects.filter(inscrit=inscrit).exists():
                user, compte = _creer_compte_apprenant(inscrit)
            else:
                compte = inscrit.compte_apprenant
                user = compte.user

            is_staff_registrant = request.user.is_authenticated and (
                request.user.is_staff or request.user.is_superuser
            )
            if is_staff_registrant:
                request.session["wizard_by_staff"] = True
            else:
                from django.contrib.auth import login as auth_login

                user.backend = "django.contrib.auth.backends.ModelBackend"
                auth_login(request, user)

            for k in ["wizard_step1", "wizard_step2", "wizard_step3"]:
                request.session.pop(k, None)

            request.session["pending_inscription_id"] = inscription.pk
            request.session["new_compte_username"] = user.username

            return redirect("portail_paiement", pk=inscription.pk)

    # GET requests
    certifications = Certification.objects.filter(actif=True).order_by("nom")

    if step == 1:
        from ..forms import WizardStep1Form

        initial = {}
        initial.update(request.session.get("wizard_step1", {}))
        initial.update(request.session.get("wizard_step2", {}))
        form = WizardStep1Form(initial=initial)
        return render(
            request,
            "inscriptions/portail_wizard.html",
            {"step": 1, "form": form, "certifications": certifications},
        )
    elif step == 2:
        if not request.session.get("wizard_step1"):
            return redirect("/portail/inscription/?step=1")
        from ..forms import WizardStep3Form

        form = WizardStep3Form()
        cohortes_data = [
            {
                "id": co.pk,
                "nom": co.nom,
                "certif_id": co.certification_id,
                "certif_nom": co.certification.nom,
                "option_id": co.option_id,
            }
            for co in Cohorte.objects.select_related("certification")
            .filter(certification__actif=True, actif=True)
            .order_by("certification__nom", "nom")
        ]
        # Tarifs par certification et par option
        tarifs_data = {"certif": {}, "option": {}}
        for tt in TypeTarif.objects.filter(actif=True):
            info = {
                "id": tt.pk,
                "nom": tt.nom,
                "montant": float(tt.montant),
                "description": tt.description or "",
            }
            if tt.certification_id:
                tarifs_data["certif"].setdefault(tt.certification_id, []).append(info)
            elif tt.option_id:
                tarifs_data["option"].setdefault(tt.option_id, []).append(info)
        # Trier par montant
        for d in (tarifs_data["certif"], tarifs_data["option"]):
            for k in d:
                d[k].sort(key=lambda x: x["montant"])

        return render(
            request,
            "inscriptions/portail_wizard.html",
            {
                "step": 2,
                "form": form,
                "certifications": certifications,
                "cohortes_json": json.dumps(cohortes_data),
                "tarifs_json": json.dumps(tarifs_data),
            },
        )
    elif step == 3:
        step1 = request.session.get("wizard_step1", {})
        step2 = request.session.get("wizard_step2", {})
        step3_data = request.session.get("wizard_step3", {})
        cohorte = None
        if step3_data.get("cohorte_id"):
            try:
                cohorte = Cohorte.objects.select_related("certification", "option").get(
                    pk=step3_data["cohorte_id"]
                )
            except Cohorte.DoesNotExist:
                pass
        if not all([step1, step2, cohorte]):
            return redirect("/portail/inscription/?step=1")
        type_tarif = None
        if step3_data.get("type_tarif_id"):
            try:
                type_tarif = TypeTarif.objects.get(pk=step3_data["type_tarif_id"])
            except TypeTarif.DoesNotExist:
                pass
        if type_tarif is None:
            type_tarif = _premier_type_tarif(cohorte)
        tarif = float(type_tarif.montant) if type_tarif else 0
        return render(
            request,
            "inscriptions/portail_wizard.html",
            {
                "step": 3,
                "step1": step1,
                "step2": step2,
                "cohorte": cohorte,
                "type_tarif": type_tarif,
                "tarif": tarif,
                "certifications": certifications,
            },
        )

    return redirect("/portail/inscription/?step=1")


def portail_inscrire(request, certif_pk):
    """
    Formulaire d'inscription en une seule page pré-lié à une certification.
    L'étudiant choisit la cohorte et le tarif (et l'option si applicable).
    """
    certification = get_object_or_404(Certification, pk=certif_pk, actif=True)

    # Si la certification a des options, on redirige vers le wizard complet
    # (parcours plus adapté pour le choix option/cohorte/tarif)
    if certification.a_options:
        return redirect("portail_rejoindre", certif_pk=certif_pk)

    cohortes = Cohorte.objects.filter(certification=certification, actif=True).order_by(
        "date_debut"
    )
    types_tarif = TypeTarif.objects.filter(certification=certification, actif=True).order_by(
        "montant"
    )

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
        cohorte_id = request.POST.get("cohorte_id", "").strip()
        type_tarif_id = request.POST.get("type_tarif_id", "").strip()

        form_data = {
            "nom": nom,
            "prenom": prenom,
            "email": email,
            "telephone": telephone,
            "activite": activite,
            "adresse": adresse,
            "universite": universite,
            "entreprise": entreprise,
            "cohorte_id": cohorte_id,
            "type_tarif_id": type_tarif_id,
        }

        # Valider cohorte choisie
        cohorte = None
        if cohorte_id:
            try:
                cohorte = Cohorte.objects.get(
                    pk=cohorte_id, certification=certification, actif=True
                )
            except (Cohorte.DoesNotExist, ValueError):
                pass

        # Valider tarif choisi
        type_tarif = None
        if type_tarif_id:
            try:
                type_tarif = TypeTarif.objects.get(
                    pk=type_tarif_id, certification=certification, actif=True
                )
            except (TypeTarif.DoesNotExist, ValueError):
                pass

        if not nom:
            errors["nom"] = "Le nom est requis."
        if not prenom:
            errors["prenom"] = "Le prénom est requis."
        if not email:
            errors["email"] = "L'email est requis."
        if not cohorte:
            errors["cohorte"] = "Veuillez sélectionner une session disponible."
        if not type_tarif:
            errors["type_tarif"] = "Veuillez sélectionner un tarif."

        if not errors:
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
                    nom=nom,
                    prenom=prenom,
                    email=email,
                    telephone=telephone,
                    adresse=adresse,
                    activite=activite,
                    source="portail",
                    universite=universite,
                    entreprise=entreprise,
                )

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

            if not CompteApprenant.objects.filter(inscrit=inscrit).exists():
                user, _ = _creer_compte_apprenant(inscrit)
            else:
                user = inscrit.compte_apprenant.user

            from django.contrib.auth import login as auth_login

            user.backend = "django.contrib.auth.backends.ModelBackend"
            auth_login(request, user)

            request.session["new_compte_username"] = user.username
            return redirect("portail_paiement", pk=inscription.pk)

    return render(
        request,
        "inscriptions/portail_inscrire.html",
        {
            "certification": certification,
            "cohortes": cohortes,
            "types_tarif": types_tarif,
            "errors": errors,
            "form_data": form_data,
        },
    )


def portail_paiement(request, pk):
    """Payment choice page after wizard completion."""
    inscription = get_object_or_404(Inscription, pk=pk)
    username = request.session.get("new_compte_username", "")

    if request.method == "POST":
        if request.POST.get("skip_paiement"):
            is_staff_reg = request.session.pop("wizard_by_staff", False)
            request.session.pop("paiement_skip_redirect", None)
            request.session.pop("pending_inscription_id", None)
            if not is_staff_reg:
                return redirect("espace_apprenant")
            return render(
                request,
                "inscriptions/portail_confirmation.html",
                {
                    "inscription": inscription,
                    "username": request.session.get("new_compte_username", ""),
                    "moyen": "plus_tard",
                    "is_staff_reg": is_staff_reg,
                },
            )

        moyen = request.POST.get("moyen_paiement", "")
        reference = request.POST.get("reference_virement", "").strip()

        if moyen == "wave":
            import requests as http_requests

            wave_api_key = getattr(settings, "WAVE_API_KEY", "")
            if not wave_api_key:
                messages.error(request, "Paiement Wave non configuré. Contactez l'administration.")
                return redirect("portail_paiement", pk=inscription.pk)

            client_ref = f"INS-{inscription.pk:06d}-{uuid.uuid4().hex[:6].upper()}"
            success_url = request.build_absolute_uri(
                f"/portail/paiement/{inscription.pk}/wave-retour/?ref={client_ref}&statut=succes"
            )
            error_url = request.build_absolute_uri(
                f"/portail/paiement/{inscription.pk}/wave-retour/?ref={client_ref}&statut=echec"
            )

            try:
                resp = http_requests.post(
                    "https://api.wave.com/v1/checkout/sessions",
                    headers={
                        "Authorization": f"Bearer {wave_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "amount": str(int(inscription.montant_du)),
                        "currency": "XOF",
                        "client_reference": client_ref,
                        "success_url": success_url,
                        "error_url": error_url,
                    },
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
                wave_url = data.get("wave_launch_url") or data.get("checkout_url")
                if not wave_url:
                    raise ValueError("Pas d'URL de paiement dans la réponse Wave.")
                Paiement.objects.create(
                    inscription=inscription,
                    montant=inscription.montant_du,
                    date_paiement=timezone.now().date(),
                    moyen_paiement="wave",
                    reference=client_ref,
                    statut="en_attente",
                    notes=f"Session Wave: {data.get('id', '')}",
                )
                return redirect(wave_url)
            except Exception as e:
                messages.error(request, f"Erreur lors de l'initiation du paiement Wave : {e}")
                return redirect("portail_paiement", pk=inscription.pk)

        elif moyen == "orange_money":
            txn_id = request.POST.get("txn_id", "").strip()
            numero = request.POST.get("numero_mobile", "").strip()
            if not txn_id:
                messages.error(
                    request, "Veuillez saisir l'identifiant de transaction Orange Money."
                )
                return redirect("portail_paiement", pk=inscription.pk)
            Paiement.objects.create(
                inscription=inscription,
                montant=inscription.montant_du,
                date_paiement=timezone.now().date(),
                moyen_paiement="orange_money",
                reference=txn_id,
                statut="en_attente",
                notes=f"N° Orange Money : {numero} — Réf. transaction : {txn_id}",
            )
            messages.success(
                request,
                "Transaction Orange Money déclarée."
                " L'administration vérifiera et confirmera votre inscription.",
            )

        elif moyen == "intouch":
            import requests as http_requests

            paytech_key = getattr(settings, "PAYTECH_API_KEY", "")
            paytech_secret = getattr(settings, "PAYTECH_API_SECRET", "")
            if not paytech_key or not paytech_secret:
                messages.error(
                    request, "Paiement InTouch non configuré. Contactez l'administration."
                )
                return redirect("portail_paiement", pk=inscription.pk)

            client_ref = f"INS-{inscription.pk:06d}-{uuid.uuid4().hex[:6].upper()}"
            success_url = request.build_absolute_uri(
                f"/portail/paiement/{inscription.pk}/intouch-retour/?ref={client_ref}&statut=succes"
            )
            cancel_url = request.build_absolute_uri(
                f"/portail/paiement/{inscription.pk}/intouch-retour/?ref={client_ref}&statut=echec"
            )
            ipn_url = request.build_absolute_uri(f"/portail/paiement/{inscription.pk}/intouch-ipn/")

            try:
                resp = http_requests.post(
                    "https://paytech.sn/api/payment/request-payment",
                    headers={
                        "API_KEY": paytech_key,
                        "API_SECRET": paytech_secret,
                        "Content-Type": "application/json",
                    },
                    json={
                        "item_name": f"Inscription {inscription.cohorte.certification.nom}",
                        "item_price": int(inscription.montant_du),
                        "ref_command": client_ref,
                        "command_name": f"Inscription ENSMG — {inscription.cohorte.nom}",
                        "currency": "XOF",
                        "env": "prod",
                        "ipn_url": ipn_url,
                        "success_url": success_url,
                        "cancel_url": cancel_url,
                    },
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
                redirect_url = data.get("redirect_url")
                token = data.get("token", "")
                if not redirect_url:
                    raise ValueError("Pas d'URL de paiement dans la réponse InTouch.")
                Paiement.objects.create(
                    inscription=inscription,
                    montant=inscription.montant_du,
                    date_paiement=timezone.now().date(),
                    moyen_paiement="intouch",
                    reference=client_ref,
                    statut="en_attente",
                    notes=f"Token InTouch: {token}",
                )
                return redirect(redirect_url)
            except Exception as e:
                messages.error(request, f"Erreur lors de l'initiation du paiement InTouch : {e}")
                return redirect("portail_paiement", pk=inscription.pk)

        elif moyen == "virement":
            Paiement.objects.create(
                inscription=inscription,
                montant=inscription.montant_du,
                date_paiement=timezone.now().date(),
                moyen_paiement="virement",
                reference=reference or f"VIR-{uuid.uuid4().hex[:8].upper()}",
                statut="en_attente",
                notes="Virement bancaire déclaré depuis le portail",
            )
            messages.success(
                request,
                "Virement déclaré. L'administration le vérifiera et confirmera votre inscription.",
            )

        is_staff_reg = request.session.pop("wizard_by_staff", False)
        request.session.pop("pending_inscription_id", None)

        return render(
            request,
            "inscriptions/portail_confirmation.html",
            {
                "inscription": inscription,
                "username": username,
                "moyen": moyen,
                "is_staff_reg": is_staff_reg,
            },
        )

    rib_info = {
        "banque": "Banque de l'Habitat du Sénégal (BHS)",
        "titulaire": "ENSMG — École Nationale Supérieure de Management et de Gouvernance",
        "iban": "SN38 SN010 10100 20030050001 23",
        "swift": "BHSASNDA",
        "reference": f"INS-{inscription.pk:06d}-{inscription.inscrit.nom.upper()[:6]}",
    }

    return render(
        request,
        "inscriptions/portail_paiement.html",
        {
            "inscription": inscription,
            "rib_info": rib_info,
            "username": username,
            "wave_configured": bool(getattr(settings, "WAVE_API_KEY", "")),
            "intouch_configured": bool(
                getattr(settings, "PAYTECH_API_KEY", "")
                and getattr(settings, "PAYTECH_API_SECRET", "")
            ),
        },
    )


def portail_wave_retour(request, pk):
    """Page de retour après paiement Wave (success_url / error_url)."""
    inscription = get_object_or_404(Inscription, pk=pk)
    statut = request.GET.get("statut", "echec")
    ref = request.GET.get("ref", "")

    if statut == "succes":
        paiement = Paiement.objects.filter(
            inscription=inscription,
            reference=ref,
            moyen_paiement="wave",
        ).first()
        if paiement and paiement.statut == "en_attente":
            paiement.statut = "confirme"
            paiement.save(update_fields=["statut"])
            if inscription.statut == "pre_inscrit":
                inscription.statut = "inscrit"
                inscription.save(update_fields=["statut"])
            notifier_paiement_confirme(paiement)
        messages.success(request, "Paiement Wave confirmé ! Votre inscription est validée.")
    else:
        messages.error(request, "Le paiement Wave a échoué ou a été annulé.")

    username = request.session.get("new_compte_username", "")
    is_staff_reg = request.session.pop("wizard_by_staff", False)
    return render(
        request,
        "inscriptions/portail_confirmation.html",
        {
            "inscription": inscription,
            "username": username,
            "moyen": "wave",
            "wave_succes": statut == "succes",
            "is_staff_reg": is_staff_reg,
        },
    )


def portail_intouch_retour(request, pk):
    """Retour navigateur après paiement InTouch (success_url / cancel_url)."""
    inscription = get_object_or_404(Inscription, pk=pk)
    statut = request.GET.get("statut", "echec")
    ref = request.GET.get("ref", "")

    if statut == "succes":
        paiement = Paiement.objects.filter(
            inscription=inscription,
            reference=ref,
            moyen_paiement="intouch",
        ).first()
        if paiement and paiement.statut == "en_attente":
            paiement.statut = "confirme"
            paiement.save(update_fields=["statut"])
            if inscription.statut == "pre_inscrit":
                inscription.statut = "inscrit"
                inscription.save(update_fields=["statut"])
            notifier_paiement_confirme(paiement)
        messages.success(request, "Paiement InTouch confirmé ! Votre inscription est validée.")
    else:
        messages.error(request, "Le paiement a été annulé ou a échoué.")

    username = request.session.get("new_compte_username", "")
    is_staff_reg = request.session.pop("wizard_by_staff", False)
    return render(
        request,
        "inscriptions/portail_confirmation.html",
        {
            "inscription": inscription,
            "username": username,
            "moyen": "intouch",
            "intouch_succes": statut == "succes",
            "is_staff_reg": is_staff_reg,
        },
    )


# Backward-compatible alias
portail_paytech_retour = portail_intouch_retour


@csrf_exempt
def portail_intouch_ipn(request, pk):
    """Webhook IPN InTouch — confirmation serveur-à-serveur."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    inscription = get_object_or_404(Inscription, pk=pk)
    ref_command = request.POST.get("ref_command", "")
    type_event = request.POST.get("type_event", "")

    if type_event == "sale_complete" and ref_command:
        paiement = Paiement.objects.filter(
            inscription=inscription,
            reference=ref_command,
            moyen_paiement="intouch",
        ).first()
        if paiement and paiement.statut == "en_attente":
            paiement.statut = "confirme"
            paiement.save(update_fields=["statut"])
            if inscription.statut == "pre_inscrit":
                inscription.statut = "inscrit"
                inscription.save(update_fields=["statut"])
            notifier_paiement_confirme(paiement)

    return JsonResponse({"status": "ok"})


# Backward-compatible alias
portail_paytech_ipn = portail_intouch_ipn
