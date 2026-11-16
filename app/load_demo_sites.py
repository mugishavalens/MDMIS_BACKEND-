"""Load the 10 shared demo sites into a database, without any user accounts.

For production: app.seed also creates demo logins whose passwords are in
this repo, which must not exist on the live site. This creates only the demo
organisation (no users) and its sites, marked shared so every organisation
sees them read-only. Safe to run again. Then load their 3D terrain:

  python -m app.load_demo_sites
  python -m app.import_terrain --dir ../mdmis-ml-service/data/terrain
"""
import asyncio
from datetime import datetime

from sqlalchemy import select

import app.models_registry  # noqa: F401
from app.accounts.models import Organisation
from app.database import AsyncSessionLocal
from app.seed import DEMO_SITES
from app.sites.models import Site


async def main() -> None:
    async with AsyncSessionLocal() as db:
        org = await db.scalar(select(Organisation).where(Organisation.slug == "mdmis-rwanda"))
        if org is None:
            org = Organisation(name="MDMIS Rwanda Operations", slug="mdmis-rwanda", country_code="RW",
                               license_tier="enterprise", primary_contact_email="admin@mdmis.rw")
            db.add(org)
            await db.flush()
            print("Created demo organisation (no users)")
        for data in DEMO_SITES:
            if await db.get(Site, data["id"]) is None:
                last_scan = datetime.fromisoformat(data["last_scan"].replace("Z", "+00:00"))
                db.add(Site(organisation_id=org.id, is_shared=True, **{**data, "last_scan": last_scan}))
                print(f"Created site: {data['id']}")
        await db.commit()


if __name__ == "__main__":
    asyncio.run(main())
