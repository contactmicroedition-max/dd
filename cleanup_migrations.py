import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dronesec.settings')
django.setup()

from django.db import connection

with connection.cursor() as cursor:
    # Delete old app migrations
    old_apps = ["users", "dashboard", "drones", "monitoring", "alerts", "reports", "settings_app"]
    for app in old_apps:
        cursor.execute('DELETE FROM django_migrations WHERE app = %s', [app])
    connection.commit()
    print(f'✅ Cleaned up migrations for {len(old_apps)} old apps')
