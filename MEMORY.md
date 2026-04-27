# MEMORY.md — Mémoire du projet

Dernière mise à jour : 2026-04-17

## CONTEXTE ACTUEL
- Où on en est : Session initiale — état des lieux complet effectué, SPEC.md créé
- Dernière fonctionnalité travaillée : aucune pour l'instant (exploration seule)
- Prochaine fonctionnalité prévue : à définir après validation du bilan
- Problèmes ouverts : voir Points de vigilance

## DÉCISIONS TECHNIQUES
| Date | Décision | Pourquoi | Alternative écartée |
|------|----------|----------|---------------------|
| 2026-04-17 | PDFs attestations stockés en BinaryField DB | Render free tier n'a pas de filesystem persistant | Stockage disque (perdrait fichiers au redeploy) |
| 2026-04-17 | JWT + Session auth en parallèle | JWT pour API REST, Session pour templates Django | JWT seul (templates nécessitent session) |

## CE QUI A ÉTÉ FAIT
| Date | Fonctionnalité | Statut | Notes |
|------|----------------|--------|-------|
| 2026-04-17 | MEMORY.md créé | stable | Fichier initial |
| 2026-04-17 | SPEC.md créé | stable | Rempli depuis codebase existante |
| — | Gestion certifications | stable | CRUD complet + logo partenaire |
| — | Gestion cohortes | stable | Associées à certification |
| — | Gestion inscrits | stable | Import Excel inclus |
| — | Inscriptions & statuts | stable | Workflow pré-inscrit → certifié |
| — | Paiements multi-moyens | stable | Wave, OM, InTouch, espèces, virement |
| — | Attestations PDF | stable | ReportLab + QR code vérification |
| — | Espace apprenant | stable | Dashboard + téléchargement attestation |
| — | Portail public | stable | Inscription + vérification attestation |
| — | API REST | stable | DRF + JWT + Swagger |
| — | Webhooks paiements | stable | Wave + OrangeMoney HMAC-SHA256 |
| — | Système de rôles | stable | 4 groupes + middleware |

## PROBLÈMES RENCONTRÉS & SOLUTIONS
| Date | Problème | Cause | Solution appliquée |
|------|----------|-------|--------------------|
| — | Fichiers media perdus au redeploy Render | Render free tier sans filesystem persistant | Stockage PDF en BinaryField |

## POINTS DE VIGILANCE
- **views.py fait 3626 lignes** : toute la logique métier est concentrée ici, fragile à modifier
- **Système de rôles dupliqué** : logique présente à la fois dans views.py et middleware.py → incohérence possible
- **Pas de tests** : aucune suite de tests formelle — les régressions ne sont pas détectées automatiquement
- **Media sur Render free** : logos partenaires peuvent être perdus au redeploy (PDFs attestations protégés par BinaryField)
- **Webhooks Wave/OrangeMoney** : non couverts par tests, flux de confirmation paiements critiques
- **6 migrations en cascade** : ralentit les fresh clones, squash à prévoir
- **Pas de rate limiting** sur l'API → vulnérable au brute-force

## DETTE TECHNIQUE EN COURS
| Priorité | Problème | Impact | Effort |
|----------|----------|--------|--------|
| CRITIQUE | Pas de tests unitaires/intégration | Régressions silencieuses | L |
| CRITIQUE | Pas de linting/formatage automatisé | Code inconsistant | S |
| IMPORTANT | Système de rôles dupliqué | Maintenance fragile | S |
| IMPORTANT | Pas de rate limiting API | Brute-force vulnérable | M |
| IMPORTANT | Properties Certification non cachées | Perf dégradée à scale | S |
| IMPORTANT | Migrations non squashées | Fresh clone lent | S |
| NICE-TO-HAVE | Pas de pages d'erreur 404/500 | UX dégradée | S |
| NICE-TO-HAVE | Génération PDF asynchrone | UX lors de bulk | M |

## NOTES DE SESSION
### 2026-04-17 — Session initiale
- Première ouverture du projet
- Exploration complète réalisée (35 fichiers Python, 54 templates HTML)
- MEMORY.md et SPEC.md créés depuis la codebase existante
- Aucune modification de code effectuée
- En attente de validation de l'état des lieux + bilan avant toute implémentation
