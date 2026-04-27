from django.contrib import messages
from django.contrib.auth.models import User
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render
from django_ratelimit.decorators import ratelimit


def custom_logout(request):
    """Logout — accepts GET and POST, redirects to homepage."""
    from django.contrib.auth import logout as auth_logout

    auth_logout(request)
    return redirect("portail_accueil_home")


@ratelimit(key="ip", rate="10/m", method="POST", block=True)
def custom_login(request):
    """Login page that redirects apprenants to their space and admins to dashboard."""
    from django.contrib.auth import authenticate
    from django.contrib.auth import login as auth_login

    if request.user.is_authenticated:
        try:
            _ = request.user.compte_apprenant
            return redirect("espace_apprenant")
        except Exception:
            pass
        return redirect("dashboard")

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        if "@" in username:
            try:
                username = User.objects.get(email__iexact=username).username
            except User.DoesNotExist:
                pass
        user = authenticate(request, username=username, password=password)
        if user is not None:
            if user.is_active:
                auth_login(request, user)
                next_url = request.POST.get("next", request.GET.get("next", ""))
                if next_url:
                    return redirect(next_url)
                try:
                    _ = user.compte_apprenant
                    return redirect("espace_apprenant")
                except Exception:
                    pass
                return redirect("dashboard")
            else:
                messages.error(request, "Ce compte est désactivé.")
        else:
            messages.error(request, "Identifiant ou mot de passe incorrect.")

    return render(
        request,
        "inscriptions/login.html",
        {"next": request.GET.get("next", "")},
    )


def register_admin(request, key=""):
    """Page de création de compte admin — protégée par clé dans l'URL."""
    from django.conf import settings as _s
    from django.http import Http404

    register_key = _s.REGISTER_KEY
    if not register_key or key != register_key:
        raise Http404

    errors = {}
    form_data = {}

    if request.method == "POST":
        prenom = request.POST.get("prenom", "").strip()
        nom = request.POST.get("nom", "").strip()
        email = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password", "")
        password2 = request.POST.get("password2", "")
        form_data = {"prenom": prenom, "nom": nom, "email": email}

        if not prenom:
            errors["prenom"] = "Le prénom est obligatoire."
        if not nom:
            errors["nom"] = "Le nom est obligatoire."
        if not email:
            errors["email"] = "L'adresse email est obligatoire."
        elif (
            User.objects.filter(username__iexact=email).exists()
            or User.objects.filter(email__iexact=email).exists()
        ):
            errors["email"] = "Un compte avec cet email existe déjà."
        if not password:
            errors["password"] = "Le mot de passe est obligatoire."
        elif len(password) < 6:
            errors["password"] = "Le mot de passe doit contenir au moins 6 caractères."
        if password and password != password2:
            errors["password2"] = "Les mots de passe ne correspondent pas."

        if not errors:
            User.objects.create_user(
                username=email,
                email=email,
                password=password,
                first_name=prenom,
                last_name=nom,
                is_staff=True,
                is_superuser=True,
            )
            messages.success(request, f"Compte créé avec succès ! Connectez-vous avec {email}.")
            return redirect("login")

    return render(
        request,
        "inscriptions/register_admin.html",
        {"errors": errors, "form_data": form_data},
    )


def bootstrap_admin(request):
    """
    One-time bootstrap: creates admin account if it doesn't exist.
    Protected by BOOTSTRAP_KEY env var.
    Access: /bootstrap/?key=<BOOTSTRAP_KEY>
    Remove BOOTSTRAP_KEY env var after first use.
    """
    import os

    secret = os.environ.get("BOOTSTRAP_KEY", "")
    provided = request.GET.get("key", "")
    if not secret or provided != secret:
        return HttpResponseForbidden("Accès refusé.")

    username = "admin@ensmg.sn"
    password = "password"
    if User.objects.filter(username=username).exists():
        msg = f"✅ Compte déjà existant : {username}"
    else:
        User.objects.create_superuser(
            username=username,
            email=username,
            password=password,
            first_name="Admin",
            last_name="ENSMG",
        )
        msg = f"✅ Compte créé : {username} / {password}"
    return HttpResponse(msg)
