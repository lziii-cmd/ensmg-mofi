"""Fixtures partagées pour tous les tests ENSMG."""

import pytest
from django.contrib.auth.models import User


@pytest.fixture(autouse=True)
def use_simple_static_storage(settings):
    settings.STORAGES = {
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    }


from inscriptions.models import (
    Certification,
    Cohorte,
    CompteApprenant,
    Inscription,
    Inscrit,
    Paiement,
    TypeTarif,
)

# ---------------------------------------------------------------------------
# Fixtures utilisateurs
# ---------------------------------------------------------------------------


@pytest.fixture
def superuser(db):
    return User.objects.create_superuser(
        username="admin@ensmg.sn",
        email="admin@ensmg.sn",
        password="testpass123",
        first_name="Admin",
        last_name="ENSMG",
    )


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        username="staff@ensmg.sn",
        email="staff@ensmg.sn",
        password="testpass123",
        is_staff=True,
    )


@pytest.fixture
def regular_user(db):
    return User.objects.create_user(
        username="user@ensmg.sn",
        email="user@ensmg.sn",
        password="testpass123",
    )


# ---------------------------------------------------------------------------
# Fixtures métier
# ---------------------------------------------------------------------------


@pytest.fixture
def certification(db):
    cert = Certification.objects.create(
        nom="Certification Test",
        description="Une certification de test",
        actif=True,
    )
    TypeTarif.objects.create(certification=cert, nom="Étudiant", montant=150000, actif=True)
    TypeTarif.objects.create(certification=cert, nom="Professionnel", montant=250000, actif=True)
    return cert


@pytest.fixture
def certification_inactive(db):
    cert = Certification.objects.create(
        nom="Certification Inactive",
        actif=False,
    )
    TypeTarif.objects.create(certification=cert, nom="Étudiant", montant=100000, actif=True)
    TypeTarif.objects.create(certification=cert, nom="Professionnel", montant=200000, actif=True)
    return cert


@pytest.fixture
def cohorte(db, certification):
    from django.utils import timezone

    return Cohorte.objects.create(
        certification=certification,
        nom="Cohorte 2024-A",
        date_debut=timezone.now().date(),
        actif=True,
    )


@pytest.fixture
def inscrit(db):
    return Inscrit.objects.create(
        nom="Diallo",
        prenom="Mamadou",
        email="mamadou.diallo@test.sn",
        telephone="771234567",
        activite="etudiant",
    )


@pytest.fixture
def inscrit_professionnel(db):
    return Inscrit.objects.create(
        nom="Ndiaye",
        prenom="Fatou",
        email="fatou.ndiaye@test.sn",
        telephone="770987654",
        activite="professionnel",
    )


@pytest.fixture
def inscription(db, inscrit, cohorte):
    return Inscription.objects.create(
        inscrit=inscrit,
        cohorte=cohorte,
        statut="inscrit",
        montant_du=150000,
    )


@pytest.fixture
def paiement(db, inscription):
    return Paiement.objects.create(
        inscription=inscription,
        montant=75000,
        moyen_paiement="especes",
        statut="confirme",
    )


@pytest.fixture
def apprenant_user(db, inscrit):
    """Un User Django lié à un CompteApprenant."""
    user = User.objects.create_user(
        username="mamadou.diallo@ensmg.sn",
        email="mamadou.diallo@test.sn",
        password="testpass123",
        first_name="Mamadou",
        last_name="Diallo",
    )
    CompteApprenant.objects.create(user=user, inscrit=inscrit, mdp_change=True)
    return user
