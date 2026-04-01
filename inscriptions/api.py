"""
API REST — ENSMG Certification.
Endpoints DRF avec JWT authentication + webhooks Wave / Orange Money.
"""
import hashlib
import hmac
import logging
from django.conf import settings
from django.contrib.auth.models import User, Group
from django.utils import timezone
from rest_framework import viewsets, status, generics
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Certification, Cohorte, Inscrit, Inscription, Paiement, Attestation
from .serializers import (
    CertificationSerializer, CohorteSerializer, InscritSerializer,
    InscritCreateSerializer, InscriptionSerializer, PaiementSerializer,
    AttestationSerializer, UserRoleSerializer,
    WaveWebhookSerializer, OrangeMoneyWebhookSerializer,
)
from .permissions import (
    IsAdministrateur, IsAdminOrResponsable, IsAdminOrComptable, IsStaffOrReadOnly,
)
from .notifications import notifier_paiement_confirme

logger = logging.getLogger(__name__)


# ── Certifications ────────────────────────────────────────────────────────────

class CertificationViewSet(viewsets.ModelViewSet):
    """CRUD certifications. Lecture libre (staff), écriture admin uniquement."""
    queryset = Certification.objects.all().order_by("nom")
    serializer_class = CertificationSerializer
    permission_classes = [IsAuthenticated, IsStaffOrReadOnly]


# ── Cohortes ──────────────────────────────────────────────────────────────────

class CohorteViewSet(viewsets.ModelViewSet):
    queryset = Cohorte.objects.select_related("certification").order_by("-date_debut")
    serializer_class = CohorteSerializer
    permission_classes = [IsAuthenticated, IsStaffOrReadOnly]

    def get_queryset(self):
        qs = super().get_queryset()
        certif_id = self.request.query_params.get("certification")
        if certif_id:
            qs = qs.filter(certification_id=certif_id)
        actif = self.request.query_params.get("actif")
        if actif is not None:
            qs = qs.filter(actif=(actif.lower() == "true"))
        return qs


# ── Inscrits ──────────────────────────────────────────────────────────────────

class InscritViewSet(viewsets.ModelViewSet):
    queryset = Inscrit.objects.all().order_by("nom", "prenom")
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == "create":
            return InscritCreateSerializer
        return InscritSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        q = self.request.query_params.get("q")
        if q:
            qs = qs.filter(nom__icontains=q) | qs.filter(prenom__icontains=q) | qs.filter(email__icontains=q)
        return qs


# ── Inscriptions ──────────────────────────────────────────────────────────────

class InscriptionViewSet(viewsets.ModelViewSet):
    queryset = (
        Inscription.objects
        .select_related("inscrit", "cohorte__certification")
        .order_by("-date_inscription")
    )
    serializer_class = InscriptionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        inscrit_id = self.request.query_params.get("inscrit")
        if inscrit_id:
            qs = qs.filter(inscrit_id=inscrit_id)
        cohorte_id = self.request.query_params.get("cohorte")
        if cohorte_id:
            qs = qs.filter(cohorte_id=cohorte_id)
        statut = self.request.query_params.get("statut")
        if statut:
            qs = qs.filter(statut=statut)
        return qs


# ── Paiements ──────────────────────────────────────────────────────────────────

class PaiementViewSet(viewsets.ModelViewSet):
    queryset = (
        Paiement.objects
        .select_related("inscription__inscrit", "inscription__cohorte__certification")
        .order_by("-date_paiement")
    )
    serializer_class = PaiementSerializer
    permission_classes = [IsAuthenticated, IsAdminOrComptable]

    def get_queryset(self):
        qs = super().get_queryset()
        inscription_id = self.request.query_params.get("inscription")
        if inscription_id:
            qs = qs.filter(inscription_id=inscription_id)
        statut = self.request.query_params.get("statut")
        if statut:
            qs = qs.filter(statut=statut)
        return qs

    @action(detail=True, methods=["post"], url_path="confirmer")
    def confirmer(self, request, pk=None):
        """Confirmer un paiement en attente."""
        paiement = self.get_object()
        if paiement.statut == "confirme":
            return Response({"detail": "Paiement déjà confirmé."}, status=status.HTTP_400_BAD_REQUEST)
        paiement.statut = "confirme"
        paiement.save(update_fields=["statut"])
        notifier_paiement_confirme(paiement)
        return Response(PaiementSerializer(paiement).data)


# ── Attestations ──────────────────────────────────────────────────────────────

class AttestationViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = (
        Attestation.objects
        .select_related("inscription__inscrit", "inscription__cohorte__certification")
        .order_by("-generated_at")
    )
    serializer_class = AttestationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        inscription_id = self.request.query_params.get("inscription")
        if inscription_id:
            qs = qs.filter(inscription_id=inscription_id)
        return qs


# ── Utilisateurs / Rôles ──────────────────────────────────────────────────────

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.prefetch_related("groups").order_by("username")
    serializer_class = UserRoleSerializer
    permission_classes = [IsAuthenticated, IsAdministrateur]

    @action(detail=True, methods=["post"], url_path="set-role")
    def set_role(self, request, pk=None):
        """Assigner un rôle (groupe) à un utilisateur."""
        user = self.get_object()
        role = request.data.get("role", "")
        user.groups.clear()
        user.is_superuser = False
        user.is_staff = False
        if role == "Administrateur":
            user.is_superuser = True
            user.is_staff = True
        elif role in ("Comptable", "Responsable"):
            group, _ = Group.objects.get_or_create(name=role)
            user.groups.add(group)
            user.is_staff = True
        user.save(update_fields=["is_superuser", "is_staff"])
        return Response(UserRoleSerializer(user).data)


# ── Profil courant ────────────────────────────────────────────────────────────

class MeView(generics.RetrieveAPIView):
    """Retourne le profil de l'utilisateur authentifié."""
    serializer_class = UserRoleSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user


# ── Webhooks ──────────────────────────────────────────────────────────────────

class WaveWebhookView(APIView):
    """
    Endpoint POST pour les notifications de paiement Wave.
    Wave envoie un header X-Wave-Signature (HMAC-SHA256) pour authentifier la requête.
    """
    permission_classes = [AllowAny]

    def _verify_signature(self, request):
        secret = getattr(settings, "WAVE_WEBHOOK_SECRET", None)
        if not secret:
            return True  # signature check désactivée si secret non configuré
        sig_header = request.headers.get("X-Wave-Signature", "")
        body = request.body
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(f"sha256={expected}", sig_header)

    def post(self, request):
        if not self._verify_signature(request):
            return Response({"detail": "Signature invalide."}, status=status.HTTP_401_UNAUTHORIZED)

        serializer = WaveWebhookSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        if data["status"] != "succeeded":
            return Response({"detail": "Statut ignoré."})

        ref = data.get("client_reference", "")
        try:
            inscription_id = int(ref)
            inscription = Inscription.objects.get(pk=inscription_id)
        except (ValueError, TypeError, Inscription.DoesNotExist):
            logger.warning("Wave webhook: inscription introuvable pour ref=%s", ref)
            return Response({"detail": "Référence inconnue."}, status=status.HTTP_404_NOT_FOUND)

        paiement = Paiement.objects.create(
            inscription=inscription,
            montant=data["amount"],
            moyen_paiement="wave",
            reference=data["id"],
            statut="confirme",
            date_paiement=timezone.now().date(),
            notes="Paiement automatique via webhook Wave",
        )
        from .notifications import notifier_paiement
        notifier_paiement(paiement)
        logger.info("Wave webhook: paiement %s créé (inscription %s)", paiement.pk, inscription_id)
        return Response({"detail": "Paiement enregistré.", "paiement_id": paiement.pk})


class OrangeMoneyWebhookView(APIView):
    """
    Endpoint POST pour les notifications de paiement Orange Money.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = OrangeMoneyWebhookSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        if data["status"] not in ("SUCCESS", "success"):
            return Response({"detail": "Statut ignoré."})

        ref = data.get("orderId", "")
        try:
            inscription_id = int(ref)
            inscription = Inscription.objects.get(pk=inscription_id)
        except (ValueError, TypeError, Inscription.DoesNotExist):
            logger.warning("OM webhook: inscription introuvable pour orderId=%s", ref)
            return Response({"detail": "Référence inconnue."}, status=status.HTTP_404_NOT_FOUND)

        paiement = Paiement.objects.create(
            inscription=inscription,
            montant=data["amount"],
            moyen_paiement="orange_money",
            reference=data["txnid"],
            statut="confirme",
            date_paiement=timezone.now().date(),
            notes=f"Paiement automatique via webhook Orange Money (msisdn: {data.get('msisdn', '')})",
        )
        from .notifications import notifier_paiement
        notifier_paiement(paiement)
        logger.info("OM webhook: paiement %s créé (inscription %s)", paiement.pk, inscription_id)
        return Response({"detail": "Paiement enregistré.", "paiement_id": paiement.pk})
