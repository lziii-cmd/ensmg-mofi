#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input

# Réinitialise le schéma inscriptions si le schéma est obsolète (ex: colonnes manquantes)
python manage.py shell -c "
from django.db import connection
c = connection.cursor()
try:
    c.execute('SELECT tarif_etudiant FROM inscriptions_certification LIMIT 1')
    print('Schema OK — aucune réinitialisation nécessaire.')
except Exception:
    print('Schema obsolète détecté — réinitialisation...')
    for t in ['inscriptions_compteapprenant','inscriptions_attestation','inscriptions_paiement','inscriptions_inscription','inscriptions_inscrit','inscriptions_cohorte','inscriptions_certification']:
        c.execute(f'DROP TABLE IF EXISTS {t} CASCADE')
        print(f'  Table {t} supprimée.')
    try:
        c.execute(\"DELETE FROM django_migrations WHERE app = 'inscriptions'\")
        print('  Historique migrations nettoyé.')
    except Exception as e:
        print(f'  Note migrations: {e}')
"

python manage.py migrate
python manage.py shell -c "
from django.contrib.auth.models import User
# Nettoyer les anciens comptes admin (username différent)
for old in ['admin', 'admin@ensmg.com']:
    if User.objects.filter(username=old).exists():
        User.objects.filter(username=old).delete()
        print(f'Ancien compte {old} supprimé.')

if not User.objects.filter(username='admin@ensmg.sn').exists():
    User.objects.create_superuser('admin@ensmg.sn', 'admin@ensmg.sn', 'passer01')
    print('Superuser admin@ensmg.sn créé.')
else:
    u = User.objects.get(username='admin@ensmg.sn')
    u.email = 'admin@ensmg.sn'
    u.set_password('passer01')
    u.is_superuser = True
    u.is_staff = True
    u.save()
    print('Superuser admin@ensmg.sn mis à jour.')
"
