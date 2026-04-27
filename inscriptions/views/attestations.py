import io

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from ..models import Attestation, Certification, Inscription, Notification
from ..notifications import notifier_attestation
from ._base import _send_email_apprenant


@login_required
def certifier_home(request):
    certifications = Certification.objects.filter(actif=True).order_by("nom")
    return render(
        request,
        "inscriptions/certifier_home.html",
        {
            "certifications": certifications,
            "active_page": "certifier",
        },
    )


@login_required
def certifier_inscrits(request, pk):
    certification = get_object_or_404(Certification, pk=pk)
    inscriptions = (
        Inscription.objects.filter(cohorte__certification=certification)
        .exclude(statut="certifie")
        .select_related("inscrit", "cohorte")
        .order_by("inscrit__nom", "inscrit__prenom")
    )
    certifies = (
        Inscription.objects.filter(cohorte__certification=certification, statut="certifie")
        .select_related("inscrit", "cohorte")
        .prefetch_related("attestations")
        .order_by("inscrit__nom", "inscrit__prenom")
    )
    return render(
        request,
        "inscriptions/certifier_inscrits.html",
        {
            "certification": certification,
            "inscriptions": inscriptions,
            "certifies": certifies,
            "active_page": "certifier",
        },
    )


@login_required
def certifier_action(request, pk):
    if request.method != "POST":
        return redirect("certifier_inscrits", pk=pk)

    certification = get_object_or_404(Certification, pk=pk)
    inscription_ids = request.POST.getlist("inscription_ids")

    if not inscription_ids:
        messages.warning(request, "Aucun inscrit sélectionné.")
        return redirect("certifier_inscrits", pk=pk)

    inscriptions_qs = Inscription.objects.filter(
        pk__in=inscription_ids,
        cohorte__certification=certification,
    ).select_related("inscrit", "cohorte", "cohorte__certification")

    nb_ok = 0
    for inscription in inscriptions_qs:
        if inscription.attestations.exists():
            continue

        inscription.statut = "certifie"
        inscription.save()

        annee = timezone.now().year
        abbrev = "".join(c for c in certification.nom.upper() if c.isalpha())[:6]
        seq = (
            Attestation.objects.filter(
                inscription__cohorte__certification=certification,
                date_delivrance__year=annee,
            ).count()
            + 1
        )
        numero = f"CERT-ENSMG-{abbrev}-{annee}-{seq:03d}"
        while Attestation.objects.filter(numero=numero).exists():
            seq += 1
            numero = f"CERT-ENSMG-{abbrev}-{annee}-{seq:03d}"

        Attestation.objects.create(
            inscription=inscription,
            numero=numero,
            date_delivrance=timezone.now().date(),
            contenu_pdf=None,
        )
        nb_ok += 1

    if nb_ok:
        messages.success(
            request,
            f"{nb_ok} apprenant(s) certifié(s). "
            "Téléchargez les QR codes, apposez-les sur vos documents, "
            "puis chargez les attestations PDF ci-dessous.",
        )
    else:
        messages.info(request, "Tous les inscrits sélectionnés ont déjà une attestation.")
    return redirect("certifier_inscrits", pk=pk)


@login_required
def attestation_qr_download(request, pk):
    """Génère et télécharge le QR code de vérification d'une attestation (PNG)."""
    attestation = get_object_or_404(Attestation, pk=pk)
    verification_url = request.build_absolute_uri(f"/attestations/{attestation.numero}/verifier/")
    try:
        import qrcode as _qrcode
        from PIL import Image as _PilImage
        from PIL import ImageOps as _ops

        qr = _qrcode.QRCode(
            version=2,
            box_size=12,
            border=4,
            error_correction=_qrcode.constants.ERROR_CORRECT_H,
        )
        qr.add_data(verification_url)
        qr.make(fit=True)

        qr_bw = qr.make_image(fill_color="black", back_color="white").convert("L")
        w, h = qr_bw.size
        alpha = _ops.invert(qr_bw)
        alpha = alpha.point(lambda x: 0 if x < 128 else 255)

        qr_rgba = _PilImage.new("RGBA", (w, h), (13, 36, 97, 255))
        qr_rgba.putalpha(alpha)

        buf = io.BytesIO()
        qr_rgba.save(buf, format="PNG")
        buf.seek(0)
        nom = attestation.inscription.inscrit.nom_complet.replace(" ", "_")
        response = HttpResponse(buf.getvalue(), content_type="image/png")
        response["Content-Disposition"] = (
            f'attachment; filename="QR_{nom}_{attestation.numero}.png"'
        )
        return response
    except Exception as e:
        messages.error(request, f"Erreur QR : {e}")
        return redirect(request.META.get("HTTP_REFERER", "certifier_home"))


@login_required
def attestation_upload_pdf(request, pk):
    """Charge (ou remplace) le PDF d'une attestation existante."""
    attestation = get_object_or_404(Attestation, pk=pk)
    certif_pk = attestation.inscription.cohorte.certification.pk

    if request.method == "POST":
        pdf_file = request.FILES.get("pdf_file")
        if not pdf_file:
            messages.error(request, "Aucun fichier sélectionné.")
        elif not pdf_file.name.lower().endswith(".pdf"):
            messages.error(request, "Le fichier doit être au format PDF.")
        elif pdf_file.size > 20 * 1024 * 1024:
            messages.error(request, "Fichier trop volumineux (max 20 Mo).")
        else:
            attestation.contenu_pdf = pdf_file.read()
            attestation.save()

            notifier_attestation(attestation)
            try:
                inscrit = attestation.inscription.inscrit
                if hasattr(inscrit, "compte_apprenant"):
                    Notification.objects.create(
                        destinataire=inscrit.compte_apprenant,
                        type_notif="attestation_generee",
                        message=(
                            "Votre attestation pour "
                            f"« {attestation.inscription.cohorte.certification.nom} »"
                            " est maintenant disponible en téléchargement."
                        ),
                        lien="/apprenant/attestations/",
                    )
            except Exception:
                pass
            _send_email_apprenant(
                attestation.inscription.inscrit,
                subject=(
                    f"[ENSMG] Votre attestation est disponible — "
                    f"{attestation.inscription.cohorte.certification.nom}"
                ),
                body=(
                    f"Bonjour {attestation.inscription.inscrit.prenom},\n\n"
                    f"Félicitations ! Votre attestation pour la certification "
                    f"« {attestation.inscription.cohorte.certification.nom} » "
                    f"est maintenant disponible en téléchargement.\n\n"
                    f"Connectez-vous à votre espace apprenant : "
                    f"https://ensmg.sn/apprenant/attestations/\n\n"
                    f"Numéro d'attestation : {attestation.numero}\n\n"
                    f"Cordialement,\nL'équipe ENSMG"
                ),
            )
            messages.success(
                request,
                f"PDF chargé avec succès pour {attestation.inscription.inscrit.nom_complet}.",
            )

    return redirect("certifier_inscrits", pk=certif_pk)


@login_required
def attestation_download(request, pk):
    """Téléchargement du PDF (force download) — servi depuis la base de données."""
    attestation = get_object_or_404(Attestation, pk=pk)
    if not attestation.contenu_pdf:
        messages.error(
            request,
            "PDF non disponible. Veuillez re-certifier cet inscrit pour régénérer l'attestation.",
        )
        return redirect(request.META.get("HTTP_REFERER", "certifier_home"))
    nom = attestation.inscription.inscrit.nom_complet.replace(" ", "_")
    response = HttpResponse(bytes(attestation.contenu_pdf), content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="attestation_{nom}_{attestation.numero}.pdf"'
    )
    return response


@login_required
def attestation_view(request, pk):
    """Visualisation inline du PDF dans le navigateur — servi depuis la base de données."""
    attestation = get_object_or_404(Attestation, pk=pk)
    if not attestation.contenu_pdf:
        messages.error(
            request,
            "PDF non disponible. Veuillez re-certifier cet inscrit pour régénérer l'attestation.",
        )
        return redirect(request.META.get("HTTP_REFERER", "certifier_home"))
    response = HttpResponse(bytes(attestation.contenu_pdf), content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{attestation.numero}.pdf"'
    return response


def attestation_verifier(request, numero):
    """Page publique de vérification d'authenticité (accessible sans connexion)."""
    try:
        attestation = Attestation.objects.select_related(
            "inscription__inscrit", "inscription__cohorte__certification"
        ).get(numero=numero)
        valide = True
    except Attestation.DoesNotExist:
        attestation = None
        valide = False
    return render(
        request,
        "inscriptions/attestation_verifier.html",
        {
            "attestation": attestation,
            "numero": numero,
            "valide": valide,
        },
    )
