"""URL configuration for ensmg_mofi project."""
from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView
from inscriptions import views as inscriptions_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/', inscriptions_views.custom_login, name='login'),
    path('logout/', inscriptions_views.custom_logout, name='logout'),
    path('', include('inscriptions.urls')),
    # API REST
    path('api/', include('inscriptions.api_urls')),
    # Documentation API
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
