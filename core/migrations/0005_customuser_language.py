from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_customuser_theme'),
    ]

    operations = [
        migrations.AddField(
            model_name='customuser',
            name='language',
            field=models.CharField(
                choices=[('en', 'English'), ('ar', 'Arabic'), ('fr', 'French')],
                default='en',
                max_length=5,
            ),
        ),
    ]
