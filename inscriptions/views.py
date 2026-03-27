from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.db.models import Sum, Count, Q
from django.utils import timezone
import openpyxl

from .models import Inscrit, Paiement
from .forms import InscritForm, PaiementForm, ImportExcelForm, PaiementInscritForm


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def dashboard(request):
    nb_inscrits = Inscrit.objects.count()
    nb_paiements = Paiement.objects.count()
    total_encaisse = Paiement.objects.aggregate(total=Sum('montant'))['total'] or 0
    inscrits_recents = Inscrit.objects.order_by('-date_inscription')[:5]
    paiements_recents = Paiement.objects.select_related('inscrit').order_by('-date_paiement', '-created_at')[:5]

    # Stats par moyen de paiement
    stats_moyens = (
        Paiement.objects
        .values('moyen_paiement')
        .annotate(total=Sum('montant'), count=Count('id'))
        .order_by('-total')
    )

    context = {
        'nb_inscrits': nb_inscrits,
        'nb_paiements': nb_paiements,
        'total_encaisse': total_encaisse,
        'inscrits_recents': inscrits_recents,
        'paiements_recents': paiements_recents,
        'stats_moyens': stats_moyens,
        'active_page': 'dashboard',
    }
    return render(request, 'inscriptions/dashboard.html', context)


# ---------------------------------------------------------------------------
# Inscrits
# ---------------------------------------------------------------------------

def inscrits_list(request):
    query = request.GET.get('q', '')
    activite_filter = request.GET.get('activite', '')
    source_filter = request.GET.get('source', '')

    inscrits = Inscrit.objects.prefetch_related('paiements').order_by('-date_inscription')

    if query:
        inscrits = inscrits.filter(
            Q(nom__icontains=query) |
            Q(prenom__icontains=query) |
            Q(email__icontains=query) |
            Q(telephone__icontains=query) |
            Q(activite__icontains=query)
        )

    if activite_filter:
        inscrits = inscrits.filter(activite__icontains=activite_filter)

    if source_filter:
        inscrits = inscrits.filter(source=source_filter)

    # List of unique activites for filter dropdown
    activites = Inscrit.objects.values_list('activite', flat=True).distinct().order_by('activite')

    context = {
        'inscrits': inscrits,
        'query': query,
        'activite_filter': activite_filter,
        'source_filter': source_filter,
        'activites': activites,
        'active_page': 'inscrits',
    }
    return render(request, 'inscriptions/inscrits_list.html', context)


def inscrit_detail(request, pk):
    inscrit = get_object_or_404(Inscrit, pk=pk)
    paiements = inscrit.paiements.order_by('-date_paiement')
    form = PaiementInscritForm(initial={'date_paiement': timezone.now().date()})

    context = {
        'inscrit': inscrit,
        'paiements': paiements,
        'form': form,
        'active_page': 'inscrits',
    }
    return render(request, 'inscriptions/inscrit_detail.html', context)


def inscrit_ajouter(request):
    if request.method == 'POST':
        form = InscritForm(request.POST)
        if form.is_valid():
            inscrit = form.save(commit=False)
            inscrit.source = 'manuel'
            inscrit.save()
            messages.success(request, f'Inscrit "{inscrit}" ajouté avec succès.')
            return redirect('inscrit_detail', pk=inscrit.pk)
    else:
        form = InscritForm()

    context = {
        'form': form,
        'titre': 'Ajouter un inscrit',
        'action': 'Ajouter',
        'active_page': 'inscrits',
    }
    return render(request, 'inscriptions/inscrit_form.html', context)


def inscrit_modifier(request, pk):
    inscrit = get_object_or_404(Inscrit, pk=pk)
    if request.method == 'POST':
        form = InscritForm(request.POST, instance=inscrit)
        if form.is_valid():
            form.save()
            messages.success(request, f'Inscrit "{inscrit}" modifié avec succès.')
            return redirect('inscrit_detail', pk=inscrit.pk)
    else:
        form = InscritForm(instance=inscrit)

    context = {
        'form': form,
        'inscrit': inscrit,
        'titre': f'Modifier : {inscrit}',
        'action': 'Enregistrer',
        'active_page': 'inscrits',
    }
    return render(request, 'inscriptions/inscrit_form.html', context)


def inscrit_supprimer(request, pk):
    inscrit = get_object_or_404(Inscrit, pk=pk)
    if request.method == 'POST':
        nom = str(inscrit)
        inscrit.delete()
        messages.success(request, f'Inscrit "{nom}" supprimé avec succès.')
        return redirect('inscrits_list')

    context = {
        'inscrit': inscrit,
        'active_page': 'inscrits',
    }
    return render(request, 'inscriptions/inscrit_confirm_delete.html', context)


# ---------------------------------------------------------------------------
# Import Excel
# ---------------------------------------------------------------------------

COLUMN_ALIASES = {
    'nom': ['nom', 'name', 'last_name', 'lastname', 'family_name'],
    'prenom': ['prenom', 'prénom', 'first_name', 'firstname', 'given_name'],
    'email': ['email', 'e-mail', 'mail', 'courriel', 'adresse_email'],
    'telephone': ['telephone', 'téléphone', 'tel', 'phone', 'mobile', 'portable'],
    'activite': ['activite', 'activité', 'formation', 'certification', 'programme', 'cours'],
}


def _normalize_header(header):
    """Normalize a column header for matching."""
    if header is None:
        return ''
    return str(header).lower().strip().replace(' ', '_').replace('-', '_')


def _map_columns(headers):
    """Map spreadsheet column indices to model field names."""
    mapping = {}
    normalized = [_normalize_header(h) for h in headers]
    for field, aliases in COLUMN_ALIASES.items():
        for i, norm in enumerate(normalized):
            if norm in aliases:
                mapping[field] = i
                break
    return mapping


def import_excel(request):
    if request.method == 'POST':
        form = ImportExcelForm(request.POST, request.FILES)
        if form.is_valid():
            fichier = request.FILES['fichier']

            try:
                wb = openpyxl.load_workbook(fichier, read_only=True, data_only=True)
                ws = wb.active

                rows = list(ws.iter_rows(values_only=True))
                if not rows:
                    messages.error(request, 'Le fichier est vide.')
                    return render(request, 'inscriptions/import_excel.html', {'form': form, 'active_page': 'inscrits'})

                headers = rows[0]
                col_map = _map_columns(headers)

                required = ['nom', 'prenom', 'email']
                missing = [f for f in required if f not in col_map]
                if missing:
                    messages.error(
                        request,
                        f'Colonnes obligatoires manquantes : {", ".join(missing)}. '
                        f'Colonnes trouvées : {", ".join(str(h) for h in headers if h)}'
                    )
                    return render(request, 'inscriptions/import_excel.html', {'form': form, 'active_page': 'inscrits'})

                created = 0
                updated = 0
                errors = []

                for row_idx, row in enumerate(rows[1:], start=2):
                    try:
                        nom = str(row[col_map['nom']] or '').strip()
                        prenom = str(row[col_map['prenom']] or '').strip()
                        email = str(row[col_map['email']] or '').strip().lower()

                        if not nom or not prenom or not email:
                            errors.append(f'Ligne {row_idx}: données manquantes (nom, prénom ou email vide).')
                            continue

                        telephone = ''
                        if 'telephone' in col_map and row[col_map['telephone']]:
                            telephone = str(row[col_map['telephone']]).strip()

                        activite = ''
                        if 'activite' in col_map and row[col_map['activite']]:
                            activite = str(row[col_map['activite']]).strip()

                        inscrit, was_created = Inscrit.objects.update_or_create(
                            email=email,
                            defaults={
                                'nom': nom,
                                'prenom': prenom,
                                'telephone': telephone,
                                'activite': activite,
                                'source': 'excel',
                            }
                        )
                        if was_created:
                            created += 1
                        else:
                            updated += 1

                    except Exception as e:
                        errors.append(f'Ligne {row_idx}: erreur — {e}')

                wb.close()

                if created or updated:
                    messages.success(
                        request,
                        f'Import terminé : {created} inscrit(s) créé(s), {updated} mis à jour.'
                    )
                if errors:
                    for err in errors[:10]:
                        messages.warning(request, err)
                    if len(errors) > 10:
                        messages.warning(request, f'... et {len(errors) - 10} autres erreurs.')

                return redirect('inscrits_list')

            except Exception as e:
                messages.error(request, f'Erreur lors de la lecture du fichier : {e}')

    else:
        form = ImportExcelForm()

    context = {
        'form': form,
        'active_page': 'inscrits',
    }
    return render(request, 'inscriptions/import_excel.html', context)


# ---------------------------------------------------------------------------
# Paiements
# ---------------------------------------------------------------------------

def paiements_list(request):
    query = request.GET.get('q', '')
    moyen_filter = request.GET.get('moyen', '')

    paiements = Paiement.objects.select_related('inscrit').order_by('-date_paiement', '-created_at')

    if query:
        paiements = paiements.filter(
            Q(inscrit__nom__icontains=query) |
            Q(inscrit__prenom__icontains=query) |
            Q(inscrit__email__icontains=query) |
            Q(reference__icontains=query)
        )

    if moyen_filter:
        paiements = paiements.filter(moyen_paiement=moyen_filter)

    total_filtre = paiements.aggregate(total=Sum('montant'))['total'] or 0

    context = {
        'paiements': paiements,
        'query': query,
        'moyen_filter': moyen_filter,
        'moyen_choices': Paiement.MOYEN_CHOICES,
        'total_filtre': total_filtre,
        'active_page': 'paiements',
    }
    return render(request, 'inscriptions/paiements_list.html', context)


def paiement_ajouter(request):
    inscrit_pk = request.GET.get('inscrit')
    initial = {'date_paiement': timezone.now().date()}

    if request.method == 'POST':
        form = PaiementForm(request.POST)
        if form.is_valid():
            paiement = form.save()
            messages.success(request, f'Paiement de {paiement.montant} FCFA enregistré.')
            next_url = request.POST.get('next', '')
            if next_url:
                return redirect(next_url)
            return redirect('inscrit_detail', pk=paiement.inscrit.pk)
    else:
        if inscrit_pk:
            initial['inscrit'] = inscrit_pk
        form = PaiementForm(initial=initial)

    context = {
        'form': form,
        'titre': 'Ajouter un paiement',
        'action': 'Enregistrer',
        'active_page': 'paiements',
    }
    return render(request, 'inscriptions/paiement_form.html', context)


def paiement_ajouter_pour_inscrit(request, pk):
    """Add payment directly from inscrit detail page."""
    inscrit = get_object_or_404(Inscrit, pk=pk)
    if request.method == 'POST':
        form = PaiementInscritForm(request.POST)
        if form.is_valid():
            paiement = form.save(commit=False)
            paiement.inscrit = inscrit
            paiement.save()
            messages.success(request, f'Paiement de {paiement.montant} FCFA enregistré.')
        else:
            messages.error(request, 'Erreur dans le formulaire de paiement.')
    return redirect('inscrit_detail', pk=pk)


def paiement_modifier(request, pk):
    paiement = get_object_or_404(Paiement, pk=pk)
    if request.method == 'POST':
        form = PaiementForm(request.POST, instance=paiement)
        if form.is_valid():
            form.save()
            messages.success(request, 'Paiement modifié avec succès.')
            return redirect('inscrit_detail', pk=paiement.inscrit.pk)
    else:
        form = PaiementForm(instance=paiement)

    context = {
        'form': form,
        'paiement': paiement,
        'titre': f'Modifier le paiement',
        'action': 'Enregistrer',
        'active_page': 'paiements',
    }
    return render(request, 'inscriptions/paiement_form.html', context)


def paiement_supprimer(request, pk):
    paiement = get_object_or_404(Paiement, pk=pk)
    inscrit_pk = paiement.inscrit.pk
    if request.method == 'POST':
        montant = paiement.montant
        paiement.delete()
        messages.success(request, f'Paiement de {montant} FCFA supprimé.')
        return redirect('inscrit_detail', pk=inscrit_pk)

    context = {
        'paiement': paiement,
        'active_page': 'paiements',
    }
    return render(request, 'inscriptions/paiement_confirm_delete.html', context)
