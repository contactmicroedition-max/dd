# Generated migration for adding theme field

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='customuser',
            name='theme',
            field=models.CharField(
                choices=[('dark', 'Dark Modern'), ('light', 'Light Professional'), ('vibrant', 'Vibrant Neon')],
                default='dark',
                max_length=20
            ),
        ),
    ]
