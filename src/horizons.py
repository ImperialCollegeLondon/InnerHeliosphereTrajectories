"""Thin, caching client for the JPL Horizons API (vector ephemerides)."""

from __future__ import annotations

import hashlib
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

API = "https://ssd.jpl.nasa.gov/api/horizons.api"
CACHE = Path(__file__).resolve().parent.parent / "data" / "raw"

# Horizons refuses very long tables; keep each request comfortably below the limit.
MAX_ROWS_PER_REQUEST = 6000
_MIN_INTERVAL = 0.25  # seconds between calls, to be a polite API citizen
_last_call = 0.0

_NO_EPHEM = re.compile(
    r'No ephemeris for target "(?P<target>[^"]*)" (?P<side>prior to|after) '
    r"A\.D\. (?P<when>[0-9]{4}-[A-Za-z]{3}-[0-9]{2} [0-9:.]+)"
)


class HorizonsRangeError(Exception):
    """Raised when the requested interval falls outside the object's ephemeris."""

    def __init__(self, side: str, when: str):
        super().__init__(f"ephemeris limit ({side} {when})")
        self.side = side  # 'prior to' | 'after'
        self.when = when  # e.g. '2020-Feb-10 04:56:58.8550'


@dataclass(frozen=True)
class Request:
    command: str
    start: str
    stop: str
    step: str
    velocities: bool = False

    def params(self) -> list[tuple[str, str]]:
        return [
            ("format", "text"),
            ("COMMAND", f"'{self.command}'"),
            ("OBJ_DATA", "'NO'"),
            ("MAKE_EPHEM", "'YES'"),
            ("EPHEM_TYPE", "'VECTORS'"),
            ("CENTER", "'500@10'"),          # Sun body centre
            ("REF_PLANE", "'FRAME'"),        # ICRF; rotated to HCI ourselves
            ("REF_SYSTEM", "'ICRF'"),
            ("VEC_CORR", "'NONE'"),          # geometric states
            ("VEC_TABLE", "'2'" if self.velocities else "'1'"),
            ("VEC_LABELS", "'NO'"),
            ("OUT_UNITS", "'AU-D'"),
            ("CSV_FORMAT", "'YES'"),
            ("START_TIME", f"'{self.start}'"),
            ("STOP_TIME", f"'{self.stop}'"),
            ("STEP_SIZE", f"'{self.step}'"),
        ]

    def cache_path(self) -> Path:
        blob = repr(self.params()).encode()
        digest = hashlib.sha1(blob).hexdigest()[:16]
        safe = self.command.replace("-", "m")
        return CACHE / f"{safe}_{self.start[:10]}_{self.step.replace(' ', '')}_{digest}.txt"


def _throttle() -> None:
    global _last_call
    wait = _MIN_INTERVAL - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def raw(req: Request, *, refresh: bool = False, verbose: bool = True) -> str:
    """Return the raw Horizons response text, using the on-disk cache if possible."""
    path = req.cache_path()
    if path.exists() and not refresh:
        return path.read_text()

    url = API + "?" + urllib.parse.urlencode(req.params())
    if verbose:
        print(f"    GET {req.command} {req.start[:16]} -> {req.stop[:16]} @ {req.step}", flush=True)
    last_error: Exception | None = None
    for attempt in range(4):
        _throttle()
        try:
            with urllib.request.urlopen(url, timeout=180) as resp:
                text = resp.read().decode("utf-8", "replace")
            break
        except Exception as exc:  # transient network/server hiccups
            last_error = exc
            time.sleep(2 * (attempt + 1))
    else:
        raise RuntimeError(f"Horizons request failed after retries: {last_error}")

    limit = _NO_EPHEM.search(text)
    if limit:
        raise HorizonsRangeError(limit.group("side"), limit.group("when"))
    if "$$SOE" not in text:
        head = "\n".join(text.splitlines()[:25])
        raise RuntimeError(f"Unexpected Horizons reply for {req.command}:\n{head}")

    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return text


def parse(text: str) -> list[list[float]]:
    """Extract the ephemeris rows as [jdtdb, x, y, z, (vx, vy, vz)] in AU and AU/day."""
    rows: list[list[float]] = []
    inside = False
    for line in text.splitlines():
        if line.startswith("$$SOE"):
            inside = True
            continue
        if line.startswith("$$EOE"):
            break
        if not inside:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            continue
        # columns: JDTDB, calendar date, X, Y, Z[, VX, VY, VZ]
        values = [float(parts[0])] + [float(p) for p in parts[2:] if p]
        rows.append(values)
    return rows


def vectors(command: str, start: str, stop: str, step: str, **kw) -> list[list[float]]:
    return parse(raw(Request(command, start, stop, step), **kw))
