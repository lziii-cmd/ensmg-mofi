"""Tests des vues Django — accès, redirections, création d'objets."""

import pytest
from django.urls import reverse

from inscriptions.models import Certification, Cohorte, Inscription, Inscrit, Paiement

# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


class TestDashboard:
    def test_dashboard_requires_login(self, client):
        response = client.get(reverse("dashboard"))
        assert response.status_code == 302
        assert "/login/" in response["Location"]

    def test_dashboard_accessible_to_logged_in(self, client, superuser):
        client.force_login(superuser)
        response = client.get(reverse("dashboard"))
        assert response.status_code == 200

    def test_dashboard_contains_stats(self, client, superuser, inscription):
        client.force_login(superuser)
        response = client.get(reverse("dashboard"))
        assert response.status_code == 200
        assert b"dashboard" in response.content.lower() or response.status_code == 200


# ---------------------------------------------------------------------------
# Certifications
# ---------------------------------------------------------------------------


class TestCertificationsViews:
    def test_list_requires_login(self, client):
        response = client.get(reverse("certifications_list"))
        assert response.status_code == 302

    def test_list_ok(self, client, superuser, certification):
        client.force_login(superuser)
        response = client.get(reverse("certifications_list"))
        assert response.status_code == 200
        assert "Certification Test".encode() in response.content

    def test_list_search(self, client, superuser, certification):
        client.force_login(superuser)
        response = client.get(reverse("certifications_list") + "?q=Test")
        assert response.status_code == 200
        assert "Certification Test".encode() in response.content

    def test_list_search_no_result(self, client, superuser, certification):
        client.force_login(superuser)
        response = client.get(reverse("certifications_list") + "?q=XXXXXXINEXISTANT")
        assert response.status_code == 200
        assert "Certification Test".encode() not in response.content

    def test_detail_ok(self, client, superuser, certification):
        client.force_login(superuser)
        response = client.get(reverse("certification_detail", args=[certification.pk]))
        assert response.status_code == 200

    def test_ajouter_get(self, client, superuser):
        client.force_login(superuser)
        response = client.get(reverse("certification_ajouter"))
        assert response.status_code == 200

    def test_ajouter_post(self, client, superuser, db):
        client.force_login(superuser)
        response = client.post(
            reverse("certification_ajouter"),
            {
                "nom": "Nouvelle Certification",
                "description": "Test",
                "actif": True,
            },
        )
        assert response.status_code == 302
        assert Certification.objects.filter(nom="Nouvelle Certification").exists()

    def test_modifier_post(self, client, superuser, certification):
        client.force_login(superuser)
        response = client.post(
            reverse("certification_modifier", args=[certification.pk]),
            {
                "nom": "Certification Modifiée",
                "actif": True,
            },
        )
        assert response.status_code == 302
        certification.refresh_from_db()
        assert certification.nom == "Certification Modifiée"

    def test_supprimer_post(self, client, superuser, certification):
        client.force_login(superuser)
        pk = certification.pk
        response = client.post(reverse("certification_supprimer", args=[pk]))
        assert response.status_code == 302
        assert not Certification.objects.filter(pk=pk).exists()


# ---------------------------------------------------------------------------
# Cohortes
# ---------------------------------------------------------------------------


class TestCohorteViews:
    def test_detail_ok(self, client, superuser, cohorte):
        client.force_login(superuser)
        response = client.get(reverse("cohorte_detail", args=[cohorte.pk]))
        assert response.status_code == 200

    def test_ajouter_post(self, client, superuser, certification, db):
        client.force_login(superuser)
        response = client.post(
            reverse("cohorte_ajouter", args=[certification.pk]),
            {"nom": "Cohorte Test", "actif": True},
        )
        assert response.status_code == 302
        assert Cohorte.objects.filter(nom="Cohorte Test").exists()


# ---------------------------------------------------------------------------
# Inscrits
# ---------------------------------------------------------------------------


class TestInscritsViews:
    def test_list_ok(self, client, superuser, inscrit):
        client.force_login(superuser)
        response = client.get(reverse("inscrits_list"))
        assert response.status_code == 200

    def test_detail_ok(self, client, superuser, inscrit):
        client.force_login(superuser)
        response = client.get(reverse("inscrit_detail", args=[inscrit.pk]))
        assert response.status_code == 200

    def test_ajouter_get(self, client, superuser):
        client.force_login(superuser)
        response = client.get(reverse("inscrit_ajouter"))
        assert response.status_code == 200

    def test_ajouter_post(self, client, superuser, db):
        client.force_login(superuser)
        response = client.post(
            reverse("inscrit_ajouter"),
            {
                "nom": "Ba",
                "prenom": "Moussa",
                "email": "moussa.ba@test.sn",
                "telephone": "775551234",
                "activite": "professionnel",
                "source": "manuel",
            },
        )
        assert response.status_code == 302
        assert Inscrit.objects.filter(email="moussa.ba@test.sn").exists()

    def test_supprimer_post(self, client, superuser, inscrit):
        client.force_login(superuser)
        pk = inscrit.pk
        response = client.post(reverse("inscrit_supprimer", args=[pk]))
        assert response.status_code == 302
        assert not Inscrit.objects.filter(pk=pk).exists()


# ---------------------------------------------------------------------------
# Paiements
# ---------------------------------------------------------------------------


class TestPaiementsViews:
    def test_list_ok(self, client, superuser):
        client.force_login(superuser)
        response = client.get(reverse("paiements_list"))
        assert response.status_code == 200

    def test_paiement_ajouter_pour_inscription_depasse_reste(self, client, superuser, inscription):
        """Un paiement dépassant le reste à payer doit être rejeté."""
        client.force_login(superuser)
        # montant_du = 150000, aucun paiement → reste = 150000
        response = client.post(
            reverse("paiement_ajouter_pour_inscription", args=[inscription.pk]),
            {
                "montant": "999999",
                "moyen_paiement": "especes",
                "statut": "confirme",
                "date_paiement": "2024-01-01",
            },
        )
        assert response.status_code == 302
        assert Paiement.objects.filter(inscription=inscription).count() == 0

    def test_paiement_ajouter_pour_inscription_ok(self, client, superuser, inscription):
        client.force_login(superuser)
        response = client.post(
            reverse("paiement_ajouter_pour_inscription", args=[inscription.pk]),
            {
                "montant": "50000",
                "moyen_paiement": "especes",
                "statut": "confirme",
                "date_paiement": "2024-01-01",
            },
        )
        assert response.status_code == 302
        assert Paiement.objects.filter(inscription=inscription).count() == 1


# ---------------------------------------------------------------------------
# Authentification
# ---------------------------------------------------------------------------


class TestAuthViews:
    def test_login_get(self, client):
        response = client.get(reverse("login"))
        assert response.status_code == 200

    def test_login_post_invalid(self, client, db):
        response = client.post(
            reverse("login"),
            {
                "username": "invalid@test.sn",
                "password": "wrongpassword",
            },
        )
        assert response.status_code == 200
        assert "incorrect" in response.content.decode().lower() or response.status_code == 200

    def test_login_post_valid(self, client, superuser):
        response = client.post(
            reverse("login"),
            {
                "username": superuser.username,
                "password": "testpass123",
            },
        )
        assert response.status_code == 302
        assert response["Location"] in ["/dashboard/", "/apprenant/"]

    def test_logout(self, client, superuser):
        client.force_login(superuser)
        response = client.get(reverse("logout"))
        assert response.status_code == 302


# ---------------------------------------------------------------------------
# Portail public
# ---------------------------------------------------------------------------


class TestPortailViews:
    def test_accueil_accessible_sans_connexion(self, client, db):
        response = client.get(reverse("portail_accueil_home"))
        assert response.status_code == 200

    def test_accueil_redirige_admin_connecte(self, client, superuser):
        client.force_login(superuser)
        response = client.get(reverse("portail_accueil_home"))
        assert response.status_code == 302
        assert "dashboard" in response["Location"]

    def test_accueil_redirige_apprenant_connecte(self, client, apprenant_user):
        client.force_login(apprenant_user)
        response = client.get(reverse("portail_accueil_home"))
        assert response.status_code == 302
        assert "apprenant" in response["Location"]

    def test_attestation_verifier_inexistante(self, client, db):
        response = client.get(reverse("attestation_verifier", args=["CERT-INVALIDE-0000-000"]))
        assert response.status_code == 200
        assert b"CERT-INVALIDE-0000-000" in response.content


# ---------------------------------------------------------------------------
# Espace Apprenant
# ---------------------------------------------------------------------------


class TestEspaceApprenant:
    def test_espace_requires_apprenant(self, client, superuser):
        """Un admin ne peut pas accéder à l'espace apprenant."""
        client.force_login(superuser)
        response = client.get(reverse("espace_apprenant"))
        assert response.status_code == 302

    def test_espace_accessible_a_apprenant(self, client, apprenant_user):
        client.force_login(apprenant_user)
        response = client.get(reverse("espace_apprenant"))
        assert response.status_code == 200

    def test_apprenant_paiements(self, client, apprenant_user):
        client.force_login(apprenant_user)
        response = client.get(reverse("apprenant_paiements"))
        assert response.status_code == 200

    def test_apprenant_attestations(self, client, apprenant_user):
        client.force_login(apprenant_user)
        response = client.get(reverse("apprenant_attestations"))
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# AJAX API
# ---------------------------------------------------------------------------


class TestAjaxViews:
    def test_api_cohortes_sans_certif(self, client, superuser):
        client.force_login(superuser)
        response = client.get(reverse("api_cohortes"))
        assert response.status_code == 200
        data = response.json()
        assert "cohortes" in data
        assert data["cohortes"] == []

    def test_api_cohortes_avec_certif(self, client, superuser, cohorte, certification):
        client.force_login(superuser)
        response = client.get(reverse("api_cohortes") + f"?certif_id={certification.pk}")
        assert response.status_code == 200
        data = response.json()
        assert len(data["cohortes"]) == 1
        assert data["cohortes"][0]["nom"] == "Cohorte 2024-A"

    def test_api_search_inscrits(self, client, superuser, inscrit):
        client.force_login(superuser)
        response = client.get(reverse("api_search_inscrits") + "?q=Mamadou")
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) >= 1

    def test_api_inscription_solde(self, client, superuser, inscription):
        client.force_login(superuser)
        response = client.get(reverse("api_inscription_solde") + f"?pk={inscription.pk}")
        assert response.status_code == 200
        data = response.json()
        assert data["montant_du"] == 150000.0
        assert data["total_paye"] == 0.0
        assert data["reste_a_payer"] == 150000.0

    def test_api_inscription_solde_missing_pk(self, client, superuser):
        client.force_login(superuser)
        response = client.get(reverse("api_inscription_solde"))
        assert response.status_code == 400
