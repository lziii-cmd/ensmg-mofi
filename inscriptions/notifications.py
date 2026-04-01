"""
Notifications email automatiques — ENSMG Certification.
Les emails sont envoyés de façon non-bloquante (try/except pour ne pas
interrompre le flux si le serveur SMTP est mal configuré).
"""
import logging
from django.core.mail import send_mail
from django.conf import settings

logger = logging.getLogger(__name__)

_FROM = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@ensmg.sn")


def _send(subject, body, to_list):
    """Wrapper silencieux autour de send_mail."""
    if not to_list:
        return
    try:
        send_mail(subject, body, _FROM, to_list, fail_silently=False)
    except Exception as exc:
        logger.error("Échec envoi email '%s' → %s : %s", subject, to_list, exc)


# ── Inscription ───────────────────────────────────────────────────────────────

def notifier_inscription(inscription):
    """Email de confirmation d'inscription à l'inscrit."""
    inscrit = inscription.inscrit
    cohorte = inscription.cohorte
    if not inscrit.email:
        return
    subject = f"[ENSMG] Confirmation d'inscription — {cohorte.certification.nom}"
    body = (
        f"Bonjour {inscrit.prenom} {inscrit.nom},\n\n"
        f"Votre inscription à la certification « {cohorte.certification.nom} »"
        f" (cohorte : {cohorte.nom}) a bien été enregistrée.\n\n"
        f"Montant dû : {inscription.montant_du:,.0f} FCFA\n\n"
        f"Cordialement,\nL'équipe ENSMG"
    )
    _send(subject, body, [inscrit.email])


# ── Paiement ──────────────────────────────────────────────────────────────────

def notifier_paiement(paiement):
    """Email de reçu de paiement à l'inscrit."""
    inscrit = paiement.inscription.inscrit
    if not inscrit.email:
        return
    subject = f"[ENSMG] Reçu de paiement — {paiement.montant:,.0f} FCFA"
    body = (
        f"Bonjour {inscrit.prenom} {inscrit.nom},\n\n"
        f"Nous avons bien reçu votre paiement de {paiement.montant:,.0f} FCFA"
        f" (réf. {paiement.reference or 'N/A'}) via {paiement.get_moyen_paiement_display()}.\n\n"
        f"Reste à payer : {paiement.inscription.reste_a_payer:,.0f} FCFA\n\n"
        f"Cordialement,\nL'équipe ENSMG"
    )
    _send(subject, body, [inscrit.email])


def notifier_paiement_confirme(paiement):
    """Email de confirmation de paiement (après validation admin)."""
    inscrit = paiement.inscription.inscrit
    if not inscrit.email:
        return
    subject = f"[ENSMG] Paiement confirmé — {paiement.montant:,.0f} FCFA"
    body = (
        f"Bonjour {inscrit.prenom} {inscrit.nom},\n\n"
        f"Votre paiement de {paiement.montant:,.0f} FCFA"
        f" (réf. {paiement.reference or 'N/A'}) a été confirmé par notre équipe.\n\n"
        f"Cordialement,\nL'équipe ENSMG"
    )
    _send(subject, body, [inscrit.email])


# ── Attestation ───────────────────────────────────────────────────────────────

def notifier_attestation(attestation):
    """Email d'avis de disponibilité d'attestation."""
    inscrit = attestation.inscription.inscrit
    if not inscrit.email:
        return
    certification = attestation.inscription.cohorte.certification
    subject = f"[ENSMG] Votre attestation est disponible — {certification.nom}"
    body = (
        f"Bonjour {inscrit.prenom} {inscrit.nom},\n\n"
        f"Félicitations ! Votre attestation de certification « {certification.nom} »"
        f" (N° {attestation.numero}) est disponible.\n\n"
        f"Vous pouvez la télécharger en vous connectant à votre espace apprenant.\n\n"
        f"Cordialement,\nL'équipe ENSMG"
    )
    _send(subject, body, [inscrit.email])


# ── Changement de statut ──────────────────────────────────────────────────────

def notifier_changement_statut(inscription):
    """Email informatif lors d'un changement de statut d'inscription."""
    inscrit = inscription.inscrit
    if not inscrit.email:
        return
    statut_display = inscription.get_statut_display()
    subject = f"[ENSMG] Mise à jour de votre dossier — {statut_display}"
    body = (
        f"Bonjour {inscrit.prenom} {inscrit.nom},\n\n"
        f"Le statut de votre inscription à « {inscription.cohorte.certification.nom} »"
        f" a été mis à jour : {statut_display}.\n\n"
        f"Cordialement,\nL'équipe ENSMG"
    )
    _send(subject, body, [inscrit.email])
