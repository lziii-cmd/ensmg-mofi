from django import forms
from django.contrib.auth.models import User
from .models import Certification, Cohorte, Inscrit, Inscription, Paiement


class CertificationForm(forms.ModelForm):
    class Meta:
        model = Certification
        fields = ["nom", "description", "duree", "tarif_etudiant", "tarif_professionnel", "actif"]
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
            "tarif_etudiant": forms.NumberInput(attrs={
                "class": "form-control",
                "placeholder": "0",
                "min": "0",
                "step": "1",
            }),
            "tarif_professionnel": forms.NumberInput(attrs={
                "class": "form-control",
                "placeholder": "0",
                "min": "0",
                "step": "1",
            }),
            "actif": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "nom": "Nom de la certification",
            "description": "Description",
            "duree": "Durée",
            "tarif_etudiant": "Tarif étudiant (FCFA)",
            "tarif_professionnel": "Tarif professionnel (FCFA)",
            "actif": "Certification active",
        }


class CohorteForm(forms.ModelForm):
    class Meta:
        model = Cohorte
        fields = ["nom", "date_debut", "date_fin", "actif"]
        widgets = {
            "nom": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Nom de la cohorte",
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
            "nom": "Nom de la cohorte",
            "date_debut": "Date de début",
            "date_fin": "Date de fin",
            "actif": "Cohorte active",
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


class InscriptionForm(forms.ModelForm):
    class Meta:
        model = Inscription
        fields = ["cohorte", "statut", "montant_du", "notes"]
        widgets = {
            "cohorte": forms.Select(attrs={"class": "form-select"}),
            "statut": forms.Select(attrs={"class": "form-select"}),
            "montant_du": forms.NumberInput(attrs={
                "class": "form-control",
                "placeholder": "0",
                "min": "0",
                "step": "1",
            }),
            "notes": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Notes complémentaires...",
            }),
        }
        labels = {
            "cohorte": "Cohorte",
            "statut": "Statut initial",
            "montant_du": "Montant dû (FCFA)",
            "notes": "Notes",
        }

    def __init__(self, *args, inscrit=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.inscrit = inscrit
        if inscrit:
            # Exclude cohortes already enrolled
            already = inscrit.inscriptions.values_list("cohorte_id", flat=True)
            self.fields["cohorte"].queryset = Cohorte.objects.exclude(
                pk__in=already
            ).select_related("certification")
            self.fields["cohorte"].label_from_instance = (
                lambda obj: f"{obj.certification.nom} — {obj.nom}"
            )


class ChangerStatutForm(forms.ModelForm):
    class Meta:
        model = Inscription
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
            "inscription": "Inscription (Inscrit — Cohorte)",
            "montant": "Montant (FCFA)",
            "date_paiement": "Date du paiement",
            "moyen_paiement": "Moyen de paiement",
            "reference": "Référence / N° de transaction",
            "notes": "Notes",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["inscription"].queryset = (
            Inscription.objects.select_related("inscrit", "cohorte__certification")
            .order_by("inscrit__nom", "inscrit__prenom")
        )
        self.fields["inscription"].label_from_instance = (
            lambda obj: f"{obj.inscrit.prenom} {obj.inscrit.nom} — {obj.cohorte}"
        )


class PaiementInscriptionForm(forms.ModelForm):
    """Payment form pre-linked to an Inscription."""

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
    cohorte = forms.ModelChoiceField(
        queryset=Cohorte.objects.select_related("certification").order_by("certification__nom", "nom"),
        label="Cohorte cible",
        help_text="Les inscrits importés seront inscrits à cette cohorte.",
        widget=forms.Select(attrs={"class": "form-select"}),
        empty_label="— Sélectionner une cohorte —",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cohorte"].label_from_instance = (
            lambda obj: f"{obj.certification.nom} — {obj.nom}"
        )


class UserForm(forms.ModelForm):
    password = forms.CharField(
        label="Mot de passe",
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
        required=False,
        help_text="Laisser vide pour ne pas changer le mot de passe.",
    )

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "is_staff", "is_superuser"]
        widgets = {
            "username": forms.TextInput(attrs={"class": "form-control"}),
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "is_staff": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_superuser": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "username": "Nom d'utilisateur",
            "first_name": "Prénom",
            "last_name": "Nom",
            "email": "Email",
            "is_staff": "Accès admin (chargé de certifications)",
            "is_superuser": "Super administrateur",
        }

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get("password")
        if password:
            user.set_password(password)
        if commit:
            user.save()
        return user
