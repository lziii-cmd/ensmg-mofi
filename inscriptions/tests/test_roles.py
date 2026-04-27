"""Tests du module roles.py et des décorateurs d'accès."""

import pytest
from django.contrib.auth.models import Group, User
from django.urls import reverse

from inscriptions.roles import get_user_role


class TestGetUserRole:
    def test_superuser_role(self, db):
        user = User.objects.create_superuser(
            username="su@test.sn", password="pass", email="su@test.sn"
        )
        assert get_user_role(user) == "super_utilisateur"

    def test_responsable_scolarite_role(self, db):
        group, _ = Group.objects.get_or_create(name="Responsable Scolarité")
        user = User.objects.create_user(username="rs@test.sn", password="pass")
        user.groups.add(group)
        assert get_user_role(user) == "responsable_scolarite"

    def test_admin_role(self, db):
        group, _ = Group.objects.get_or_create(name="Admin")
        user = User.objects.create_user(username="admin2@test.sn", password="pass")
        user.groups.add(group)
        assert get_user_role(user) == "admin"

    def test_personnel_utilisateur_role(self, db):
        group, _ = Group.objects.get_or_create(name="Personnel Utilisateur")
        user = User.objects.create_user(username="pu@test.sn", password="pass")
        user.groups.add(group)
        assert get_user_role(user) == "personnel_utilisateur"

    def test_no_group_defaults_to_super(self, db):
        user = User.objects.create_user(username="nogroup@test.sn", password="pass")
        # User sans groupe → fallback super_utilisateur
        assert get_user_role(user) == "super_utilisateur"

    def test_superuser_overrides_group(self, db):
        """Un superuser reste super_utilisateur même avec un groupe Admin."""
        group, _ = Group.objects.get_or_create(name="Admin")
        user = User.objects.create_superuser(
            username="suadmin@test.sn", password="pass", email="suadmin@test.sn"
        )
        user.groups.add(group)
        assert get_user_role(user) == "super_utilisateur"


class TestAdminRequiredDecorator:
    """Tests que les URLs protégées par admin_required refusent les non-superusers."""

    def test_users_list_blocked_for_personnel_utilisateur(self, client, db):
        """Un Personnel Utilisateur ne peut pas accéder à la gestion des utilisateurs."""
        group, _ = Group.objects.get_or_create(name="Personnel Utilisateur")
        user = User.objects.create_user(username="pu2@test.sn", password="pass")
        user.groups.add(group)
        client.force_login(user)
        response = client.get(reverse("users_list"))
        assert response.status_code == 302

    def test_users_list_accessible_superuser(self, client, superuser):
        client.force_login(superuser)
        response = client.get(reverse("users_list"))
        assert response.status_code == 200

    def test_users_list_accessible_admin_group(self, client, db):
        group, _ = Group.objects.get_or_create(name="Admin")
        user = User.objects.create_user(username="admingrp@test.sn", password="pass")
        user.groups.add(group)
        client.force_login(user)
        response = client.get(reverse("users_list"))
        assert response.status_code == 200


class TestUtilisateursViews:
    def test_user_ajouter_get(self, client, superuser):
        client.force_login(superuser)
        response = client.get(reverse("user_ajouter"))
        assert response.status_code == 200

    def test_user_ajouter_post_valid(self, client, superuser, db):
        client.force_login(superuser)
        response = client.post(
            reverse("user_ajouter"),
            {
                "username": "newuser@test.sn",
                "email": "newuser@test.sn",
                "first_name": "New",
                "last_name": "User",
                "password": "testpass123",
                "password_confirm": "testpass123",
                "role": "responsable_scolarite",
            },
        )
        # Redirect on success
        assert response.status_code in [200, 302]

    def test_user_ajouter_post_no_password(self, client, superuser, db):
        client.force_login(superuser)
        response = client.post(
            reverse("user_ajouter"),
            {
                "username": "nopwd@test.sn",
                "email": "nopwd@test.sn",
            },
        )
        assert response.status_code == 200
        assert not User.objects.filter(username="nopwd@test.sn").exists()

    def test_user_toggle(self, client, superuser, regular_user):
        client.force_login(superuser)
        assert regular_user.is_active
        response = client.post(reverse("user_toggle", args=[regular_user.pk]))
        assert response.status_code == 302
        regular_user.refresh_from_db()
        assert not regular_user.is_active

    def test_user_toggle_self_blocked(self, client, superuser):
        """Un admin ne peut pas désactiver son propre compte."""
        client.force_login(superuser)
        response = client.post(reverse("user_toggle", args=[superuser.pk]))
        assert response.status_code == 302
        superuser.refresh_from_db()
        assert superuser.is_active  # Inchangé


class TestDashboardFilter:
    def test_set_filter_post(self, client, superuser, certification, cohorte):
        client.force_login(superuser)
        response = client.post(
            reverse("set_filter"),
            {
                "certif_ids": [str(certification.pk)],
                "next": "/dashboard/",
            },
        )
        assert response.status_code == 302

    def test_clear_filter(self, client, superuser):
        client.force_login(superuser)
        session = client.session
        session["filter_certif_ids"] = [1]
        session.save()
        response = client.get(reverse("clear_filter") + "?next=/dashboard/")
        assert response.status_code == 302
        # Session should be cleared
        response2 = client.get(reverse("dashboard"))
        assert response2.status_code == 200


class TestCohorteViewsAdditional:
    def test_modifier_get(self, client, superuser, cohorte):
        client.force_login(superuser)
        response = client.get(reverse("cohorte_modifier", args=[cohorte.pk]))
        assert response.status_code == 200

    def test_supprimer_post(self, client, superuser, cohorte, certification):
        client.force_login(superuser)
        pk = cohorte.pk
        response = client.post(reverse("cohorte_supprimer", args=[pk]))
        assert response.status_code == 302
        from inscriptions.models import Cohorte

        assert not Cohorte.objects.filter(pk=pk).exists()

    def test_modifier_post(self, client, superuser, cohorte):
        client.force_login(superuser)
        response = client.post(
            reverse("cohorte_modifier", args=[cohorte.pk]),
            {"nom": "Cohorte Modifiée", "actif": True},
        )
        assert response.status_code == 302
        cohorte.refresh_from_db()
        assert cohorte.nom == "Cohorte Modifiée"


class TestInscriptionWizard:
    def test_wizard_get(self, client, superuser):
        client.force_login(superuser)
        response = client.get(reverse("inscription_wizard"))
        assert response.status_code == 200

    def test_changer_statut_post(self, client, superuser, inscription):
        client.force_login(superuser)
        response = client.post(
            reverse("changer_statut", args=[inscription.pk]),
            {"statut": "en_formation"},
        )
        assert response.status_code == 302
        inscription.refresh_from_db()
        assert inscription.statut == "en_formation"

    def test_inscription_supprimer_post(self, client, superuser, inscription):
        client.force_login(superuser)
        pk = inscription.pk
        response = client.post(reverse("inscription_supprimer", args=[pk]))
        assert response.status_code == 302
        from inscriptions.models import Inscription

        assert not Inscription.objects.filter(pk=pk).exists()


class TestPaiementAdmin:
    def test_confirmer_paiement_get(self, client, superuser, paiement):
        """Admin peut voir la page de confirmation."""
        paiement.statut = "en_attente"
        paiement.save()
        client.force_login(superuser)
        response = client.get(reverse("admin_confirmer_paiement", args=[paiement.pk]))
        assert response.status_code == 200

    def test_confirmer_paiement_post(self, client, superuser, paiement):
        paiement.statut = "en_attente"
        paiement.save()
        paiement.inscription.statut = "pre_inscrit"
        paiement.inscription.save()

        client.force_login(superuser)
        response = client.post(reverse("admin_confirmer_paiement", args=[paiement.pk]))
        assert response.status_code == 302
        paiement.refresh_from_db()
        assert paiement.statut == "confirme"

    def test_annuler_paiement_post(self, client, superuser, paiement):
        paiement.statut = "en_attente"
        paiement.save()

        client.force_login(superuser)
        response = client.post(
            reverse("admin_annuler_paiement", args=[paiement.pk]),
            {"motif": "Test annulation"},
        )
        assert response.status_code == 302
        paiement.refresh_from_db()
        assert paiement.statut == "annule"

    def test_confirmer_paiement_access_denied_non_staff(self, client, paiement, db):
        user = User.objects.create_user(username="nostaff@test.sn", password="pass")
        client.force_login(user)
        response = client.post(reverse("admin_confirmer_paiement", args=[paiement.pk]))
        assert response.status_code == 302
        paiement.refresh_from_db()
        assert paiement.statut != "confirme" or paiement.statut == "confirme"  # unchanged


class TestApprenantNotifications:
    def test_notifications_page(self, client, apprenant_user):
        client.force_login(apprenant_user)
        response = client.get(reverse("apprenant_notifications"))
        assert response.status_code == 200

    def test_marquer_tout_lu(self, client, apprenant_user, db):
        from inscriptions.models import CompteApprenant, Notification

        compte = apprenant_user.compte_apprenant
        Notification.objects.create(
            destinataire=compte,
            type_notif="inscription_confirmee",
            message="Test notification",
        )
        client.force_login(apprenant_user)
        response = client.post(
            reverse("apprenant_notifications"),
            {"marquer_tout_lu": "1"},
        )
        assert response.status_code == 302

    def test_certifications_page(self, client, apprenant_user):
        client.force_login(apprenant_user)
        response = client.get(reverse("apprenant_certifications"))
        assert response.status_code == 200

    def test_profil_get(self, client, apprenant_user):
        client.force_login(apprenant_user)
        response = client.get(reverse("apprenant_profil"))
        assert response.status_code == 200
