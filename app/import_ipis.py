"""Import real artisanal mining sites from IPIS open data as MDMIS sites.

Source: IPIS (International Peace Information Service), "Artisanal mining
sites in Eastern DRC" — https://ipisresearch.be/home/maps-data/open-data/
Licence: Open Data Commons Attribution (ODC-BY) v1.0 — any screen or report
showing these sites must credit IPIS.

What comes from IPIS: name, GPS position, territory, minerals, and armed
presence at the most recent visit. What doesn't: grade, tonnage, depth,
confidence — IPIS records field visits, not resource estimates, so those
stay 0 rather than being made up.

risk_level from the latest visit's armed presence (OECD due-diligence red
flags, a starting rule that's easy to change):
  non-state armed group recorded -> critical
  only army (FARDC) / police      -> high
  nothing recorded                -> moderate  (eastern DRC baseline)

Default selection: one province, each site's latest visit, visited 2017 or
later, the N largest sites (by workers) per MDMIS mineral. --all imports
every matching site.

Usage:
  python -m app.import_ipis --csv path/to/cod_mines_curated_all_opendata_p_ipis.csv
  python -m app.import_ipis --csv ... --province Nord-Kivu --per-mineral 5
  python -m app.import_ipis --csv ... --all
"""
import argparse
import asyncio
import csv
import unicodedata
from datetime import date

from sqlalchemy import select

from app.accounts.models import Organisation
from app.database import AsyncSessionLocal
from app.sites.models import Site

# IPIS mineral names (French) -> MDMIS MINERAL_CHOICES. Anything else is ignored.
MINERAL_MAP = {
    "coltan": "coltan",
    "cassiterite": "cassiterite",
    "wolframite": "wolframite",
    "or": "gold",
    "tourmaline": "gemstone",
    "amethyste": "gemstone",
    "diamant": "gemstone",
}


def _norm(name: str) -> str:
    """Accent- and case-insensitive key, so "Cassitérite" matches
    "cassiterite" whatever encoding the name arrived in."""
    return unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().strip().lower()
STATE_FORCES = ("FARDC", "PNC", "Police")
PROVINCE_CODES = {"Nord-Kivu": "NK", "Sud-Kivu": "SK", "Ituri": "IT", "Maniema": "MN", "Tanganyika": "TG"}


def _minerals(row: dict) -> list[str]:
    out = []
    for col in ("mineral1", "mineral2", "mineral3"):
        m = MINERAL_MAP.get(_norm(row.get(col)))
        if m and m not in out:
            out.append(m)
    return out


def _risk(row: dict) -> str:
    groups = [(row.get(f"armed_group{i}") or "").strip() for i in (1, 2, 3)]
    groups = [g for g in groups if g and g.lower() != "nan"]
    if any(not g.startswith(STATE_FORCES) for g in groups):
        return "critical"
    return "high" if groups else "moderate"


def _date(value: str) -> date | None:
    try:
        return date.fromisoformat((value or "")[:10])
    except ValueError:
        return None


def _workers(row: dict) -> float:
    try:
        return float(row.get("workers_numb") or 0)
    except ValueError:
        return 0.0


def select_sites(csv_path: str, province: str, per_mineral: int, take_all: bool, since_year: int,
                 minerals: list[str]) -> list[dict]:
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f) if (r.get("province") or "").strip() == province]

    latest: dict[str, dict] = {}  # one row per site: its most recent visit
    for r in rows:
        r["visit_date"] = _date(r.get("visit_date"))
        if r["visit_date"] is None:
            continue
        prev = latest.get(r["pcode"])
        if prev is None or r["visit_date"] > prev["visit_date"]:
            latest[r["pcode"]] = r

    sites = []
    for r in latest.values():
        if r["visit_date"].year < since_year or not r.get("latitude") or not r.get("longitude"):
            continue
        r["minerals"] = _minerals(r)
        if not r["minerals"]:
            continue
        r["primary"] = r["minerals"][0]
        if r["primary"] not in minerals:
            continue
        r["territoire"] = (r.get("territoire") or "").strip()
        sites.append(r)

    sites.sort(key=_workers, reverse=True)
    if take_all:
        return sites
    picked, per = [], {}
    for r in sites:
        if per.get(r["primary"], 0) < per_mineral:
            picked.append(r)
            per[r["primary"]] = per.get(r["primary"], 0) + 1
    return sorted(picked, key=lambda r: (r["primary"], -_workers(r)))


async def import_sites(rows: list[dict], province: str, org_slug: str) -> None:
    code = PROVINCE_CODES.get(province, province[:2].upper())
    async with AsyncSessionLocal() as db:
        org = await db.scalar(select(Organisation).where(Organisation.slug == org_slug))
        if org is None:
            raise SystemExit(f"No organisation with slug {org_slug!r} — run `python -m app.seed` first.")
        for r in rows:
            site_id = f"CD-{code}-{r['pcode'].replace('codmine', '')}"
            data = dict(
                name=r["name"].strip(),
                district=r["territoire"],
                country_code="CD",
                lat=float(r["latitude"]),
                lng=float(r["longitude"]),
                primary_mineral=r["primary"],
                secondary_minerals=r["minerals"][1:],
                risk_level=_risk(r),
                status="active",
            )
            site = await db.get(Site, site_id)
            if site is None:
                db.add(Site(id=site_id, organisation_id=org.id, **data))
                action = "added"
            else:
                for k, v in data.items():
                    setattr(site, k, v)
                action = "updated"
            workers = f"{int(_workers(r))} workers" if _workers(r) else "workers n/a"
            print(f"{action:7s} {site_id:13s} {data['name'][:22]:22s} {data['district']:9s} "
                  f"{'/'.join(r['minerals']):24s} risk={data['risk_level']:8s} {workers}, "
                  f"visited {r['visit_date']}")
        await db.commit()
    print(f"\n{len(rows)} sites. Data: IPIS open data (ODC-BY) - credit IPIS wherever shown.")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--csv", required=True)
    p.add_argument("--province", default="Nord-Kivu")
    p.add_argument("--per-mineral", type=int, default=3)
    p.add_argument("--since-year", type=int, default=2017)
    p.add_argument("--minerals", default="coltan,cassiterite,wolframite,gold",
                   help="primary minerals to include (MDMIS names, comma-separated)")
    p.add_argument("--all", action="store_true")
    p.add_argument("--org-slug", default="mdmis-rwanda", help="organisation the sites belong to")
    a = p.parse_args()
    rows = select_sites(a.csv, a.province, a.per_mineral, a.all, a.since_year, a.minerals.split(","))
    asyncio.run(import_sites(rows, a.province, a.org_slug))


if __name__ == "__main__":
    main()
