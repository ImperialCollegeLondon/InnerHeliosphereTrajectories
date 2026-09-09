"""Sanity checks on data/trajectories.json.

Chiefly: does cubic interpolation of the stored samples reproduce an
independently fetched, much finer ephemeris?  That is the check that matters,
since the page interpolates between stored samples.
"""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import astro
import build_data
import horizons

ROOT = Path(__file__).resolve().parent.parent
DATA = json.loads((ROOT / "data" / "trajectories.json").read_text())
OBJECTS = {o["key"]: o for o in DATA["objects"]}


def stamp(seconds: int) -> str:
    return (astro.EPOCH + timedelta(seconds=seconds)).strftime("%Y-%m-%d %H:%M")


def hermite(ts: list[int], vs: list[float], x: float) -> float:
    """The same non-uniform cubic Hermite the page uses."""
    lo, hi = 0, len(ts) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if ts[mid] <= x:
            lo = mid
        else:
            hi = mid
    h = ts[lo + 1] - ts[lo]
    s = (x - ts[lo]) / h

    def tangent(k: int) -> float:
        a, b = max(0, k - 1), min(len(ts) - 1, k + 1)
        return (vs[b] - vs[a]) / (ts[b] - ts[a])

    m0, m1 = tangent(lo), tangent(lo + 1)
    s2, s3 = s * s, s * s * s
    return ((2 * s3 - 3 * s2 + 1) * vs[lo] + (s3 - 2 * s2 + s) * h * m0
            + (-2 * s3 + 3 * s2) * vs[lo + 1] + (s3 - s2) * h * m1)


def cartesian(r: float, lon: float, lat: float) -> tuple[float, float, float]:
    lon, lat = lon * astro.DEG, lat * astro.DEG
    return (r * math.cos(lat) * math.cos(lon), r * math.cos(lat) * math.sin(lon),
            r * math.sin(lat))


def sample(obj: dict, seconds: float) -> tuple[float, float, float]:
    return (hermite(obj["t"], obj["r"], seconds),
            hermite(obj["t"], obj["lon"], seconds),
            hermite(obj["t"], obj["lat"], seconds))


def report_steps() -> None:
    print("Stored series")
    for obj in DATA["objects"]:
        t, r, lon, lat = obj["t"], obj["r"], obj["lon"], obj["lat"]
        worst, when = 0.0, None
        for i in range(len(t) - 1):
            angle = math.hypot((lon[i + 1] - lon[i]) * math.cos(lat[i] * astro.DEG),
                               lat[i + 1] - lat[i])
            if angle > worst:
                worst, when = angle, t[i]
        gaps = [t[i + 1] - t[i] for i in range(len(t) - 1)]
        flag = "" if worst < 8.0 else "   <-- coarse"
        print(f"  {obj['short']:8s} n={len(t):6d}  r {min(r):.4f}-{max(r):.4f} AU  "
              f"lat {min(lat):+6.2f}..{max(lat):+6.2f}  step {min(gaps)//60:4.0f}-{max(gaps)//60:4.0f} min"
              f"  worst gap {worst:5.2f} deg @ {stamp(when)}{flag}")
        if not math.isclose(sorted(t)[0], t[0]) or any(b <= a for a, b in zip(t, t[1:])):
            raise SystemExit(f"{obj['key']}: times not strictly increasing")


def check_against_horizons(key: str, start: str, days: int, step: str) -> None:
    """Compare interpolated positions with a fresh fine-cadence Horizons fetch."""
    target = build_data.BY_KEY[key]
    obj = OBJECTS[key]
    begin = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    rows = horizons.parse(horizons.raw(horizons.Request(
        target.command, astro.fmt(begin), astro.fmt(begin + timedelta(days=days)), step)))

    worst_km, worst_lon, when = 0.0, 0.0, None
    for jd, x, y, z in rows:
        seconds = astro.jd_to_seconds(jd)
        if seconds < obj["t"][0] or seconds > obj["t"][-1]:
            continue
        hx, hy, hz = astro.icrf_to_hci(x, y, z)
        r, lon, lat = astro.spherical(hx, hy, hz)
        if target.l1_offset:
            r -= astro.L1_DISTANCE_KM / astro.AU_KM
        ir, ilon, ilat = sample(obj, seconds)
        error = math.dist(cartesian(r, lon, lat), cartesian(ir, ilon, ilat))
        dlon = abs((ilon - lon + 180) % 360 - 180)
        if error > worst_km:
            worst_km, when = error, seconds
        worst_lon = max(worst_lon, dlon)
    print(f"  {obj['short']:8s} vs {step:>6s} Horizons, {start} +{days}d: "
          f"max {worst_km * astro.AU_KM:8.0f} km, {worst_lon:.3f} deg lon @ {stamp(when)}")


def backtest_kepler(key: str, anchor_date: str, days: int, checkpoints) -> None:
    """How well does two-body propagation stand in for the real ephemeris?

    Anchors on a state Horizons does have, propagates over the same length as
    the object's real extension, and compares.  A gravity assist inside the
    window shows up here as a large error, which is exactly what we need to know.
    """
    target = build_data.BY_KEY[key]
    anchor = datetime.strptime(anchor_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    rows = horizons.parse(horizons.raw(horizons.Request(
        target.command, astro.fmt(anchor - timedelta(days=1)), astro.fmt(anchor),
        "1440 m", True)))
    jd, *state = rows[-1]
    state = tuple(state)
    truth = horizons.parse(horizons.raw(horizons.Request(
        target.command, astro.fmt(anchor), astro.fmt(anchor + timedelta(days=days)),
        "360 m")))
    print(f"  {target.short} two-body from {anchor_date}, over {days} days:")
    for elapsed in checkpoints:
        tj, tx, ty, tz = min(truth, key=lambda r: abs(r[0] - (jd + elapsed)))
        px, py, pz = astro.propagate(state, tj - jd)
        error = math.dist((tx, ty, tz), (px, py, pz)) * astro.AU_KM
        real = astro.spherical(*astro.icrf_to_hci(tx, ty, tz))
        pred = astro.spherical(*astro.icrf_to_hci(px, py, pz))
        dlon = (pred[1] - real[1] + 180) % 360 - 180
        print(f"    +{elapsed:4.0f} d: {error:10.0f} km, dlon {dlon:+7.3f} deg "
              f"(r = {real[0]:.3f} AU)")


def closest_approach(craft: str, other: str, start: str, end: str) -> tuple[float, int]:
    a, b = OBJECTS[craft], OBJECTS[other]
    begin = int((datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                 - astro.EPOCH).total_seconds())
    finish = int((datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                  - astro.EPOCH).total_seconds())
    best, when = float("inf"), begin
    for seconds in range(begin, finish, 3600):
        gap = math.dist(cartesian(*sample(a, seconds)), cartesian(*sample(b, seconds)))
        if gap < best:
            best, when = gap, seconds
    return best * astro.AU_KM, when


def check_extension_encounters() -> None:
    """A two-body extension is only meaningful if nothing deflects the object.

    Real gravity assists come within tens of thousands of km, so anything at
    millions of km leaves the extension undisturbed.
    """
    print("Encounters inside the two-body extensions")
    for key in ("psp", "solo", "stereoa"):
        obj = OBJECTS[key]
        if "predictedFrom" not in obj:
            continue
        start = stamp(obj["predictedFrom"])[:10]
        end = stamp(obj["t"][-1])[:10]
        for other in ("venus", "mercury", "l1"):
            if other == key:
                continue
            gap, when = closest_approach(key, other, start, end)
            flag = "   <-- close enough to perturb" if gap < 2e6 else ""
            print(f"  {obj['short']:5s} {start}..{end} vs {OBJECTS[other]['short']:8s}"
                  f" {gap/1e6:8.2f} million km at {stamp(when)}{flag}")
    print("  for scale, real gravity assists:")
    for craft, other, a, b, label in (
            ("psp", "venus", "2024-10-01", "2024-12-01", "Parker, Nov 2024"),
            ("solo", "venus", "2029-05-01", "2029-08-01", "Solar Orbiter, Jun 2029"),
            ("solo", "venus", "2030-07-01", "2030-11-01", "Solar Orbiter, Sep 2030")):
        gap, when = closest_approach(craft, other, a, b)
        print(f"    {label:26s} {gap/1e6:8.3f} million km at {stamp(when)}")


def check_joins() -> None:
    """Look for a kink where predicted data takes over.

    A Kepler extension starts from the Horizons state at the join, so position
    and velocity are continuous by construction and only the acceleration can
    jump.  The day-to-day change in step length therefore has to be judged
    against how much it varies anyway in the real data either side - Parker is
    accelerating hard towards perihelion at its join, and that is not an error.
    BepiColombo's join is a substitution rather than a propagation, so there the
    position itself can move.
    """
    print("Continuity at predicted-data joins")
    day = 86400.0
    for key in ("psp", "solo", "stereoa", "bepi"):
        obj = OBJECTS[key]
        if "predictedFrom" not in obj:
            continue
        join = obj["predictedFrom"]
        points = [cartesian(*sample(obj, join + k*day)) for k in range(-5, 6)]
        steps = [math.dist(a, b) * astro.AU_KM for a, b in zip(points, points[1:])]
        changes = [abs(b - a) for a, b in zip(steps, steps[1:])]
        at_join = changes[4]
        others = sorted(changes[:4] + changes[5:])
        typical = others[len(others)//2]
        ratio = at_join/typical if typical else float("inf")
        verdict = "smooth" if ratio < 3 else "KINK"
        print(f"  {obj['short']:5s} {stamp(join)}: daily step {steps[4]:.0f} -> "
              f"{steps[5]:.0f} km; change across join {at_join:.0f} km vs "
              f"{typical:.0f} km typical nearby ({ratio:.1f}x, {verdict})")


def check_stereo_drift() -> None:
    print("STEREO-A longitude relative to L1 (expect ~+22 deg/yr)")
    previous = None
    for year in range(2018, 2031):
        seconds = int((datetime(year, 7, 1, tzinfo=timezone.utc) - astro.EPOCH).total_seconds())
        a = sample(OBJECTS["stereoa"], seconds)[1]
        b = sample(OBJECTS["l1"], seconds)[1]
        separation = (a - b + 180) % 360 - 180
        rate = "" if previous is None else f"  ({separation - previous:+6.2f} deg/yr)"
        print(f"  {year}-07-01: {separation:+8.2f} deg{rate}")
        previous = separation


def check_earth_b0() -> None:
    """Earth's heliographic latitude: +7.25 in early September, -7.25 in early March."""
    print("Earth/L1 heliographic latitude (B0 check)")
    for date in ("2024-03-06", "2024-06-06", "2024-09-07", "2024-12-07"):
        when = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        seconds = int((when - astro.EPOCH).total_seconds())
        r, lon, lat = sample(OBJECTS["l1"], seconds)
        print(f"  {date}: lat {lat:+.3f} deg, r {r:.5f} AU")


if __name__ == "__main__":
    report_steps()
    print("\nInterpolation accuracy (independent fine-cadence fetches)")
    check_against_horizons("psp", "2024-12-22", 6, "5 m")     # closest perihelion, 0.046 AU
    check_against_horizons("psp", "2019-04-01", 8, "5 m")     # early, shallower perihelion
    check_against_horizons("solo", "2023-04-07", 10, "10 m")  # Solar Orbiter perihelion
    check_against_horizons("bepi", "2021-10-01", 10, "10 m")  # Mercury flyby period
    check_against_horizons("l1", "2025-01-01", 30, "30 m")
    check_against_horizons("stereoa", "2020-06-01", 30, "30 m")
    print()
    print("Two-body extension accuracy (back-tested against the real ephemeris)")
    # Parker's real extension is a year from 2030-01-01; test equivalent years.
    backtest_kepler("psp", "2029-01-01", 365, [30, 90, 180, 270, 365])
    # Solar Orbiter's is 41 days from 2030-11-20, after its Sep 2030 Venus assist.
    backtest_kepler("solo", "2030-06-01", 41, [10, 20, 41])
    # The same test across a Venus assist, to show what a flyby would do to it.
    backtest_kepler("solo", "2029-06-01", 41, [10, 20, 41])
    print()
    check_extension_encounters()
    print()
    check_joins()
    print()
    check_stereo_drift()
    print()
    check_earth_b0()
