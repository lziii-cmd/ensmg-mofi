# views/__init__.py
# Re-exports all public view functions so that urls.py (which imports from
# `inscriptions.views`) works without any change.

from ._base import admin_required, users_required, write_required  # noqa: F401
from .ajax import api_cohortes, api_inscription_solde, api_search_inscrits  # noqa: F401
from .apprenants import (  # noqa: F401
    apprenant_attestations,
    apprenant_certifications,
    apprenant_changer_mdp,
    apprenant_inscription_directe,
    apprenant_notifications,
    apprenant_paiements,
    apprenant_payer,
    apprenant_profil,
    espace_apprenant,
)
from .attestations import (  # noqa: F401
    attestation_download,
    attestation_qr_download,
    attestation_upload_pdf,
    attestation_verifier,
    attestation_view,
    certifier_action,
    certifier_home,
    certifier_inscrits,
)
from .auth import bootstrap_admin, custom_login, custom_logout, register_admin  # noqa: F401
from .certifications import (  # noqa: F401
    api_types_tarif,
    certification_ajouter,
    certification_detail,
    certification_modifier,
    certification_supprimer,
    certifications_list,
    nom_tarif_creer_ajax,
    option_ajouter,
    option_modifier,
    option_supprimer,
    tarifs_bulk_ajouter,
    type_tarif_ajouter,
    type_tarif_modifier,
    type_tarif_supprimer,
)
from .cohortes import (  # noqa: F401
    cohorte_ajouter,
    cohorte_detail,
    cohorte_modifier,
    cohorte_supprimer,
)
from .dashboard import clear_filter, dashboard, dashboard_financier, set_filter  # noqa: F401
from .inscrits import (  # noqa: F401
    admin_certifications_pour_inscrit,
    admin_creer_compte_inscrit,
    admin_inscription_directe,
    changer_statut,
    import_excel,
    inscription_supprimer,
    inscription_wizard,
    inscrit_ajouter,
    inscrit_detail,
    inscrit_modifier,
    inscrit_supprimer,
    inscrits_list,
)
from .paiements import (  # noqa: F401
    admin_annuler_paiement,
    admin_confirmer_paiement,
    paiement_ajouter,
    paiement_ajouter_pour_inscription,
    paiement_modifier,
    paiement_supprimer,
    paiements_list,
    recu_download,
    recu_view,
)
from .portail import (  # noqa: F401
    portail_accueil,
    portail_inscrire,
    portail_intouch_ipn,
    portail_intouch_retour,
    portail_paiement,
    portail_paytech_ipn,
    portail_paytech_retour,
    portail_rejoindre,
    portail_wave_retour,
    portail_wizard,
)
from .utilisateurs import (  # noqa: F401
    extra_usage,
    user_ajouter,
    user_modifier,
    user_toggle,
    users_list,
)
