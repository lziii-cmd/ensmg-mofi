from django.db import models
from django.db.models import Sum


class Inscrit(models.Model):
    SOURCE_CHOICES = [
        ('manuel', 'Saisie manuelle'),
        ('excel', 'Import Excel'),
    ]

    nom = models.CharField(max_length=100, verbose_name='Nom')
    prenom = models.CharField(max_length=100, verbose_name='Prénom')
    email = models.EmailField(unique=True, verbose_name='Email')
    telephone = models.CharField(max_length=20, verbose_name='Téléphone')
    activite = models.CharField(max_length=200, verbose_name='Formation / Activité')
    date_inscription = models.DateField(auto_now_add=True, verbose_name='Date d\'inscription')
    source = models.CharField(
        max_length=10,
        choices=SOURCE_CHOICES,
        default='manuel',
        verbose_name='Source'
    )
    notes = models.TextField(blank=True, verbose_name='Notes')

    class Meta:
        verbose_name = 'Inscrit'
        verbose_name_plural = 'Inscrits'
        ordering = ['-date_inscription', 'nom']

    def __str__(self):
        return f"{self.prenom} {self.nom}"

    @property
    def total_paye(self):
        result = self.paiements.aggregate(total=Sum('montant'))
        return result['total'] or 0

    @property
    def statut_paiement(self):
        if self.paiements.exists():
            return 'payé'
        return 'non payé'

    def get_nom_complet(self):
        return f"{self.prenom} {self.nom}"


class Paiement(models.Model):
    MOYEN_CHOICES = [
        ('wave', 'Wave'),
        ('orange_money', 'Orange Money'),
        ('stripe', 'Stripe'),
        ('especes', 'Espèces'),
        ('virement', 'Virement bancaire'),
    ]

    inscrit = models.ForeignKey(
        Inscrit,
        on_delete=models.CASCADE,
        related_name='paiements',
        verbose_name='Inscrit'
    )
    montant = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name='Montant (FCFA)'
    )
    date_paiement = models.DateField(verbose_name='Date de paiement')
    moyen_paiement = models.CharField(
        max_length=20,
        choices=MOYEN_CHOICES,
        verbose_name='Moyen de paiement'
    )
    reference = models.CharField(
        max_length=200,
        blank=True,
        verbose_name='Référence / N° de transaction'
    )
    notes = models.TextField(blank=True, verbose_name='Notes')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Créé le')

    class Meta:
        verbose_name = 'Paiement'
        verbose_name_plural = 'Paiements'
        ordering = ['-date_paiement', '-created_at']

    def __str__(self):
        return f"Paiement {self.montant} FCFA - {self.inscrit} ({self.date_paiement})"
