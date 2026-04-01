from .models import Certification, Cohorte


def global_filters(request):
    if not request.user.is_authenticated:
        return {}
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
    }
