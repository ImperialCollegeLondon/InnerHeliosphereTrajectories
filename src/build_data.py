"""Download trajectories from JPL Horizons and reduce them to a compact dataset.

Sampling is adaptive: every object is fetched at one-day cadence, then any
stretch where the heliocentric angular rate is high (chiefly Parker Solar
Probe's perihelia, also Solar Orbiter's) is re-fetched at a finer step, so the
stored series never takes a step larger than ~5 degrees of heliocentric
longitude.  That keeps the file small while staying smooth through perihelion.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import astro
import horizons
from horizons import HorizonsRangeError, Request

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "trajectories.json"

WINDOW_START = datetime(2018, 1, 1, tzinfo=timezone.utc)
WINDOW_END = datetime(2030, 12, 31, tzinfo=timezone.utc)

# Every object is sampled at one-day cadence; these refinements are then laid
# over the top wherever the daily heliocentric angular rate exceeds the given
# threshold.  Measured against the real Parker Solar Probe ephemeris, cubic
# interpolation of one-day samples misplaces it by up to 1.6e6 km (11 deg of
# longitude) at perihelion, four-hour samples by 8000 km (0.07 deg), so 240 min
# is the workhorse and 60 min is a safety net for the deepest perihelia.
BASE_STEP = 1440
REFINEMENTS = [(240, 5.0), (60, 40.0)]


@dataclass
class Target:
    key: str
    command: str
    name: str
    short: str
    kind: str = "spacecraft"          # 'spacecraft' | 'planet'
    refine: bool = True               # adaptive sub-day sampling
    l1_offset: bool = False           # shift sunward to the L1 point
    extend: str | None = None         # 'kepler' | 'mercury'
    note: str = ""
    samples: list[list[float]] = field(default_factory=list)   # [jd, x, y, z] ICRF
    predicted_from: float | None = None                        # JD


# How each extension past the end of an SPK is described on the page.
EXTENSION_TEXT = {
    "kepler": "then a two-body propagation of its final state",
    "mercury": "then Mercury's position, by which time it is in orbit there",
}

TARGETS = [
    Target("solo", "-144", "Solar Orbiter", "SolO", extend="kepler",
           note="Launched 2020-02-10."),
    Target("psp", "-96", "Parker Solar Probe", "PSP", extend="kepler",
           note="Launched 2018-08-12."),
    Target("l1", "399", "L1 (Earth)", "L1", refine=False, l1_offset=True,
           note="Earth's position shifted 1.5 million km sunward to the L1 point."),
    Target("bepi", "-121", "BepiColombo", "Bepi", extend="mercury",
           note="Launched 2018-10-20."),
    Target("stereoa", "-234", "STEREO-A", "STA", refine=False, extend="kepler",
           note="In free heliocentric drift."),
    Target("mercury", "199", "Mercury", "Mercury", kind="planet", refine=False),
    Target("venus", "299", "Venus", "Venus", kind="planet", refine=False),
    Target("mars", "499", "Mars", "Mars", kind="planet", refine=False),
]

BY_KEY = {t.key: t for t in TARGETS}


# --- fetching ----------------------------------------------------------------
def fetch_span(target: Target, start: datetime, stop: datetime, step_minutes: int,
               *, velocities: bool = False) -> list[list[float]]:
    """Fetch one interval, splitting it so no single request is over-long."""
    step = f"{step_minutes} m" if step_minutes % 1440 else f"{step_minutes // 1440} d"
    span_minutes = (stop - start).total_seconds() / 60.0
    chunks = max(1, math.ceil(span_minutes / step_minutes / horizons.MAX_ROWS_PER_REQUEST))
    edges = [start + (stop - start) * i / chunks for i in range(chunks + 1)]

    rows: list[list[float]] = []
    for a, b in zip(edges, edges[1:]):
        req = Request(target.command, astro.fmt(a), astro.fmt(b), step, velocities)
        rows.extend(horizons.parse(horizons.raw(req)))
    return rows


def clamped_daily(target: Target) -> tuple[list[list[float]], datetime, datetime]:
    """One-day cadence over the whole window, narrowed to the SPK's coverage."""
    start, stop = WINDOW_START, WINDOW_END
    for _ in range(4):
        try:
            rows = fetch_span(target, start, stop, BASE_STEP)
            return rows, start, stop
        except HorizonsRangeError as exc:
            limit = astro.parse_horizons_time(exc.when)
            if exc.side == "prior to":
                # start on the first whole day inside coverage
                start = (limit + timedelta(days=1)).replace(hour=0, minute=0, second=0,
                                                            microsecond=0)
                print(f"    coverage starts {astro.fmt(start)}")
            else:
                stop = limit.replace(hour=0, minute=0, second=0, microsecond=0)
                print(f"    coverage ends   {astro.fmt(stop)}")
    raise RuntimeError(f"could not bracket the ephemeris of {target.name}")


def angular_rates(rows: list[list[float]]) -> list[float]:
    """Heliocentric angular rate (deg/day) for each gap between samples."""
    rates = []
    for (jd0, x0, y0, z0), (jd1, x1, y1, z1) in zip(rows, rows[1:]):
        n0 = math.sqrt(x0 * x0 + y0 * y0 + z0 * z0)
        n1 = math.sqrt(x1 * x1 + y1 * y1 + z1 * z1)
        dot = (x0 * x1 + y0 * y1 + z0 * z1) / (n0 * n1)
        angle = math.acos(max(-1.0, min(1.0, dot))) / astro.DEG
        rates.append(angle / max(1e-9, jd1 - jd0))
    return rates


def refine_intervals(rows: list[list[float]], rate_limit: float,
                     pad_days: float = 1.0, merge_days: float = 2.0):
    """Intervals where the one-day sampling is too coarse, padded and merged."""
    rates = angular_rates(rows)
    spans: list[list[float]] = []
    for i, rate in enumerate(rates):
        if rate <= rate_limit:
            continue
        a, b = rows[i][0] - pad_days, rows[i + 1][0] + pad_days
        if spans and a - spans[-1][1] <= merge_days:
            spans[-1][1] = b
        else:
            spans.append([a, b])
    return spans


def collect(target: Target) -> None:
    print(f"  {target.name}")
    daily, start, stop = clamped_daily(target)
    daily.sort(key=lambda r: r[0])
    merged = {astro.jd_to_seconds(r[0]): r for r in daily}

    if target.refine:
        for step_minutes, rate_limit in REFINEMENTS:
            # Rates are always judged on the one-day series, so each refinement
            # threshold means what it says regardless of earlier passes.
            for a, b in refine_intervals(daily, rate_limit):
                lo = max(start, astro.jd_to_datetime(a))
                hi = min(stop, astro.jd_to_datetime(b))
                if hi <= lo:
                    continue
                for row in fetch_span(target, lo, hi, step_minutes):
                    merged[astro.jd_to_seconds(row[0])] = row

    target.samples = sorted(merged.values(), key=lambda r: r[0])
    print(f"    {len(target.samples)} samples, "
          f"{astro.fmt(astro.jd_to_datetime(target.samples[0][0]))} -> "
          f"{astro.fmt(astro.jd_to_datetime(target.samples[-1][0]))}")


# --- extensions past the end of an SPK ---------------------------------------
def extend_kepler(target: Target) -> None:
    """Continue the trajectory as a two-body orbit about the Sun.

    Propagation is analytic, so the extension is sampled on the same adaptive
    grid as the real ephemeris: one day, refined where the object moves fast.
    That matters for Parker Solar Probe, whose extension crosses four perihelia.
    """
    last_jd = target.samples[-1][0]
    end = astro.jd_to_datetime(last_jd)
    if end >= WINDOW_END - timedelta(days=1):
        return
    state_rows = fetch_span(target, end - timedelta(days=1), end, 1440, velocities=True)
    anchor_jd, *state = state_rows[-1]
    state = tuple(state)
    target.predicted_from = anchor_jd
    stop_jd = astro.datetime_to_jd(WINDOW_END)

    def at(jd: float) -> list[float]:
        x, y, z = astro.propagate(state, jd - anchor_jd)
        return [jd, x, y, z]

    step_days = BASE_STEP / 1440.0
    count = int((stop_jd - anchor_jd) / step_days)
    added = {astro.jd_to_seconds(anchor_jd + i * step_days):
             at(anchor_jd + i * step_days) for i in range(count + 1)}

    if target.refine:
        coarse = sorted(added.values(), key=lambda r: r[0])
        for step_minutes, rate_limit in REFINEMENTS:
            fine = step_minutes / 1440.0
            for a, b in refine_intervals(coarse, rate_limit):
                jd = max(anchor_jd, a)
                while jd <= min(stop_jd, b):
                    added[astro.jd_to_seconds(jd)] = at(jd)
                    jd += fine

    # the anchor epoch itself is already present from the real ephemeris
    added.pop(astro.jd_to_seconds(anchor_jd), None)
    target.samples.extend(sorted(added.values(), key=lambda r: r[0]))
    target.samples.sort(key=lambda r: r[0])
    print(f"    two-body extension from {astro.fmt(end)}: "
          f"+{len(added)} samples to {astro.fmt(WINDOW_END)}")


def extend_with_mercury(target: Target) -> None:
    mercury = BY_KEY["mercury"]
    last_jd = target.samples[-1][0]
    if astro.jd_to_datetime(last_jd) >= WINDOW_END - timedelta(days=1):
        return
    target.predicted_from = last_jd
    added = [row for row in mercury.samples if row[0] > last_jd + 0.5]
    target.samples.extend(added)
    print(f"    continued as Mercury: +{len(added)} samples from "
          f"{astro.fmt(astro.jd_to_datetime(last_jd))}")


# --- reduction ---------------------------------------------------------------
def reduce_target(target: Target) -> dict:
    times, radii, longitudes, latitudes = [], [], [], []
    for jd, x, y, z, *_ in target.samples:
        hx, hy, hz = astro.icrf_to_hci(x, y, z)
        r, lon, lat = astro.spherical(hx, hy, hz)
        if target.l1_offset:
            r -= astro.L1_DISTANCE_KM / astro.AU_KM
        times.append(astro.jd_to_seconds(jd))
        radii.append(r)
        longitudes.append(lon)
        latitudes.append(lat)

    first = astro.fmt(astro.jd_to_datetime(target.samples[0][0]))[:10]
    last = astro.fmt(astro.jd_to_datetime(target.samples[-1][0]))[:10]
    real_end = (astro.fmt(astro.jd_to_datetime(target.predicted_from))[:10]
                if target.predicted_from is not None else last)

    note = f"{target.note} Horizons ephemeris {first} to {real_end}."
    record = {
        "key": target.key,
        "name": target.name,
        "short": target.short,
        "kind": target.kind,
        "t": times,
        "r": radii,
        "lon": astro.unwrap(longitudes),
        "lat": latitudes,
    }
    if target.predicted_from is not None:
        record["predictedFrom"] = astro.jd_to_seconds(target.predicted_from)
        tail = EXTENSION_TEXT[target.extend]
        note += f" Extended to {last}: {tail}."
        record["predictedNote"] = (f"{target.short}: Horizons ephemeris to {real_end}, "
                                   f"{tail}.")
    record["note"] = note
    return record


def main() -> None:
    print("Fetching from JPL Horizons (cached in data/raw)")
    for target in TARGETS:
        collect(target)
    for target in TARGETS:
        if target.extend == "kepler":
            extend_kepler(target)
        elif target.extend == "mercury":
            extend_with_mercury(target)

    payload = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "epoch": astro.EPOCH.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "frame": ("Heliocentric inertial (HCI): solar equatorial plane, x towards the "
                  "ascending node of the solar equator on the J2000 ecliptic "
                  "(i = 7.25 deg, Omega = 75.76 deg)."),
        "source": "JPL Horizons (ssd.jpl.nasa.gov/api/horizons.api), geometric states about the Sun's centre.",
        "objects": [reduce_target(t) for t in TARGETS],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload))
    total = sum(len(o["t"]) for o in payload["objects"])
    print(f"\nWrote {OUT} - {total} samples, {OUT.stat().st_size / 1e6:.2f} MB raw JSON")


if __name__ == "__main__":
    main()
