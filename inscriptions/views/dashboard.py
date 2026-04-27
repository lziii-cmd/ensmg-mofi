from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.shortcuts import redirect, render

from ..models import Certification, Inscription, Inscrit, Paiement
from ._base import _auto_transition_statuts


@login_required
def set_filter(request):
    if request.method == "POST":
        certif_ids = [int(x) for x in request.POST.getlist("certif_ids") if x.isdigit()]
        cohorte_ids = [int(x) for x in request.POST.getlist("cohorte_ids") if x.isdigit()]
        request.session["filter_certif_ids"] = certif_ids
        request.session["filter_cohorte_ids"] = cohorte_ids
    next_url = request.POST.get("next", request.GET.get("next", "/"))
    return redirect(next_url)


@login_required
def clear_filter(request):
    request.session.pop("filter_certif_ids", None)
    request.session.pop("filter_cohorte_ids", None)
    next_url = request.GET.get("next", "/")
    return redirect(next_url)


@login_required
def dashboard(request):
    _auto_transition_statuts()
    filter_certif_ids = request.session.get("filter_certif_ids", [])
    filter_cohorte_ids = request.session.get("filter_cohorte_ids", [])

    inscriptions_qs = Inscription.objects.all()
    paiements_qs = Paiement.objects.all()

    if filter_cohorte_ids:
        inscriptions_qs = inscriptions_qs.filter(cohorte_id__in=filter_cohorte_ids)
        paiements_qs = paiements_qs.filter(inscription__cohorte_id__in=filter_cohorte_ids)
    elif filter_certif_ids:
        inscriptions_qs = inscriptions_qs.filter(cohorte__certification_id__in=filter_certif_ids)
        paiements_qs = paiements_qs.filter(
            inscription__cohorte__certification_id__in=filter_certif_ids
        )

    nb_inscrits = inscriptions_qs.values("inscrit").distinct().count()
    nb_certifies = inscriptions_qs.filter(statut="certifie").count()
    total_encaisse = paiements_qs.aggregate(total=Sum("montant"))["total"] or 0
    total_inscriptions = inscriptions_qs.count()
    taux_certification = 0
    if total_inscriptions > 0:
        taux_certification = int((nb_certifies / total_inscriptions) * 100)

    certifications = Certification.objects.prefetch_related(
        "cohortes__inscriptions__paiements"
    ).order_by("-created_at")

    if filter_certif_ids:
        certifications = certifications.filter(pk__in=filter_certif_ids)

    stats_certifications = []
    for cert in certifications:
        cert_inscriptions = Inscription.objects.filter(cohorte__certification=cert)
        if filter_cohorte_ids:
            cert_inscriptions = cert_inscriptions.filter(cohorte_id__in=filter_cohorte_ids)
        nb_cert_inscrits = cert_inscriptions.count()
        nb_cert_certifies = cert_inscriptions.filter(statut="certifie").count()
        taux = 0
        if nb_cert_inscrits > 0:
            taux = int((nb_cert_certifies / nb_cert_inscrits) * 100)
        montant = (
            Paiement.objects.filter(inscription__in=cert_inscriptions).aggregate(
                total=Sum("montant")
            )["total"]
            or 0
        )
        stats_certifications.append(
            {
                "certification": cert,
                "nb_inscrits": nb_cert_inscrits,
                "nb_certifies": nb_cert_certifies,
                "nb_cohortes": cert.cohortes.count(),
                "taux": taux,
                "montant_encaisse": montant,
            }
        )

    paiements_recents = paiements_qs.select_related(
        "inscription__inscrit", "inscription__cohorte__certification"
    ).order_by("-date_paiement", "-created_at")[:8]

    stats_statut_qs = inscriptions_qs.values("statut").annotate(nb=Count("id"))
    stats_statut_dict = {s["statut"]: s["nb"] for s in stats_statut_qs}

    inscrits_recents = Inscrit.objects.prefetch_related("inscriptions").order_by(
        "-date_inscription"
    )[:8]

    context = {
        "nb_certifications": Certification.objects.count(),
        "nb_inscrits": nb_inscrits,
        "nb_certifies": nb_certifies,
        "total_encaisse": total_encaisse,
        "taux_certification": taux_certification,
        "stats_certifications": stats_certifications,
        "stats_statut_dict": stats_statut_dict,
        "paiements_recents": paiements_recents,
        "inscrits_recents": inscrits_recents,
        "filter_certif_ids": filter_certif_ids,
        "filter_cohorte_ids": filter_cohorte_ids,
        "active_page": "dashboard",
    }
    return render(request, "inscriptions/dashboard.html", context)


@login_required
def dashboard_financier(request):
    """Advanced financial dashboard with charts data."""
    import json
    from datetime import timedelta

    from django.contrib import messages
    from django.db.models.functions import TruncMonth
    from django.utils import timezone

    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "Accès réservé aux administrateurs.")
        return redirect("dashboard")

    today = timezone.now().date()
    twelve_months_ago = today - timedelta(days=365)

    monthly_data = (
        Paiement.objects.filter(statut="confirme", date_paiement__gte=twelve_months_ago)
        .annotate(mois=TruncMonth("date_paiement"))
        .values("mois")
        .annotate(total=Sum("montant"))
        .order_by("mois")
    )

    months_labels = []
    months_values = []
    for entry in monthly_data:
        mois = entry["mois"]
        months_labels.append(mois.strftime("%b %Y"))
        months_values.append(float(entry["total"]))

    total_encaisse = (
        Paiement.objects.filter(statut="confirme").aggregate(t=Sum("montant"))["t"] or 0
    )
    total_en_attente = (
        Paiement.objects.filter(statut="en_attente").aggregate(t=Sum("montant"))["t"] or 0
    )
    total_du = Inscription.objects.aggregate(t=Sum("montant_du"))["t"] or 0
    total_inscrits = Inscription.objects.count()
    total_certifies = Inscription.objects.filter(statut="certifie").count()
    taux_certif = int((total_certifies / total_inscrits * 100)) if total_inscrits else 0
    taux_recouvrement = int((float(total_encaisse) / float(total_du) * 100)) if total_du else 0
    nb_paiements_confirmes = Paiement.objects.filter(statut="confirme").count()
    montant_moyen = (
        int(float(total_encaisse) / nb_paiements_confirmes) if nb_paiements_confirmes else 0
    )

    first_day_this_month = today.replace(day=1)
    last_month_end = first_day_this_month - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    revenue_this_month = (
        Paiement.objects.filter(
            statut="confirme", date_paiement__gte=first_day_this_month
        ).aggregate(t=Sum("montant"))["t"]
        or 0
    )
    revenue_last_month = (
        Paiement.objects.filter(
            statut="confirme",
            date_paiement__gte=last_month_start,
            date_paiement__lte=last_month_end,
        ).aggregate(t=Sum("montant"))["t"]
        or 0
    )
    growth_pct = 0
    if revenue_last_month:
        growth_pct = int(
            ((float(revenue_this_month) - float(revenue_last_month)) / float(revenue_last_month))
            * 100
        )

    moyen_data = (
        Paiement.objects.filter(statut="confirme")
        .values("moyen_paiement")
        .annotate(total=Sum("montant"), count=Count("id"))
        .order_by("-total")
    )
    moyen_labels = []
    moyen_values = []
    moyen_map = dict(Paiement.MOYEN_CHOICES)
    for m in moyen_data:
        moyen_labels.append(moyen_map.get(m["moyen_paiement"], m["moyen_paiement"]))
        moyen_values.append(float(m["total"]))

    stats_certifs = []
    for cert in Certification.objects.order_by("nom"):
        nb_i = Inscription.objects.filter(cohorte__certification=cert).count()
        nb_c = Inscription.objects.filter(cohorte__certification=cert, statut="certifie").count()
        enc = (
            Paiement.objects.filter(
                inscription__cohorte__certification=cert, statut="confirme"
            ).aggregate(t=Sum("montant"))["t"]
            or 0
        )
        taux = int(nb_c / nb_i * 100) if nb_i else 0
        stats_certifs.append(
            {
                "cert": cert,
                "nb_inscrits": nb_i,
                "nb_certifies": nb_c,
                "encaisse": enc,
                "taux": taux,
            }
        )

    paiements_en_attente = (
        Paiement.objects.filter(statut="en_attente")
        .select_related("inscription__inscrit", "inscription__cohorte__certification")
        .order_by("-created_at")[:20]
    )

    context = {
        "total_encaisse": total_encaisse,
        "total_en_attente": total_en_attente,
        "total_du": total_du,
        "total_inscrits": total_inscrits,
        "total_certifies": total_certifies,
        "taux_certif": taux_certif,
        "taux_recouvrement": taux_recouvrement,
        "nb_paiements_confirmes": nb_paiements_confirmes,
        "montant_moyen": montant_moyen,
        "revenue_this_month": revenue_this_month,
        "revenue_last_month": revenue_last_month,
        "growth_pct": growth_pct,
        "months_labels_json": json.dumps(months_labels),
        "months_values_json": json.dumps(months_values),
        "moyen_labels_json": json.dumps(moyen_labels),
        "moyen_values_json": json.dumps(moyen_values),
        "stats_certifs": stats_certifs,
        "paiements_en_attente": paiements_en_attente,
        "active_page": "dashboard_financier",
    }
    return render(request, "inscriptions/dashboard_financier.html", context)
