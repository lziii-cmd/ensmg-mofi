"""URLs de l'API REST — ENSMG Certification."""

from django.urls import include, path
from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .api import (
    AttestationViewSet,
    CertificationViewSet,
    CohorteViewSet,
    InscriptionViewSet,
    InscritViewSet,
    MeView,
    OrangeMoneyWebhookView,
    PaiementViewSet,
    UserViewSet,
    WaveWebhookView,
)

router = DefaultRouter()
router.register(r"certifications", CertificationViewSet, basename="api-certification")
router.register(r"cohortes", CohorteViewSet, basename="api-cohorte")
router.register(r"inscrits", InscritViewSet, basename="api-inscrit")
router.register(r"inscriptions", InscriptionViewSet, basename="api-inscription")
router.register(r"paiements", PaiementViewSet, basename="api-paiement")
router.register(r"attestations", AttestationViewSet, basename="api-attestation")
router.register(r"utilisateurs", UserViewSet, basename="api-utilisateur")


@method_decorator(ratelimit(key="ip", rate="10/m", method="POST", block=True), name="post")
class RateLimitedTokenObtainPairView(TokenObtainPairView):
    """Endpoint JWT protégé contre le brute-force (10 requêtes/min par IP)."""

    pass


urlpatterns = [
    path("", include(router.urls)),
    # Auth JWT
    path("auth/token/", RateLimitedTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    # Profil courant
    path("auth/me/", MeView.as_view(), name="api-me"),
    # Webhooks paiements
    path("webhooks/wave/", WaveWebhookView.as_view(), name="webhook-wave"),
    path("webhooks/orange-money/", OrangeMoneyWebhookView.as_view(), name="webhook-orange-money"),
]
