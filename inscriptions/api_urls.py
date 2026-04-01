"""URLs de l'API REST — ENSMG Certification."""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .api import (
    CertificationViewSet, CohorteViewSet, InscritViewSet,
    InscriptionViewSet, PaiementViewSet, AttestationViewSet,
    UserViewSet, MeView,
    WaveWebhookView, OrangeMoneyWebhookView,
)

router = DefaultRouter()
router.register(r'certifications', CertificationViewSet, basename='api-certification')
router.register(r'cohortes', CohorteViewSet, basename='api-cohorte')
router.register(r'inscrits', InscritViewSet, basename='api-inscrit')
router.register(r'inscriptions', InscriptionViewSet, basename='api-inscription')
router.register(r'paiements', PaiementViewSet, basename='api-paiement')
router.register(r'attestations', AttestationViewSet, basename='api-attestation')
router.register(r'utilisateurs', UserViewSet, basename='api-utilisateur')

urlpatterns = [
    path('', include(router.urls)),
    # Auth JWT
    path('auth/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    # Profil courant
    path('auth/me/', MeView.as_view(), name='api-me'),
    # Webhooks paiements
    path('webhooks/wave/', WaveWebhookView.as_view(), name='webhook-wave'),
    path('webhooks/orange-money/', OrangeMoneyWebhookView.as_view(), name='webhook-orange-money'),
]
