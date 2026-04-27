"""
Logique de rôles centralisée — source unique de vérité.

Importé par views/, middleware.py et partout où les rôles sont nécessaires.
"""


def get_user_role(user):
    """Retourne le rôle string d'un utilisateur staff authentifié."""
    if user.is_superuser:
        return "super_utilisateur"
    groups = set(user.groups.values_list("name", flat=True))
    if "Responsable Scolarité" in groups:
        return "responsable_scolarite"
    if "Admin" in groups:
        return "admin"
    if "Personnel Utilisateur" in groups:
        return "personnel_utilisateur"
    return "super_utilisateur"
