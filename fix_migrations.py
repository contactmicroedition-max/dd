import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dronesec.settings')
django.setup()

from django.db import connection
from datetime import datetime

with connection.cursor() as cursor:
    # Mark core 0001_initial as applied
    cursor.execute("""
        INSERT INTO django_migrations (app, name, applied)
        VALUES (%s, %s, %s)
    """, ['core', '0001_initial', datetime.now()])
    connection.commit()
    print('✅ Marked core 0001_initial as applied')
    
    # List all applied migrations
    cursor.execute('SELECT app, name FROM django_migrations ORDER BY app, name')
    for app, name in cursor.fetchall():
        print(f'  - {app}: {name}')
