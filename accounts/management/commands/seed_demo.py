from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import Organisation, User
from sites.models import Site

DEMO_USERS = [
    ('admin@mdmis.rw', 'A. Nkurunziza', 'system_admin'),
    ('analyst@mdmis.rw', 'D. Nzeyimana', 'mine_manager'),
    ('geo@mdmis.rw', 'J. Habimana', 'geologist'),
    ('compliance@mdmis.rw', 'C. Mukamana', 'compliance_manager'),
]
DEMO_PASSWORD = 'demo1234'

# Mirrors frontend/lib/mdmis-data.ts SITES so the map explorer's static
# terrain assets (frontend/public/terrain/<id>/) line up with real DB rows.
DEMO_SITES = [
    dict(id='RW-RTG-01', name='Rutongo Tin Belt', district='Rulindo', lat=-1.7783, lng=30.0611,
         primary_mineral='cassiterite', secondary_minerals=['wolframite'], grade_pct=1.8, confidence=96.4,
         estimated_tonnage=42500, safety_score=82, risk_level='low', status='active',
         last_scan='2026-06-08T09:12:00Z', depth_meters=48),
    dict(id='RW-GTB-02', name='Gatumba Coltan Field', district='Ngororero', lat=-1.8642, lng=29.5231,
         primary_mineral='coltan', secondary_minerals=['beryl', 'cassiterite'], grade_pct=0.42, confidence=93.1,
         estimated_tonnage=12800, safety_score=61, risk_level='moderate', status='active',
         last_scan='2026-06-08T07:44:00Z', depth_meters=32),
    dict(id='RW-NYK-03', name='Nyakabingo Mine', district='Rulindo', lat=-1.7419, lng=30.0089,
         primary_mineral='wolframite', secondary_minerals=[], grade_pct=1.1, confidence=97.8,
         estimated_tonnage=30100, safety_score=88, risk_level='low', status='active',
         last_scan='2026-06-07T16:20:00Z', depth_meters=65),
    dict(id='RW-GFW-04', name='Gifurwe Tungsten', district='Rutsiro', lat=-1.9928, lng=29.4102,
         primary_mineral='wolframite', secondary_minerals=['cassiterite'], grade_pct=0.95, confidence=91.5,
         estimated_tonnage=18900, safety_score=44, risk_level='high', status='flagged',
         last_scan='2026-06-08T05:03:00Z', depth_meters=27),
    dict(id='RW-RWK-05', name='Rwinkwavu Prospect', district='Kayonza', lat=-2.1481, lng=30.5892,
         primary_mineral='gold', secondary_minerals=[], grade_pct=4.2, confidence=88.7,
         estimated_tonnage=3400, safety_score=73, risk_level='moderate', status='surveying',
         last_scan='2026-06-08T10:31:00Z', depth_meters=12),
    dict(id='RW-NMB-06', name='Nemba Coltan', district='Gakenke', lat=-1.6892, lng=29.7743,
         primary_mineral='coltan', secondary_minerals=['cassiterite'], grade_pct=0.51, confidence=94.9,
         estimated_tonnage=9600, safety_score=79, risk_level='low', status='active',
         last_scan='2026-06-07T14:55:00Z', depth_meters=40),
    dict(id='RW-BGR-07', name='Bugarama Ridge', district='Rusizi', lat=-2.6889, lng=29.0031,
         primary_mineral='lithium', secondary_minerals=['beryl'], grade_pct=1.35, confidence=85.2,
         estimated_tonnage=7200, safety_score=58, risk_level='moderate', status='surveying',
         last_scan='2026-06-08T08:17:00Z', depth_meters=22),
    dict(id='RW-MSH-08', name='Musha Cassiterite', district='Rwamagana', lat=-1.9231, lng=30.3402,
         primary_mineral='cassiterite', secondary_minerals=['coltan'], grade_pct=1.62, confidence=95.6,
         estimated_tonnage=21500, safety_score=34, risk_level='critical', status='flagged',
         last_scan='2026-06-08T11:02:00Z', depth_meters=55),
    dict(id='RW-KRG-09', name='Karongi Beryl Zone', district='Karongi', lat=-2.0031, lng=29.3781,
         primary_mineral='beryl', secondary_minerals=['lithium'], grade_pct=0.88, confidence=82.3,
         estimated_tonnage=5100, safety_score=76, risk_level='low', status='active',
         last_scan='2026-06-06T13:40:00Z', depth_meters=18),
    dict(id='RW-RTS-10', name='Rutsiro Gold Belt', district='Rutsiro', lat=-1.9312, lng=29.3312,
         primary_mineral='gold', secondary_minerals=['wolframite'], grade_pct=3.6, confidence=90.1,
         estimated_tonnage=2800, safety_score=67, risk_level='moderate', status='active',
         last_scan='2026-06-08T06:28:00Z', depth_meters=15),
]


class Command(BaseCommand):
    help = 'Seed a demo organisation, the 4 demo users, and the 10 demo sites used by the frontend.'

    def handle(self, *args, **options):
        org, created = Organisation.objects.get_or_create(
            slug='mdmis-rwanda',
            defaults=dict(
                name='MDMIS Rwanda Operations',
                country_code='RW',
                license_tier='enterprise',
                primary_contact_email='admin@mdmis.rw',
            ),
        )
        self.stdout.write(self.style.SUCCESS(f"{'Created' if created else 'Using'} organisation: {org.name}"))

        for email, full_name, role in DEMO_USERS:
            user, created = User.objects.get_or_create(
                email=email,
                defaults=dict(full_name=full_name, role=role, organisation=org, is_active=True, is_staff=(role == 'system_admin')),
            )
            if created:
                user.set_password(DEMO_PASSWORD)
                user.save()
                self.stdout.write(self.style.SUCCESS(f'Created user: {email} ({role})'))
            else:
                self.stdout.write(f'User already exists: {email}')

        for data in DEMO_SITES:
            site_id = data['id']
            last_scan = timezone.datetime.fromisoformat(data['last_scan'].replace('Z', '+00:00'))
            site, created = Site.objects.update_or_create(
                id=site_id,
                defaults=dict(
                    organisation=org,
                    name=data['name'],
                    district=data['district'],
                    lat=data['lat'],
                    lng=data['lng'],
                    primary_mineral=data['primary_mineral'],
                    secondary_minerals=data['secondary_minerals'],
                    grade_pct=data['grade_pct'],
                    confidence=data['confidence'],
                    estimated_tonnage=data['estimated_tonnage'],
                    safety_score=data['safety_score'],
                    risk_level=data['risk_level'],
                    status=data['status'],
                    last_scan=last_scan,
                    depth_meters=data['depth_meters'],
                ),
            )
            self.stdout.write(f"{'Created' if created else 'Updated'} site: {site_id}")

        self.stdout.write(self.style.SUCCESS('Seed complete. Demo login password for all demo users: ' + DEMO_PASSWORD))
