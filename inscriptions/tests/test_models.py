"""Tests des modèles — propriétés calculées, contraintes d'intégrité."""

from decimal import Decimal

import pytest

from inscriptions.models import Attestation, Certification, Cohorte, Inscription, Inscrit, Paiement

# ---------------------------------------------------------------------------
# Certification
# ---------------------------------------------------------------------------


class TestCertificationModel:
    def test_str(self, certification):
        assert str(certification) == "Certification Test"

    def test_nb_inscrits_zero(self, certification):
        assert certification.nb_inscrits == 0

    def test_nb_inscrits_avec_inscriptions(self, inscription, certification):
        assert certification.nb_inscrits == 1

    def test_nb_certifies_zero(self, certification):
        assert certification.nb_certifies == 0

    def test_nb_certifies_avec_certifie(self, inscription):
        inscription.statut = "certifie"
        inscription.save()
        cert = inscription.cohorte.certification
        assert cert.nb_certifies == 1

    def test_nb_cohortes(self, cohorte, certification):
        assert certification.nb_cohortes == 1

    def test_montant_encaisse_sans_paiement(self, inscription):
        cert = inscription.cohorte.certification
        assert cert.montant_encaisse == 0

    def test_montant_encaisse_avec_paiement(self, paiement):
        cert = paiement.inscription.cohorte.certification
        assert cert.montant_encaisse == Decimal("75000")


# ---------------------------------------------------------------------------
# Cohorte
# ---------------------------------------------------------------------------


class TestCohorteModel:
    def test_str(self, cohorte, certification):
        assert str(cohorte) == f"{certification.nom} — {cohorte.nom}"

    def test_nb_inscrits_zero(self, cohorte):
        assert cohorte.nb_inscrits == 0

    def test_nb_inscrits(self, inscription):
        assert inscription.cohorte.nb_inscrits == 1

    def test_nb_certifies_zero(self, cohorte):
        assert cohorte.nb_certifies == 0

    def test_montant_encaisse(self, paiement):
        assert paiement.inscription.cohorte.montant_encaisse == Decimal("75000")


# ---------------------------------------------------------------------------
# Inscrit
# ---------------------------------------------------------------------------


class TestInscritModel:
    def test_str(self, inscrit):
        assert str(inscrit) == "Mamadou Diallo"

    def test_nom_complet(self, inscrit):
        assert inscrit.nom_complet == "Mamadou Diallo"


# ---------------------------------------------------------------------------
# Inscription
# ---------------------------------------------------------------------------


class TestInscriptionModel:
    def test_str(self, inscription):
        assert "Mamadou Diallo" in str(inscription)
        assert "Cohorte 2024-A" in str(inscription)

    def test_total_paye_sans_paiement(self, inscription):
        assert inscription.total_paye == 0

    def test_total_paye_avec_paiements(self, inscription, db):
        Paiement.objects.create(
            inscription=inscription,
            montant=50000,
            moyen_paiement="especes",
            statut="confirme",
        )
        Paiement.objects.create(
            inscription=inscription,
            montant=30000,
            moyen_paiement="wave",
            statut="confirme",
        )
        # Reload to clear prefetch cache
        insc = Inscription.objects.get(pk=inscription.pk)
        assert insc.total_paye == Decimal("80000")

    def test_reste_a_payer(self, paiement):
        insc = Inscription.objects.prefetch_related("paiements").get(pk=paiement.inscription.pk)
        # montant_du=150000, paiement=75000
        assert insc.reste_a_payer == Decimal("75000")

    def test_reste_a_payer_jamais_negatif(self, inscription, db):
        Paiement.objects.create(
            inscription=inscription,
            montant=200000,
            moyen_paiement="especes",
            statut="confirme",
        )
        insc = Inscription.objects.prefetch_related("paiements").get(pk=inscription.pk)
        assert insc.reste_a_payer == 0

    def test_pourcentage_paye(self, paiement):
        insc = Inscription.objects.prefetch_related("paiements").get(pk=paiement.inscription.pk)
        assert insc.pourcentage_paye == 50

    def test_pourcentage_paye_montant_zero(self, inscription):
        inscription.montant_du = 0
        inscription.save()
        assert inscription.pourcentage_paye == 100

    def test_unique_together(self, inscription, inscrit, cohorte, db):
        """Un inscrit ne peut pas être inscrit deux fois à la même cohorte."""
        from django.db import IntegrityError

        with pytest.raises(IntegrityError):
            Inscription.objects.create(
                inscrit=inscrit,
                cohorte=cohorte,
                statut="inscrit",
                montant_du=150000,
            )


# ---------------------------------------------------------------------------
# Paiement
# ---------------------------------------------------------------------------


class TestPaiementModel:
    def test_paiement_creation(self, paiement):
        assert paiement.montant == Decimal("75000")
        assert paiement.statut == "confirme"
        assert paiement.moyen_paiement == "especes"

    def test_paiement_en_attente(self, inscription, db):
        p = Paiement.objects.create(
            inscription=inscription,
            montant=50000,
            moyen_paiement="wave",
            statut="en_attente",
        )
        assert p.statut == "en_attente"
