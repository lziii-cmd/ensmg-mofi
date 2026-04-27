import io

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from ..forms import PaiementForm, PaiementInscriptionForm
from ..models import Inscription, Notification, Paiement
from ..notifications import notifier_paiement, notifier_paiement_confirme
from ._base import _send_email_apprenant


@login_required
def paiement_ajouter_pour_inscription(request, pk):
    inscription = get_object_or_404(Inscription, pk=pk)

    if request.method == "POST":
        form = PaiementInscriptionForm(request.POST)
        if form.is_valid():
            paiement = form.save(commit=False)
            paiement.inscription = inscription
            reste = inscription.reste_a_payer
            if reste <= 0:
                messages.warning(request, "Ce dossier est déjà intégralement réglé.")
            elif paiement.montant > reste:
                messages.error(
                    request,
                    f"Le montant saisi ({paiement.montant} FCFA) dépasse le reste"
                    f" à payer ({reste} FCFA). Veuillez corriger.",
                )
            else:
                paiement.save()
                notifier_paiement(paiement)
                messages.success(request, f"Paiement de {paiement.montant} FCFA enregistré.")
        else:
            messages.error(request, "Erreur dans le formulaire de paiement.")
    return redirect("inscrit_detail", pk=inscription.inscrit.pk)


@login_required
def paiements_list(request):
    query = request.GET.get("q", "").strip()
    moyen_filter = request.GET.get("moyen", "")

    paiements = Paiement.objects.select_related(
        "inscription__inscrit", "inscription__cohorte__certification"
    ).order_by("-date_paiement", "-created_at")

    if query:
        for mot in query.split():
            paiements = paiements.filter(
                Q(inscription__inscrit__nom__icontains=mot)
                | Q(inscription__inscrit__prenom__icontains=mot)
                | Q(inscription__inscrit__email__icontains=mot)
                | Q(inscription__cohorte__certification__nom__icontains=mot)
                | Q(inscription__cohorte__nom__icontains=mot)
                | Q(reference__icontains=mot)
            )

    if moyen_filter:
        paiements = paiements.filter(moyen_paiement=moyen_filter)

    filter_certif_ids = request.session.get("filter_certif_ids", [])
    filter_cohorte_ids = request.session.get("filter_cohorte_ids", [])
    if filter_cohorte_ids:
        paiements = paiements.filter(inscription__cohorte_id__in=filter_cohorte_ids)
    elif filter_certif_ids:
        paiements = paiements.filter(inscription__cohorte__certification_id__in=filter_certif_ids)

    total_filtre = paiements.aggregate(total=Sum("montant"))["total"] or 0

    paiements_en_attente = (
        Paiement.objects.filter(statut="en_attente")
        .select_related("inscription__inscrit", "inscription__cohorte__certification")
        .order_by("-created_at")
    )

    paginator = Paginator(paiements, 25)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    context = {
        "paiements": page_obj,
        "page_obj": page_obj,
        "paiements_en_attente": paiements_en_attente,
        "query": query,
        "moyen_filter": moyen_filter,
        "moyen_choices": Paiement.MOYEN_CHOICES,
        "total_filtre": total_filtre,
        "active_page": "paiements",
    }
    return render(request, "inscriptions/paiements_list.html", context)


@login_required
def paiement_ajouter(request):
    if request.method == "POST":
        form = PaiementForm(request.POST)
        if form.is_valid():
            paiement = form.save()
            notifier_paiement(paiement)
            messages.success(request, f"Paiement de {paiement.montant} FCFA enregistré.")
            return redirect("inscrit_detail", pk=paiement.inscription.inscrit.pk)
    else:
        form = PaiementForm(initial={"date_paiement": timezone.now().date()})

    context = {
        "form": form,
        "titre": "Ajouter un paiement",
        "action": "Enregistrer",
        "active_page": "paiements",
    }
    return render(request, "inscriptions/paiement_form.html", context)


@login_required
def paiement_modifier(request, pk):
    paiement = get_object_or_404(Paiement, pk=pk)
    if request.method == "POST":
        form = PaiementForm(request.POST, instance=paiement)
        if form.is_valid():
            form.save()
            messages.success(request, "Paiement modifié avec succès.")
            return redirect("inscrit_detail", pk=paiement.inscription.inscrit.pk)
    else:
        form = PaiementForm(instance=paiement)

    context = {
        "form": form,
        "paiement": paiement,
        "titre": "Modifier le paiement",
        "action": "Enregistrer",
        "active_page": "paiements",
    }
    return render(request, "inscriptions/paiement_form.html", context)


@login_required
def paiement_supprimer(request, pk):
    paiement = get_object_or_404(Paiement, pk=pk)
    inscrit_pk = paiement.inscription.inscrit.pk
    if request.method == "POST":
        montant = paiement.montant
        paiement.delete()
        messages.success(request, f"Paiement de {montant} FCFA supprimé.")
        return redirect("inscrit_detail", pk=inscrit_pk)

    context = {
        "paiement": paiement,
        "active_page": "paiements",
    }
    return render(request, "inscriptions/paiement_confirm_delete.html", context)


@login_required
def admin_confirmer_paiement(request, pk):
    """Admin confirms a pending (virement/wave/om) payment."""
    paiement = get_object_or_404(Paiement, pk=pk)
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "Accès refusé.")
        return redirect("dashboard")
    if request.method == "POST":
        paiement.statut = "confirme"
        paiement.save()
        inscription = paiement.inscription
        if inscription.statut == "pre_inscrit":
            inscription.statut = "inscrit"
            inscription.save(update_fields=["statut"])
        notifier_paiement_confirme(paiement)
        try:
            if hasattr(inscription.inscrit, "compte_apprenant"):
                Notification.objects.create(
                    destinataire=inscription.inscrit.compte_apprenant,
                    type_notif="paiement_confirme",
                    message=(
                        f"Votre paiement de {paiement.montant} FCFA pour "
                        f"« {inscription.cohorte.certification.nom} » a été confirmé. "
                        "Votre inscription est validée."
                    ),
                    lien="/apprenant/paiements/",
                )
        except Exception:
            pass
        _send_email_apprenant(
            inscription.inscrit,
            subject=f"[ENSMG] Paiement confirmé — {inscription.cohorte.certification.nom}",
            body=(
                f"Bonjour {inscription.inscrit.prenom},\n\n"
                f"Votre paiement de {paiement.montant} FCFA pour la certification "
                f"« {inscription.cohorte.certification.nom} » a été confirmé.\n\n"
                "Votre inscription est maintenant validée. "
                "Vous pouvez accéder à votre espace apprenant : "
                "https://ensmg.sn/apprenant/\n\n"
                "Cordialement,\nL'équipe ENSMG"
            ),
        )
        messages.success(
            request,
            f"Paiement de {paiement.montant} FCFA confirmé. Statut mis à jour : Inscrit.",
        )
        return redirect("paiements_list")
    return render(request, "inscriptions/confirmer_paiement.html", {"paiement": paiement})


@login_required
def admin_annuler_paiement(request, pk):
    """Admin cancels/rejects a pending payment."""
    paiement = get_object_or_404(Paiement, pk=pk)
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "Accès refusé.")
        return redirect("dashboard")
    if request.method == "POST":
        motif = request.POST.get("motif", "").strip()
        paiement.statut = "annule"
        paiement.notes = (paiement.notes or "") + f"\n[Annulé par admin: {motif}]"
        paiement.save()
        inscription = paiement.inscription
        try:
            if hasattr(inscription.inscrit, "compte_apprenant"):
                Notification.objects.create(
                    destinataire=inscription.inscrit.compte_apprenant,
                    type_notif="paiement_annule",
                    message=(
                        f"Votre paiement de {paiement.montant} FCFA pour "
                        f"« {inscription.cohorte.certification.nom} » a été annulé."
                        f"{' Motif : ' + motif if motif else ''}"
                    ),
                    lien="/apprenant/paiements/",
                )
        except Exception:
            pass
        _send_email_apprenant(
            inscription.inscrit,
            subject=f"[ENSMG] Paiement annulé — {inscription.cohorte.certification.nom}",
            body=(
                f"Bonjour {inscription.inscrit.prenom},\n\n"
                f"Votre paiement de {paiement.montant} FCFA pour la certification "
                f"« {inscription.cohorte.certification.nom} »"
                " a été annulé par l'administration.\n\n"
                f"{'Motif : ' + motif + chr(10) + chr(10) if motif else ''}"
                "Pour toute question, contactez-nous à admin@ensmg.sn\n\n"
                "Cordialement,\nL'équipe ENSMG"
            ),
        )
        messages.warning(request, f"Paiement de {paiement.montant} FCFA annulé.")
        return redirect("paiements_list")
    return render(request, "inscriptions/annuler_paiement.html", {"paiement": paiement})


def _generer_recu_pdf(paiement, request=None):
    """Generate a payment receipt PDF and return bytes."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        HRFlowable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2.5 * cm,
        rightMargin=2.5 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    navy = colors.HexColor("#1a2340")
    accent = colors.HexColor("#4f6ef7")
    gold = colors.HexColor("#d4a017")
    grey = colors.HexColor("#718096")
    green = colors.HexColor("#38a169")

    styles = getSampleStyleSheet()

    def ms(name, **kw):
        return ParagraphStyle(name, parent=styles["Normal"], **kw)

    s_title = ms(
        "t",
        fontSize=22,
        textColor=navy,
        alignment=TA_CENTER,
        fontName="Helvetica-Bold",
        leading=28,
        spaceAfter=4,
    )
    s_sub = ms("s", fontSize=10, textColor=accent, alignment=TA_CENTER, leading=14)
    s_label = ms("l", fontSize=9, textColor=grey, leading=13)
    s_value = ms("v", fontSize=11, textColor=navy, fontName="Helvetica-Bold", leading=16)
    s_big = ms(
        "b",
        fontSize=18,
        textColor=green,
        fontName="Helvetica-Bold",
        alignment=TA_CENTER,
        leading=24,
    )
    s_footer = ms("f", fontSize=8, textColor=grey, alignment=TA_CENTER, leading=11)

    inscrit = paiement.inscription.inscrit
    certification = paiement.inscription.cohorte.certification
    moyen_map = dict(Paiement.MOYEN_CHOICES)
    moyen_label = moyen_map.get(paiement.moyen_paiement, paiement.moyen_paiement)

    story = []
    story.append(Paragraph("ÉCOLE NATIONALE SUPÉRIEURE DES MINES ET DE LA GÉOLOGIE", s_title))
    story.append(Paragraph("ENSMG — Dakar, Sénégal", s_sub))
    story.append(Spacer(1, 0.3 * cm))
    story.append(HRFlowable(width="100%", thickness=3, color=accent, spaceAfter=3))
    story.append(HRFlowable(width="100%", thickness=1, color=gold, spaceAfter=10))
    story.append(Spacer(1, 0.3 * cm))
    story.append(
        Paragraph(
            "REÇU DE PAIEMENT",
            ms(
                "rp",
                fontSize=26,
                textColor=navy,
                alignment=TA_CENTER,
                fontName="Helvetica-Bold",
                leading=32,
                spaceAfter=6,
            ),
        )
    )
    story.append(
        Paragraph(
            f"N° {paiement.reference or paiement.pk}",
            ms("ref", fontSize=11, textColor=grey, alignment=TA_CENTER, leading=14),
        )
    )
    story.append(Spacer(1, 0.5 * cm))

    data = [
        [Paragraph("Bénéficiaire", s_label), Paragraph(f"{inscrit.prenom} {inscrit.nom}", s_value)],
        [Paragraph("Certification", s_label), Paragraph(certification.nom, s_value)],
        [Paragraph("Cohorte", s_label), Paragraph(paiement.inscription.cohorte.nom, s_value)],
        [
            Paragraph("Date", s_label),
            Paragraph(paiement.date_paiement.strftime("%d/%m/%Y"), s_value),
        ],
        [Paragraph("Moyen", s_label), Paragraph(moyen_label, s_value)],
    ]
    if paiement.reference:
        data.append([Paragraph("Référence", s_label), Paragraph(paiement.reference, s_value)])

    t = Table(data, colWidths=[5 * cm, 12 * cm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f0f2f8")),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#f8f9ff")]),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                ("PADDING", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(t)
    story.append(Spacer(1, 0.6 * cm))
    story.append(
        HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e2e8f0"), spaceAfter=10)
    )
    story.append(Paragraph(f"{int(paiement.montant):,} FCFA".replace(",", " "), s_big))
    story.append(Spacer(1, 0.4 * cm))
    story.append(HRFlowable(width="100%", thickness=1, color=accent, spaceAfter=4))
    story.append(HRFlowable(width="100%", thickness=3, color=navy, spaceAfter=6))
    story.append(
        Paragraph(
            "Ce document atteste du paiement effectué auprès de"
            " l'École Nationale Supérieure des Mines et de la Géologie.",
            s_footer,
        )
    )
    story.append(
        Paragraph(
            "ENSMG — École Nationale Supérieure des Mines et de la Géologie"
            " — Dakar, Sénégal — www.ensmg.sn",
            s_footer,
        )
    )

    doc.build(story)
    return buffer.getvalue()


@login_required
def recu_download(request, pk):
    """Download or generate payment receipt PDF."""
    paiement = get_object_or_404(Paiement, pk=pk)
    is_owner = False
    try:
        compte = request.user.compte_apprenant
        if paiement.inscription.inscrit == compte.inscrit:
            is_owner = True
    except Exception:
        pass

    if not is_owner and not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "Accès refusé.")
        return redirect("dashboard")

    if not paiement.recu_pdf:
        pdf_bytes = _generer_recu_pdf(paiement, request)
        paiement.recu_pdf = pdf_bytes
        paiement.save(update_fields=["recu_pdf"])

    nom = paiement.inscription.inscrit.nom_complet.replace(" ", "_")
    response = HttpResponse(bytes(paiement.recu_pdf), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="recu_{nom}_{paiement.pk}.pdf"'
    return response


@login_required
def recu_view(request, pk):
    """View payment receipt PDF inline in the browser."""
    paiement = get_object_or_404(Paiement, pk=pk)
    is_owner = False
    try:
        compte = request.user.compte_apprenant
        if paiement.inscription.inscrit == compte.inscrit:
            is_owner = True
    except Exception:
        pass

    if not is_owner and not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "Accès refusé.")
        return redirect("dashboard")

    if not paiement.recu_pdf:
        pdf_bytes = _generer_recu_pdf(paiement, request)
        paiement.recu_pdf = pdf_bytes
        paiement.save(update_fields=["recu_pdf"])

    nom = paiement.inscription.inscrit.nom_complet.replace(" ", "_")
    response = HttpResponse(bytes(paiement.recu_pdf), content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="recu_{nom}_{paiement.pk}.pdf"'
    return response
