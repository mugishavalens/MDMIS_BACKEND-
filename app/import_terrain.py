"""Load 3D-block terrain produced by mdmis-ml-service into site_terrains.

mdmis-ml-service's scripts/ingest_terrain.py writes one folder per site,
data/terrain/<site id>/dem_grid.json (the frontend's DemGrid shape). This
copies each one whose site exists in this database, replacing what was
stored before. Run it against whichever database the app uses — locally,
or the deployed one by setting DATABASE_URL for that run.

Usage:
  python -m app.import_terrain --dir ../mdmis-ml-service/data/terrain
  python -m app.import_terrain --dir ... --site RW-RTG-01 --site CD-NK-0001
"""
import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.sites.models import Site, SiteTerrain

REQUIRED_KEYS = ("elevations", "gridSize", "minElevation", "maxElevation")


def load_grid(path: Path) -> dict:
    grid = json.loads(path.read_text(encoding="utf-8"))
    missing = [k for k in REQUIRED_KEYS if k not in grid]
    if missing:
        raise ValueError(f"{path}: not a DemGrid, missing {missing}")
    return grid


async def run(terrain_dir: Path, only: set[str]) -> None:
    files = {p.parent.name: p for p in sorted(terrain_dir.glob("*/dem_grid.json"))}
    if only:
        files = {k: v for k, v in files.items() if k in only}
    async with AsyncSessionLocal() as db:
        known = set((await db.execute(select(Site.id).where(Site.id.in_(files)))).scalars())
        loaded = 0
        for site_id, path in files.items():
            if site_id not in known:
                print(f"  skip {site_id}: no such site in this database")
                continue
            grid = load_grid(path)
            source = str(grid.get("source", ""))[:200]
            row = await db.get(SiteTerrain, site_id)
            if row is None:
                db.add(SiteTerrain(site_id=site_id, grid=grid, source=source))
            else:
                row.grid, row.source = grid, source
            loaded += 1
            print(f"  {site_id}: {grid['gridSize']}x{grid['gridSize']}, "
                  f"{grid['minElevation']:.0f}-{grid['maxElevation']:.0f} m ({source or 'no source'})")
        await db.commit()
    print(f"Loaded terrain for {loaded} of {len(files)} site folder(s).")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dir", required=True, type=Path, help="mdmis-ml-service/data/terrain")
    p.add_argument("--site", action="append", default=[], help="only these site ids (repeatable)")
    a = p.parse_args()
    asyncio.run(run(a.dir, set(a.site)))


if __name__ == "__main__":
    main()
