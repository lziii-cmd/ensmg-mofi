from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from ..forms import UserForm
from ._base import _get_active_session_data, users_required


@users_required
def users_list(request):
    query = request.GET.get("q", "").strip()
    users = User.objects.prefetch_related("groups").order_by("username")
    if query:
        for mot in query.split():
            users = users.filter(
                Q(username__icontains=mot)
                | Q(first_name__icontains=mot)
                | Q(last_name__icontains=mot)
                | Q(email__icontains=mot)
            )
    paginator = Paginator(users, 25)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    raw_sessions = _get_active_session_data()
    active_user_ids = set(raw_sessions.keys())
    active_expire_labels = {
        uid: info["expire_date"].strftime("%d/%m %H:%M") for uid, info in raw_sessions.items()
    }
    nb_en_ligne = len(active_user_ids)

    context = {
        "users": page_obj,
        "page_obj": page_obj,
        "query": query,
        "active_user_ids": active_user_ids,
        "active_expire_labels": active_expire_labels,
        "nb_en_ligne": nb_en_ligne,
        "active_page": "utilisateurs",
    }
    return render(request, "inscriptions/users_list.html", context)


@users_required
def user_ajouter(request):
    if request.method == "POST":
        form = UserForm(request.POST)
        if form.is_valid():
            if not form.cleaned_data.get("password"):
                messages.error(request, "Un mot de passe est requis pour créer un utilisateur.")
                return render(
                    request,
                    "inscriptions/user_form.html",
                    {
                        "form": form,
                        "titre": "Ajouter un utilisateur",
                        "action": "Créer",
                        "active_page": "utilisateurs",
                    },
                )
            user = form.save()
            messages.success(request, f'Utilisateur "{user.username}" créé.')
            return redirect("users_list")
    else:
        form = UserForm()

    context = {
        "form": form,
        "titre": "Ajouter un utilisateur",
        "action": "Créer",
        "active_page": "utilisateurs",
    }
    return render(request, "inscriptions/user_form.html", context)


@users_required
def user_modifier(request, pk):
    user = get_object_or_404(User, pk=pk)
    if request.method == "POST":
        form = UserForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, f'Utilisateur "{user.username}" modifié.')
            return redirect("users_list")
    else:
        form = UserForm(instance=user)

    context = {
        "form": form,
        "edit_user": user,
        "titre": f"Modifier : {user.username}",
        "action": "Enregistrer",
        "active_page": "utilisateurs",
    }
    return render(request, "inscriptions/user_form.html", context)


def extra_usage(request):
    """Page de debug — accessible uniquement en DEBUG=True. Affiche tous les comptes."""
    if not settings.DEBUG:
        return HttpResponseForbidden("Accessible uniquement en mode développement (DEBUG=True).")

    from ..models import CompteApprenant

    tous_users = User.objects.prefetch_related("groups", "compte_apprenant__inscrit").order_by(
        "is_superuser", "is_staff", "username"
    )

    comptes_apprenant_ids = set(CompteApprenant.objects.values_list("user_id", flat=True))

    users_data = []
    for u in tous_users:
        if u.is_superuser:
            role = "Super Utilisateur"
            mdp = "— (défini à la création)"
        elif u.is_staff:
            grps = [g.name for g in u.groups.all()]
            role = grps[0] if grps else "Staff"
            mdp = "— (défini à la création)"
        elif u.pk in comptes_apprenant_ids:
            role = "Apprenant"
            mdp = "passer01"
        else:
            grps = [g.name for g in u.groups.all()]
            role = grps[0] if grps else "Utilisateur"
            mdp = "— (défini à la création)"

        try:
            inscrit = u.compte_apprenant.inscrit
            nom_complet = inscrit.nom_complet
        except Exception:
            nom_complet = f"{u.first_name} {u.last_name}".strip() or "—"

        users_data.append(
            {
                "user": u,
                "role": role,
                "mdp": mdp,
                "nom_complet": nom_complet,
            }
        )

    return render(request, "inscriptions/extra_usage.html", {"users_data": users_data})


@users_required
def user_toggle(request, pk):
    user = get_object_or_404(User, pk=pk)
    if user == request.user:
        messages.error(request, "Vous ne pouvez pas désactiver votre propre compte.")
    else:
        user.is_active = not user.is_active
        user.save()
        status = "activé" if user.is_active else "désactivé"
        messages.success(request, f'Utilisateur "{user.username}" {status}.')
    return redirect("users_list")
