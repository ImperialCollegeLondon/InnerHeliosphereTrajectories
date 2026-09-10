"""Check that the object labels hold still while time runs.

Two markers on top of one another used to trade places from frame to frame -
BepiColombo sitting on Mercury was the obvious case - because the labels were
laid out in paint order, which reverses as soon as the depth ordering does.
This steps the real slider frame by frame, records where every Bepi/Mercury
label is drawn, and reports the moves that are too big to be a label simply
following its marker.

    python3 src/labelcheck.py            # check the built page
    python3 src/labelcheck.py HEAD~1     # and compare against an older one

Non-zero exit if the built page shows any discontinuous move.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "heliotrajectories.html"
STAGE = ROOT / "shots"          # Edge is a Windows binary: it can only open /mnt/c
EDGE = "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"

# Headless --dump-dom produces no compositor frames, so requestAnimationFrame
# never fires and the page's render loop would never run.  Put it on a timer.
SHIM = ("<script>window.requestAnimationFrame="
        "cb=>setTimeout(()=>cb(performance.now()),16);</script>")

# Captures every label the renderer draws, one list per frame.
DRIVER = """<script>
addEventListener('load',()=>setTimeout(async()=>{
 const done=t=>{const d=document.createElement('div');d.id='__labels';d.textContent=t;
                document.body.appendChild(d);};
 try{
  const cap=[], proto=CanvasRenderingContext2D.prototype, orig=proto.fillText;
  proto.fillText=function(t,x,y){cap.push([t,Math.round(x),Math.round(y)]);
                                 return orig.apply(this,arguments);};
  const j=document.getElementById('jump'); j.value='__DATE__';
  j.dispatchEvent(new Event('change'));
  const sp=document.getElementById('span'); sp.value='__SPAN__';
  sp.dispatchEvent(new Event('change'));
  const z=document.querySelector('[data-zoom="__ZOOM__"]'); if(z) z.click();
  const tick=()=>new Promise(r=>setTimeout(r,40));
  const s=document.getElementById('time'), lo=+s.min, hi=+s.max, N=__FRAMES__, out=[];
  await tick();
  for(let k=0;k<=N;k++){
    s.value=String(Math.round(lo+(hi-lo)*k/N));
    s.dispatchEvent(new Event('input'));
    cap.length=0;
    await tick();
    out.push(cap.filter(e=>/Bepi|Mercury|·/.test(e[0]))
                .map(e=>e[0].trim()+'@'+e[1]+','+e[2]));
  }
  done(JSON.stringify(out));
 }catch(e){ done('ERR '+e.message); }
},400));
</script>"""

# name, date the window is centred on, slider span (s), zoom preset, frames
SCENES = [
    ("bepi-at-mercury", "2027-06-01", "86400", "1.05", 60),   # exactly coincident
    ("bepi-flyby", "2025-01-08", "86400", "0.34", 60),        # a Mercury flyby, zoomed in
    ("bepi-near-mercury", "2026-11-20", "604800", "1.05", 60),
]


def edge(args, seconds=120):
    """Run Edge, tolerating the headless process failing to exit on its own."""
    try:
        return subprocess.run(args, capture_output=True, timeout=seconds, text=True).stdout
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        return out.decode("utf-8", "replace") if isinstance(out, bytes) else out


def probe(page: Path, tag: str, scene) -> list[list[str]] | str:
    _, date, span, zoom, frames = scene
    driver = (DRIVER.replace("__DATE__", date).replace("__SPAN__", span)
                    .replace("__ZOOM__", zoom).replace("__FRAMES__", str(frames)))
    html = page.read_text()
    html = html.replace("<body>", "<body>" + SHIM, 1)
    html = html.replace("</body>", driver + "</body>", 1)
    tmp = STAGE / f"_labels_{tag}.html"
    STAGE.mkdir(exist_ok=True)
    tmp.write_text(html)
    url = "file:///" + str(tmp).replace("/mnt/c/", "C:/")
    dom = edge([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                "--virtual-time-budget=25000", "--window-size=1440,900",
                "--dump-dom", url])
    match = re.search(r'id="__labels"[^>]*>(.*?)</div>', dom, re.S)
    if not match:
        return "NO REPORT (page did not finish)"
    text = match.group(1)
    return text if text.startswith("ERR") else json.loads(text)


def discontinuities(frames: list[list[str]]) -> list[tuple[int, str, int, int]]:
    """Label moves too large to be it tracking its marker.

    Following a marker shifts a label a few pixels per frame; taking a
    different vertical slot moves it by a whole 15 px step, and swapping sides
    of the marker by more than its own width.
    """
    def positions(frame):
        out = {}
        for entry in frame:
            name, pos = entry.split("@")
            x, y = pos.split(",")
            out[name] = (int(x), int(y))
        return out

    jumps = []
    for i in range(1, len(frames)):
        before, after = positions(frames[i-1]), positions(frames[i])
        for name in sorted(before.keys() & after.keys()):
            dx = after[name][0] - before[name][0]
            dy = after[name][1] - before[name][1]
            if abs(dy) >= 12 or abs(dx) >= 25:
                jumps.append((i, name, dx, dy))
    return jumps


def report(label: str, frames) -> int:
    if isinstance(frames, str):
        print(f"  {label:9s} {frames}")
        return -1
    jumps = discontinuities(frames)
    shared = sum(1 for f in frames if any(e.startswith("·") for e in f))
    detail = "; ".join(f"frame {i} {name} moved {dx:+d},{dy:+d}"
                       for i, name, dx, dy in jumps[:4])
    print(f"  {label:9s} {len(frames):3d} frames, {len(jumps):3d} discontinuous moves, "
          f"{shared:3d} frames with one shared label"
          + (f"\n            {detail}" if detail else ""))
    return len(jumps)


if __name__ == "__main__":
    against = sys.argv[1] if len(sys.argv) > 1 else None
    old = None
    if against:
        old = STAGE / "_labels_old.html"
        STAGE.mkdir(exist_ok=True)
        old.write_text(subprocess.run(
            ["git", "show", f"{against}:heliotrajectories.html"],
            cwd=ROOT, capture_output=True, text=True, check=True).stdout)

    bad = 0
    for scene in SCENES:
        print(scene[0])
        if old:
            report(against, probe(old, "old_" + scene[0], scene))
        bad += max(0, report("page", probe(PAGE, "new_" + scene[0], scene)))
    for leftover in STAGE.glob("_labels_*.html"):
        leftover.unlink()
    print("\n" + ("stable" if bad == 0 else f"{bad} discontinuous label moves"))
    sys.exit(1 if bad else 0)
