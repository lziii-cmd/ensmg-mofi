"""
Seed data script :
  1. Met à jour les dates des sessions (toutes avant le 12-05-2026)
  2. Ajoute 5 inscrits par cohorte (avec paiements)
  3. Plusieurs inscrits font plus d'une certification
"""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ensmg_mofi.settings")
django.setup()

from datetime import date

from django.contrib.auth.models import User

from inscriptions.models import (
    Attestation,
    Cohorte,
    CompteApprenant,
    Inscription,
    Inscrit,
    Paiement,
    Session,
    TypeTarif,
)

# ─────────────────────────────────────────────
# 1. MISE À JOUR DES DATES DES SESSIONS
# ─────────────────────────────────────────────
nouvelles_dates = {
    12: (date(2026, 1, 5), date(2026, 2, 20)),  # SOUDURE/Construction avr
    1: (date(2026, 1, 12), date(2026, 3, 6)),  # DS/IA ERP avr
    5: (date(2026, 1, 19), date(2026, 3, 13)),  # SOUDURE/Tuyauterie sept
    2: (date(2026, 2, 2), date(2026, 4, 3)),  # MGMT juin
    3: (date(2026, 2, 9), date(2026, 4, 10)),  # DS/DataScience juin
    4: (date(2026, 2, 16), date(2026, 4, 17)),  # DS/Intelligence juil
    10: (date(2026, 3, 2), date(2026, 4, 24)),  # SOUDURE/Construction sept
    7: (date(2026, 3, 9), date(2026, 5, 1)),  # DS/DataScience oct
    9: (date(2026, 3, 16), date(2026, 5, 8)),  # DS/IA ERP oct
    6: (date(2026, 3, 23), date(2026, 5, 9)),  # MGMT nov
    8: (date(2026, 3, 30), date(2026, 5, 10)),  # DS/Intelligence nov
    11: (date(2026, 4, 6), date(2026, 5, 11)),  # SOUDURE/Tuyauterie jan
}

for pk, (debut, fin) in nouvelles_dates.items():
    Session.objects.filter(pk=pk).update(date_debut=debut, date_fin=fin)
    print(f"  Session {pk} -> {debut} / {fin}")

print(f"OK {len(nouvelles_dates)} sessions mises à jour\n")

# ─────────────────────────────────────────────
# 2. POOL D'INSCRITS (hors Mamadou déjà existant)
# ─────────────────────────────────────────────
POOL = [
    ("Ousmane", "Diallo", "ousmane.diallo@ensmg.sn", "+221771001001", "salarie"),
    ("Fatou", "Sarr", "fatou.sarr@ensmg.sn", "+221772002002", "etudiant"),
    ("Ibrahima", "Ndiaye", "ibrahima.ndiaye@ensmg.sn", "+221773003003", "fonctionnaire"),
    ("Aminata", "Ba", "aminata.ba@ensmg.sn", "+221774004004", "etudiant"),
    ("Moussa", "Diop", "moussa.diop@ensmg.sn", "+221775005005", "professionnel"),
    ("Aissatou", "Fall", "aissatou.fall@ensmg.sn", "+221776006006", "demandeur_emploi"),
    ("Cheikh", "Gueye", "cheikh.gueye@ensmg.sn", "+221777007007", "salarie"),
    ("Mariama", "Sow", "mariama.sow@ensmg.sn", "+221778008008", "etudiant"),
    ("Modou", "Mbaye", "modou.mbaye@ensmg.sn", "+221779009009", "demandeur_emploi"),
    ("Rokhaya", "Diouf", "rokhaya.diouf@ensmg.sn", "+221770010010", "fonctionnaire"),
    ("Pape", "Ndoye", "pape.ndoye@ensmg.sn", "+221771011011", "etudiant"),
    ("Ndeye", "Thiaw", "ndeye.thiaw@ensmg.sn", "+221772012012", "salarie"),
    ("Serigne", "Lo", "serigne.lo@ensmg.sn", "+221773013013", "professionnel"),
    ("Khady", "Wade", "khady.wade@ensmg.sn", "+221774014014", "etudiant"),
    ("Alioune", "Diagne", "alioune.diagne@ensmg.sn", "+221775015015", "fonctionnaire"),
    ("Adja", "Cisse", "adja.cisse@ensmg.sn", "+221776016016", "etudiant"),
    ("Babacar", "Faye", "babacar.faye@ensmg.sn", "+221777017017", "salarie"),
    ("Sokhna", "Tall", "sokhna.tall@ensmg.sn", "+221778018018", "demandeur_emploi"),
    ("Lamine", "Drame", "lamine.drame@ensmg.sn", "+221779019019", "etudiant"),
    ("Coumba", "Kane", "coumba.kane@ensmg.sn", "+221770020020", "fonctionnaire"),
]

inscrits = {}
for prenom, nom, email, tel, activite in POOL:
    inscrit, created = Inscrit.objects.get_or_create(
        email=email,
        defaults=dict(prenom=prenom, nom=nom, telephone=tel, activite=activite, source="portail"),
    )
    if created:
        # Créer le compte apprenant
        username = email.split("@")[0]
        user, _ = User.objects.get_or_create(
            username=username, defaults=dict(email=email, first_name=prenom, last_name=nom)
        )
        user.set_password("ENSMG")
        user.save()
        CompteApprenant.objects.get_or_create(
            inscrit=inscrit, defaults=dict(user=user, mdp_change=True)
        )
    inscrits[prenom] = inscrit

# Récupérer Mamadou existant et mettre à jour son mot de passe
mamadou = Inscrit.objects.get(pk=1)
inscrits["Mamadou"] = mamadou
try:
    mamadou_user = mamadou.compte_apprenant.user
    mamadou_user.set_password("ENSMG")
    mamadou_user.save()
    print("  Mamadou -> mot de passe mis à jour")
except Exception as e:
    print(f"  Mamadou -> impossible de mettre à jour le mdp : {e}")

print(f"OK {len(inscrits)} inscrits prêts\n")


# ─────────────────────────────────────────────
# 3. TARIFS PAR COHORTE
#    (on prend le tarif Étudiant ou Demandeur d'emploi le moins cher)
# ─────────────────────────────────────────────
def get_tarif(cohorte):
    """Retourne le TypeTarif le moins cher pour cette cohorte."""
    if cohorte.session.option_id:
        qs = TypeTarif.objects.filter(option_id=cohorte.session.option_id, actif=True)
    else:
        qs = TypeTarif.objects.filter(certification_id=cohorte.session.certification_id, actif=True)
    return qs.order_by("montant").first()


# ─────────────────────────────────────────────
# 4. PLAN D'INSCRIPTION : 5 inscrits par cohorte
#    (certains inscrits apparaissent dans plusieurs certifications)
# ─────────────────────────────────────────────
# Format : {cohorte_pk: [prenom, ...]}
PLAN = {
    1: ["Mamadou", "Modou", "Serigne", "Aminata", "Babacar"],  # SOUDURE/Constr
    2: ["Ousmane", "Fatou", "Ibrahima", "Aminata", "Moussa"],  # DS/IA ERP
    3: ["Mamadou", "Ousmane", "Ibrahima", "Moussa", "Mariama"],  # MGMT
    4: ["Mariama", "Ndeye", "Khady", "Lamine", "Sokhna"],  # MGMT
    5: ["Ousmane", "Rokhaya", "Coumba", "Babacar", "Lamine"],  # DS/DataScience
    6: ["Ibrahima", "Cheikh", "Pape", "Khady", "Moussa"],  # DS/DataScience
    7: ["Aminata", "Adja", "Ndeye", "Fatou", "Serigne"],  # DS/Intelligence
    8: ["Ousmane", "Moussa", "Rokhaya", "Coumba", "Lamine"],  # DS/Intelligence
    9: ["Ibrahima", "Cheikh", "Alioune", "Adja", "Sokhna"],  # DS/IA ERP
    10: ["Fatou", "Modou", "Serigne", "Sokhna", "Aissatou"],  # SOUDURE/Tuyaut
    11: ["Mamadou", "Cheikh", "Rokhaya", "Alioune", "Babacar"],  # SOUDURE/Constr
    12: ["Fatou", "Pape", "Ndeye", "Khady", "Adja"],  # SOUDURE/Tuyaut
}

# Statuts rotatifs pour varier les données
STATUTS = ["inscrit", "en_formation", "certifie", "inscrit", "en_formation"]

nb_inscriptions = 0
nb_paiements = 0
nb_attestations = 0

for cohorte_pk, prenoms in PLAN.items():
    cohorte = Cohorte.objects.select_related("session__certification", "session__option").get(
        pk=cohorte_pk
    )
    tarif = get_tarif(cohorte)
    montant = float(tarif.montant) if tarif else 0

    print(f"  Cohorte {cohorte_pk} ({cohorte.session.certification.nom[:20]}) :")

    for i, prenom in enumerate(prenoms):
        inscrit = inscrits[prenom]
        statut = STATUTS[i % len(STATUTS)]

        inscription, created = Inscription.objects.get_or_create(
            inscrit=inscrit,
            cohorte=cohorte,
            defaults=dict(
                statut=statut,
                type_tarif=tarif,
                montant_du=montant,
            ),
        )

        if not created:
            # Mettre à jour le statut si l'inscription existait déjà
            inscription.statut = statut
            inscription.save(update_fields=["statut"])
        else:
            nb_inscriptions += 1

        # Ajouter un paiement confirmé si pas déjà payé
        if montant > 0 and not inscription.paiements.filter(statut="confirme").exists():
            Paiement.objects.create(
                inscription=inscription,
                montant=montant,
                date_paiement=cohorte.session.date_debut,
                moyen_paiement="orange_money",
                reference=f"OM-SEED-{cohorte_pk:03d}-{inscrit.pk:04d}",
                statut="confirme",
                notes="Paiement seed data",
            )
            nb_paiements += 1

        # Créer une attestation pour les certifiés
        if statut == "certifie" and not inscription.attestations.exists():
            import re

            abbrev = re.sub(r"[^A-Z]", "", cohorte.session.certification.nom.upper())[:6]
            annee = cohorte.session.date_debut.year
            seq = (
                Attestation.objects.filter(
                    inscription__cohorte__session__certification=cohorte.session.certification
                ).count()
                + 1
            )
            numero = f"CERT-ENSMG-{abbrev}-{annee}-{seq:03d}"
            while Attestation.objects.filter(numero=numero).exists():
                seq += 1
                numero = f"CERT-ENSMG-{abbrev}-{annee}-{seq:03d}"
            Attestation.objects.create(
                inscription=inscription,
                numero=numero,
                date_delivrance=cohorte.session.date_fin,
            )
            inscription.statut = "certifie"
            inscription.save(update_fields=["statut"])
            nb_attestations += 1

        tag = "OK créé" if created else "-> existe"
        print(f"    {tag} {prenom} | statut={statut} | {montant:,.0f} FCFA")

    print()

print(f"OK {nb_inscriptions} inscriptions créées")
print(f"OK {nb_paiements} paiements confirmés")
print(f"OK {nb_attestations} attestations générées")
print()

# ─────────────────────────────────────────────
# 5. RÉSUMÉ MULTI-CERTIFICATION
# ─────────────────────────────────────────────
print("=== INSCRITS MULTI-CERTIFICATION ===")
from django.db.models import Count

multi = (
    Inscrit.objects.annotate(
        nb_certifs=Count("inscriptions__cohorte__session__certification", distinct=True)
    )
    .filter(nb_certifs__gt=1)
    .order_by("-nb_certifs")
)
for i in multi:
    certifs = list(
        i.inscriptions.values_list("cohorte__session__certification__nom", flat=True).distinct()
    )
    nb_ins = i.inscriptions.count()
    nb_cer = len(certifs)
    noms = ", ".join(certifs)
    print(f"  {i.nom_complet} -> {nb_ins} inscriptions | {nb_cer} certifications : {noms}")
