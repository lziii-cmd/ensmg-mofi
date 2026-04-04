from django import forms
from django.contrib.auth.models import User, Group
from .models import Certification, Cohorte, Inscrit, Inscription, Paiement



class CertificationForm(forms.ModelForm):
    class Meta:
        model = Certification
        fields = [
            "nom", "description", "duree", "tarif_etudiant", "tarif_professionnel", "actif",
            "partenaire_nom", "partenaire_logo", "partenaire_titre_signataire",
        ]
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
            "partenaire_nom": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Ex: Université Cheikh Anta Diop",
            }),
            "partenaire_logo": forms.FileInput(attrs={"class": "form-control", "accept": "image/*"}),
            "partenaire_titre_signataire": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Ex: Le Recteur, Le Directeur...",
            }),
        }
        labels = {
            "nom": "Nom de la certification",
            "description": "Description",
            "duree": "Durée",
            "tarif_etudiant": "Tarif étudiant (FCFA)",
            "tarif_professionnel": "Tarif professionnel (FCFA)",
            "actif": "Certification active",
            "partenaire_nom": "Nom du partenaire",
            "partenaire_logo": "Logo du partenaire",
            "partenaire_titre_signataire": "Titre du signataire partenaire",
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
        fields = ["nom", "prenom", "email", "telephone", "activite", "universite", "entreprise", "notes"]
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
            "activite": forms.Select(attrs={
                "class": "form-select",
                "id": "id_activite",
            }),
            "universite": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Nom de l'université ou de l'école",
            }),
            "entreprise": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Nom de l'entreprise",
            }),
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
            "universite": "Université / École",
            "entreprise": "Entreprise",
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
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cohorte"].label_from_instance = (
            lambda obj: f"{obj.certification.nom} — {obj.nom}"
        )


class UserForm(forms.ModelForm):
    ROLE_CHOICES = [
        ("Super Utilisateur",    "Super Utilisateur — accès complet"),
        ("Responsable Scolarité","Responsable Scolarité — gestion certifications/inscrits/paiements"),
        ("Admin",                "Admin — gestion utilisateurs + audit"),
        ("Personnel Utilisateur","Personnel Utilisateur — lecture seule"),
    ]
    password = forms.CharField(
        label="Mot de passe",
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
        required=False,
        help_text="Laisser vide pour ne pas changer le mot de passe.",
    )
    role = forms.ChoiceField(
        label="Rôle",
        choices=ROLE_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
        required=False,
        initial="Personnel Utilisateur",
    )

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "is_active"]
        widgets = {
            "username": forms.TextInput(attrs={"class": "form-control"}),
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "username": "Nom d'utilisateur",
            "first_name": "Prénom",
            "last_name": "Nom",
            "email": "Email",
            "is_active": "Compte actif",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            if self.instance.is_superuser:
                self.fields["role"].initial = "Super Utilisateur"
            elif self.instance.groups.filter(name="Responsable Scolarité").exists():
                self.fields["role"].initial = "Responsable Scolarité"
            elif self.instance.groups.filter(name="Admin").exists():
                self.fields["role"].initial = "Admin"
            else:
                self.fields["role"].initial = "Personnel Utilisateur"

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get("password")
        if password:
            user.set_password(password)
        role = self.cleaned_data.get("role", "Personnel Utilisateur")
        user.is_superuser = (role == "Super Utilisateur")
        # is_staff=True donne accès à /admin/ Django (Super Utilisateur + Admin seulement)
        user.is_staff = (role in ("Super Utilisateur", "Admin"))
        if commit:
            user.save()
            user.groups.clear()
            if role in ("Responsable Scolarité", "Admin", "Personnel Utilisateur"):
                group, _ = Group.objects.get_or_create(name=role)
                user.groups.add(group)
        return user


# ---------------------------------------------------------------------------
# Portail / Wizard forms
# ---------------------------------------------------------------------------

class WizardStep1Form(forms.Form):
    """Étape 1 : informations personnelles"""
    nom = forms.CharField(
        label="Nom",
        max_length=100,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Nom de famille"}),
    )
    prenom = forms.CharField(
        label="Prénom",
        max_length=100,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Prénom"}),
    )
    email = forms.EmailField(
        label="Email personnel",
        widget=forms.EmailInput(attrs={"class": "form-control", "placeholder": "votre@email.com"}),
    )
    telephone = forms.CharField(
        label="Téléphone",
        max_length=30,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "+221 77 000 00 00"}),
    )
    adresse = forms.CharField(
        label="Adresse",
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Votre adresse"}),
    )


class WizardStep2Form(forms.Form):
    """Étape 2 : profil"""
    ACTIVITE_CHOICES = [
        ("etudiant", "Étudiant(e)"),
        ("professionnel", "Professionnel(le)"),
    ]
    activite = forms.ChoiceField(
        label="Profil",
        choices=ACTIVITE_CHOICES,
        widget=forms.RadioSelect(attrs={"class": "form-check-input"}),
    )
    universite = forms.CharField(
        label="Université / École",
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Nom de votre université"}),
    )
    entreprise = forms.CharField(
        label="Entreprise",
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Nom de votre entreprise"}),
    )


class WizardStep3Form(forms.Form):
    """Étape 3 : choix certification + cohorte"""
    certif_id = forms.IntegerField(widget=forms.HiddenInput(), required=False)
    cohorte = forms.ModelChoiceField(
        queryset=Cohorte.objects.filter(actif=True).select_related("certification").order_by(
            "certification__nom", "nom"
        ),
        label="Cohorte",
        empty_label="— Sélectionner une cohorte —",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cohorte"].label_from_instance = (
            lambda obj: f"{obj.certification.nom} — {obj.nom}"
        )


class ChangerMdpApprenantForm(forms.Form):
    """Formulaire de changement de mot de passe (première connexion)"""
    nouveau_mdp = forms.CharField(
        label="Nouveau mot de passe",
        min_length=6,
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": "Minimum 6 caractères"}
        ),
    )
    confirmation_mdp = forms.CharField(
        label="Confirmer le mot de passe",
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": "Répétez le mot de passe"}
        ),
    )

    def clean(self):
        cleaned = super().clean()
        mdp1 = cleaned.get("nouveau_mdp")
        mdp2 = cleaned.get("confirmation_mdp")
        if mdp1 and mdp2 and mdp1 != mdp2:
            raise forms.ValidationError("Les mots de passe ne correspondent pas.")
        return cleaned


class ProfilApprenantForm(forms.ModelForm):
    """Modification du profil apprenant"""

    class Meta:
        model = Inscrit
        fields = ["nom", "prenom", "email", "telephone", "adresse", "universite", "entreprise", "activite"]
        widgets = {
            "nom": forms.TextInput(attrs={"class": "form-control"}),
            "prenom": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "telephone": forms.TextInput(attrs={"class": "form-control"}),
            "adresse": forms.TextInput(attrs={"class": "form-control"}),
            "universite": forms.TextInput(attrs={"class": "form-control"}),
            "entreprise": forms.TextInput(attrs={"class": "form-control"}),
            "activite": forms.Select(attrs={"class": "form-select"}),
        }
