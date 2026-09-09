"""Encode data/trajectories.json into src/template.html to make the standalone page.

The series are stored as second-order differences of scaled integers, LEB128
varints, base64.  Second differences of smooth motion are small, so this gets
the whole 13-year dataset down to a few hundred kB with no runtime dependency
beyond atob().
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "trajectories.json"
TEMPLATE = Path(__file__).resolve().parent / "template.html"
OUT = ROOT / "heliotrajectories.html"

PLACEHOLDER = "/*__DATA__*/"

# Quantisation.  1e-6 AU is 150 m; 1e-3 deg is 2.6 km at 1 AU and 120 m at
# Parker Solar Probe's perihelion - far below anything the page can draw.
SCALES = {"r": 1_000_000, "lon": 1_000, "lat": 1_000, "t": 1}


def varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def zigzag(value: int) -> int:
    return 2 * value if value >= 0 else -2 * value - 1


def encode(values: list[float], scale: int) -> str:
    ints = [round(v * scale) for v in values]
    stream = bytearray()
    previous_delta = 0
    for i, value in enumerate(ints):
        if i == 0:
            residual = value
        elif i == 1:
            residual = value - ints[0]
            previous_delta = residual
        else:
            delta = value - ints[i - 1]
            residual = delta - previous_delta
            previous_delta = delta
        stream += varint(zigzag(residual))
    return base64.b64encode(bytes(stream)).decode("ascii")


def decode(blob: str, count: int, scale: int) -> list[float]:
    """Reference implementation of the page's decoder, used to verify the encoding."""
    raw = base64.b64decode(blob)
    out: list[float] = []
    pos = previous = previous_delta = 0
    for i in range(count):
        shift = value = 0
        while True:
            byte = raw[pos]
            pos += 1
            value |= (byte & 0x7F) << shift
            shift += 7
            if not byte & 0x80:
                break
        residual = value // 2 if value % 2 == 0 else -(value + 1) // 2
        if i == 0:
            current = residual
        elif i == 1:
            previous_delta = residual
            current = previous + previous_delta
        else:
            previous_delta += residual
            current = previous + previous_delta
        out.append(current / scale)
        previous = current
    return out


def main() -> None:
    data = json.loads(DATA.read_text())
    objects = []
    total_bytes = 0
    print("Encoding")
    for obj in data["objects"]:
        count = len(obj["t"])
        record = {k: obj[k] for k in ("key", "name", "short", "kind", "note")}
        record["n"] = count
        for optional in ("predictedFrom", "predictedNote"):
            if optional in obj:
                record[optional] = obj[optional]
        for field in ("t", "r", "lon", "lat"):
            blob = encode(obj[field], SCALES[field])
            # verify losslessness against the rounded series before shipping it
            restored = decode(blob, count, SCALES[field])
            expected = [round(v * SCALES[field]) / SCALES[field] for v in obj[field]]
            if restored != expected:
                raise SystemExit(f"round-trip failed for {obj['key']}.{field}")
            record[field] = blob
            total_bytes += len(blob)
        objects.append(record)
        print(f"  {obj['short']:8s} {count:6d} samples -> "
              f"{sum(len(record[f]) for f in 'tr') + len(record['lon']) + len(record['lat']):8d} B base64")

    payload = {
        "generated": data["generated"],
        "epoch": data["epoch"],
        "frame": data["frame"],
        "source": data["source"],
        "scales": SCALES,
        "objects": objects,
    }
    blob = json.dumps(payload, separators=(",", ":"))
    html = TEMPLATE.read_text()
    if PLACEHOLDER not in html:
        raise SystemExit(f"{TEMPLATE} has no {PLACEHOLDER} placeholder")
    OUT.write_text(html.replace(PLACEHOLDER, blob))
    print(f"\nWrote {OUT} - {OUT.stat().st_size / 1e6:.2f} MB "
          f"({total_bytes / 1e6:.2f} MB of that is trajectory data)")


if __name__ == "__main__":
    main()
