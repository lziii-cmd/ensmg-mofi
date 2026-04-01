"""
Permissions DRF basées sur les rôles (groupes Django).
"""
from rest_framework.permissions import BasePermission, IsAuthenticated


class IsAdministrateur(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)


class IsComptable(BasePermission):
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        return request.user.groups.filter(name="Comptable").exists()


class IsResponsable(BasePermission):
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        return request.user.groups.filter(name="Responsable").exists()


class IsAdminOrResponsable(BasePermission):
    """Administrateur ou Responsable."""
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        return request.user.groups.filter(name__in=["Responsable", "Administrateur"]).exists()


class IsAdminOrComptable(BasePermission):
    """Administrateur ou Comptable."""
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        return request.user.groups.filter(name__in=["Comptable", "Administrateur"]).exists()


class IsStaffOrReadOnly(BasePermission):
    """Lecture pour tous les authentifiés, écriture réservée au staff."""
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        return request.user.is_staff or request.user.is_superuser
