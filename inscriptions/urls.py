from django.urls import path
from . import views

urlpatterns = [
    # Dashboard
    path("", views.dashboard, name="dashboard"),

    # Certifications
    path("certifications/", views.certifications_list, name="certifications_list"),
    path("certifications/ajouter/", views.certification_ajouter, name="certification_ajouter"),
    path("certifications/<int:pk>/", views.certification_detail, name="certification_detail"),
    path("certifications/<int:pk>/modifier/", views.certification_modifier, name="certification_modifier"),
    path("certifications/<int:pk>/supprimer/", views.certification_supprimer, name="certification_supprimer"),

    # Inscrits
    path("inscrits/", views.inscrits_list, name="inscrits_list"),
    path("inscrits/ajouter/", views.inscrit_ajouter, name="inscrit_ajouter"),
    path("inscrits/import/", views.import_excel, name="import_excel"),
    path("inscrits/<int:pk>/", views.inscrit_detail, name="inscrit_detail"),
    path("inscrits/<int:pk>/modifier/", views.inscrit_modifier, name="inscrit_modifier"),
    path("inscrits/<int:pk>/supprimer/", views.inscrit_supprimer, name="inscrit_supprimer"),
    path("inscrits/<int:pk>/inscrire/", views.inscrire_a_certification, name="inscrire_a_certification"),

    # InscriptionCertification actions
    path("inscriptions/<int:pk>/statut/", views.changer_statut, name="changer_statut"),
    path("inscriptions/<int:pk>/supprimer/", views.inscription_supprimer, name="inscription_supprimer"),
    path("inscriptions/<int:pk>/paiement/", views.paiement_ajouter_pour_inscription, name="paiement_ajouter_pour_inscription"),

    # Paiements
    path("paiements/", views.paiements_list, name="paiements_list"),
    path("paiements/ajouter/", views.paiement_ajouter, name="paiement_ajouter"),
    path("paiements/<int:pk>/modifier/", views.paiement_modifier, name="paiement_modifier"),
    path("paiements/<int:pk>/supprimer/", views.paiement_supprimer, name="paiement_supprimer"),
]
