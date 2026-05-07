"""
Migration 0003 — Session / Cohorte refactor
============================================
Sépare la notion temporelle (Session = quand) de la notion humaine (Cohorte = qui).

Opérations :
  1. Crée le modèle Session
  2. Ajoute session FK nullable sur Cohorte
  3. Data migration : crée une Session par Cohorte existante
  4. Rend session non-nullable, renomme les cohortes en "Cohorte A"
  5. Supprime les anciens champs de Cohorte (certification, option, date_debut, date_fin)
"""

from django.db import migrations, models
import django.db.models.deletion


MOIS_FR = {
    1: "janvier",
    2: "février",
    3: "mars",
    4: "avril",
    5: "mai",
    6: "juin",
    7: "juillet",
    8: "août",
    9: "septembre",
    10: "octobre",
    11: "novembre",
    12: "décembre",
}


def create_sessions_from_cohortes(apps, schema_editor):
    """
    Pour chaque Cohorte existante :
      - Crée une Session portant les infos temporelles (certification, option, dates, nom)
      - Renomme la Cohorte en "Cohorte A" (l'info temporelle est maintenant dans Session)
      - Rattache la Cohorte à la nouvelle Session
    """
    Cohorte = apps.get_model("inscriptions", "Cohorte")
    Session = apps.get_model("inscriptions", "Session")

    for cohorte in Cohorte.objects.all():
        # Construire le nom de session à partir de la date de début
        if cohorte.date_debut:
            mois = MOIS_FR.get(cohorte.date_debut.month, "")
            nom_session = f"Session de {mois} {cohorte.date_debut.year}"
        else:
            nom_session = f"Session — {cohorte.nom}"

        session = Session.objects.create(
            certification_id=cohorte.certification_id,
            option_id=cohorte.option_id,
            nom=nom_session,
            date_debut=cohorte.date_debut,
            date_fin=cohorte.date_fin,
            actif=cohorte.actif,
        )

        # Rattacher la cohorte à sa session et la renommer
        Cohorte.objects.filter(pk=cohorte.pk).update(
            session_id=session.pk,
            nom="Cohorte A",
        )


def reverse_sessions_to_cohortes(apps, schema_editor):
    """Reverse : recopie les infos de session dans chaque cohorte."""
    Cohorte = apps.get_model("inscriptions", "Cohorte")

    for cohorte in Cohorte.objects.select_related("session").all():
        s = cohorte.session
        Cohorte.objects.filter(pk=cohorte.pk).update(
            certification_id=s.certification_id,
            option_id=s.option_id,
            date_debut=s.date_debut,
            date_fin=s.date_fin,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("inscriptions", "0002_add_nom_type_tarif"),
    ]

    operations = [
        # ── 1. Créer le modèle Session ──────────────────────────────────────
        migrations.CreateModel(
            name="Session",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False)),
                (
                    "certification",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="sessions",
                        to="inscriptions.certification",
                        verbose_name="Certification",
                    ),
                ),
                (
                    "option",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="sessions",
                        to="inscriptions.optioncertification",
                        verbose_name="Option",
                    ),
                ),
                ("nom", models.CharField(max_length=200, verbose_name="Nom de la session")),
                (
                    "date_debut",
                    models.DateField(blank=True, null=True, verbose_name="Date de début"),
                ),
                (
                    "date_fin",
                    models.DateField(blank=True, null=True, verbose_name="Date de fin"),
                ),
                ("actif", models.BooleanField(default=True, verbose_name="Active")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Session",
                "verbose_name_plural": "Sessions",
                "ordering": ["date_debut", "nom"],
            },
        ),
        # ── 2. Ajouter session FK nullable sur Cohorte ───────────────────────
        migrations.AddField(
            model_name="cohorte",
            name="session",
            field=models.ForeignKey(
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="cohortes",
                to="inscriptions.session",
                verbose_name="Session",
            ),
        ),
        # ── 3. Data migration : créer les sessions depuis les cohortes ───────
        migrations.RunPython(
            create_sessions_from_cohortes,
            reverse_code=reverse_sessions_to_cohortes,
        ),
        # ── 4. Rendre session obligatoire ────────────────────────────────────
        migrations.AlterField(
            model_name="cohorte",
            name="session",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="cohortes",
                to="inscriptions.session",
                verbose_name="Session",
            ),
        ),
        # ── 5. Supprimer les anciens champs de Cohorte ────────────────────────
        migrations.RemoveField(model_name="cohorte", name="certification"),
        migrations.RemoveField(model_name="cohorte", name="option"),
        migrations.RemoveField(model_name="cohorte", name="date_debut"),
        migrations.RemoveField(model_name="cohorte", name="date_fin"),
    ]
