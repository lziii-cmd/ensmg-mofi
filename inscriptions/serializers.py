"""
Sérialiseurs DRF pour l'API REST ENSMG Certification.
"""

from django.contrib.auth.models import User
from rest_framework import serializers

from .models import Attestation, Certification, Cohorte, Inscription, Inscrit, Paiement, TypeTarif


class TypeTarifSerializer(serializers.ModelSerializer):
    class Meta:
        model = TypeTarif
        fields = ["id", "nom", "montant", "actif"]


class CertificationSerializer(serializers.ModelSerializer):
    nb_inscrits = serializers.ReadOnlyField()
    nb_certifies = serializers.ReadOnlyField()
    nb_en_formation = serializers.ReadOnlyField()
    montant_encaisse = serializers.ReadOnlyField()
    types_tarif = TypeTarifSerializer(many=True, read_only=True)

    class Meta:
        model = Certification
        fields = [
            "id",
            "nom",
            "description",
            "duree",
            "a_options",
            "actif",
            "types_tarif",
            "nb_inscrits",
            "nb_certifies",
            "nb_en_formation",
            "montant_encaisse",
            "created_at",
        ]
        read_only_fields = ["created_at"]


class CohorteSerializer(serializers.ModelSerializer):
    certification_nom = serializers.ReadOnlyField(source="certification.nom")
    nb_inscrits = serializers.ReadOnlyField()
    nb_certifies = serializers.ReadOnlyField()

    class Meta:
        model = Cohorte
        fields = [
            "id",
            "certification",
            "certification_nom",
            "nom",
            "date_debut",
            "date_fin",
            "actif",
            "nb_inscrits",
            "nb_certifies",
            "created_at",
        ]
        read_only_fields = ["created_at"]


class InscritSerializer(serializers.ModelSerializer):
    nom_complet = serializers.ReadOnlyField()

    class Meta:
        model = Inscrit
        fields = [
            "id",
            "nom",
            "prenom",
            "nom_complet",
            "email",
            "telephone",
            "activite",
            "adresse",
            "universite",
            "entreprise",
            "source",
            "notes",
            "date_inscription",
        ]
        read_only_fields = ["source", "date_inscription"]

    def validate_email(self, value):
        qs = Inscrit.objects.filter(email__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if value and qs.exists():
            raise serializers.ValidationError("Un inscrit avec cet email existe déjà.")
        return value


class InscritCreateSerializer(InscritSerializer):
    """Sérialiseur pour la création via API — source forcée à 'manuel'."""

    def create(self, validated_data):
        validated_data["source"] = "manuel"
        return super().create(validated_data)


class InscriptionSerializer(serializers.ModelSerializer):
    inscrit_nom = serializers.ReadOnlyField(source="inscrit.nom_complet")
    certification_nom = serializers.ReadOnlyField(source="cohorte.certification.nom")
    cohorte_nom = serializers.ReadOnlyField(source="cohorte.nom")
    total_paye = serializers.ReadOnlyField()
    reste_a_payer = serializers.ReadOnlyField()
    pourcentage_paye = serializers.ReadOnlyField()

    class Meta:
        model = Inscription
        fields = [
            "id",
            "inscrit",
            "inscrit_nom",
            "cohorte",
            "cohorte_nom",
            "certification_nom",
            "statut",
            "montant_du",
            "total_paye",
            "reste_a_payer",
            "pourcentage_paye",
            "notes",
            "date_inscription",
        ]
        read_only_fields = ["date_inscription"]


class PaiementSerializer(serializers.ModelSerializer):
    inscrit_nom = serializers.ReadOnlyField(source="inscription.inscrit.nom_complet")
    certification_nom = serializers.ReadOnlyField(source="inscription.cohorte.certification.nom")

    class Meta:
        model = Paiement
        fields = [
            "id",
            "inscription",
            "inscrit_nom",
            "certification_nom",
            "montant",
            "date_paiement",
            "moyen_paiement",
            "reference",
            "statut",
            "notes",
            "created_at",
        ]
        read_only_fields = ["created_at", "statut"]


class AttestationSerializer(serializers.ModelSerializer):
    inscrit_nom = serializers.ReadOnlyField(source="inscription.inscrit.nom_complet")
    certification_nom = serializers.ReadOnlyField(source="inscription.cohorte.certification.nom")

    class Meta:
        model = Attestation
        fields = [
            "id",
            "numero",
            "inscrit_nom",
            "certification_nom",
            "date_delivrance",
            "generated_at",
        ]
        read_only_fields = ["numero", "date_delivrance", "generated_at"]


# ── Auth / Users ─────────────────────────────────────────────────────────────


class UserRoleSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "email", "is_active", "role"]

    def get_role(self, obj):
        if obj.is_superuser:
            return "Administrateur"
        groups = [g.name for g in obj.groups.all()]
        if "Comptable" in groups:
            return "Comptable"
        if "Responsable" in groups:
            return "Responsable"
        return "Utilisateur"


# ── Webhooks ──────────────────────────────────────────────────────────────────


class WaveWebhookSerializer(serializers.Serializer):
    """Payload Wave — champ client_reference = numéro d'inscription."""

    id = serializers.CharField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    currency = serializers.CharField(default="XOF")
    client_reference = serializers.CharField(required=False, allow_blank=True)
    status = serializers.CharField()
    timestamp = serializers.CharField(required=False)


class OrangeMoneyWebhookSerializer(serializers.Serializer):
    """Payload Orange Money CI/SN."""

    txnid = serializers.CharField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    msisdn = serializers.CharField(required=False, allow_blank=True)
    status = serializers.CharField()
    orderId = serializers.CharField(required=False, allow_blank=True)
