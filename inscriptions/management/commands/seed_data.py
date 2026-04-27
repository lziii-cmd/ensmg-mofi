"""
Management command: python manage.py seed_data
Crée 8 certifications avec cohortes, inscrits et paiements de test.
"""

import random
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand

from inscriptions.models import Certification, Cohorte, Inscription, Inscrit, Paiement, TypeTarif

CERTIFICATIONS = [
    {
        "nom": "Management de Projet (MOFI)",
        "description": "Formation complète en gestion de projet selon les standards PMI et Prince2.",  # noqa: E501
        "duree": "4 mois",
        "tarif_etudiant": Decimal("150000"),
        "tarif_professionnel": Decimal("350000"),
    },
    {
        "nom": "Marketing Digital",
        "description": "Stratégies digitales, SEO, réseaux sociaux et analytics.",
        "duree": "3 mois",
        "tarif_etudiant": Decimal("120000"),
        "tarif_professionnel": Decimal("280000"),
    },
    {
        "nom": "Finance d'Entreprise",
        "description": "Analyse financière, budgétisation et gestion de trésorerie.",
        "duree": "5 mois",
        "tarif_etudiant": Decimal("180000"),
        "tarif_professionnel": Decimal("420000"),
    },
    {
        "nom": "Data Science & Intelligence Artificielle",
        "description": "Python, Machine Learning, Deep Learning et visualisation de données.",
        "duree": "6 mois",
        "tarif_etudiant": Decimal("200000"),
        "tarif_professionnel": Decimal("500000"),
    },
    {
        "nom": "Gestion des Ressources Humaines",
        "description": "Recrutement, droit du travail, gestion de la paie et développement RH.",
        "duree": "3 mois",
        "tarif_etudiant": Decimal("100000"),
        "tarif_professionnel": Decimal("250000"),
    },
    {
        "nom": "Leadership & Management",
        "description": "Développement du leadership, management d'équipes et communication.",
        "duree": "2 mois",
        "tarif_etudiant": Decimal("80000"),
        "tarif_professionnel": Decimal("200000"),
    },
    {
        "nom": "Comptabilité et Audit",
        "description": "Normes SYSCOHADA, IFRS, audit interne et contrôle de gestion.",
        "duree": "4 mois",
        "tarif_etudiant": Decimal("160000"),
        "tarif_professionnel": Decimal("380000"),
    },
    {
        "nom": "Entrepreneuriat & Innovation",
        "description": "Business plan, financement, lean startup et gestion de l'innovation.",
        "duree": "3 mois",
        "tarif_etudiant": Decimal("0"),  # Gratuit pour étudiants
        "tarif_professionnel": Decimal("150000"),
    },
]
# NOTE: tarif_etudiant/tarif_professionnel are kept in the dict above only for seed
# purposes — they are migrated into TypeTarif objects below.

COHORTES_PAR_CERTIF = [
    # (nom, date_debut, date_fin)
    [
        ("Session Janvier 2024", date(2024, 1, 15), date(2024, 5, 15)),
        ("Session Septembre 2024", date(2024, 9, 2), date(2025, 1, 15)),
        ("Session Janvier 2025", date(2025, 1, 13), date(2025, 5, 30)),
    ],
    [
        ("Promo Mars 2024", date(2024, 3, 1), date(2024, 6, 30)),
        ("Promo Octobre 2024", date(2024, 10, 7), date(2025, 1, 31)),
    ],
    [
        ("Cohorte 1 - 2024", date(2024, 2, 1), date(2024, 7, 31)),
        ("Cohorte 2 - 2024", date(2024, 8, 5), date(2025, 1, 31)),
        ("Cohorte 1 - 2025", date(2025, 2, 3), date(2025, 7, 31)),
    ],
    [
        ("Batch Avril 2024", date(2024, 4, 1), date(2024, 10, 31)),
        ("Batch Novembre 2024", date(2024, 11, 4), date(2025, 5, 30)),
    ],
    [
        ("Session Juin 2024", date(2024, 6, 3), date(2024, 9, 30)),
        ("Session Janvier 2025", date(2025, 1, 6), date(2025, 4, 30)),
    ],
    [
        ("Promo Mai 2024", date(2024, 5, 6), date(2024, 7, 31)),
        ("Promo Février 2025", date(2025, 2, 10), date(2025, 4, 30)),
    ],
    [
        ("Session Juillet 2024", date(2024, 7, 1), date(2024, 11, 30)),
        ("Session Mars 2025", date(2025, 3, 3), date(2025, 7, 31)),
    ],
    [
        ("Batch Août 2024", date(2024, 8, 1), date(2024, 11, 30)),
        ("Batch Janvier 2025", date(2025, 1, 20), date(2025, 4, 30)),
    ],
]

INSCRITS_DATA = [
    ("Diallo", "Mamadou", "mamadou.diallo@gmail.com", "+221 77 123 45 67", "etudiant"),
    ("Ndiaye", "Fatou", "fatou.ndiaye@yahoo.fr", "+221 78 987 65 43", "professionnel"),
    ("Sow", "Ibrahima", "ibrahima.sow@gmail.com", "+221 76 555 44 33", "etudiant"),
    ("Ba", "Aissatou", "aissatou.ba@hotmail.com", "+221 77 321 98 76", "professionnel"),
    ("Fall", "Oumar", "oumar.fall@ensmg.sn", "+221 70 444 55 66", "etudiant"),
    ("Camara", "Mariama", "mariama.camara@gmail.com", "+221 77 654 32 10", "professionnel"),
    ("Toure", "Aliou", "aliou.toure@gmail.com", "+221 78 111 22 33", "etudiant"),
    ("Coulibaly", "Kadiatou", "kadiatou.coulibaly@yahoo.fr", "+221 76 222 33 44", "professionnel"),
    ("Traore", "Seydou", "seydou.traore@gmail.com", "+221 77 333 44 55", "etudiant"),
    ("Keita", "Rokhaya", "rokhaya.keita@gmail.com", "+221 70 444 55 66", "etudiant"),
    ("Mbaye", "Cheikh", "cheikh.mbaye@gmail.com", "+221 77 555 66 77", "professionnel"),
    ("Sarr", "Aminata", "aminata.sarr@gmail.com", "+221 78 666 77 88", "etudiant"),
    ("Gueye", "Moussa", "moussa.gueye@gmail.com", "+221 76 777 88 99", "professionnel"),
    ("Diouf", "Ndeye", "ndeye.diouf@gmail.com", "+221 77 888 99 00", "etudiant"),
    ("Faye", "Pape", "pape.faye@gmail.com", "+221 70 999 00 11", "professionnel"),
    ("Sy", "Coumba", "coumba.sy@gmail.com", "+221 77 100 20 30", "etudiant"),
    ("Diop", "Abdoulaye", "abdoulaye.diop@yahoo.fr", "+221 78 200 30 40", "professionnel"),
    ("Cisse", "Marieme", "marieme.cisse@gmail.com", "+221 76 300 40 50", "etudiant"),
    ("Thiam", "Babacar", "babacar.thiam@gmail.com", "+221 77 400 50 60", "professionnel"),
    ("Wade", "Sokhna", "sokhna.wade@gmail.com", "+221 70 500 60 70", "etudiant"),
    ("Diagne", "Lamine", "lamine.diagne@gmail.com", "+221 77 600 70 80", "professionnel"),
    ("Samb", "Khadija", "khadija.samb@gmail.com", "+221 78 700 80 90", "etudiant"),
    ("Mendy", "Tidiane", "tidiane.mendy@gmail.com", "+221 76 800 90 00", "professionnel"),
    ("Badji", "Fatoumata", "fatoumata.badji@gmail.com", "+221 77 900 10 20", "etudiant"),
    ("Diatta", "Modou", "modou.diatta@gmail.com", "+221 70 010 20 30", "professionnel"),
    ("Ndour", "Binta", "binta.ndour@gmail.com", "+221 77 020 30 40", "etudiant"),
    ("Bassene", "Serigne", "serigne.bassene@gmail.com", "+221 78 030 40 50", "professionnel"),
    ("Dieme", "Awa", "awa.dieme@gmail.com", "+221 76 040 50 60", "etudiant"),
    ("Manga", "Elhadji", "elhadji.manga@gmail.com", "+221 77 050 60 70", "professionnel"),
    ("Sonko", "Yaye", "yaye.sonko@gmail.com", "+221 70 060 70 80", "etudiant"),
    ("Balde", "Ibou", "ibou.balde@gmail.com", "+221 77 070 80 90", "professionnel"),
    ("Kouyate", "Mariam", "mariam.kouyate@gmail.com", "+221 78 080 90 00", "etudiant"),
    ("Diakite", "Mamou", "mamou.diakite@yahoo.fr", "+221 76 090 00 11", "professionnel"),
    ("Fofana", "Ousmane", "ousmane.fofana@gmail.com", "+221 77 110 21 31", "etudiant"),
    ("Conde", "Alpha", "alpha.conde@gmail.com", "+221 70 220 32 42", "professionnel"),
    ("Barry", "Hawa", "hawa.barry@gmail.com", "+221 77 330 43 53", "etudiant"),
    ("Bah", "Thierno", "thierno.bah@gmail.com", "+221 78 440 54 64", "professionnel"),
    ("Camara", "Aissata", "aissata.camara@gmail.com", "+221 76 550 65 75", "etudiant"),
    ("Tounkara", "Boubacar", "boubacar.tounkara@gmail.com", "+221 77 660 76 86", "professionnel"),
    ("Keita", "Fatoumata", "fatoumata.keita@gmail.com", "+221 70 770 87 97", "etudiant"),
]

STATUTS = [
    "inscrit",
    "en_formation",
    "en_formation",
    "formation_terminee",
    "certifie",
    "certifie",
    "abandon",
]

# Payment modes per certification (some single, some multiple)
PAIEMENT_MODES = [
    ["wave"],  # Certif 1 - paiement unique Wave
    ["orange_money"],  # Certif 2 - paiement unique Orange Money
    ["especes"],  # Certif 3 - paiement unique Espèces
    ["virement"],  # Certif 4 - paiement unique Virement
    ["wave", "orange_money"],  # Certif 5 - Wave + Orange Money
    ["wave", "especes", "orange_money"],  # Certif 6 - Wave + Espèces + Orange Money
    ["virement", "especes"],  # Certif 7 - Virement + Espèces
    ["wave", "orange_money", "especes", "virement"],  # Certif 8 - tous les moyens
]


class Command(BaseCommand):
    help = "Crée des données de test : 8 certifications, cohortes, inscrits et paiements."

    def handle(self, *args, **options):
        self.stdout.write("Création des données de test...")

        # Créer les inscrits
        inscrits = []
        for nom, prenom, email, tel, activite in INSCRITS_DATA:
            inscrit, _ = Inscrit.objects.get_or_create(
                email=email,
                defaults={
                    "nom": nom,
                    "prenom": prenom,
                    "telephone": tel,
                    "activite": activite,
                    "source": "manuel",
                },
            )
            inscrits.append(inscrit)
        self.stdout.write(f"  {len(inscrits)} inscrits créés.")

        # Créer les certifications, cohortes et inscriptions
        random.seed(42)
        total_inscriptions = 0
        total_paiements = 0

        for i, cert_data in enumerate(CERTIFICATIONS):
            cert, _ = Certification.objects.get_or_create(
                nom=cert_data["nom"],
                defaults={
                    "description": cert_data["description"],
                    "duree": cert_data["duree"],
                    "actif": True,
                },
            )
            # Créer les types de tarif si pas encore présents
            tt_etu, _ = TypeTarif.objects.get_or_create(
                certification=cert,
                nom="Étudiant",
                defaults={"montant": cert_data["tarif_etudiant"], "actif": True},
            )
            tt_pro, _ = TypeTarif.objects.get_or_create(
                certification=cert,
                nom="Professionnel",
                defaults={"montant": cert_data["tarif_professionnel"], "actif": True},
            )

            modes = PAIEMENT_MODES[i]
            cohortes_info = COHORTES_PAR_CERTIF[i]

            for cohorte_nom, date_debut, date_fin in cohortes_info:
                cohorte, _ = Cohorte.objects.get_or_create(
                    certification=cert,
                    nom=cohorte_nom,
                    defaults={
                        "date_debut": date_debut,
                        "date_fin": date_fin,
                        "actif": True,
                    },
                )

                # Assigner entre 5 et 12 inscrits par cohorte
                nb = random.randint(5, 12)
                sample = random.sample(inscrits, min(nb, len(inscrits)))

                for inscrit in sample:
                    statut = random.choice(STATUTS)
                    if inscrit.activite == "etudiant":
                        type_tarif = tt_etu
                    else:
                        type_tarif = tt_pro
                    montant_du = type_tarif.montant

                    inscription, created = Inscription.objects.get_or_create(
                        inscrit=inscrit,
                        cohorte=cohorte,
                        defaults={
                            "statut": statut,
                            "type_tarif": type_tarif,
                            "montant_du": montant_du,
                        },
                    )
                    if not created:
                        continue
                    total_inscriptions += 1

                    # Créer paiement si statut avancé et montant > 0
                    if (
                        statut in ("en_formation", "formation_terminee", "certifie")
                        and montant_du > 0
                    ):
                        mode = random.choice(modes)
                        date_p = date_debut + timedelta(days=random.randint(1, 30))
                        Paiement.objects.create(
                            inscription=inscription,
                            montant=montant_du,
                            date_paiement=date_p,
                            moyen_paiement=mode,
                            reference=f"REF-{cert.pk:02d}-{inscription.pk:04d}",
                        )
                        total_paiements += 1

                    elif statut == "abandon" and montant_du > 0:
                        # Paiement partiel pour les abandons
                        mode = random.choice(modes)
                        date_p = date_debut + timedelta(days=random.randint(1, 15))
                        Paiement.objects.create(
                            inscription=inscription,
                            montant=montant_du * Decimal("0.5"),
                            date_paiement=date_p,
                            moyen_paiement=mode,
                            reference=f"REF-{cert.pk:02d}-{inscription.pk:04d}-P",
                        )
                        total_paiements += 1

            self.stdout.write(f"  Certification '{cert.nom}' — modes: {', '.join(modes)}")

        self.stdout.write(
            self.style.SUCCESS(
                f"\nTermine ! {Certification.objects.count()} certifications, "
                f"{Cohorte.objects.count()} cohortes, "
                f"{Inscrit.objects.count()} inscrits, "
                f"{total_inscriptions} inscriptions, "
                f"{total_paiements} paiements."
            )
        )
