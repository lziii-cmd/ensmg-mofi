"""
Management command: python manage.py create_admin
Crée le compte superuser admin@ensmg.sn s'il n'existe pas déjà.
Appelé automatiquement au build Render.
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User


class Command(BaseCommand):
    help = "Crée le compte admin ENSMG s'il n'existe pas."

    def handle(self, *args, **options):
        username = 'admin@ensmg.sn'
        password = 'password'
        if User.objects.filter(username=username).exists():
            self.stdout.write(f"Admin déjà existant : {username}")
        else:
            User.objects.create_superuser(
                username=username,
                email=username,
                password=password,
                first_name='Admin',
                last_name='ENSMG',
            )
            self.stdout.write(self.style.SUCCESS(f"Admin créé : {username} / {password}"))
