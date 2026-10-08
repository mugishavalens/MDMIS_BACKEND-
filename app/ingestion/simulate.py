"""Sensor simulator — behaves like a real field device pushing live
readings into MDMIS with its API key (the "direct injection" path).

Register a device in the web app (Sensor Data → Devices) to get its key, then:

    python -m app.ingestion.simulate --key mdk_... --type gas
    python -m app.ingestion.simulate --key mdk_... --type gas --spike   # breach CO threshold
    python -m app.ingestion.simulate --key mdk_... --type geotechnical --api https://your-backend/api

Sends one reading every --interval seconds until stopped (Ctrl+C), or
--count readings if given.
"""
import argparse
import math
import random
import time
from datetime import datetime, timezone

import httpx


def gas_reading(t: int, spike: bool) -> dict:
    co = 8 + 3 * math.sin(t / 6) + random.uniform(-1, 1)
    if spike and t >= 3:
        co = 48 + random.uniform(0, 12)  # above the 35 ppm default threshold
    return {
        "co_ppm": round(co, 1),
        "h2s_ppm": round(max(0.0, 1.2 + random.uniform(-0.4, 0.4)), 2),
        "ch4_pct_lel": round(max(0.0, 2.5 + random.uniform(-0.8, 0.8)), 2),
        "o2_pct": round(20.8 + random.uniform(-0.15, 0.1), 2),
        "co2_ppm": round(900 + 150 * math.sin(t / 9) + random.uniform(-40, 40)),
    }


def geotechnical_reading(t: int, spike: bool) -> dict:
    rate = 0.2 + random.uniform(-0.05, 0.05)
    if spike and t >= 3:
        rate = 1.6 + random.uniform(0, 0.8)  # above the 1 mm/h default threshold
    return {
        "displacement_rate_mm_per_h": round(rate, 3),
        "slope_angle_deg": round(38 + random.uniform(-0.3, 0.3), 2),
        "pore_pressure_kpa": round(95 + random.uniform(-4, 4), 1),
    }


GENERATORS = {"gas": gas_reading, "geotechnical": geotechnical_reading}


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate an MDMIS field sensor.")
    parser.add_argument("--key", required=True, help="Device API key (mdk_...)")
    parser.add_argument("--api", default="http://localhost:8002/api", help="MDMIS API base URL")
    parser.add_argument("--type", choices=sorted(GENERATORS), default="gas")
    parser.add_argument("--interval", type=float, default=5.0, help="Seconds between readings")
    parser.add_argument("--count", type=int, default=0, help="Stop after N readings (0 = run forever)")
    parser.add_argument("--spike", action="store_true", help="Push values over the safety threshold after a few readings")
    parser.add_argument("--lat", type=float, default=None)
    parser.add_argument("--lng", type=float, default=None)
    args = parser.parse_args()

    generate = GENERATORS[args.type]
    t = 0
    with httpx.Client(base_url=args.api, headers={"X-Device-Key": args.key}, timeout=30) as client:
        while True:
            reading = {"recorded_at": datetime.now(timezone.utc).isoformat(), "values": generate(t, args.spike)}
            if args.lat is not None and args.lng is not None:
                reading.update(lat=args.lat, lng=args.lng)
            try:
                r = client.post("/ingest/readings", json={"readings": [reading]})
            except httpx.HTTPError as e:
                print(f"[{t}] network error: {e}")
            else:
                if r.status_code == 201:
                    body = r.json()
                    line = f"[{t}] sent {reading['values']}"
                    for inc in body["incidentsCreated"]:
                        line += f"\n    ⚠ incident opened: {inc['description']}"
                    print(line)
                else:
                    print(f"[{t}] rejected {r.status_code}: {r.text}")
                    if r.status_code in (401, 403):
                        return
            t += 1
            if args.count and t >= args.count:
                return
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
