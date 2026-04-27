from django.contrib import admin

from .models import (
    Attestation,
    Certification,
    Cohorte,
    Inscription,
    Inscrit,
    OptionCertification,
    Paiement,
    TypeTarif,
)


class PaiementInline(admin.TabularInline):
    model = Paiement
    extra = 0
    readonly_fields = ["created_at"]
    fields = ["montant", "date_paiement", "moyen_paiement", "reference", "notes", "created_at"]


class InscriptionInline(admin.TabularInline):
    model = Inscription
    extra = 0
    readonly_fields = ["date_inscription"]
    fields = ["cohorte", "statut", "montant_du", "notes", "date_inscription"]
    show_change_link = True


class CohorteInline(admin.TabularInline):
    model = Cohorte
    extra = 0
    readonly_fields = ["created_at"]
    fields = ["nom", "date_debut", "date_fin", "actif", "created_at"]
    show_change_link = True


@admin.register(Certification)
class CertificationAdmin(admin.ModelAdmin):
    list_display = [
        "nom",
        "duree",
        "a_options",
        "actif",
        "nb_inscrits_display",
        "nb_certifies_display",
        "nb_cohortes_display",
        "created_at",
    ]
    list_filter = ["actif", "a_options"]
    search_fields = ["nom", "description"]
    readonly_fields = ["created_at"]
    ordering = ["-created_at"]
    inlines = [CohorteInline]

    def nb_inscrits_display(self, obj):
        return obj.nb_inscrits

    nb_inscrits_display.short_description = "Nb inscrits"

    def nb_certifies_display(self, obj):
        return obj.nb_certifies

    nb_certifies_display.short_description = "Nb certifiés"

    def nb_cohortes_display(self, obj):
        return obj.nb_cohortes

    nb_cohortes_display.short_description = "Cohortes"


@admin.register(Cohorte)
class CohorteAdmin(admin.ModelAdmin):
    list_display = [
        "nom",
        "certification",
        "date_debut",
        "date_fin",
        "actif",
        "nb_inscrits_display",
        "created_at",
    ]
    list_filter = ["actif", "certification"]
    search_fields = ["nom", "certification__nom"]
    readonly_fields = ["created_at"]
    autocomplete_fields = ["certification"]

    def nb_inscrits_display(self, obj):
        return obj.nb_inscrits

    nb_inscrits_display.short_description = "Nb inscrits"


@admin.register(Inscrit)
class InscritAdmin(admin.ModelAdmin):
    list_display = [
        "nom",
        "prenom",
        "email",
        "telephone",
        "activite",
        "source",
        "date_inscription",
        "nb_inscriptions_display",
    ]
    list_filter = ["source", "activite", "date_inscription"]
    search_fields = ["nom", "prenom", "email", "telephone"]
    readonly_fields = ["date_inscription"]
    inlines = [InscriptionInline]
    ordering = ["-date_inscription"]

    def nb_inscriptions_display(self, obj):
        return obj.inscriptions.count()

    nb_inscriptions_display.short_description = "Inscriptions"


@admin.register(Inscription)
class InscriptionAdmin(admin.ModelAdmin):
    list_display = [
        "inscrit",
        "cohorte",
        "statut",
        "montant_du",
        "total_paye_display",
        "reste_display",
        "date_inscription",
    ]
    list_filter = ["statut", "cohorte__certification", "date_inscription"]
    search_fields = [
        "inscrit__nom",
        "inscrit__prenom",
        "inscrit__email",
        "cohorte__nom",
        "cohorte__certification__nom",
    ]
    readonly_fields = ["date_inscription"]
    inlines = [PaiementInline]
    autocomplete_fields = ["inscrit", "cohorte"]

    def total_paye_display(self, obj):
        return f"{obj.total_paye:,.0f} FCFA"

    total_paye_display.short_description = "Total payé"

    def reste_display(self, obj):
        return f"{obj.reste_a_payer:,.0f} FCFA"

    reste_display.short_description = "Reste à payer"


@admin.register(Paiement)
class PaiementAdmin(admin.ModelAdmin):
    list_display = [
        "inscription",
        "montant",
        "moyen_paiement",
        "date_paiement",
        "reference",
        "created_at",
    ]
    list_filter = ["moyen_paiement", "date_paiement"]
    search_fields = [
        "inscription__inscrit__nom",
        "inscription__inscrit__prenom",
        "inscription__inscrit__email",
        "inscription__cohorte__nom",
        "inscription__cohorte__certification__nom",
        "reference",
    ]
    readonly_fields = ["created_at"]
    ordering = ["-date_paiement"]


@admin.register(Attestation)
class AttestationAdmin(admin.ModelAdmin):
    list_display = [
        "numero",
        "inscrit_display",
        "certification_display",
        "date_delivrance",
        "generated_at",
    ]
    list_filter = ["date_delivrance", "inscription__cohorte__certification"]
    search_fields = ["numero", "inscription__inscrit__nom", "inscription__inscrit__prenom"]
    readonly_fields = ["numero", "generated_at"]
    ordering = ["-date_delivrance"]

    def inscrit_display(self, obj):
        return obj.inscription.inscrit.nom_complet

    inscrit_display.short_description = "Inscrit"

    def certification_display(self, obj):
        return obj.inscription.cohorte.certification.nom

    certification_display.short_description = "Certification"


@admin.register(OptionCertification)
class OptionCertificationAdmin(admin.ModelAdmin):
    list_display = ["nom", "certification", "actif", "nb_inscrits_display", "created_at"]
    list_filter = ["actif", "certification"]
    search_fields = ["nom", "certification__nom"]
    readonly_fields = ["created_at"]
    autocomplete_fields = ["certification"]

    def nb_inscrits_display(self, obj):
        return obj.nb_inscrits

    nb_inscrits_display.short_description = "Nb inscrits"


@admin.register(TypeTarif)
class TypeTarifAdmin(admin.ModelAdmin):
    list_display = ["nom", "montant", "certification", "option", "actif", "created_at"]
    list_filter = ["actif", "certification"]
    search_fields = ["nom", "certification__nom", "option__nom"]
    readonly_fields = ["created_at"]
