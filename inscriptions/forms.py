from django import forms
from .models import Inscrit, Paiement


class InscritForm(forms.ModelForm):
    class Meta:
        model = Inscrit
        fields = ['nom', 'prenom', 'email', 'telephone', 'activite', 'notes']
        widgets = {
            'nom': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nom de famille'
            }),
            'prenom': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Prénom'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'adresse@email.com'
            }),
            'telephone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '+221 77 000 00 00'
            }),
            'activite': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: Formation Python, Certification PMP...'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Notes ou informations complémentaires...'
            }),
        }
        labels = {
            'nom': 'Nom',
            'prenom': 'Prénom',
            'email': 'Adresse email',
            'telephone': 'Téléphone',
            'activite': 'Formation / Activité',
            'notes': 'Notes',
        }
        help_texts = {
            'email': 'Doit être unique dans le système.',
            'activite': 'Nom de la formation ou certification.',
        }


class PaiementForm(forms.ModelForm):
    class Meta:
        model = Paiement
        fields = ['inscrit', 'montant', 'date_paiement', 'moyen_paiement', 'reference', 'notes']
        widgets = {
            'inscrit': forms.Select(attrs={'class': 'form-select'}),
            'montant': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '0',
                'min': '0',
                'step': '1'
            }),
            'date_paiement': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'moyen_paiement': forms.Select(attrs={'class': 'form-select'}),
            'reference': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Numéro de transaction ou référence'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Notes complémentaires...'
            }),
        }
        labels = {
            'inscrit': 'Inscrit',
            'montant': 'Montant (FCFA)',
            'date_paiement': 'Date du paiement',
            'moyen_paiement': 'Moyen de paiement',
            'reference': 'Référence / N° de transaction',
            'notes': 'Notes',
        }


class PaiementInscritForm(forms.ModelForm):
    """Paiement form pre-linked to an inscrit (inscrit field hidden)."""
    class Meta:
        model = Paiement
        fields = ['montant', 'date_paiement', 'moyen_paiement', 'reference', 'notes']
        widgets = {
            'montant': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '0',
                'min': '0',
                'step': '1'
            }),
            'date_paiement': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'moyen_paiement': forms.Select(attrs={'class': 'form-select'}),
            'reference': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Numéro de transaction ou référence'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Notes complémentaires...'
            }),
        }
        labels = {
            'montant': 'Montant (FCFA)',
            'date_paiement': 'Date du paiement',
            'moyen_paiement': 'Moyen de paiement',
            'reference': 'Référence / N° de transaction',
            'notes': 'Notes',
        }


class ImportExcelForm(forms.Form):
    fichier = forms.FileField(
        label='Fichier Excel (.xlsx)',
        widget=forms.ClearableFileInput(attrs={
            'class': 'form-control',
            'accept': '.xlsx'
        }),
        help_text='Formats acceptés : .xlsx. Colonnes attendues : nom, prenom, email, telephone, activite'
    )
