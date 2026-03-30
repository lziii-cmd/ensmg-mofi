from django import forms
from .models import Certification, Inscrit, InscriptionCertification, Paiement


class CertificationForm(forms.ModelForm):
    class Meta:
        model = Certification
        fields = ["nom", "description", "duree", "cout_total", "date_debut", "date_fin", "actif"]
        widgets = {
            "nom": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Nom de la certification",
            }),
            "description": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Description de la certification...",
            }),
            "duree": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Ex: 3 mois, 120 heures...",
            }),
            "cout_total": forms.NumberInput(attrs={
                "class": "form-control",
                "placeholder": "0",
                "min": "0",
                "step": "1",
            }),
            "date_debut": forms.DateInput(attrs={
                "class": "form-control",
                "type": "date",
            }),
            "date_fin": forms.DateInput(attrs={
                "class": "form-control",
                "type": "date",
            }),
            "actif": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "nom": "Nom de la certification",
            "description": "Description",
            "duree": "Durée",
            "cout_total": "Coût total (FCFA)",
            "date_debut": "Date de début",
            "date_fin": "Date de fin",
            "actif": "Certification active",
        }


class InscritForm(forms.ModelForm):
    class Meta:
        model = Inscrit
        fields = ["nom", "prenom", "email", "telephone", "activite", "notes"]
        widgets = {
            "nom": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Nom de famille",
            }),
            "prenom": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Prénom",
            }),
            "email": forms.EmailInput(attrs={
                "class": "form-control",
                "placeholder": "adresse@email.com",
            }),
            "telephone": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "+221 77 000 00 00",
            }),
            "activite": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Notes ou informations complémentaires...",
            }),
        }
        labels = {
            "nom": "Nom",
            "prenom": "Prénom",
            "email": "Adresse email",
            "telephone": "Téléphone",
            "activite": "Activité / Profil",
            "notes": "Notes",
        }


class InscriptionCertificationForm(forms.ModelForm):
    class Meta:
        model = InscriptionCertification
        fields = ["certification", "statut", "notes"]
        widgets = {
            "certification": forms.Select(attrs={"class": "form-select"}),
            "statut": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Notes complémentaires...",
            }),
        }
        labels = {
            "certification": "Certification",
            "statut": "Statut initial",
            "notes": "Notes",
        }

    def __init__(self, *args, inscrit=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.inscrit = inscrit
        if inscrit:
            # Exclude certifications already enrolled
            already = inscrit.inscriptions.values_list("certification_id", flat=True)
            self.fields["certification"].queryset = Certification.objects.exclude(
                pk__in=already
            )


class ChangerStatutForm(forms.ModelForm):
    class Meta:
        model = InscriptionCertification
        fields = ["statut"]
        widgets = {
            "statut": forms.Select(attrs={"class": "form-select form-select-sm"}),
        }
        labels = {"statut": "Nouveau statut"}


class PaiementForm(forms.ModelForm):
    class Meta:
        model = Paiement
        fields = [
            "inscription",
            "montant",
            "date_paiement",
            "moyen_paiement",
            "reference",
            "notes",
        ]
        widgets = {
            "inscription": forms.Select(attrs={"class": "form-select"}),
            "montant": forms.NumberInput(attrs={
                "class": "form-control",
                "placeholder": "0",
                "min": "0",
                "step": "1",
            }),
            "date_paiement": forms.DateInput(attrs={
                "class": "form-control",
                "type": "date",
            }),
            "moyen_paiement": forms.Select(attrs={"class": "form-select"}),
            "reference": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Numéro de transaction ou référence",
            }),
            "notes": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Notes complémentaires...",
            }),
        }
        labels = {
            "inscription": "Inscription (Inscrit — Certification)",
            "montant": "Montant (FCFA)",
            "date_paiement": "Date du paiement",
            "moyen_paiement": "Moyen de paiement",
            "reference": "Référence / N° de transaction",
            "notes": "Notes",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Show a readable label for each InscriptionCertification
        self.fields["inscription"].queryset = (
            InscriptionCertification.objects.select_related("inscrit", "certification")
            .order_by("inscrit__nom", "inscrit__prenom")
        )
        self.fields["inscription"].label_from_instance = (
            lambda obj: f"{obj.inscrit.prenom} {obj.inscrit.nom} — {obj.certification.nom}"
        )


class PaiementInscriptionForm(forms.ModelForm):
    """Payment form pre-linked to an InscriptionCertification."""

    class Meta:
        model = Paiement
        fields = ["montant", "date_paiement", "moyen_paiement", "reference", "notes"]
        widgets = {
            "montant": forms.NumberInput(attrs={
                "class": "form-control",
                "placeholder": "0",
                "min": "0",
                "step": "1",
            }),
            "date_paiement": forms.DateInput(attrs={
                "class": "form-control",
                "type": "date",
            }),
            "moyen_paiement": forms.Select(attrs={"class": "form-select"}),
            "reference": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Numéro de transaction ou référence",
            }),
            "notes": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Notes complémentaires...",
            }),
        }
        labels = {
            "montant": "Montant (FCFA)",
            "date_paiement": "Date du paiement",
            "moyen_paiement": "Moyen de paiement",
            "reference": "Référence / N° de transaction",
            "notes": "Notes",
        }


class ImportExcelForm(forms.Form):
    fichier = forms.FileField(
        label="Fichier Excel (.xlsx)",
        widget=forms.ClearableFileInput(attrs={
            "class": "form-control",
            "accept": ".xlsx",
        }),
        help_text="Format accepté : .xlsx",
    )
    certification = forms.ModelChoiceField(
        queryset=Certification.objects.all(),
        label="Certification cible",
        help_text="Les inscrits importés seront inscrits à cette certification.",
        widget=forms.Select(attrs={"class": "form-select"}),
        empty_label="— Sélectionner une certification —",
    )
