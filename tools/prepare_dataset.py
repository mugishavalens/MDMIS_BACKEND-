"""Prepare an external dataset (Kaggle, open-data portals, survey exports…)
for MDMIS: keep only what MDMIS consumes, drop everything else, and explain
every dropped row.

    python tools/prepare_dataset.py <file.csv|.xlsx|.json> --target magnetometer
    python tools/prepare_dataset.py assays.xlsx --target lab --region none
    python tools/prepare_dataset.py data.csv --target gamma --map th_ppm=eTh_value
    python tools/prepare_dataset.py --list-targets

Deterministic on purpose — no AI decides what is kept. The same input always
gives the same output, and every excluded row is written to *.rejected.csv
with the rule that excluded it, so the selection can be audited.

Outputs, next to the input file:
    <name>.mdmis-<target>.csv   clean data in MDMIS's input format
    <name>.rejected.csv         every dropped row + reason
    <name>.report.json          column mapping, unit conversions, counts per rule
For gas/geotechnical targets also <name>.mdmis-<target>.readings.json, ready
to POST to /api/ingest/readings (batches of 500).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

# ---- Region filter ------------------------------------------------------------

REGIONS = {
    # Rwanda's extent with a small margin (min_lat, min_lon, max_lat, max_lon).
    "rwanda": (-2.90, 28.80, -1.00, 30.95),
}

# ---- Minerals MDMIS tracks (for occurrence datasets) ----------------------------

MINERAL_ALIASES = {
    "cassiterite": ["cassiterite", "tin", "sn", "sno2"],
    "coltan": ["coltan", "columbite", "tantalite", "tantalum", "niobium", "ta", "nb", "ta2o5", "nb2o5"],
    "wolframite": ["wolframite", "tungsten", "wolfram", "scheelite", "w", "wo3"],
    "gold": ["gold", "au"],
    "beryl": ["beryl", "beryllium", "be"],
    "lithium": ["lithium", "li", "spodumene", "lepidolite", "li2o"],
}

# ---- Assay units and oxide → element conversion --------------------------------

# Element mass fraction in the oxide: element % = oxide % × factor.
OXIDE_TO_ELEMENT = {
    "sno2": ("sn", 0.7877), "ta2o5": ("ta", 0.8190), "nb2o5": ("nb", 0.6990),
    "wo3": ("w", 0.7930), "li2o": ("li", 0.4645), "beo": ("be", 0.3603),
}
UNIT_TO_PPM = {"ppm": 1.0, "g/t": 1.0, "gt": 1.0, "ppb": 0.001, "mg/kg": 1.0, "%": 10_000.0, "pct": 10_000.0, "percent": 10_000.0}


@dataclass
class Field:
    name: str                       # output column name (MDMIS format)
    synonyms: list[str]             # normalised header names that map to it
    required: bool = False
    kind: str = "number"            # number | text | datetime
    valid: tuple[float, float] | None = None  # physically plausible range


@dataclass
class Target:
    description: str
    fields: list[Field]
    point: bool = True              # rows carry lat/lon
    need_one_of: list[str] = field(default_factory=list)  # at least one of these must be present per row
    readings: bool = False          # emit /ingest/readings JSON
    assays: bool = False            # map element assays with unit/oxide conversion
    occurrences: bool = False       # filter to MDMIS minerals


LAT = Field("lat", ["lat", "latitude", "y", "lat_dd", "decimallatitude", "gps_lat", "lat_wgs84", "northing_dd"], True, valid=(-90, 90))
LON = Field("lon", ["lon", "lng", "long", "longitude", "x", "lon_dd", "decimallongitude", "gps_lon", "gps_lng", "lon_wgs84"], True, valid=(-180, 180))
TIME = Field("timestamp", ["timestamp", "time", "datetime", "date_time", "date", "recorded_at", "utc", "time_utc"], kind="datetime")

TARGETS: dict[str, Target] = {
    "magnetometer": Target("Ground/drone magnetic survey points → magnetometer upload", [
        TIME, LAT, LON,
        Field("total_field_nT", ["total_field", "total_field_nt", "tmi", "mag", "magnetic_field", "field_nt", "nt", "f", "total_magnetic_intensity"], True, valid=(20_000, 70_000)),
        Field("altitude_m", ["altitude", "alt", "elevation", "height", "altitude_m", "elev"], valid=(-500, 9_000)),
    ]),
    "gamma": Target("Gamma-ray spectrometry points → gamma upload", [
        TIME, LAT, LON,
        Field("k_pct", ["k", "k_pct", "potassium", "k_percent"], valid=(0, 15)),
        Field("u_ppm", ["u", "eu", "u_ppm", "eu_ppm", "uranium"], valid=(0, 1_000)),
        Field("th_ppm", ["th", "eth", "th_ppm", "eth_ppm", "thorium"], valid=(0, 2_000)),
        Field("total_count_cps", ["tc", "total_count", "total_counts", "cps", "dose_rate", "count_rate"], valid=(0, 100_000)),
    ], need_one_of=["k_pct", "u_ppm", "th_ppm", "total_count_cps"]),
    "em": Target("Electromagnetic conductivity points → EM upload", [
        TIME, LAT, LON,
        Field("conductivity_mS_m", ["conductivity", "apparent_conductivity", "ec", "sigma", "conductivity_ms_m", "cond"], valid=(0, 10_000)),
        Field("resistivity_ohm_m", ["resistivity", "apparent_resistivity", "rho", "res"], valid=(0.01, 1_000_000)),
    ], need_one_of=["conductivity_mS_m", "resistivity_ohm_m"]),
    "lab": Target("Laboratory assays → lab spectrometer upload (element ppm)", [
        Field("sample_id", ["sample_id", "sample", "sampleid", "id", "sample_no", "sample_number", "lab_id"], kind="text"),
        LAT, LON,
        Field("depth_m", ["depth", "depth_m", "from", "from_m", "sample_depth"], valid=(0, 3_000)),
    ], assays=True),
    "occurrences": Target("Known mineral occurrences → reference points for MDMIS minerals", [
        Field("name", ["name", "site", "site_name", "deposit", "deposit_name", "occurrence", "locality", "dep_name"], kind="text"),
        LAT, LON,
        Field("commodity", ["commodity", "commod", "commod1", "commodities", "mineral", "minerals", "ore", "commodity_list"], True, kind="text"),
    ], occurrences=True),
    "gas": Target("Gas monitor readings → POST /api/ingest/readings", [
        Field("recorded_at", TIME.synonyms, True, kind="datetime"),
        Field("co_ppm", ["co", "co_ppm", "carbon_monoxide"], valid=(0, 5_000)),
        Field("h2s_ppm", ["h2s", "h2s_ppm", "hydrogen_sulfide", "hydrogen_sulphide"], valid=(0, 1_000)),
        Field("ch4_pct_lel", ["ch4", "ch4_lel", "ch4_pct_lel", "methane", "lel"], valid=(0, 100)),
        Field("o2_pct", ["o2", "o2_pct", "oxygen"], valid=(0, 25)),
        Field("co2_ppm", ["co2", "co2_ppm", "carbon_dioxide"], valid=(0, 100_000)),
    ], point=False, need_one_of=["co_ppm", "h2s_ppm", "ch4_pct_lel", "o2_pct", "co2_ppm"], readings=True),
    "geotechnical": Target("Slope / displacement monitor readings → POST /api/ingest/readings", [
        Field("recorded_at", TIME.synonyms, True, kind="datetime"),
        Field("displacement_rate_mm_per_h", ["displacement_rate", "velocity", "displacement_rate_mm_h", "rate_mm_h", "movement_rate"], valid=(-1_000, 1_000)),
        Field("slope_angle_deg", ["slope_angle", "slope", "angle", "inclination", "tilt"], valid=(0, 90)),
        Field("pore_pressure_kpa", ["pore_pressure", "piezometer", "pore_pressure_kpa", "pwp"], valid=(-100, 5_000)),
    ], point=False, need_one_of=["displacement_rate_mm_per_h", "slope_angle_deg", "pore_pressure_kpa"], readings=True),
}

ASSAY_ELEMENTS = ["sn", "ta", "nb", "w", "au", "li", "be"]

# ---- Header handling ------------------------------------------------------------

_UNIT_IN_HEADER = re.compile(r"[\(\[]\s*([^\)\]]+?)\s*[\)\]]")


def split_header(raw: str) -> tuple[str, str | None]:
    """'Au (ppb)' → ('au', 'ppb'); 'SnO2_pct' → ('sno2', 'pct'); 'Latitude' → ('latitude', None)."""
    text = str(raw).strip()
    unit = None
    m = _UNIT_IN_HEADER.search(text)
    if m:
        unit = m.group(1).strip().lower()
        text = _UNIT_IN_HEADER.sub("", text)
    base = re.sub(r"[^a-z0-9%/]+", "_", text.lower()).strip("_")
    if unit is None:
        for u in ("ppm", "ppb", "pct", "percent", "g_t", "gt", "mg_kg", "%"):
            if base.endswith("_" + u) or (u == "%" and base.endswith("%")):
                unit = {"g_t": "g/t", "mg_kg": "mg/kg"}.get(u, u)
                base = base[: -len(u)].rstrip("_")
                break
    return base.replace("%", ""), unit


def read_any(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        return pd.read_excel(path)
    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = next((v for v in data.values() if isinstance(v, list)), [data])
        return pd.json_normalize(data)
    # CSV/TXT: let pandas sniff the delimiter; tolerate odd encodings.
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return pd.read_csv(path, sep=None, engine="python", encoding=enc)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Can't read {path.name}")


# ---- Core -------------------------------------------------------------------------

def prepare(df: pd.DataFrame, target_key: str, region: tuple | None, overrides: dict[str, str]):
    target = TARGETS[target_key]
    report = {"target": target_key, "input_rows": int(len(df)), "input_columns": [str(c) for c in df.columns],
              "mapping": {}, "conversions": [], "dropped_columns": [], "rejected_by_rule": {}}
    headers = {c: split_header(c) for c in df.columns}
    need_one_of = list(target.need_one_of)
    used: set = set()
    out = pd.DataFrame(index=df.index)

    def find(fld: Field):
        if fld.name in overrides:
            col = overrides[fld.name]
            if col not in df.columns:
                sys.exit(f"--map {fld.name}={col}: no column named '{col}'. Columns: {list(df.columns)}")
            return col
        for col, (base, _unit) in headers.items():
            if col not in used and base in fld.synonyms:
                return col
        return None

    for fld in target.fields:
        col = find(fld)
        if col is None:
            if fld.required:
                sys.exit(f"Required column '{fld.name}' not found. Looked for: {fld.synonyms}.\n"
                         f"Columns in file: {list(df.columns)}\nUse --map {fld.name}=<column> to point at it.")
            continue
        used.add(col)
        report["mapping"][fld.name] = str(col)
        if fld.kind == "datetime":
            out[fld.name] = pd.to_datetime(df[col], errors="coerce", utc=True)
        elif fld.kind == "text":
            out[fld.name] = df[col].astype("string").str.strip()
        else:
            out[fld.name] = pd.to_numeric(df[col], errors="coerce")

    # EM: derive conductivity from resistivity when only that is present.
    if target_key == "em" and "resistivity_ohm_m" in out and "conductivity_mS_m" not in out:
        out["conductivity_mS_m"] = 1000.0 / out["resistivity_ohm_m"]
        report["conversions"].append("conductivity_mS_m = 1000 / resistivity_ohm_m")

    if target.assays:
        for col, (base, unit) in headers.items():
            if col in used:
                continue
            element, factor = base, 1.0
            if base in OXIDE_TO_ELEMENT:
                element, factor = OXIDE_TO_ELEMENT[base]
                unit = unit or "pct"  # oxide grades are conventionally reported in %
            if element not in ASSAY_ELEMENTS:
                continue
            unit = (unit or "ppm").lower()
            if unit not in UNIT_TO_PPM:
                report["conversions"].append(f"skipped '{col}': unknown unit '{unit}'")
                continue
            values = pd.to_numeric(df[col], errors="coerce") * factor * UNIT_TO_PPM[unit]
            name = f"{element}_ppm"
            out[name] = values if name not in out else out[name].fillna(values)
            used.add(col)
            report["mapping"][name] = str(col)
            if factor != 1.0 or unit != "ppm":
                report["conversions"].append(f"{name} ← '{col}' × {factor:g} (oxide→element) × {UNIT_TO_PPM[unit]:g} ({unit}→ppm)"
                                             if factor != 1.0 else f"{name} ← '{col}' × {UNIT_TO_PPM[unit]:g} ({unit}→ppm)")
        need_one_of = [c for c in out.columns if c.endswith("_ppm") and c[:-4] in ASSAY_ELEMENTS]
        if not need_one_of:
            sys.exit("No assay columns (Sn, Ta, Nb, W, Au, Li, Be or their oxides) found. Use --map sn_ppm=<column>.")

    report["dropped_columns"] = [str(c) for c in df.columns if c not in used]
    report["warnings"] = {}
    for fld in target.fields:
        if fld.name in out and not fld.required and fld.name in report["mapping"]:
            src = df[report["mapping"][fld.name]]
            unreadable = int((src.notna() & (src.astype("string").str.strip() != "") & out[fld.name].isna()).sum())
            if unreadable:
                report["warnings"][f"unreadable {fld.name} (row kept, value left blank)"] = unreadable

    # ---- Row rules, applied in order; first failing rule is the recorded reason ----
    reason = pd.Series(pd.NA, index=df.index, dtype="string")

    def reject(mask, rule):
        mask = mask & reason.isna()
        reason[mask] = rule

    for fld in target.fields:
        if fld.name not in out:
            continue
        if fld.required:
            reject(out[fld.name].isna(), f"missing or unreadable {fld.name}")
    if need_one_of:
        present = [c for c in need_one_of if c in out]
        reject(out[present].isna().all(axis=1), f"no usable value in any of: {', '.join(present)}")
    for fld in target.fields:
        if fld.valid and fld.name in out:
            lo, hi = fld.valid
            v = out[fld.name]
            reject(v.notna() & ((v < lo) | (v > hi)), f"{fld.name} outside plausible range {lo:g}–{hi:g}")
    if target.assays:
        for c in need_one_of:
            reject(out[c].notna() & (out[c] < 0), f"negative {c}")
    if target.point and region:
        min_lat, min_lon, max_lat, max_lon = region
        outside = (out["lat"] < min_lat) | (out["lat"] > max_lat) | (out["lon"] < min_lon) | (out["lon"] > max_lon)
        reject((out["lat"] == 0) & (out["lon"] == 0), "placeholder coordinates 0,0")
        reject(out["lat"].notna() & out["lon"].notna() & outside, "outside the selected region")
    if target.occurrences:
        def canonical(text):
            if pd.isna(text):
                return None
            tokens = set(re.split(r"[^a-z0-9]+", str(text).lower()))
            found = [mineral for mineral, aliases in MINERAL_ALIASES.items() if tokens & set(aliases)]
            return ";".join(found) or None
        out["mineral"] = out["commodity"].map(canonical)
        reject(out["mineral"].isna(), "commodity is not a mineral MDMIS tracks")
    if target.readings and "recorded_at" in out:
        reject(out["recorded_at"] > pd.Timestamp.now(tz="UTC"), "timestamp in the future")

    key_cols = [c for c in out.columns if c not in ("commodity",)]
    dup = out[key_cols].duplicated(keep="first")
    reject(dup, "duplicate of an earlier row")

    kept = out[reason.isna()].copy()
    rejected = df[reason.notna()].copy()
    rejected.insert(0, "rejection_reason", reason[reason.notna()])

    # Stable, MDMIS-friendly output.
    for c in ("timestamp", "recorded_at"):
        if c in kept:
            kept[c] = kept[c].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    if "timestamp" in kept and kept["timestamp"].isna().all():
        kept = kept.drop(columns="timestamp")
    kept = kept.dropna(axis=1, how="all")
    numeric = kept.select_dtypes("number").columns
    kept[numeric] = kept[numeric].round(6)

    report["kept_rows"] = int(len(kept))
    report["rejected_rows"] = int(len(rejected))
    report["rejected_by_rule"] = {k: int(v) for k, v in reason.value_counts().items()}
    return kept, rejected, report


def readings_payload(kept: pd.DataFrame) -> list[dict]:
    metrics = [c for c in kept.columns if c not in ("recorded_at",)]
    readings = []
    for row in kept.to_dict(orient="records"):
        values = {m: float(row[m]) for m in metrics if pd.notna(row.get(m))}
        if values:
            readings.append({"recorded_at": row["recorded_at"], "values": values})
    return [{"readings": readings[i:i + 500]} for i in range(0, len(readings), 500)]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Filter an external dataset down to what MDMIS consumes.")
    ap.add_argument("file", nargs="?", type=Path)
    ap.add_argument("--target", choices=sorted(TARGETS))
    ap.add_argument("--region", default="rwanda",
                    help="'rwanda' (default), 'none', or 'min_lat,min_lon,max_lat,max_lon'")
    ap.add_argument("--map", action="append", default=[], metavar="FIELD=COLUMN",
                    help="force a column mapping, e.g. --map total_field_nT=MagField")
    ap.add_argument("--list-targets", action="store_true")
    args = ap.parse_args(argv)

    if args.list_targets or not args.file:
        for key, t in TARGETS.items():
            print(f"{key:13} {t.description}")
        return 0
    if not args.target:
        ap.error("--target is required (see --list-targets)")

    if args.region == "none":
        region = None
    elif args.region in REGIONS:
        region = REGIONS[args.region]
    else:
        region = tuple(float(v) for v in args.region.split(","))
        if len(region) != 4:
            ap.error("--region needs four numbers: min_lat,min_lon,max_lat,max_lon")
    overrides = dict(m.split("=", 1) for m in args.map)

    df = read_any(args.file)
    kept, rejected, report = prepare(df, args.target, region, overrides)
    report["source"] = str(args.file)
    report["region"] = args.region

    stem = args.file.with_suffix("")
    clean_path = Path(f"{stem}.mdmis-{args.target}.csv")
    kept.to_csv(clean_path, index=False)
    rejected.to_csv(Path(f"{stem}.rejected.csv"), index=False)
    if TARGETS[args.target].readings:
        Path(f"{stem}.mdmis-{args.target}.readings.json").write_text(
            json.dumps(readings_payload(kept), indent=1), encoding="utf-8")
    Path(f"{stem}.report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print(f"{args.file.name} → {args.target}: kept {report['kept_rows']} of {report['input_rows']} rows")
    print("  columns used: " + ", ".join(f"{k}←'{v}'" for k, v in report["mapping"].items()))
    if report["dropped_columns"]:
        print(f"  columns dropped ({len(report['dropped_columns'])}): {', '.join(report['dropped_columns'][:12])}"
              + (" …" if len(report["dropped_columns"]) > 12 else ""))
    for c in report["conversions"]:
        print(f"  converted: {c}")
    for rule, n in report["rejected_by_rule"].items():
        print(f"  dropped {n:>5} row(s): {rule}")
    for note, n in report["warnings"].items():
        print(f"  warning {n:>5} row(s): {note}")
    print(f"  wrote {clean_path.name}, {stem.name}.rejected.csv, {stem.name}.report.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
