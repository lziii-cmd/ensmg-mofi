from django.urls import path
from . import views

urlpatterns = [
    # Page d'accueil — portail public (redirige les admins vers le dashboard)
    path("", views.portail_accueil, name="portail_accueil_home"),
    # Dashboard (accès direct pour les admins)
    path("dashboard/", views.dashboard, name="dashboard"),

    # Session filters
    path("filtrer/", views.set_filter, name="set_filter"),
    path("filtrer/effacer/", views.clear_filter, name="clear_filter"),

    # AJAX API
    path("api/cohortes/", views.api_cohortes, name="api_cohortes"),
    path("api/inscrits/recherche/", views.api_search_inscrits, name="api_search_inscrits"),

    # Certifications
    path("certifications/", views.certifications_list, name="certifications_list"),
    path("certifications/ajouter/", views.certification_ajouter, name="certification_ajouter"),
    path("certifications/<int:pk>/", views.certification_detail, name="certification_detail"),
    path("certifications/<int:pk>/modifier/", views.certification_modifier, name="certification_modifier"),
    path("certifications/<int:pk>/supprimer/", views.certification_supprimer, name="certification_supprimer"),

    # Cohortes
    path("certifications/<int:certif_pk>/cohortes/ajouter/", views.cohorte_ajouter, name="cohorte_ajouter"),
    path("cohortes/<int:pk>/", views.cohorte_detail, name="cohorte_detail"),
    path("cohortes/<int:pk>/modifier/", views.cohorte_modifier, name="cohorte_modifier"),
    path("cohortes/<int:pk>/supprimer/", views.cohorte_supprimer, name="cohorte_supprimer"),

    # Inscrits
    path("inscrits/", views.inscrits_list, name="inscrits_list"),
    path("inscrits/ajouter/", views.inscrit_ajouter, name="inscrit_ajouter"),
    path("inscrits/import/", views.import_excel, name="import_excel"),
    path("inscrits/inscrire/", views.inscription_wizard, name="inscription_wizard"),
    path("inscrits/<int:pk>/", views.inscrit_detail, name="inscrit_detail"),
    path("inscrits/<int:pk>/modifier/", views.inscrit_modifier, name="inscrit_modifier"),
    path("inscrits/<int:pk>/supprimer/", views.inscrit_supprimer, name="inscrit_supprimer"),

    # Inscription actions
    path("inscriptions/<int:pk>/statut/", views.changer_statut, name="changer_statut"),
    path("inscriptions/<int:pk>/supprimer/", views.inscription_supprimer, name="inscription_supprimer"),
    path("inscriptions/<int:pk>/paiement/", views.paiement_ajouter_pour_inscription, name="paiement_ajouter_pour_inscription"),

    # Paiements
    path("paiements/", views.paiements_list, name="paiements_list"),
    path("paiements/ajouter/", views.paiement_ajouter, name="paiement_ajouter"),
    path("paiements/<int:pk>/modifier/", views.paiement_modifier, name="paiement_modifier"),
    path("paiements/<int:pk>/supprimer/", views.paiement_supprimer, name="paiement_supprimer"),
    path("paiements/<int:pk>/confirmer/", views.admin_confirmer_paiement, name="admin_confirmer_paiement"),
    path("paiements/<int:pk>/recu/", views.recu_download, name="recu_download"),

    # Utilisateurs (admin only)
    path("utilisateurs/", views.users_list, name="users_list"),
    path("utilisateurs/ajouter/", views.user_ajouter, name="user_ajouter"),
    path("utilisateurs/<int:pk>/modifier/", views.user_modifier, name="user_modifier"),
    path("utilisateurs/<int:pk>/activer/", views.user_toggle, name="user_toggle"),

    # Certifier — attestations
    path("certifier/", views.certifier_home, name="certifier_home"),
    path("certifier/<int:pk>/inscrits/", views.certifier_inscrits, name="certifier_inscrits"),
    path("certifier/<int:pk>/action/", views.certifier_action, name="certifier_action"),
    path("attestations/<int:pk>/telecharger/", views.attestation_download, name="attestation_download"),
    path("attestations/<int:pk>/voir/", views.attestation_view, name="attestation_view"),
    path("attestations/<str:numero>/verifier/", views.attestation_verifier, name="attestation_verifier"),

    # Portail public
    path("portail/", views.portail_accueil, name="portail_accueil"),
    path("portail/inscrire/<int:certif_pk>/", views.portail_inscrire, name="portail_inscrire"),
    path("portail/inscription/", views.portail_wizard, name="portail_wizard"),
    path("portail/paiement/<int:pk>/", views.portail_paiement, name="portail_paiement"),
    path("portail/paiement/<int:pk>/wave-retour/", views.portail_wave_retour, name="portail_wave_retour"),

    # Espace apprenant
    path("apprenant/", views.espace_apprenant, name="espace_apprenant"),
    path("apprenant/profil/", views.apprenant_profil, name="apprenant_profil"),
    path("apprenant/paiements/", views.apprenant_paiements, name="apprenant_paiements"),
    path("apprenant/attestations/", views.apprenant_attestations, name="apprenant_attestations"),
    path("apprenant/changer-mdp/", views.apprenant_changer_mdp, name="apprenant_changer_mdp"),
    path("apprenant/payer/<int:inscription_pk>/", views.apprenant_payer, name="apprenant_payer"),

    # Dashboard financier
    path("finances/", views.dashboard_financier, name="dashboard_financier"),
]
