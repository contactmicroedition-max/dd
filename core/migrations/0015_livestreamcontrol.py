from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0014_alter_securitysystemlog_event_type'),
    ]

    operations = [
        migrations.CreateModel(
            name='LiveStreamControl',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('singleton_key', models.CharField(default='global', editable=False, max_length=30, unique=True)),
                ('state', models.CharField(choices=[('active', 'Active'), ('suspended', 'Temporarily Suspended'), ('shutdown', 'Shut Down')], default='active', max_length=20)),
                ('admin_note', models.CharField(blank=True, max_length=255)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='live_stream_control_updates', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-updated_at'],
            },
        ),
    ]
