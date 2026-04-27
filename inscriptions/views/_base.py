"""
Imports communs, décorateurs et helpers partagés entre tous les modules de vues.
Ce fichier est le seul endroit où ces utilitaires sont définis.
"""

import io
import json
import re
import unicodedata
import uuid
from functools import wraps

import openpyxl
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django_ratelimit.decorators import ratelimit

from ..forms import (
    CertificationForm,
    ChangerStatutForm,
    CohorteForm,
    ImportExcelForm,
    InscriptionForm,
    InscritForm,
    PaiementForm,
    PaiementInscriptionForm,
    UserForm,
)
from ..models import (
    Attestation,
    Certification,
    Cohorte,
    CompteApprenant,
    Inscription,
    Inscrit,
    Paiement,
)
from ..notifications import (
    notifier_attestation,
    notifier_changement_statut,
    notifier_inscription,
    notifier_paiement,
    notifier_paiement_confirme,
)
from ..roles import get_user_role as _get_user_role

# ---------------------------------------------------------------------------
# Décorateurs
# ---------------------------------------------------------------------------


def admin_required(view_func):
    """Réservé aux Super Utilisateurs uniquement."""

    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_superuser:
            messages.error(request, "Accès réservé aux super utilisateurs.")
            return redirect("dashboard")
        return view_func(request, *args, **kwargs)

    return wrapper


def users_required(view_func):
    """Gestion des utilisateurs : Super Utilisateur + Admin."""

    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        role = _get_user_role(request.user)
        if role not in ("super_utilisateur", "admin"):
            messages.error(request, "Accès réservé aux administrateurs système.")
            return redirect("dashboard")
        return view_func(request, *args, **kwargs)

    return wrapper


def write_required(view_func):
    """Opérations d'écriture : Super Utilisateur + Responsable Scolarité uniquement."""

    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        role = _get_user_role(request.user)
        if role in ("admin", "personnel_utilisateur"):
            messages.warning(request, "Vous avez un accès en lecture seule.")
            return redirect(request.META.get("HTTP_REFERER", "dashboard"))
        return view_func(request, *args, **kwargs)

    return wrapper


def _apprenant_required(view_func):
    """Decorator: must be logged in as apprenant (has compte_apprenant)."""

    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        try:
            _ = request.user.compte_apprenant
        except Exception:
            messages.error(request, "Accès réservé aux apprenants.")
            return redirect("dashboard")
        return view_func(request, *args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# Auto-transitions de statut
# ---------------------------------------------------------------------------


def _auto_transition_statuts():
    """
    Parcourt les inscriptions et met à jour automatiquement le statut selon
    les dates de la cohorte :
      - statut = 'inscrit' + cohorte.date_debut <= today + reste_a_payer == 0 → 'en_formation'
      - statut = 'en_formation' + cohorte.date_fin <= today → 'formation_terminee'
    Les pré-inscrits (sans paiement confirmé) ne sont PAS promus.
    """
    today = timezone.now().date()

    candidates = Inscription.objects.filter(
        statut="inscrit",
        cohorte__date_debut__lte=today,
        cohorte__date_fin__gte=today,
    ).prefetch_related("paiements")

    to_promote = [
        ic.pk
        for ic in candidates
        if sum(p.montant for p in ic.paiements.all() if p.statut == "confirme") >= ic.montant_du
    ]
    if to_promote:
        Inscription.objects.filter(pk__in=to_promote).update(statut="en_formation")

    Inscription.objects.filter(
        statut="en_formation",
        cohorte__date_fin__lt=today,
    ).update(statut="formation_terminee")


# ---------------------------------------------------------------------------
# Import Excel helpers
# ---------------------------------------------------------------------------

COLUMN_ALIASES = {
    "nom": ["nom", "name", "last_name", "lastname", "family_name"],
    "prenom": ["prenom", "prénom", "first_name", "firstname", "given_name"],
    "email": ["email", "e-mail", "mail", "courriel", "adresse_email"],
    "telephone": ["telephone", "téléphone", "tel", "phone", "mobile", "portable"],
    "activite": ["activite", "activité", "formation", "profil"],
}


def _normalize_header(header):
    if header is None:
        return ""
    return str(header).lower().strip().replace(" ", "_").replace("-", "_")


def _map_columns(headers):
    mapping = {}
    normalized = [_normalize_header(h) for h in headers]
    for field, aliases in COLUMN_ALIASES.items():
        for i, norm in enumerate(normalized):
            if norm in aliases:
                mapping[field] = i
                break
    return mapping


# ---------------------------------------------------------------------------
# Sessions actives
# ---------------------------------------------------------------------------


def _get_active_session_data():
    """
    Retourne un dict {user_id: session_info} pour toutes les sessions non expirées.
    session_info = {'expire_date': datetime, 'session_key': str}
    """
    from django.contrib.sessions.models import Session

    active = {}
    for session in Session.objects.filter(expire_date__gte=timezone.now()):
        try:
            data = session.get_decoded()
            uid = data.get("_auth_user_id")
            if uid:
                uid = int(uid)
                if uid not in active or session.expire_date > active[uid]["expire_date"]:
                    active[uid] = {
                        "expire_date": session.expire_date,
                        "session_key": session.session_key,
                    }
        except Exception:
            pass
    return active


# ---------------------------------------------------------------------------
# Génération QR + attestation PDF
# ---------------------------------------------------------------------------


def _generer_qr_image(url):
    """Génère un QR code en mémoire et renvoie un objet reportlab Image."""
    import qrcode
    from reportlab.platypus import Image as RLImage

    qr = qrcode.QRCode(
        version=2, box_size=4, border=2, error_correction=qrcode.constants.ERROR_CORRECT_H
    )
    qr.add_data(url)
    qr.make(fit=True)
    pil_img = qr.make_image(fill_color="#1a2340", back_color="white")
    buf = io.BytesIO()
    pil_img.save(buf, format="PNG")
    buf.seek(0)
    return RLImage(buf, width=2.8 * 28.35, height=2.8 * 28.35)


def _generer_attestation_pdf(inscription, verification_url=""):
    """Génère le PDF d'attestation via PIL (template PNG + overlay CSS)."""
    import os

    from PIL import Image, ImageDraw, ImageFont

    inscrit = inscription.inscrit
    certification = inscription.cohorte.certification
    today = timezone.now().date()

    STATIC = os.path.join(settings.BASE_DIR, "inscriptions", "static", "inscriptions")
    IMG_DIR = os.path.join(STATIC, "img")
    FONT_DIR = os.path.join(STATIC, "fonts")
    NAVY = (13, 36, 97)
    GREY = (68, 68, 68)
    DPI = 150

    A4W = int(297 * DPI / 25.4)
    A4H = int(210 * DPI / 25.4)

    tmpl = Image.open(os.path.join(IMG_DIR, "cert_template.png")).convert("RGB")
    img = tmpl.resize((A4W, A4H), Image.LANCZOS)
    W, H = A4W, A4H
    draw = ImageDraw.Draw(img)

    def px(x_mm, y_mm):
        return int(x_mm * W / 297), int(y_mm * H / 210)

    def white_box(x1_mm, y1_mm, x2_mm, y2_mm):
        x1, y1 = px(x1_mm, y1_mm)
        x2, y2 = px(x2_mm, y2_mm)
        draw.rectangle([x1, y1, x2, y2], fill="white")

    def pt(size_mm):
        return max(10, int(size_mm * DPI / 25.4))

    def load_font(name, size_mm):
        try:
            return ImageFont.truetype(os.path.join(FONT_DIR, name), pt(size_mm))
        except Exception:
            return ImageFont.load_default()

    def load_sys_font(name, size_mm):
        for path in [
            f"C:/Windows/Fonts/{name}",
            f"/usr/share/fonts/truetype/liberation/{name}",
            f"/usr/share/fonts/{name}",
        ]:
            try:
                return ImageFont.truetype(path, pt(size_mm))
            except Exception:
                continue
        return ImageFont.load_default()

    def draw_centered(text, y_mm, font, color=NAVY):
        _, y = px(0, y_mm)
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        draw.text(((W - tw) // 2, y), text, font=font, fill=color)

    font_script = load_font("DancingScript-Bold.ttf", 14)
    font_bold = load_sys_font("arialbd.ttf", 5.5)
    font_reg = load_sys_font("arial.ttf", 4.5)
    font_sm = load_sys_font("arial.ttf", 3.5)
    font_tiny = load_sys_font("arial.ttf", 2.8)

    white_box(125, 0, 173, 27)

    cert_num = f"ENSMG-{today.year}-{inscription.pk:04d}"
    white_box(5.5, 8.2, 48, 14)
    x1, y1 = px(5.5, 8.2)
    x2, y2 = px(48, 14)
    draw.rounded_rectangle([x1, y1, x2, y2], radius=6, outline=NAVY, width=2)
    cert_txt = f"Certificat N° : {cert_num}"
    bbox = draw.textbbox((0, 0), cert_txt, font=font_tiny)
    th = bbox[3] - bbox[1]
    draw.text((x1 + 8, (y1 + y2) // 2 - th // 2), cert_txt, font=font_tiny, fill=GREY)

    white_box(2, 100, 295, 120)
    nom_txt = f"{inscrit.prenom} {inscrit.nom}"
    fn = font_script
    bbox_n = draw.textbbox((0, 0), nom_txt, font=fn)
    while (bbox_n[2] - bbox_n[0]) > int(0.85 * W) and fn.size > pt(7):
        fn = ImageFont.truetype(os.path.join(FONT_DIR, "DancingScript-Bold.ttf"), fn.size - 4)
        bbox_n = draw.textbbox((0, 0), nom_txt, font=fn)
    _, y_top = px(0, 100)
    _, y_bot = px(0, 120)
    th_n = bbox_n[3] - bbox_n[1]
    y_name = y_top + (y_bot - y_top - th_n) // 2
    draw.text(((W - (bbox_n[2] - bbox_n[0])) // 2, y_name), nom_txt, font=fn, fill=NAVY)

    white_box(2, 119, 295, 160)
    nom_cert = certification.nom
    bbox_f = draw.textbbox((0, 0), nom_cert, font=font_bold)
    if (bbox_f[2] - bbox_f[0]) > int(0.82 * W):
        words = nom_cert.split()
        mid = len(words) // 2
        draw_centered(" ".join(words[:mid]), 123, font_bold, NAVY)
        draw_centered(" ".join(words[mid:]), 132, font_bold, NAVY)
        desc_y = 143
    else:
        draw_centered(nom_cert, 127, font_bold, NAVY)
        desc_y = 139

    desc = certification.description.strip() if certification.description else ""
    if desc:
        desc_txt = f"({desc})" if not desc.startswith("(") else desc
        draw_centered(desc_txt, desc_y, font_reg, GREY)

    white_box(6, 143, 46, 184)
    if verification_url:
        try:
            import qrcode as _qrcode

            _qr = _qrcode.QRCode(
                version=2, box_size=8, border=2, error_correction=_qrcode.constants.ERROR_CORRECT_H
            )
            _qr.add_data(verification_url)
            _qr.make(fit=True)
            qr_img = _qr.make_image(fill_color=(13, 36, 97), back_color="white").convert("RGB")
            qr_px = int(38 * W / 297)
            qr_img = qr_img.resize((qr_px, qr_px), Image.LANCZOS)
            qx, qy = px(7.5, 144.8)
            img.paste(qr_img, (qx, qy))
        except Exception:
            pass

    white_box(220, 193, 293, 204)
    date_str = f"Fait à Dakar, le {today.day:02d} / {today.month:02d} / {today.year}"
    _, y_date = px(0, 196)
    bbox_d = draw.textbbox((0, 0), date_str, font=font_sm)
    tw_d = bbox_d[2] - bbox_d[0]
    draw.text((W - px(8, 0)[0] - tw_d, y_date), date_str, font=font_sm, fill=NAVY)

    buf = io.BytesIO()
    img.save(buf, format="PDF", resolution=DPI)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Utilitaires comptes apprenants
# ---------------------------------------------------------------------------


def _slugify_name(text):
    """
    Convert a name (possibly compound) to a lowercase ASCII slug without separators.
    'Mamadou Fole' -> 'mamadoufole'
    """
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]", "", text)
    return text


def _creer_compte_apprenant(inscrit):
    """Create Django User + CompteApprenant for a new portal registrant. Returns (user, compte)."""
    base_username = f"{_slugify_name(inscrit.prenom)}.{_slugify_name(inscrit.nom)}@ensmg.sn"
    username = base_username
    counter = 2
    while User.objects.filter(username=username).exists():
        name_part = base_username.replace("@ensmg.sn", "")
        username = f"{name_part}{counter}@ensmg.sn"
        counter += 1

    user = User.objects.create_user(
        username=username,
        email=inscrit.email or username,
        password="passer01",
        first_name=inscrit.prenom,
        last_name=inscrit.nom,
    )
    compte = CompteApprenant.objects.create(user=user, inscrit=inscrit, mdp_change=False)

    if inscrit.email:
        _send_email_apprenant(
            inscrit,
            subject="[ENSMG] Vos identifiants de connexion au portail",
            body=(
                f"Bonjour {inscrit.prenom},\n\n"
                f"Un compte a été créé pour vous sur le portail ENSMG.\n\n"
                f"Vos identifiants de connexion :\n"
                f"  Identifiant : {username}\n"
                f"  Mot de passe provisoire : passer01\n\n"
                f"Connectez-vous sur : https://ensmg.sn/login/\n"
                f"Vous serez invité(e) à changer votre mot de passe à la première connexion.\n\n"
                f"Cordialement,\nL'équipe ENSMG"
            ),
        )
    return user, compte


def _send_email_apprenant(inscrit, subject, body):
    """Send an email to an apprenant. Silently ignores errors (no email configured)."""
    if not inscrit.email:
        return
    try:
        from django.core.mail import send_mail

        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[inscrit.email],
            fail_silently=True,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Génération reçu PDF
# ---------------------------------------------------------------------------


def _generer_recu_pdf(paiement, request=None):
    """Generate a payment receipt PDF and return bytes."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
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
