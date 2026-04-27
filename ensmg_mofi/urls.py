"""URL configuration for ensmg_mofi project."""

from django.contrib import admin
from django.urls import include, path

# Custom error pages — actives uniquement quand DEBUG=False (production)
handler404 = "django.views.defaults.page_not_found"
handler500 = "django.views.defaults.server_error"
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from inscriptions import views as inscriptions_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", inscriptions_views.custom_login, name="login"),
    path("logout/", inscriptions_views.custom_logout, name="logout"),
    # Réinitialisation de mot de passe (email)
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="inscriptions/password_reset.html",
            email_template_name="inscriptions/password_reset_email.html",
            subject_template_name="inscriptions/password_reset_subject.txt",
        ),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="inscriptions/password_reset_done.html",
        ),
        name="password_reset_done",
    ),
    path(
        "password-reset/confirm/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="inscriptions/password_reset_confirm.html",
        ),
        name="password_reset_confirm",
    ),
    path(
        "password-reset/complete/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="inscriptions/password_reset_complete.html",
        ),
        name="password_reset_complete",
    ),
    path("", include("inscriptions.urls")),
    # API REST
    path("api/", include("inscriptions.api_urls")),
    # Documentation API
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
