# mdmis-backend

Django + Django REST Framework backend for MDMIS (Mineral Detection & Mining
Intelligence System), targeting Neon (serverless Postgres).

## Apps

- `accounts` — Organisation + custom User model (10 SRS roles), JWT auth (register/login/refresh/me)
- `sites` — mining sites/concessions
- `scans` — ScanSession, MineralZone
- `traceability` — MineralBatch, CustodyEvent (chain of custody)
- `safety` — SafetyIncident
- `transport` — Shipment
- `compliance` — ComplianceReport

All client-data models are scoped to `organisation` and enforced at the API
layer via `common.permissions.OrgScopedQuerysetMixin` — one org can never
read or write another org's records (`system_admin` is the only exception).

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
cp .env.example .env          # fill in DATABASE_URL (Neon connection string)
python manage.py migrate
python manage.py seed_demo    # creates demo org, 4 demo users, 10 sites
python manage.py runserver
```

Without a `DATABASE_URL` set, it falls back to a local `db.sqlite3` so the
project runs out of the box.

## Demo accounts (after `seed_demo`)

All use password `demo1234`:

- `admin@mdmis.rw` — system_admin
- `analyst@mdmis.rw` — mine_manager
- `geo@mdmis.rw` — geologist
- `compliance@mdmis.rw` — compliance_manager
