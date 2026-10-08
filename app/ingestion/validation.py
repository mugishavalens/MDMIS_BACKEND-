"""Sensor file validation (REQ-ING-001 / REQ-ING-002).

Checks, per SRS 4.1.1: the format is one that sensor produces, the bytes
really are that format (magic numbers / header structure), the file isn't
trivially empty, and a geospatial bounding box is present — read from the
file itself where the format carries one (GeoTIFF tags, lat/lon columns),
otherwise supplied by the uploader. Every failure carries the check that
failed and a suggested fix, so the uploader knows what to do.

Pure-Python on purpose: heavy readers (GDAL, h5py) belong in the
preprocessing worker, not in the upload request.
"""
import csv
import io
import json
import struct
from dataclasses import dataclass, field
from pathlib import Path

# SRS 4.1.1 — which formats each sensor produces.
SENSOR_FORMATS: dict[str, set[str]] = {
    "hyperspectral": {"hdf5", "geotiff"},
    "gpr": {"segy", "binary"},
    "em": {"table", "binary"},
    "magnetometer": {"table"},
    "gamma": {"table"},
    "satellite": {"geotiff"},
    "lab": {"table", "json"},
}

EXTENSION_KIND = {
    ".tif": "geotiff", ".tiff": "geotiff",
    ".h5": "hdf5", ".hdf5": "hdf5", ".he5": "hdf5", ".hdf": "hdf5",
    ".sgy": "segy", ".segy": "segy",
    ".dzt": "binary", ".rd3": "binary", ".dt1": "binary", ".bin": "binary",
    ".csv": "table", ".txt": "table", ".xyz": "table", ".asc": "table",
    ".json": "json",
}

KIND_LABEL = {
    "geotiff": "GeoTIFF (.tif)", "hdf5": "HDF5 (.h5)", "segy": "SEG-Y (.sgy)",
    "binary": "binary (.dzt/.bin)", "table": "CSV/ASCII (.csv/.txt/.xyz)", "json": "JSON",
}

MIN_BYTES = 64
_LAT_NAMES = {"lat", "latitude", "y", "lat_dd", "gps_lat"}
_LON_NAMES = {"lon", "lng", "long", "longitude", "x", "lon_dd", "gps_lng", "gps_lon"}
_MAX_TABLE_BYTES = 200 * 1024 * 1024


@dataclass
class ValidationResult:
    kind: str | None = None
    errors: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    bbox: list[float] | None = None  # [min_lng, min_lat, max_lng, max_lat]
    metadata: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def fail(self, check: str, message: str, fix: str) -> None:
        self.errors.append({"check": check, "message": message, "fix": fix})


def _bbox_ok(b) -> bool:
    return (
        b is not None and len(b) == 4
        and -180 <= b[0] <= b[2] <= 180 and -90 <= b[1] <= b[3] <= 90
    )


def validate_sensor_file(
    path: str, filename: str, sensor_type: str, size: int, manual_bbox: list[float] | None = None
) -> ValidationResult:
    r = ValidationResult()
    ext = Path(filename).suffix.lower()
    allowed = SENSOR_FORMATS.get(sensor_type)
    if allowed is None:
        r.fail("sensor_type", f"Unknown sensor type '{sensor_type}'.",
               f"Use one of: {', '.join(SENSOR_FORMATS)}.")
        return r

    kind = EXTENSION_KIND.get(ext)
    accepted = ", ".join(KIND_LABEL[k] for k in sorted(allowed))
    if kind is None or kind not in allowed:
        r.fail("format", f"'{ext or 'no extension'}' is not a {sensor_type} format.",
               f"{sensor_type} files must be {accepted}.")
        return r
    r.kind = kind

    if size < MIN_BYTES:
        r.fail("size", f"File is only {size} bytes — it looks empty.", "Re-export the file from the sensor software.")
        return r

    with open(path, "rb") as f:
        {
            "geotiff": _check_geotiff, "hdf5": _check_hdf5, "segy": _check_segy,
            "binary": _check_binary, "table": _check_table, "json": _check_json,
        }[kind](f, size, r)

    if r.ok and r.bbox is None:
        if _bbox_ok(manual_bbox):
            r.bbox = manual_bbox
            r.warnings.append("Bounding box entered manually (not read from the file).")
        else:
            r.fail("geospatial", "No survey area (bounding box) found in the file.",
                   "Enter the survey area's min/max latitude and longitude with the upload.")
    return r


# ---- format checks --------------------------------------------------------------


def _check_geotiff(f, size, r: ValidationResult) -> None:
    head = f.read(16)
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        order = "<" if head[:2] == b"II" else ">"
    elif head[:4] in (b"II+\x00", b"MM\x00+"):
        r.metadata["bigtiff"] = True
        r.warnings.append("BigTIFF: georeferencing is read during preprocessing, not at upload.")
        return
    else:
        r.fail("integrity", "Not a TIFF file (bad header bytes).", "Export the imagery as GeoTIFF.")
        return
    try:
        tags = _read_tiff_tags(f, order, struct.unpack(order + "I", head[4:8])[0])
    except (struct.error, ValueError) as e:
        r.fail("integrity", f"TIFF structure is corrupted ({e}).", "Re-export the GeoTIFF; the file may be truncated.")
        return
    width, height = tags.get(256, [0])[0], tags.get(257, [0])[0]
    r.metadata.update(width=width, height=height, bands=tags.get(277, [1])[0])
    scale, tie = tags.get(33550), tags.get(33922)
    if not (scale and tie and width and height):
        r.warnings.append("GeoTIFF has no ModelTiepoint/PixelScale tags.")
        return
    min_x = tie[3] - tie[0] * scale[0]
    max_y = tie[4] + tie[1] * scale[1]
    bbox = [min_x, max_y - height * scale[1], min_x + width * scale[0], max_y]
    if _bbox_ok(bbox):
        r.bbox = [round(v, 6) for v in bbox]
    else:
        r.warnings.append("GeoTIFF uses a projected CRS; lat/lon extent is computed during preprocessing.")


_TIFF_TYPES = {1: ("B", 1), 3: ("H", 2), 4: ("I", 4), 12: ("d", 8), 11: ("f", 4), 16: ("Q", 8)}


def _read_tiff_tags(f, order: str, ifd_offset: int) -> dict[int, list]:
    f.seek(ifd_offset)
    (count,) = struct.unpack(order + "H", f.read(2))
    if count > 1000:
        raise ValueError("implausible tag count")
    entries = [struct.unpack(order + "HHI4s", f.read(12)) for _ in range(count)]
    tags = {}
    for tag, typ, n, raw in entries:
        if typ not in _TIFF_TYPES or n > 100_000:
            continue
        fmt, width = _TIFF_TYPES[typ]
        if n * width <= 4:
            data = raw[: n * width]
        else:
            f.seek(struct.unpack(order + "I", raw)[0])
            data = f.read(n * width)
        tags[tag] = list(struct.unpack(order + fmt * n, data))
    return tags


def _check_hdf5(f, size, r: ValidationResult) -> None:
    # The HDF5 superblock may sit at 0, 512, 1024, 2048… bytes.
    for offset in (0, 512, 1024, 2048, 4096):
        if offset >= size:
            break
        f.seek(offset)
        if f.read(8) == b"\x89HDF\r\n\x1a\n":
            r.metadata["superblock_offset"] = offset
            return
    r.fail("integrity", "No HDF5 signature found.", "Export the hyperspectral cube as HDF5 or GeoTIFF.")


def _check_segy(f, size, r: ValidationResult) -> None:
    if size < 3600 + 240:
        r.fail("integrity", "Too small for SEG-Y (needs 3600-byte header + a trace).", "Re-export the GPR survey as SEG-Y.")
        return
    f.seek(3216)
    interval, _, samples = struct.unpack(">HHH", f.read(6))
    if interval == 0 or samples == 0:
        r.fail("integrity", "SEG-Y binary header has no sample interval / samples per trace.",
               "The file may not be SEG-Y; re-export from the GPR processing software.")
        return
    r.metadata.update(sample_interval_us=interval, samples_per_trace=samples)


def _check_binary(f, size, r: ValidationResult) -> None:
    r.metadata["bytes"] = size
    r.warnings.append("Raw binary format: contents are checked during preprocessing.")


def _check_table(f, size, r: ValidationResult) -> None:
    if size > _MAX_TABLE_BYTES:
        r.warnings.append("Large table: coordinates are checked during preprocessing.")
        return
    raw = f.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith(("#", "/"))]
    if len(lines) < 2:
        r.fail("integrity", "Table has no data rows.", "Include a header row and at least one reading.")
        return
    try:
        dialect = csv.Sniffer().sniff(lines[0], delimiters=",;\t |")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO("\n".join(lines)), dialect))
    header = [h.strip().lower() for h in rows[0]]
    lat_i = next((i for i, h in enumerate(header) if h in _LAT_NAMES), None)
    lon_i = next((i for i, h in enumerate(header) if h in _LON_NAMES), None)
    r.metadata.update(columns=[h for h in header if h][:40], rows=len(rows) - 1)
    if lat_i is None or lon_i is None:
        r.fail("geospatial", "No latitude/longitude columns found in the header.",
               "Name the coordinate columns 'lat' and 'lon' (or latitude/longitude).")
        return
    _bbox_from_points(((row[lat_i], row[lon_i]) for row in rows[1:] if len(row) > max(lat_i, lon_i)), len(rows) - 1, r)


def _check_json(f, size, r: ValidationResult) -> None:
    try:
        data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        r.fail("integrity", f"Invalid JSON ({e}).", "Check the export; the file may be truncated.")
        return
    items = data.get("samples", data.get("readings")) if isinstance(data, dict) else data
    if not isinstance(items, list) or not items or not all(isinstance(i, dict) for i in items):
        r.fail("integrity", "Expected a list of samples (or {\"samples\": [...]}).", "Export one object per sample.")
        return
    r.metadata["rows"] = len(items)

    def coord(item, names):
        return next((item[k] for k in item if k.lower() in names), None)

    _bbox_from_points(((coord(i, _LAT_NAMES), coord(i, _LON_NAMES)) for i in items), len(items), r)


def _bbox_from_points(points, total: int, r: ValidationResult) -> None:
    lats, lons, bad = [], [], 0
    for lat, lon in points:
        try:
            la, lo = float(lat), float(lon)
        except (TypeError, ValueError):
            bad += 1
            continue
        if -90 <= la <= 90 and -180 <= lo <= 180:
            lats.append(la)
            lons.append(lo)
        else:
            bad += 1
    if not lats:
        r.fail("geospatial", "No valid coordinates in the data rows.", "Check the lat/lon columns contain decimal degrees.")
        return
    if bad > max(1, total // 10):
        r.fail("integrity", f"{bad} of {total} rows have missing or invalid coordinates.",
               "Fix or remove the bad rows and upload again.")
        return
    if bad:
        r.warnings.append(f"{bad} row(s) with invalid coordinates were ignored.")
    r.bbox = [round(min(lons), 6), round(min(lats), 6), round(max(lons), 6), round(max(lats), 6)]
