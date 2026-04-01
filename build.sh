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
# Migrate old admin account if exists
if User.objects.filter(username='admin').exists():
    u = User.objects.get(username='admin')
    u.username = 'admin@ensmg.com'
    u.email = 'admin@ensmg.sn'
    u.set_password('passer01')
    u.save()
    print('Ancien compte admin migré vers admin@ensmg.com')
elif not User.objects.filter(username='admin@ensmg.com').exists():
    User.objects.create_superuser('admin@ensmg.com', 'admin@ensmg.sn', 'passer01')
    print('Superuser admin@ensmg.com créé.')
else:
    print('Superuser admin@ensmg.com existe déjà.')
"
