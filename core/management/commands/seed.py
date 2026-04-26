"""
Management command: python manage.py seed
Creates admin, sample drones, sample alerts for demo.
"""
import os

from django.core.management.base import BaseCommand, CommandError
from core.models import CustomUser, Drone, Alert


class Command(BaseCommand):
    help = 'Seed the database with demo data'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.MIGRATE_HEADING('🚀 Seeding DroneSec database...'))
        admin_password = (os.getenv('SEED_ADMIN_PASSWORD') or '').strip()
        agent_password = (os.getenv('SEED_AGENT_PASSWORD') or '').strip()

        if not admin_password or not agent_password:
            raise CommandError(
                'Missing required environment variables: '
                'SEED_ADMIN_PASSWORD and SEED_AGENT_PASSWORD.'
            )

        # ── Admin ───────────────────────────────────────────────────────────
        if not CustomUser.objects.filter(username='admin').exists():
            admin = CustomUser.objects.create_superuser(
                username='admin',
                email='admin@dronesec.io',
                password=admin_password,
                first_name='System',
                last_name='Administrator',
                role='admin',
                is_approved=True,
                email_verified=True,
            )
            self.stdout.write(self.style.SUCCESS('  ✅ Admin created  (username: admin)'))
        else:
            admin = CustomUser.objects.get(username='admin')
            self.stdout.write('  ⏭  Admin already exists')

        # ── Demo agents ─────────────────────────────────────────────────────
        agents_data = [
            ('agent1', 'Karim',   'Mansouri', 'agent1@dronesec.io', 'Field Ops',   True),
            ('agent2', 'Sarra',   'Ben Ali',  'agent2@dronesec.io', 'Control Room', True),
            ('agent3', 'Youssef', 'Trabelsi', 'agent3@dronesec.io', 'Analysis',    False),
        ]
        for uname, fn, ln, email, dept, approved in agents_data:
            if not CustomUser.objects.filter(username=uname).exists():
                CustomUser.objects.create_user(
                    username=uname, email=email, password=agent_password,
                    first_name=fn, last_name=ln,
                    role='agent', is_approved=approved,
                    department=dept, email_verified=True,
                )
                status = '✅' if approved else '⏳'
                self.stdout.write(f'  {status} Agent {uname} created')

        # ── Drones ──────────────────────────────────────────────────────────
        drones_data = [
            ('DRN-ALPHA-01', 'Alpha',   'patrolling', 87, 36.8200, 10.1800, 'North Sector'),
            ('DRN-BETA-02',  'Beta',    'online',     62, 36.7900, 10.1500, 'West Gate'),
            ('DRN-GAMMA-03', 'Gamma',   'charging',   23, 36.8100, 10.2100, 'Base Station'),
            ('DRN-DELTA-04', 'Delta',   'offline',     0, 36.8300, 10.1900, 'Maintenance Bay'),
            ('DRN-ECHO-05',  'Echo',    'patrolling', 91, 36.8050, 10.1750, 'South Perimeter'),
        ]
        drones = []
        for serial, name, status, battery, lat, lng, loc in drones_data:
            drone, created = Drone.objects.get_or_create(serial_number=serial, defaults={
                'name': name, 'status': status, 'battery': battery,
                'latitude': lat, 'longitude': lng, 'location_name': loc,
                'camera_active': status in ['patrolling', 'online'],
                'assigned_to': admin,
            })
            drones.append(drone)
            if created:
                self.stdout.write(f'  🚁 Drone {name} created')

        # ── Alerts ──────────────────────────────────────────────────────────
        if Alert.objects.count() < 5:
            alert_templates = [
                ('Unauthorized Person Detected', 'Unknown individual spotted near restricted zone B-7.', 'critical', 'intrusion'),
                ('Unknown Face Identified', 'Face recognition returned no match in database.', 'high', 'face'),
                ('Suspicious Vehicle Detected', 'Unregistered vehicle parked near perimeter fence.', 'high', 'object'),
                ('Motion in Restricted Area', 'Unexpected movement detected after curfew hours.', 'medium', 'motion'),
                ('Drone Battery Critical', 'Battery level dropped below 15%. Return to base recommended.', 'high', 'battery'),
                ('Geofence Breach', 'Drone Delta exited assigned operational zone.', 'medium', 'geofence'),
                ('Signal Interruption', 'Brief connection loss detected – auto-recovery successful.', 'low', 'connection'),
                ('System Health Check', 'All systems nominal. Scheduled diagnostic complete.', 'low', 'system'),
            ]
            for i, (title, desc, severity, atype) in enumerate(alert_templates):
                drone = drones[i % len(drones)]
                Alert.objects.create(
                    title=title, description=desc,
                    severity=severity, alert_type=atype,
                    drone=drone,
                    is_read=(i > 4),
                    is_resolved=(i > 5),
                )
            self.stdout.write(self.style.SUCCESS(f'  🔔 {len(alert_templates)} alerts created'))

        self.stdout.write(self.style.SUCCESS('\n✅ Database seeded successfully!'))
        self.stdout.write(self.style.WARNING('   Login: admin / value of SEED_ADMIN_PASSWORD'))
