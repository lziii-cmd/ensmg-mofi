from functools import cached_property

from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.utils import timezone


class Certification(models.Model):
    nom = models.CharField(max_length=200, verbose_name="Nom de la certification")
    description = models.TextField(blank=True, verbose_name="Description")
    duree = models.CharField(max_length=100, blank=True, verbose_name="Durée")
    a_options = models.BooleanField(
        default=False,
        verbose_name="Avec options",
        help_text="Si activé, la certification est organisée en options (ex: A1, A2…). "
        "Chaque option dispose de ses propres cohortes et tarifs.",
    )
    actif = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Certification"
        verbose_name_plural = "Certifications"
        ordering = ["-created_at"]

    def __str__(self):
        return self.nom

    @cached_property
    def nb_inscrits(self):
        return Inscription.objects.filter(cohorte__certification=self).count()

    @cached_property
    def nb_certifies(self):
        return Inscription.objects.filter(cohorte__certification=self, statut="certifie").count()

    @cached_property
    def nb_en_formation(self):
        return Inscription.objects.filter(
            cohorte__certification=self, statut="en_formation"
        ).count()

    @cached_property
    def nb_cohortes(self):
        return self.cohortes.count()

    @cached_property
    def montant_encaisse(self):
        result = Paiement.objects.filter(inscription__cohorte__certification=self).aggregate(
            total=Sum("montant")
        )
        return result["total"] or 0


class OptionCertification(models.Model):
    """Option d'une certification (ex: A1, A2, Module Python…).
    Utilisée uniquement quand Certification.a_options=True."""

    certification = models.ForeignKey(
        Certification,
        on_delete=models.CASCADE,
        related_name="options",
        verbose_name="Certification",
    )
    nom = models.CharField(max_length=200, verbose_name="Nom de l'option")
    actif = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Option de certification"
        verbose_name_plural = "Options de certification"
        ordering = ["nom"]
        unique_together = [["certification", "nom"]]

    def __str__(self):
        return f"{self.certification.nom} — {self.nom}"

    @cached_property
    def nb_inscrits(self):
        return Inscription.objects.filter(cohorte__option=self).count()

    @cached_property
    def montant_encaisse(self):
        result = Paiement.objects.filter(inscription__cohorte__option=self).aggregate(
            total=Sum("montant")
        )
        return result["total"] or 0


class NomTypeTarif(models.Model):
    """Catalogue global de noms de types de tarif (Étudiant, Professionnel…).
    Réutilisable sur toutes les certifications."""

    nom = models.CharField(max_length=100, unique=True, verbose_name="Nom")
    actif = models.BooleanField(default=True, verbose_name="Actif")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Nom de type de tarif"
        verbose_name_plural = "Noms de types de tarif"
        ordering = ["nom"]

    def __str__(self):
        return self.nom


class TypeTarif(models.Model):
    """Type de tarif flexible (Étudiant, Professionnel, Chômeur, Fonctionnaire…).
    Rattaché soit à une Certification (si a_options=False),
    soit à une OptionCertification (si a_options=True)."""

    certification = models.ForeignKey(
        Certification,
        on_delete=models.CASCADE,
        related_name="types_tarif",
        verbose_name="Certification",
        null=True,
        blank=True,
    )
    option = models.ForeignKey(
        OptionCertification,
        on_delete=models.CASCADE,
        related_name="types_tarif",
        verbose_name="Option",
        null=True,
        blank=True,
    )
    nom = models.CharField(max_length=100, verbose_name="Nom du tarif")
    montant = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, verbose_name="Montant (FCFA)"
    )
    actif = models.BooleanField(default=True, verbose_name="Actif")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Type de tarif"
        verbose_name_plural = "Types de tarif"
        ordering = ["nom"]

    def __str__(self):
        if self.option:
            return f"{self.option} — {self.nom} ({self.montant} FCFA)"
        if self.certification:
            return f"{self.certification.nom} — {self.nom} ({self.montant} FCFA)"
        return f"{self.nom} ({self.montant} FCFA)"

    @property
    def parent(self):
        """Retourne l'option ou la certification parente."""
        return self.option or self.certification


class Cohorte(models.Model):
    certification = models.ForeignKey(
        Certification,
        on_delete=models.CASCADE,
        related_name="cohortes",
        verbose_name="Certification",
    )
    option = models.ForeignKey(
        OptionCertification,
        on_delete=models.SET_NULL,
        related_name="cohortes",
        verbose_name="Option",
        null=True,
        blank=True,
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

    @cached_property
    def nb_inscrits(self):
        return self.inscriptions.count()

    @cached_property
    def nb_certifies(self):
        return self.inscriptions.filter(statut="certifie").count()

    @cached_property
    def montant_encaisse(self):
        result = Paiement.objects.filter(inscription__cohorte=self).aggregate(total=Sum("montant"))
        return result["total"] or 0


class Inscrit(models.Model):
    ACTIVITE_CHOICES = [
        ("etudiant", "Étudiant"),
        ("professionnel", "Professionnel"),
    ]
    SOURCE_CHOICES = [
        ("manuel", "Manuel"),
        ("excel", "Import Excel"),
        ("portail", "Portail en ligne"),
    ]

    nom = models.CharField(max_length=100, verbose_name="Nom", db_index=True)
    prenom = models.CharField(max_length=100, verbose_name="Prénom", db_index=True)
    email = models.EmailField(blank=True, verbose_name="Email", db_index=True)
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
    adresse = models.CharField(max_length=255, blank=True, verbose_name="Adresse")
    universite = models.CharField(max_length=200, blank=True, verbose_name="Université")
    entreprise = models.CharField(max_length=200, blank=True, verbose_name="Entreprise")
    notes = models.TextField(blank=True, verbose_name="Notes")
    date_inscription = models.DateTimeField(auto_now_add=True, verbose_name="Date d'inscription")

    class Meta:
        verbose_name = "Inscrit"
        verbose_name_plural = "Inscrits"
        ordering = ["-date_inscription"]

    def __str__(self):
        return f"{self.prenom} {self.nom}"

    @cached_property
    def nom_complet(self):
        return f"{self.prenom} {self.nom}"


class Inscription(models.Model):
    STATUT_CHOICES = [
        ("pre_inscrit", "Pré-inscrit"),  # Inscrit, paiement non encore confirmé
        ("inscrit", "Inscrit"),  # Paiement confirmé — officiellement admis
        ("en_formation", "En formation"),  # Cohorte démarrée (auto)
        ("abandon", "Abandon"),  # Manuel
        ("formation_terminee", "Formation terminée"),  # Cohorte terminée (auto)
        ("certifie", "Certifié"),  # Attestation délivrée (auto)
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
        db_index=True,
    )
    type_tarif = models.ForeignKey(
        TypeTarif,
        on_delete=models.SET_NULL,
        related_name="inscriptions",
        verbose_name="Type de tarif",
        null=True,
        blank=True,
    )
    montant_du = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, verbose_name="Montant dû (FCFA)"
    )
    date_inscription = models.DateTimeField(auto_now_add=True, verbose_name="Date d'inscription")
    notes = models.TextField(blank=True, verbose_name="Notes")

    class Meta:
        verbose_name = "Inscription"
        verbose_name_plural = "Inscriptions"
        unique_together = [["inscrit", "cohorte"]]
        ordering = ["-date_inscription"]

    def __str__(self):
        return f"{self.inscrit} — {self.cohorte}"

    @cached_property
    def total_paye(self):
        """Somme des paiements (bénéficie du prefetch_related si activé)."""
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
        ("intouch", "InTouch Sénégal"),
        ("carte", "Carte bancaire"),
        ("especes", "Espèces"),
        ("virement", "Virement bancaire"),
    ]

    STATUT_CHOICES = [
        ("confirme", "Confirmé"),
        ("en_attente", "En attente"),
    ]

    inscription = models.ForeignKey(
        Inscription,
        on_delete=models.CASCADE,
        related_name="paiements",
        verbose_name="Inscription",
    )
    montant = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Montant (FCFA)")
    date_paiement = models.DateField(default=timezone.now, verbose_name="Date de paiement")
    moyen_paiement = models.CharField(
        max_length=20,
        choices=MOYEN_CHOICES,
        default="especes",
        verbose_name="Moyen de paiement",
        db_index=True,
    )
    reference = models.CharField(max_length=100, blank=True, verbose_name="Référence")
    statut = models.CharField(
        max_length=20,
        choices=STATUT_CHOICES,
        default="confirme",
        verbose_name="Statut",
    )
    recu_pdf = models.BinaryField(null=True, blank=True, verbose_name="Reçu PDF")
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


class CompteApprenant(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="compte_apprenant",
        verbose_name="Utilisateur",
    )
    inscrit = models.OneToOneField(
        Inscrit, on_delete=models.CASCADE, related_name="compte_apprenant", verbose_name="Inscrit"
    )
    mdp_change = models.BooleanField(default=False, verbose_name="Mot de passe changé")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Compte Apprenant"
        verbose_name_plural = "Comptes Apprenants"

    def __str__(self):
        return f"Compte de {self.inscrit}"


class Notification(models.Model):
    TYPE_CHOICES = [
        ("nouvelle_certification", "Nouvelle certification disponible"),
        ("attestation_generee", "Attestation générée"),
        ("paiement_confirme", "Paiement confirmé"),
    ]
    destinataire = models.ForeignKey(
        CompteApprenant,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name="Destinataire",
    )
    type_notif = models.CharField(max_length=30, choices=TYPE_CHOICES, verbose_name="Type")
    message = models.TextField(verbose_name="Message")
    lu = models.BooleanField(default=False, verbose_name="Lu")
    date_creation = models.DateTimeField(auto_now_add=True)
    lien = models.CharField(max_length=200, blank=True, verbose_name="Lien")

    class Meta:
        ordering = ["-date_creation"]
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"

    def __str__(self):
        return f"[{self.type_notif}] → {self.destinataire}"
