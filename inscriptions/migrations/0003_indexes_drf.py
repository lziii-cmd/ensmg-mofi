"""
Migration 0003 — Indexes sur les champs fréquemment filtrés + suppression du
champ fichier de l'ancienne Attestation si présent (sécurité).
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inscriptions", "0002_v2"),
    ]

    operations = [
        # Indexes sur Inscrit
        migrations.AlterField(
            model_name="inscrit",
            name="nom",
            field=models.CharField(db_index=True, max_length=100, verbose_name="Nom"),
        ),
        migrations.AlterField(
            model_name="inscrit",
            name="prenom",
            field=models.CharField(db_index=True, max_length=100, verbose_name="Prénom"),
        ),
        migrations.AlterField(
            model_name="inscrit",
            name="email",
            field=models.EmailField(blank=True, db_index=True, max_length=254, verbose_name="Email"),
        ),
        # Index sur Inscription.statut
        migrations.AlterField(
            model_name="inscription",
            name="statut",
            field=models.CharField(
                choices=[
                    ("inscrit", "Inscrit"),
                    ("en_formation", "En formation"),
                    ("abandon", "Abandon"),
                    ("formation_terminee", "Formation terminée"),
                    ("certifie", "Certifié"),
                ],
                db_index=True,
                default="inscrit",
                max_length=20,
                verbose_name="Statut",
            ),
        ),
        # Index sur Paiement.moyen_paiement
        migrations.AlterField(
            model_name="paiement",
            name="moyen_paiement",
            field=models.CharField(
                choices=[
                    ("wave", "Wave"),
                    ("orange_money", "Orange Money"),
                    ("carte", "Carte bancaire"),
                    ("stripe", "Stripe"),
                    ("especes", "Espèces"),
                    ("virement", "Virement bancaire"),
                ],
                db_index=True,
                default="especes",
                max_length=20,
                verbose_name="Moyen de paiement",
            ),
        ),
    ]
