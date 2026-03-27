from django.contrib import admin
from django.db.models import Sum
from .models import Inscrit, Paiement


class PaiementInline(admin.TabularInline):
    model = Paiement
    extra = 0
    readonly_fields = ['created_at']
    fields = ['montant', 'date_paiement', 'moyen_paiement', 'reference', 'notes', 'created_at']


@admin.register(Inscrit)
class InscritAdmin(admin.ModelAdmin):
    list_display = ['nom', 'prenom', 'email', 'telephone', 'activite', 'source', 'date_inscription', 'total_paye_display']
    list_filter = ['source', 'activite', 'date_inscription']
    search_fields = ['nom', 'prenom', 'email', 'telephone', 'activite']
    readonly_fields = ['date_inscription', 'source']
    inlines = [PaiementInline]
    ordering = ['-date_inscription']

    def total_paye_display(self, obj):
        return f"{obj.total_paye:,.0f} FCFA"
    total_paye_display.short_description = 'Total payé'


@admin.register(Paiement)
class PaiementAdmin(admin.ModelAdmin):
    list_display = ['inscrit', 'montant', 'moyen_paiement', 'date_paiement', 'reference', 'created_at']
    list_filter = ['moyen_paiement', 'date_paiement']
    search_fields = ['inscrit__nom', 'inscrit__prenom', 'inscrit__email', 'reference']
    readonly_fields = ['created_at']
    ordering = ['-date_paiement']
    autocomplete_fields = ['inscrit']
