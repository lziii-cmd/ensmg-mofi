from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inscriptions', '0004_add_notification_model'),
    ]

    operations = [
        migrations.AlterField(
            model_name='paiement',
            name='moyen_paiement',
            field=models.CharField(
                choices=[
                    ('wave', 'Wave'),
                    ('orange_money', 'Orange Money'),
                    ('intouch', 'InTouch Sénégal'),
                    ('carte', 'Carte bancaire'),
                    ('especes', 'Espèces'),
                    ('virement', 'Virement bancaire'),
                ],
                db_index=True,
                default='especes',
                max_length=20,
                verbose_name='Moyen de paiement',
            ),
        ),
    ]
