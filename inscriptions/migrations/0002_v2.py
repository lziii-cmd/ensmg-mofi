"""
Migration v2.0 — adds portal fields to Inscrit, statut/recu_pdf to Paiement,
and creates the CompteApprenant model.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inscriptions', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ── Inscrit: new fields ──────────────────────────────────────────
        migrations.AddField(
            model_name='inscrit',
            name='adresse',
            field=models.CharField(blank=True, max_length=255, verbose_name='Adresse'),
        ),
        migrations.AddField(
            model_name='inscrit',
            name='universite',
            field=models.CharField(blank=True, max_length=200, verbose_name='Université'),
        ),
        migrations.AddField(
            model_name='inscrit',
            name='entreprise',
            field=models.CharField(blank=True, max_length=200, verbose_name='Entreprise'),
        ),
        # Update source choices (CharField — no data migration needed, just alter)
        migrations.AlterField(
            model_name='inscrit',
            name='source',
            field=models.CharField(
                choices=[
                    ('manuel', 'Manuel'),
                    ('excel', 'Import Excel'),
                    ('portail', 'Portail en ligne'),
                ],
                default='manuel',
                max_length=20,
                verbose_name='Source',
            ),
        ),

        # ── Paiement: new fields ─────────────────────────────────────────
        migrations.AddField(
            model_name='paiement',
            name='statut',
            field=models.CharField(
                choices=[('confirme', 'Confirmé'), ('en_attente', 'En attente')],
                default='confirme',
                max_length=20,
                verbose_name='Statut',
            ),
        ),
        migrations.AddField(
            model_name='paiement',
            name='recu_pdf',
            field=models.BinaryField(blank=True, null=True, verbose_name='Reçu PDF'),
        ),
        # Add carte to moyen_paiement choices
        migrations.AlterField(
            model_name='paiement',
            name='moyen_paiement',
            field=models.CharField(
                choices=[
                    ('wave', 'Wave'),
                    ('orange_money', 'Orange Money'),
                    ('carte', 'Carte bancaire'),
                    ('stripe', 'Stripe'),
                    ('especes', 'Espèces'),
                    ('virement', 'Virement bancaire'),
                ],
                default='especes',
                max_length=20,
                verbose_name='Moyen de paiement',
            ),
        ),

        # ── CompteApprenant: new model ───────────────────────────────────
        migrations.CreateModel(
            name='CompteApprenant',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('mdp_change', models.BooleanField(default=False, verbose_name='Mot de passe changé')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('inscrit', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='compte_apprenant',
                    to='inscriptions.inscrit',
                    verbose_name='Inscrit',
                )),
                ('user', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='compte_apprenant',
                    to=settings.AUTH_USER_MODEL,
                    verbose_name='Utilisateur',
                )),
            ],
            options={
                'verbose_name': 'Compte Apprenant',
                'verbose_name_plural': 'Comptes Apprenants',
            },
        ),
    ]
