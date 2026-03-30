from django.contrib import admin
from django.db.models import Sum
from .models import Certification, Inscrit, InscriptionCertification, Paiement


class PaiementInline(admin.TabularInline):
    model = Paiement
    extra = 0
    readonly_fields = ["created_at"]
    fields = ["montant", "date_paiement", "moyen_paiement", "reference", "notes", "created_at"]


class InscriptionCertificationInline(admin.TabularInline):
    model = InscriptionCertification
    extra = 0
    readonly_fields = ["date_inscription"]
    fields = ["certification", "statut", "notes", "date_inscription"]
    show_change_link = True


@admin.register(Certification)
class CertificationAdmin(admin.ModelAdmin):
    list_display = [
        "nom", "duree", "cout_total", "date_debut", "date_fin", "actif",
        "nb_inscrits_display", "nb_certifies_display", "created_at",
    ]
    list_filter = ["actif", "date_debut", "date_fin"]
    search_fields = ["nom", "description"]
    readonly_fields = ["created_at"]
    ordering = ["-created_at"]

    def nb_inscrits_display(self, obj):
        return obj.nb_inscrits
    nb_inscrits_display.short_description = "Nb inscrits"

    def nb_certifies_display(self, obj):
        return obj.nb_certifies
    nb_certifies_display.short_description = "Nb certifiés"


@admin.register(Inscrit)
class InscritAdmin(admin.ModelAdmin):
    list_display = [
        "nom", "prenom", "email", "telephone", "activite", "source",
        "date_inscription", "nb_certifications_display",
    ]
    list_filter = ["source", "activite", "date_inscription"]
    search_fields = ["nom", "prenom", "email", "telephone"]
    readonly_fields = ["date_inscription"]
    inlines = [InscriptionCertificationInline]
    ordering = ["-date_inscription"]

    def nb_certifications_display(self, obj):
        return obj.inscriptions.count()
    nb_certifications_display.short_description = "Certifications"


@admin.register(InscriptionCertification)
class InscriptionCertificationAdmin(admin.ModelAdmin):
    list_display = [
        "inscrit", "certification", "statut", "total_paye_display",
        "reste_display", "date_inscription",
    ]
    list_filter = ["statut", "certification", "date_inscription"]
    search_fields = [
        "inscrit__nom", "inscrit__prenom", "inscrit__email",
        "certification__nom",
    ]
    readonly_fields = ["date_inscription"]
    inlines = [PaiementInline]
    autocomplete_fields = ["inscrit", "certification"]

    def total_paye_display(self, obj):
        return f"{obj.total_paye:,.0f} FCFA"
    total_paye_display.short_description = "Total payé"

    def reste_display(self, obj):
        return f"{obj.reste_a_payer:,.0f} FCFA"
    reste_display.short_description = "Reste à payer"


@admin.register(Paiement)
class PaiementAdmin(admin.ModelAdmin):
    list_display = [
        "inscription", "montant", "moyen_paiement", "date_paiement",
        "reference", "created_at",
    ]
    list_filter = ["moyen_paiement", "date_paiement"]
    search_fields = [
        "inscription__inscrit__nom",
        "inscription__inscrit__prenom",
        "inscription__inscrit__email",
        "inscription__certification__nom",
        "reference",
    ]
    readonly_fields = ["created_at"]
    ordering = ["-date_paiement"]
