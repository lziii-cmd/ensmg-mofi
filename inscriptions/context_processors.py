from .models import Certification, Cohorte


def _role_from_user(user):
    """Détermine le rôle d'un utilisateur staff."""
    if user.is_superuser:
        return 'super_utilisateur'
    groups = set(user.groups.values_list('name', flat=True))
    if 'Responsable Scolarité' in groups:
        return 'responsable_scolarite'
    if 'Admin' in groups:
        return 'admin'
    if 'Personnel Utilisateur' in groups:
        return 'personnel_utilisateur'
    return 'super_utilisateur'


def global_filters(request):
    if not request.user.is_authenticated:
        return {}

    # Apprenants : pas de filtres scolarité
    try:
        _ = request.user.compte_apprenant
        return {'user_role': 'apprenant'}
    except Exception:
        pass

    user_role = _role_from_user(request.user)

    certifications = Certification.objects.order_by('nom')
    selected_certif_ids = request.session.get('filter_certif_ids', [])
    selected_cohorte_ids = request.session.get('filter_cohorte_ids', [])
    cohortes = Cohorte.objects.none()
    if selected_certif_ids:
        cohortes = Cohorte.objects.filter(
            certification_id__in=selected_certif_ids
        ).select_related('certification').order_by('nom')
    return {
        'gf_certifications': certifications,
        'gf_cohortes': cohortes,
        'gf_selected_certif_ids': [int(x) for x in selected_certif_ids],
        'gf_selected_cohorte_ids': [int(x) for x in selected_cohorte_ids],
        'user_role': user_role,
    }
