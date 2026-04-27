from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse

from ..models import Cohorte, Inscription, Inscrit


@login_required
def api_cohortes(request):
    certif_ids = request.GET.getlist("certif_id")
    cohortes = []
    if certif_ids:
        qs = (
            Cohorte.objects.filter(certification_id__in=certif_ids)
            .select_related("certification")
            .order_by("nom")
        )
        cohortes = [{"id": c.pk, "nom": c.nom, "certification": c.certification.nom} for c in qs]
    return JsonResponse({"cohortes": cohortes})


@login_required
def api_search_inscrits(request):
    q = request.GET.get("q", "").strip()
    results = []
    if q:
        inscrits = Inscrit.objects.filter(
            Q(nom__icontains=q) | Q(prenom__icontains=q) | Q(email__icontains=q)
        ).order_by("nom", "prenom")[:20]
        results = [
            {"id": i.pk, "text": f"{i.prenom} {i.nom} ({i.email or i.telephone or 'no contact'})"}
            for i in inscrits
        ]
    return JsonResponse({"results": results})


@login_required
def api_inscription_solde(request):
    """Returns reste_a_payer for a given inscription pk (used in paiement form)."""
    pk = request.GET.get("pk")
    if not pk:
        return JsonResponse({"error": "missing pk"}, status=400)
    try:
        ic = (
            Inscription.objects.select_related("cohorte__certification", "inscrit")
            .prefetch_related("paiements")
            .get(pk=pk)
        )
        return JsonResponse(
            {
                "reste_a_payer": float(ic.reste_a_payer),
                "montant_du": float(ic.montant_du),
                "total_paye": float(ic.total_paye),
                "nom_inscrit": ic.inscrit.nom_complet,
                "activite": ic.inscrit.activite,
            }
        )
    except Inscription.DoesNotExist:
        return JsonResponse({"error": "not found"}, status=404)
