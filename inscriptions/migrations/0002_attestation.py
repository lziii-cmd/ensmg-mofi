"""
Migration d'origine : création du modèle Attestation avec FileField.
Cette migration correspond à l'état déjà appliqué sur le serveur Render.
NE PAS MODIFIER — utiliser 0003 pour toute évolution.
"""
import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


def _upload_path_placeholder(instance, filename):
    """Placeholder conservé uniquement pour la compatibilité de la migration."""
    return f"attestations/{filename}"


class Migration(migrations.Migration):

    dependencies = [
        ("inscriptions", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Attestation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("numero", models.CharField(max_length=50, unique=True, verbose_name="Numéro d'attestation")),
                ("date_delivrance", models.DateField(default=django.utils.timezone.now, verbose_name="Date de délivrance")),
                ("fichier", models.FileField(upload_to=_upload_path_placeholder, verbose_name="Fichier PDF")),
                ("generated_at", models.DateTimeField(auto_now_add=True)),
                ("inscription", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="attestations",
                    to="inscriptions.inscription",
                    verbose_name="Inscription",
                )),
            ],
            options={
                "verbose_name": "Attestation",
                "verbose_name_plural": "Attestations",
                "ordering": ["-date_delivrance", "-generated_at"],
            },
        ),
    ]
