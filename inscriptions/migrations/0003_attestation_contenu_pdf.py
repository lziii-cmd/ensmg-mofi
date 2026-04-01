"""
Migration 0003 : remplacement du FileField par un BinaryField.
Les PDFs sont désormais stockés en base de données (compatible Render free tier).
Les attestations existantes conservent leur ligne mais contenu_pdf sera NULL —
elles devront être régénérées via la page Certifier.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inscriptions", "0002_attestation"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="attestation",
            name="fichier",
        ),
        migrations.AddField(
            model_name="attestation",
            name="contenu_pdf",
            field=models.BinaryField(
                blank=True,
                null=True,
                verbose_name="Contenu PDF",
                help_text="PDF stocké en base de données (persist sur tous les hébergeurs).",
            ),
        ),
    ]
