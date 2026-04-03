"""
Management command: python manage.py init_production

Réinitialise complètement la base de données et crée le compte admin.
Usage sur Render : à lancer depuis le Shell Render après déploiement.

ATTENTION : supprime toutes les données existantes.
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.core.management import call_command


class Command(BaseCommand):
    help = "Réinitialise la base et crée le compte admin ENSMG."

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Confirmer la réinitialisation sans prompt interactif.',
        )

    def handle(self, *args, **options):
        if not options['force']:
            confirm = input(
                "\n⚠️  ATTENTION : cette commande supprime TOUTES les données.\n"
                "Tapez 'oui' pour confirmer : "
            )
            if confirm.strip().lower() != 'oui':
                self.stdout.write(self.style.WARNING("Annulé."))
                return

        self.stdout.write("1. Suppression de toutes les données...")
        call_command('flush', '--no-input')

        self.stdout.write("2. Application des migrations...")
        call_command('migrate', '--no-input')

        self.stdout.write("3. Création du compte administrateur...")
        admin_username = 'admin@ensmg.sn'
        admin_password = 'password'

        if User.objects.filter(username=admin_username).exists():
            user = User.objects.get(username=admin_username)
            user.set_password(admin_password)
            user.is_staff = True
            user.is_superuser = True
            user.is_active = True
            user.save()
            self.stdout.write(f"   Compte existant mis à jour : {admin_username}")
        else:
            User.objects.create_superuser(
                username=admin_username,
                email=admin_username,
                password=admin_password,
                first_name='Admin',
                last_name='ENSMG',
            )
            self.stdout.write(f"   Compte créé : {admin_username}")

        self.stdout.write(self.style.SUCCESS(
            f"\n✅  Initialisation terminée !\n"
            f"   Identifiant : {admin_username}\n"
            f"   Mot de passe : {admin_password}\n"
            f"   URL de connexion : /login/\n"
        ))
