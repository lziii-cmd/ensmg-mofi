import uuid
from django.db import models
from django.utils import timezone


class Certification(models.Model):
    nom = models.CharField(max_length=200, verbose_name="Nom de la certification")
    description = models.TextField(blank=True, verbose_name="Description")
    duree = models.CharField(max_length=100, blank=True, verbose_name="Durée")
    tarif_etudiant = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, verbose_name="Tarif étudiant (FCFA)"
    )
    tarif_professionnel = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, verbose_name="Tarif professionnel (FCFA)"
    )
    actif = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Certification"
        verbose_name_plural = "Certifications"
        ordering = ["-created_at"]

    def __str__(self):
        return self.nom

    @property
    def nb_inscrits(self):
        return Inscription.objects.filter(cohorte__certification=self).count()

    @property
    def nb_certifies(self):
        return Inscription.objects.filter(cohorte__certification=self, statut="certifie").count()

    @property
    def nb_en_formation(self):
        return Inscription.objects.filter(cohorte__certification=self, statut="en_formation").count()

    @property
    def nb_cohortes(self):
        return self.cohortes.count()

    @property
    def montant_encaisse(self):
        total = sum(
            p.montant
            for insc in Inscription.objects.filter(cohorte__certification=self)
            for p in insc.paiements.all()
        )
        return total


class Cohorte(models.Model):
    certification = models.ForeignKey(
        Certification,
        on_delete=models.CASCADE,
        related_name="cohortes",
        verbose_name="Certification",
    )
    nom = models.CharField(max_length=200, verbose_name="Nom de la cohorte")
    date_debut = models.DateField(null=True, blank=True, verbose_name="Date de début")
    date_fin = models.DateField(null=True, blank=True, verbose_name="Date de fin")
    actif = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Cohorte"
        verbose_name_plural = "Cohortes"
        ordering = ["nom"]

    def __str__(self):
        return f"{self.certification.nom} — {self.nom}"

    @property
    def nb_inscrits(self):
        return self.inscriptions.count()

    @property
    def nb_certifies(self):
        return self.inscriptions.filter(statut="certifie").count()

    @property
    def montant_encaisse(self):
        total = sum(
            p.montant
            for insc in self.inscriptions.all()
            for p in insc.paiements.all()
        )
        return total


class Inscrit(models.Model):
    ACTIVITE_CHOICES = [
        ("etudiant", "Étudiant"),
        ("professionnel", "Professionnel"),
    ]
    SOURCE_CHOICES = [
        ("manuel", "Manuel"),
        ("excel", "Import Excel"),
    ]

    nom = models.CharField(max_length=100, verbose_name="Nom")
    prenom = models.CharField(max_length=100, verbose_name="Prénom")
    email = models.EmailField(blank=True, verbose_name="Email")
    telephone = models.CharField(max_length=30, blank=True, verbose_name="Téléphone")
    activite = models.CharField(
        max_length=20,
        choices=ACTIVITE_CHOICES,
        default="etudiant",
        verbose_name="Activité",
    )
    source = models.CharField(
        max_length=20,
        choices=SOURCE_CHOICES,
        default="manuel",
        verbose_name="Source",
    )
    notes = models.TextField(blank=True, verbose_name="Notes")
    date_inscription = models.DateTimeField(
        auto_now_add=True, verbose_name="Date d'inscription"
    )

    class Meta:
        verbose_name = "Inscrit"
        verbose_name_plural = "Inscrits"
        ordering = ["-date_inscription"]

    def __str__(self):
        return f"{self.prenom} {self.nom}"

    @property
    def nom_complet(self):
        return f"{self.prenom} {self.nom}"


class Inscription(models.Model):
    STATUT_CHOICES = [
        ("inscrit", "Inscrit"),
        ("en_formation", "En formation"),
        ("abandon", "Abandon"),
        ("formation_terminee", "Formation terminée"),
        ("certifie", "Certifié"),
    ]

    inscrit = models.ForeignKey(
        Inscrit,
        on_delete=models.CASCADE,
        related_name="inscriptions",
        verbose_name="Inscrit",
    )
    cohorte = models.ForeignKey(
        Cohorte,
        on_delete=models.CASCADE,
        related_name="inscriptions",
        verbose_name="Cohorte",
    )
    statut = models.CharField(
        max_length=20,
        choices=STATUT_CHOICES,
        default="inscrit",
        verbose_name="Statut",
    )
    montant_du = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, verbose_name="Montant dû (FCFA)"
    )
    date_inscription = models.DateTimeField(
        auto_now_add=True, verbose_name="Date d'inscription"
    )
    notes = models.TextField(blank=True, verbose_name="Notes")

    class Meta:
        verbose_name = "Inscription"
        verbose_name_plural = "Inscriptions"
        unique_together = [["inscrit", "cohorte"]]
        ordering = ["-date_inscription"]

    def __str__(self):
        return f"{self.inscrit} — {self.cohorte}"

    @property
    def total_paye(self):
        return sum(p.montant for p in self.paiements.all())

    @property
    def reste_a_payer(self):
        reste = self.montant_du - self.total_paye
        return max(reste, 0)

    @property
    def pourcentage_paye(self):
        if self.montant_du <= 0:
            return 100
        pct = (self.total_paye / self.montant_du) * 100
        return min(int(pct), 100)

    def get_statut_display_badge(self):
        mapping = {
            "inscrit": "primary",
            "en_formation": "warning",
            "abandon": "danger",
            "formation_terminee": "secondary",
            "certifie": "success",
        }
        return mapping.get(self.statut, "secondary")


class Paiement(models.Model):
    MOYEN_CHOICES = [
        ("wave", "Wave"),
        ("orange_money", "Orange Money"),
        ("stripe", "Stripe"),
        ("especes", "Espèces"),
        ("virement", "Virement bancaire"),
    ]

    inscription = models.ForeignKey(
        Inscription,
        on_delete=models.CASCADE,
        related_name="paiements",
        verbose_name="Inscription",
    )
    montant = models.DecimalField(
        max_digits=12, decimal_places=2, verbose_name="Montant (FCFA)"
    )
    date_paiement = models.DateField(
        default=timezone.now, verbose_name="Date de paiement"
    )
    moyen_paiement = models.CharField(
        max_length=20,
        choices=MOYEN_CHOICES,
        default="especes",
        verbose_name="Moyen de paiement",
    )
    reference = models.CharField(
        max_length=100, blank=True, verbose_name="Référence"
    )
    notes = models.TextField(blank=True, verbose_name="Notes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Paiement"
        verbose_name_plural = "Paiements"
        ordering = ["-date_paiement", "-created_at"]

    def __str__(self):
        return f"{self.inscription} — {self.montant} FCFA"


class Attestation(models.Model):
    inscription = models.ForeignKey(
        Inscription,
        on_delete=models.CASCADE,
        related_name="attestations",
        verbose_name="Inscription",
    )
    numero = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="Numéro d'attestation",
    )
    date_delivrance = models.DateField(
        default=timezone.now,
        verbose_name="Date de délivrance",
    )
    contenu_pdf = models.BinaryField(
        null=True,
        blank=True,
        verbose_name="Contenu PDF",
        help_text="PDF stocké en base de données (persist sur tous les hébergeurs).",
    )
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Attestation"
        verbose_name_plural = "Attestations"
        ordering = ["-date_delivrance", "-generated_at"]

    def __str__(self):
        return f"Attestation {self.numero} — {self.inscription.inscrit.nom_complet}"
