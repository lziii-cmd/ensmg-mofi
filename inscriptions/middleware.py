from django.shortcuts import redirect

# ──────────────────────────────────────────────────────────────────────────────
# URLs PUBLIQUES — accessibles sans authentification
# Uniquement la page d'accueil, le flux d'inscription portail, et les services
# ──────────────────────────────────────────────────────────────────────────────
PUBLIC_PATHS = {
    '/',          # Page d'accueil (liste des certifications)
    '/login/',    # Connexion
    '/logout/',   # Déconnexion
}

PUBLIC_PREFIXES = (
    '/portail/inscrire/',   # Formulaire d'auto-inscription
    '/portail/paiement/',   # Paiement après inscription
    '/portail/inscription/',# Wizard d'inscription (ancien)
    '/static/',
    '/media/',
    '/admin/',
    '/apprenant/changer-mdp/',
    '/attestations/',       # Vérification QR code
    '/api/',
)


class ApprenantPasswordMiddleware:
    """
    1. Protège toutes les pages sauf les URLs publiques ci-dessus.
       → Redirige vers /login/ si l'utilisateur n'est pas connecté.
    2. Force les apprenants n'ayant jamais changé leur mot de passe
       à le faire avant d'accéder à quoi que ce soit.
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

        # ── 2. Toutes les autres pages → authentification obligatoire ─────
        if not request.user.is_authenticated:
            return redirect(f'/login/?next={path}')

        # ── 3. Apprenants : forcer le changement de mot de passe initial ──
        try:
            compte = request.user.compte_apprenant
            if not compte.mdp_change:
                return redirect('/apprenant/changer-mdp/')
        except Exception:
            pass

        return self.get_response(request)
