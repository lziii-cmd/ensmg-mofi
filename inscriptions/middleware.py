from django.shortcuts import redirect

# URLs accessibles sans authentification (portail public)
PUBLIC_PREFIXES = (
    '/portail/',
    '/login/',
    '/logout/',
    '/static/',
    '/media/',
    '/admin/',
    '/apprenant/changer-mdp/',
    '/attestations/',   # vérification QR code
    '/api/',
)


class ApprenantPasswordMiddleware:
    """
    Force apprenants who have never changed their default password to the
    password-change page before they can access anything else.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Les URLs publiques ne sont jamais interceptées
        if any(request.path.startswith(p) for p in PUBLIC_PREFIXES):
            return self.get_response(request)
        # La page d'accueil (/) est publique
        if request.path == '/':
            return self.get_response(request)

        if request.user.is_authenticated:
            try:
                compte = request.user.compte_apprenant
                if not compte.mdp_change:
                    return redirect('/apprenant/changer-mdp/')
            except Exception:
                pass
        return self.get_response(request)
