"""Frames, time conversions and two-body propagation."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

DEG = math.pi / 180.0

# --- constants ---------------------------------------------------------------
# IAU solar rotation axis (right ascension / declination, ICRF) and the J2000
# obliquity of the ecliptic.
SUN_POLE_RA = 286.13 * DEG
SUN_POLE_DEC = 63.87 * DEG
OBLIQUITY = 23.439291111 * DEG

AU_KM = 149597870.7
GM_SUN = 2.959122082855911e-4      # AU^3 / day^2
L1_DISTANCE_KM = 1.5e6             # Sun-Earth L1, sunward of the Earth

EPOCH = datetime(2018, 1, 1, tzinfo=timezone.utc)
EPOCH_JD = 2458119.5               # 2018-01-01 00:00 TDB


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(v):
    n = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    return (v[0] / n, v[1] / n, v[2] / n)


def _hci_basis():
    """Rows of the ICRF -> HCI rotation matrix.

    HCI (heliocentric inertial) is the solar equatorial frame: z along the solar
    rotation axis, x towards the ascending node of the solar equator on the
    J2000 ecliptic.  This construction reproduces the standard values
    i = 7.25 deg, Omega = 75.76 deg (Franz & Harper 2002).
    """
    z_sun = (
        math.cos(SUN_POLE_DEC) * math.cos(SUN_POLE_RA),
        math.cos(SUN_POLE_DEC) * math.sin(SUN_POLE_RA),
        math.sin(SUN_POLE_DEC),
    )
    z_ecliptic = (0.0, -math.sin(OBLIQUITY), math.cos(OBLIQUITY))
    x = _norm(_cross(z_ecliptic, z_sun))
    y = _norm(_cross(z_sun, x))
    return x, y, _norm(z_sun)


HCI_X, HCI_Y, HCI_Z = _hci_basis()


def icrf_to_hci(x: float, y: float, z: float) -> tuple[float, float, float]:
    v = (x, y, z)
    return (
        HCI_X[0] * v[0] + HCI_X[1] * v[1] + HCI_X[2] * v[2],
        HCI_Y[0] * v[0] + HCI_Y[1] * v[1] + HCI_Y[2] * v[2],
        HCI_Z[0] * v[0] + HCI_Z[1] * v[1] + HCI_Z[2] * v[2],
    )


def spherical(x: float, y: float, z: float) -> tuple[float, float, float]:
    """Cartesian -> (radius AU, longitude deg in [0,360), latitude deg)."""
    r = math.sqrt(x * x + y * y + z * z)
    lon = math.atan2(y, x) / DEG % 360.0
    lat = math.asin(max(-1.0, min(1.0, z / r))) / DEG if r else 0.0
    return r, lon, lat


def unwrap(longitudes: list[float]) -> list[float]:
    """Make a longitude series continuous, so it can be interpolated safely."""
    out: list[float] = []
    offset = 0.0
    previous = None
    for lon in longitudes:
        if previous is not None:
            delta = lon + offset - previous
            if delta > 180.0:
                offset -= 360.0
            elif delta < -180.0:
                offset += 360.0
        value = lon + offset
        out.append(value)
        previous = value
    return out


# --- time --------------------------------------------------------------------
def jd_to_seconds(jd: float) -> int:
    """Seconds since 2018-01-01T00:00 (Horizons TDB treated as UTC; ~69 s offset)."""
    return int(round((jd - EPOCH_JD) * 86400.0))


def jd_to_datetime(jd: float) -> datetime:
    return EPOCH + timedelta(seconds=jd_to_seconds(jd))


def datetime_to_jd(when: datetime) -> float:
    return EPOCH_JD + (when - EPOCH).total_seconds() / 86400.0


def parse_horizons_time(text: str) -> datetime:
    """'2020-Feb-10 04:56:58.8550' -> datetime."""
    date_part, _, time_part = text.partition(" ")
    stamp = datetime.strptime(date_part, "%Y-%b-%d").replace(tzinfo=timezone.utc)
    if time_part:
        hh, mm, ss = time_part.split(":")
        stamp += timedelta(hours=int(hh), minutes=int(mm), seconds=float(ss))
    return stamp


def fmt(when: datetime) -> str:
    return when.strftime("%Y-%m-%d %H:%M")


# --- two-body propagation ----------------------------------------------------
def propagate(state: tuple[float, ...], dt_days: float) -> tuple[float, float, float]:
    """Keplerian two-body propagation of (x,y,z,vx,vy,vz) by dt days.

    Used only to extend STEREO-A past the end of its SPK, where it is in free
    heliocentric drift and a two-body arc is a good approximation.
    """
    x, y, z, vx, vy, vz = state
    r0 = math.sqrt(x * x + y * y + z * z)
    v0sq = vx * vx + vy * vy + vz * vz
    rv = x * vx + y * vy + z * vz

    energy = v0sq / 2.0 - GM_SUN / r0
    a = -GM_SUN / (2.0 * energy)

    # eccentricity and semi-latus rectum from the angular momentum vector
    hx, hy, hz = _cross((x, y, z), (vx, vy, vz))
    h = math.sqrt(hx * hx + hy * hy + hz * hz)
    p = h * h / GM_SUN
    ecc = math.sqrt(max(0.0, 1.0 - p / a))

    # eccentric anomaly at the initial epoch
    cos_e = (1.0 - r0 / a) / ecc if ecc else 0.0
    sin_e = rv / (ecc * math.sqrt(GM_SUN * a)) if ecc else 0.0
    e0 = math.atan2(sin_e, max(-1.0, min(1.0, cos_e)))

    n = math.sqrt(GM_SUN / a ** 3)
    mean = e0 - ecc * math.sin(e0) + n * dt_days

    # Newton solve of Kepler's equation.  The first-order starter matters at
    # Parker Solar Probe's eccentricity (~0.88), where M alone converges poorly.
    ea = mean + ecc * math.sin(mean)
    for _ in range(80):
        f = ea - ecc * math.sin(ea) - mean
        fp = 1.0 - ecc * math.cos(ea)
        step = f / fp
        ea -= step
        if abs(step) < 1e-14:
            break

    # Lagrange f/g functions give the new position from the old state
    de = ea - e0
    f_l = 1.0 - a / r0 * (1.0 - math.cos(de))
    g_l = dt_days + (math.sin(de) - de) / n
    return (f_l * x + g_l * vx, f_l * y + g_l * vy, f_l * z + g_l * vz)
