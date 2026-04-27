from django.contrib import messages
from django.shortcuts import redirect

# ──────────────────────────────────────────────────────────────────────────────
# URLs PUBLIQUES — accessibles sans authentification
# ──────────────────────────────────────────────────────────────────────────────
PUBLIC_PATHS = {
    "/",  # Page d'accueil (liste des certifications)
    "/login/",  # Connexion
    "/logout/",  # Déconnexion
    "/extra-usage/",  # Debug — comptes & mots de passe (DEBUG=True uniquement)
}

PUBLIC_PREFIXES = (
    "/portail/",  # Tout le portail public
    "/static/",
    "/media/",
    "/admin/",
    "/apprenant/changer-mdp/",
    "/attestations/",  # Vérification QR code
    "/api/",
    "/password-reset/",
    "/accounts/",
    "/register/",  # Création compte admin — protégée par clé dans l'URL
)

# Sections accessibles uniquement aux rôles "scolarité"
# (Responsable Scolarité, Super Utilisateur, Personnel Utilisateur)
# → Le rôle "Admin" est redirigé vers /utilisateurs/
SCOLARITE_PREFIXES = (
    "/dashboard/",
    "/certifications/",
    "/cohortes/",
    "/inscrits/",
    "/paiements/",
    "/certifier/",
    "/finances/",
    "/filtrer/",
    "/import/",
)

# Sections accessibles uniquement aux rôles "gestion utilisateurs"
# (Super Utilisateur + Admin)
# → Les autres rôles sont redirigés vers /dashboard/
USERS_PREFIXES = ("/utilisateurs/",)


from .roles import get_user_role as _get_staff_role


class ApprenantPasswordMiddleware:
    """
    1. Protège toutes les pages sauf les URLs publiques.
    2. Force les apprenants à changer leur mot de passe à la première connexion.
    3. Applique les restrictions de rôle pour les utilisateurs staff.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path

        # ── 1. Laisser passer les URLs publiques ──────────────────────────
        if path in PUBLIC_PATHS:
            return self.get_response(request)
        if any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return self.get_response(request)

        # ── 2. Authentification obligatoire ───────────────────────────────
        if not request.user.is_authenticated:
            return redirect(f"/login/?next={path}")

        # ── 3. Apprenants : forcer le changement de mot de passe initial ──
        try:
            compte = request.user.compte_apprenant
            if not compte.mdp_change:
                return redirect("/apprenant/changer-mdp/")
            return self.get_response(request)
        except Exception:
            pass  # Pas un apprenant → continuer avec les rôles staff

        # ── 4. Restrictions par rôle staff ────────────────────────────────
        role = _get_staff_role(request.user)

        # Rôle "Admin" : accès limité aux utilisateurs + inscrits de base
        if role == "admin":
            allowed = ("/utilisateurs/", "/inscrits/", "/static/", "/media/")
            if not any(path.startswith(p) for p in allowed):
                messages.warning(
                    request, "Votre rôle (Admin) ne vous autorise pas à accéder à cette section."
                )
                return redirect("/utilisateurs/")

        # Rôle "Responsable Scolarité" : pas accès à la gestion des utilisateurs
        if role == "responsable_scolarite":
            if any(path.startswith(p) for p in USERS_PREFIXES):
                messages.warning(
                    request,
                    "La gestion des utilisateurs est réservée aux Admins et Super Utilisateurs.",
                )
                return redirect("/dashboard/")

        # Rôle "Personnel Utilisateur" : lecture seule — bloquer les POSTs d'écriture
        if role == "personnel_utilisateur" and request.method == "POST":
            # Chemins d'écriture bloqués (ajouter, modifier, supprimer, certifier, importer)
            write_paths = (
                "/certifications/ajouter/",
                "/certifications/",
                "/cohortes/",
                "/inscrits/ajouter/",
                "/inscrits/import/",
                "/inscrits/inscrire/",
                "/paiements/ajouter/",
                "/paiements/",
                "/certifier/",
            )
            is_write = any(path.startswith(p) for p in write_paths) and any(
                kw in path
                for kw in [
                    "ajouter",
                    "modifier",
                    "supprimer",
                    "action",
                    "import",
                    "inscrire",
                    "confirmer",
                    "annuler",
                ]
            )
            if is_write:
                messages.warning(request, "Vous avez un accès en lecture seule.")
                return redirect(request.META.get("HTTP_REFERER", "/dashboard/"))

        return self.get_response(request)
