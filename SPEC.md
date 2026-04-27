# SPEC.md — Spécifications du projet ENSMG MOFI

Dernière mise à jour : 2026-04-17

---

## 1. PRÉSENTATION DU PROJET

**Nom :** ENSMG MOFI
**Type :** Application web de gestion des certifications professionnelles
**Client :** ENSMG (École Nationale Supérieure de Management et de Gouvernance)
**Statut :** En production sur Render.com
**URL production :** [À COMPLÉTER]
**Description :** Plateforme centralisant le cycle complet de gestion des certifications : création de programmes, gestion des cohortes, inscription des apprenants, suivi des paiements (Wave, Orange Money, InTouch, espèces, virement), délivrance d'attestations PDF sécurisées avec QR code, et espace personnel apprenant.

---

## 2. STACK TECHNIQUE

### Langages & Frameworks
| Composant | Version | Rôle |
|-----------|---------|------|
| Python | 3.11 | Langage principal |
| Django | 4.2+ | Framework web |
| Django REST Framework | 3.15+ | API REST |
| djangorestframework-simplejwt | 5.3+ | Authentification JWT |
| drf-spectacular | 0.27+ | Documentation Swagger/OpenAPI auto |

### Base de données
| Environnement | BD |
|---------------|----|
| Développement | SQLite3 (db.sqlite3) |
| Production | PostgreSQL (Render.com managed) |

### Librairies métier
| Librairie | Version | Rôle |
|-----------|---------|------|
| ReportLab | 4.0+ | Génération PDF attestations |
| qrcode + Pillow | 7.4+ / 10.0+ | QR codes de vérification |
| openpyxl | 3.1+ | Import/export Excel inscrits |

### Infrastructure
| Composant | Outil |
|-----------|-------|
| Hébergement | Render.com (Web Service + PostgreSQL free tier) |
| WSGI Server | Gunicorn (2 workers, timeout 120s) |
| Static files | WhiteNoise (CompressedManifestStaticFilesStorage) |
| Gestionnaire de paquets | pip (requirements.txt) |

---

## 3. ARCHITECTURE

### Pattern
Django MVT standard (Model-View-Template) avec une couche API REST supplémentaire.

### Structure des dossiers
```
ensmg_mofi/               # Racine projet
├── manage.py             # CLI Django
├── requirements.txt      # Dépendances
├── render.yaml           # Config déploiement
├── ensmg_mofi/           # Package principal Django
│   ├── settings.py       # Configuration globale
│   ├── urls.py           # Routage principal
│   └── wsgi.py           # Point d'entrée WSGI
└── inscriptions/         # Application principale
    ├── models.py         # ORM (8 modèles)
    ├── views.py          # Logique métier + templates (3626 lignes)
    ├── api.py            # Endpoints REST (ViewSets)
    ├── serializers.py    # Sérialiseurs DRF
    ├── permissions.py    # Permissions par rôle
    ├── middleware.py     # Auth + rôles
    ├── forms.py          # Formulaires Django
    ├── notifications.py  # Emails automatiques
    ├── urls.py           # Routes web
    ├── api_urls.py       # Routes API
    ├── admin.py          # Admin panel
    ├── context_processors.py
    ├── templatetags/     # Filtres custom (fr_money, dict_filters)
    ├── templates/        # 54 templates HTML
    ├── migrations/       # 6 migrations
    └── management/commands/ # 5 commandes custom
```

### Modèle de données
```
Certification (nom, description, durée, tarifs étudiant/pro, actif, logo, partenaire)
  └─ Cohorte (nom, dates début/fin, actif) [N:1 → Certification]
       └─ Inscription (statut, montant_dû, notes) [N:1 → Cohorte]
            ├─ Inscrit (nom, prénom, email, téléphone, activité) [N:1 → Inscription]
            └─ Paiement (montant, moyen, date, statut, reçu_pdf) [1:N → Inscription]
                 └─ Attestation (numéro unique, date, contenu_pdf) [1:1 → Inscription]

CompteApprenant (user Django, inscrit, mdp_changé) [1:1 → Inscrit + User]
  └─ Notification (type, message, lu) [1:N → CompteApprenant]
```

**Statuts Inscription :**
`pre_inscrit` → `inscrit` → `en_formation` → `formation_terminee` → `certifie`

**Moyens Paiement :**
Wave, Orange Money, InTouch Sénégal, Carte bancaire, Espèces, Virement

---

## 4. FONCTIONNALITÉS

### 4.1 Gestion des Certifications [stable]
- Création, modification, suppression de programmes de certification
- Tarifs différenciés (étudiant / professionnel)
- Statut actif/inactif
- Logo + signataire partenaire optionnel
- Statistiques auto : nb inscrits, nb certifiés, nb cohortes, montant encaissé

### 4.2 Gestion des Cohortes [stable]
- Création, modification, suppression de cohortes par certification
- Dates début/fin
- Comptage auto inscrits/certifiés

### 4.3 Gestion des Inscrits [stable]
- CRUD complet (nom, prénom, email, téléphone, activité)
- Import en masse via fichier Excel (openpyxl)
- Tracking source : manuel, Excel, portail public
- Création auto d'un CompteApprenant à l'inscription

### 4.4 Inscriptions & Workflow [stable]
- Création d'inscriptions liant un inscrit à une cohorte
- Workflow de statuts : pré-inscrit → inscrit → en formation → certifié
- Montant dû configurable par inscription
- Calculs automatiques : total payé, reste à payer, pourcentage réglé
- Notes libres par inscription

### 4.5 Paiements [stable]
- Enregistrement paiements multi-moyens
- Génération reçu PDF par paiement
- Suivi statut (en attente, confirmé, annulé)
- Webhooks de confirmation externe : Wave, Orange Money (HMAC-SHA256)

### 4.6 Attestations PDF [stable]
- Génération PDF professionnel (ReportLab) à la certification
- Numérotation séquentielle : `CERT-ENSMG-MOFI-AAAA-NNN`
- QR code intégré pour vérification (qrcode + pillow)
- Stockage en BinaryField (persistance sur Render)
- Téléchargement direct PDF
- Page publique de vérification (par numéro ou QR code)

### 4.7 Espace Apprenant [stable]
- Dashboard personnel (inscriptions, statuts)
- Téléchargement de ses attestations
- Notifications internes
- Gestion profil + changement mot de passe
- Changement de mot de passe obligatoire à la 1ère connexion (middleware)

### 4.8 Portail Public [stable]
- Inscription en ligne (wizard multi-étapes)
- Vérification d'attestation (sans authentification)
- Accessible sans compte

### 4.9 Dashboard Administratif [stable]
- Vue synthétique par certification (inscrits, certifiés, revenus)
- Filtres par certification et cohorte
- Accès conditionnel selon le rôle

### 4.10 API REST [stable]
- Endpoints complets sur toutes les entités (CRUD)
- Authentification JWT (access 8h, refresh 7j, rotation)
- Documentation Swagger auto (drf-spectacular)
- Pagination (50 items/page)

### 4.11 Gestion des Utilisateurs & Rôles [stable]
**4 groupes d'accès :**
| Groupe | Droits |
|--------|--------|
| Super Utilisateur | Accès complet à tout |
| Responsable Scolarité | Certifications, inscrits, paiements, attestations (pas gestion users) |
| Admin | Gestion users + inscrits basiques |
| Personnel Utilisateur | Lecture seule (GET uniquement) |

---

## 5. ENDPOINTS API

| Endpoint | Méthodes | Auth |
|----------|----------|------|
| `/api/certifications/` | GET/POST/PUT/DELETE | JWT |
| `/api/cohortes/` | GET/POST/PUT/DELETE | JWT |
| `/api/inscrits/` | GET/POST/PUT/DELETE | JWT |
| `/api/inscriptions/` | GET/POST/PUT/DELETE | JWT |
| `/api/paiements/` | GET/POST/PUT/DELETE | JWT |
| `/api/attestations/` | GET/POST/PUT/DELETE | JWT |
| `/api/utilisateurs/` | GET/POST/PUT/DELETE | JWT (Admin+) |
| `/api/auth/token/` | POST | — |
| `/api/auth/token/refresh/` | POST | JWT Refresh |
| `/api/auth/me/` | GET | JWT |
| `/api/webhooks/wave/` | POST | HMAC-SHA256 |
| `/api/webhooks/orange-money/` | POST | HMAC-SHA256 |
| `/api/docs/` | GET | — (Swagger UI) |
| `/api/redoc/` | GET | — (ReDoc) |

---

## 6. VARIABLES D'ENVIRONNEMENT

| Variable | Requis | Description |
|----------|--------|-------------|
| `SECRET_KEY` | Oui | Clé secrète Django (auto-générée par Render) |
| `DEBUG` | Oui | `False` en production |
| `DATABASE_URL` | Oui | URL PostgreSQL (fournie par Render) |
| `ALLOWED_HOSTS` | Oui | `.onrender.com` en production |
| `BOOTSTRAP_KEY` | Oui | Clé création premier admin (`ensmg2025`) |
| `REGISTER_KEY` | Oui | Clé auto-inscription via portail |
| `EMAIL_HOST_USER` | Non | Gmail SMTP sender |
| `EMAIL_HOST_PASSWORD` | Non | Mot de passe app Gmail |
| `WAVE_API_KEY` | Non | Clé API Wave paiements |
| `WAVE_WEBHOOK_SECRET` | Non | Secret vérification webhooks Wave |
| `PAYTECH_API_KEY` | Non | Clé API PayTech |
| `PAYTECH_API_SECRET` | Non | Secret PayTech |

---

## 7. CONVENTIONS

### Nommage
- **Python** : snake_case (PEP 8)
- **Templates HTML** : kebab-case (`certification_list.html`)
- **Models** : Noms en français avec `verbose_name`
- **Variables et fonctions** : Noms français dans le code

### Patterns établis
- **Décorateurs de vues** : `@admin_required`, `@users_required`, `@write_required` (définis dans views.py)
- **Filtre template** : `{{ value|fr_money }}` pour montants FCFA
- **Context processor** : Certifications actives + rôle user injectés globalement
- **Sérialiseurs DRF** : Méthodes séparées `create()` / `update()` + validation custom
- **Propriétés calculées** : `@property` sur models (pas de caching actuellement)

### Tests
- [À COMPLÉTER] Aucune suite de tests existante — à créer avec pytest-django

### Linting
- [À COMPLÉTER] Aucun outil configuré — à mettre en place (Black, flake8, isort)

---

## 8. SCORE DE SANTÉ

Évalué le 2026-04-17 (session initiale).

| Axe | Note | Justification |
|-----|------|---------------|
| Architecture | 7/10 | MVT propre, API séparée, mais views.py trop gros (3626 L) |
| Qualité code | 5/10 | Conventions cohérentes, mais pas de tests et rôles dupliqués |
| Tests | 1/10 | Aucun test formel détecté |
| Sécurité | 7/10 | JWT, CSRF, HMAC webhooks, mais pas de rate limiting |
| Performance | 6/10 | Indexes DB, pagination, mais properties non cachées |
| Maintenabilité | 5/10 | views.py monolithique, rôles en deux endroits |
| Infrastructure | 7/10 | Render.com adapté, pas de CI/CD, media non persistant |
| **Global** | **5.4/10** | Fonctionnel en production, risques maintenabilité moyen terme |

---

## 9. PLAN D'AMÉLIORATION

### CRITIQUE — Traiter avant nouvelles fonctionnalités
| Problème | Solution proposée | Effort |
|----------|-------------------|--------|
| Pas de tests | Ajouter pytest-django + tests critiques | L |
| Pas de linting | Black + flake8 + isort + pre-commit hooks | S |
| Système de rôles dupliqué | Extraire en utility unique centralisée | S |
| Pas de rate limiting | Ajouter django-ratelimit sur API + login | M |

### IMPORTANT — À planifier prochains sprints
| Problème | Solution proposée | Effort |
|----------|-------------------|--------|
| Properties non cachées | @cached_property ou DB count | S |
| Migrations non squashées | Squash après stabilisation | S |
| Media logos partenaires non persistant | S3 ou Azure Blob pour media | M |
| CI/CD absent | GitHub Actions : tests + deploy | M |

### NICE TO HAVE
| Problème | Solution proposée | Effort |
|----------|-------------------|--------|
| Pages 404/500 absentes | Créer templates d'erreur | S |
| PDF asynchrone | Celery + Redis pour bulk | M |
| Webhooks non testés | Tests fonctionnels mocks | M |

---

## 10. COMMANDES UTILES

```bash
# Développement
python manage.py runserver

# Migrations
python manage.py makemigrations
python manage.py migrate

# Admin initial
python manage.py create_admin

# Données de test
python manage.py seed_data

# Reset base (dev seulement)
python manage.py reset_db

# Collecte statiques
python manage.py collectstatic

# Déploiement (Render.com)
# Automatique au push selon render.yaml
```

---

## 11. LIENS UTILES

- **Render.com dashboard :** [À COMPLÉTER]
- **URL de production :** [À COMPLÉTER]
- **Documentation API Swagger :** [URL prod]/api/docs/
- **Cahier des charges :** `Nouveau dossier/CAHIER_DES_CHARGES.md`
