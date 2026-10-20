#!/usr/bin/env python3
"""Generate worker/seed.sql — the fake Groupe Auto Laval service calendar.

Rules (from SPEC-phase1.md §2):
  * business days (Mon-Fri) starting 2026-10-16, for 21 business days
  * 07:30 to 16:00 in steps of 90 minutes, 3 bays
  * every service type available on every slot
  * roughly 30% of slots already taken, from a deterministic hash so the file
    is reproducible byte-for-byte
  * times are America/Toronto wall clock, stored as UTC ISO instants

Run:  uv run python scripts/gen_seed.py
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Toronto")
START = date(2026, 10, 16)
BUSINESS_DAYS = 21
FIRST_SLOT = time(7, 30)
LAST_SLOT = time(16, 0)
STEP_MINUTES = 90
BAYS = 3
TAKEN_PCT = 30

SERVICE_TYPES = [
    "oil_change",
    "tires",
    "recall_repair",
    "diagnostic",
    "maintenance",
]

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "worker" / "seed.sql"


def business_days(start: date, count: int) -> list[date]:
    days: list[date] = []
    cursor = start
    while len(days) < count:
        if cursor.weekday() < 5:  # Mon-Fri
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def slot_times() -> list[time]:
    times: list[time] = []
    cursor = datetime.combine(date(2000, 1, 1), FIRST_SLOT)
    end = datetime.combine(date(2000, 1, 1), LAST_SLOT)
    while cursor <= end:
        times.append(cursor.time())
        cursor += timedelta(minutes=STEP_MINUTES)
    return times


def is_taken(day_idx: int, time_idx: int, bay: int) -> bool:
    """Deterministic pseudo-random 30%: hash the coordinates, not the clock."""
    key = f"allo-{day_idx}-{time_idx}-{bay}".encode()
    return int.from_bytes(hashlib.sha256(key).digest()[:4], "big") % 100 < TAKEN_PCT


def main() -> None:
    days = business_days(START, BUSINESS_DAYS)
    times = slot_times()

    types_json = json.dumps(SERVICE_TYPES, separators=(",", ":")).replace("'", "''")
    rows: list[str] = []
    total = taken = 0
    for day_idx, day in enumerate(days):
        for time_idx, tm in enumerate(times):
            local = datetime.combine(day, tm, tzinfo=TZ)
            utc_iso = local.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            for bay in range(1, BAYS + 1):
                slot_id = f"{day.isoformat()}-{tm.strftime('%H%M')}-b{bay}"
                taken_flag = 1 if is_taken(day_idx, time_idx, bay) else 0
                total += 1
                taken += taken_flag
                rows.append(
                    "  ('{id}', '{ts}', {bay}, '{types}', {taken})".format(
                        id=slot_id,
                        ts=utc_iso,
                        bay=bay,
                        types=types_json,
                        taken=taken_flag,
                    )
                )

    body = ",\n".join(rows)
    sql = f"""-- GENERATED FILE — do not hand-edit. Regenerate with:
--   uv run python scripts/gen_seed.py
--
-- Groupe Auto Laval service calendar: {len(days)} business days from {days[0]} to {days[-1]},
-- {len(times)} slots/day ({times[0].strftime('%H:%M')}-{times[-1].strftime('%H:%M')} step {STEP_MINUTES}m),
-- {BAYS} bays. {total} slots, {taken} pre-taken ({taken * 100 // total}%).
-- service_types is a JSON array; the Worker JSON.parses it before matching.

DELETE FROM slots;
DELETE FROM appointments;

INSERT INTO slots (id, start_ts, bay, service_types, taken) VALUES
{body};
"""
    OUT.write_text(sql, encoding="utf-8")
    print(f"wrote {OUT} — {total} slots, {taken} taken ({taken * 100 // total}%)")


if __name__ == "__main__":
    main()
