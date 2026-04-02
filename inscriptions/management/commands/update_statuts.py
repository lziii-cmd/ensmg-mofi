"""
Commande Django : python manage.py update_statuts

Met à jour automatiquement les statuts des inscriptions selon les dates de cohorte.

Transitions effectuées :
  inscrit       + cohorte.date_debut <= today <= cohorte.date_fin → en_formation
  en_formation  + cohorte.date_fin   <  today                     → formation_terminee

Usage :
  python manage.py update_statuts
  python manage.py update_statuts --dry-run   (affiche sans modifier)

À planifier via un cron quotidien sur Render.com :
  0 6 * * *   cd /opt/render/project/src && python manage.py update_statuts
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from inscriptions.models import Inscription


class Command(BaseCommand):
    help = "Met à jour les statuts des inscriptions selon les dates de cohorte (en_formation / formation_terminee)"

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help="Affiche les changements sans les appliquer",
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        today = timezone.now().date()
        updated = 0

        # ── inscrit → en_formation ─────────────────────────────────────────
        qs_debut = Inscription.objects.filter(
            statut='inscrit',
            cohorte__date_debut__lte=today,
            cohorte__date_fin__gte=today,
        ).select_related('inscrit', 'cohorte')

        for ins in qs_debut:
            self.stdout.write(
                f"  [en_formation]      {ins.inscrit} — {ins.cohorte} "
                f"(début: {ins.cohorte.date_debut})"
            )
            if not dry_run:
                ins.statut = 'en_formation'
                ins.save(update_fields=['statut'])
            updated += 1

        # ── en_formation → formation_terminee ─────────────────────────────
        qs_fin = Inscription.objects.filter(
            statut='en_formation',
            cohorte__date_fin__lt=today,
        ).select_related('inscrit', 'cohorte')

        for ins in qs_fin:
            self.stdout.write(
                f"  [formation_terminee] {ins.inscrit} — {ins.cohorte} "
                f"(fin: {ins.cohorte.date_fin})"
            )
            if not dry_run:
                ins.statut = 'formation_terminee'
                ins.save(update_fields=['statut'])
            updated += 1

        mode = "[DRY RUN] " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"{mode}{updated} inscription(s) mise(s) à jour."
            )
        )
