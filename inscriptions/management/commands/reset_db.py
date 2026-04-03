from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = 'Vide toutes les tables (TRUNCATE CASCADE) sauf django_migrations'

    def handle(self, *args, **options):
        self.stdout.write('Vidage de la base de données…')
        with connection.cursor() as cursor:
            cursor.execute("""
                DO $$ DECLARE
                    r RECORD;
                BEGIN
                    FOR r IN (
                        SELECT tablename FROM pg_tables
                        WHERE schemaname = 'public'
                          AND tablename NOT IN ('django_migrations')
                    ) LOOP
                        EXECUTE 'TRUNCATE TABLE ' || quote_ident(r.tablename) || ' CASCADE';
                    END LOOP;
                END $$;
            """)
        self.stdout.write(self.style.SUCCESS('Base de données vidée avec succès.'))
