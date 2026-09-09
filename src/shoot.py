"""Render heliotrajectories.html headlessly in Edge, driving the UI first.

Development aid: each scenario is a snippet of DOM-level JavaScript, so it
exercises the real controls.  Any uncaught error is stamped into the title and
reported here.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "heliotrajectories.html"
SHOTS = ROOT / "shots"
EDGE = "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"

# Headless virtual time freezes CSS transitions at their start value, so a
# screenshot of a sheet mid-transition is misleading.  Static shots only.
FREEZE = "<style>*{transition:none!important;animation:none!important}</style>"

CATCH = """<script>
window.__errors=[];
addEventListener('error',e=>{window.__errors.push(e.message+' @'+e.lineno);});
addEventListener('unhandledrejection',e=>{window.__errors.push('reject '+e.reason);});
</script>"""

REPORT = """<script>
addEventListener('load',()=>setTimeout(()=>{
  const d=document.createElement('div');
  d.id='__report';
  d.textContent = (window.__errors.length ? 'ERRORS: '+window.__errors.join(' | ') : 'OK')
    + ' [viewport '+innerWidth+'x'+innerHeight+']';
  d.style.cssText='position:fixed;left:0;top:0;z-index:99;font:12px monospace;padding:2px 6px;'+
    (window.__errors.length?'background:#c00;color:#fff':'display:none');
  document.body.appendChild(d);
},900));
</script>"""


def edge(args, seconds=45):
    """Run Edge, tolerating the headless process failing to exit on its own."""
    try:
        return subprocess.run(args, capture_output=True, timeout=seconds, text=True).stdout
    except subprocess.TimeoutExpired as exc:
        return (exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) \
            else (exc.stdout or "")

# (window width, window height, driver script).  Note that Edge headless clamps
# the CSS viewport to ~492px wide, so the narrow scenarios actually test around
# there rather than at a true phone width; the report states what was measured.
# The device scale factor only sharpens the PNG, it does not shrink the viewport.
SCENARIOS = {
    "desktop": (1440, 900, ""),
    "fixed-solo": (1440, 900, """
      document.getElementById('frame').value='solo';
      document.getElementById('frame').dispatchEvent(new Event('change'));
      const tr=document.getElementById('trail'); tr.value='120';
      tr.dispatchEvent(new Event('input'));
      document.getElementById('optPaths').click();
      document.querySelector('[data-zoom="3.5"]').click();
    """),
    "pole-fixed-l1": (1440, 900, """
      document.getElementById('frame').value='l1';
      document.getElementById('frame').dispatchEvent(new Event('change'));
      document.getElementById('viewTop').click();
      const tr=document.getElementById('trail'); tr.value='40';
      tr.dispatchEvent(new Event('input'));
      document.getElementById('conn').value='spiral';
      document.getElementById('conn').dispatchEvent(new Event('change'));
      document.querySelector('[data-zoom="3.5"]').click();
    """),
    "psp-perihelion": (1440, 900, """
      const j=document.getElementById('jump'); j.value='2024-12-24';
      j.dispatchEvent(new Event('change'));
      document.getElementById('optPlanets').click();
      const tr=document.getElementById('trail'); tr.value='6';
      tr.dispatchEvent(new Event('input'));
      document.querySelector('[data-zoom="0.34"]').click();
    """),
    "corotating": (1440, 900, """
      document.getElementById('frame').value='corot';
      document.getElementById('frame').dispatchEvent(new Event('change'));
      document.getElementById('viewSide').click();
      const tr=document.getElementById('trail'); tr.value='27';
      tr.dispatchEvent(new Event('input'));
    """),
    "end-of-window": (1440, 900, """
      const j=document.getElementById('jump'); j.value='2029-06-15';
      j.dispatchEvent(new Event('change'));
      document.getElementById('frame').value='psp';
      document.getElementById('frame').dispatchEvent(new Event('change'));
    """),
    "extensions-2030": (1440, 900, """
      const j=document.getElementById('jump'); j.value='2030-12-15';
      j.dispatchEvent(new Event('change'));
      const tr=document.getElementById('trail'); tr.value='45';
      tr.dispatchEvent(new Event('input'));
      document.getElementById('sheetBtn');
    """),
    "narrow": (500, 900, ""),
    "narrow-panel": (500, 900, "document.getElementById('sheetBtn').click();"),
    "tablet": (820, 1180, ""),
    "dark": (1440, 900, """
      const b=document.getElementById('themeBtn'); b.click(); b.click();  /* -> dark */
      const tr=document.getElementById('trail'); tr.value='30';
      tr.dispatchEvent(new Event('input'));
    """),
    "dark-narrow-7d": (500, 900, """
      const b=document.getElementById('themeBtn'); b.click(); b.click();
      const sp=document.getElementById('span'); sp.value='604800';
      sp.dispatchEvent(new Event('change'));
    """),
    "light": (1440, 900, """
      document.getElementById('themeBtn').click();          /* auto -> light */
      const tr=document.getElementById('trail'); tr.value='30';
      tr.dispatchEvent(new Event('input'));
    """),
    "light-fixed-psp": (1440, 900, """
      document.getElementById('themeBtn').click();
      document.getElementById('frame').value='psp';
      document.getElementById('frame').dispatchEvent(new Event('change'));
      document.getElementById('viewTop').click();
      const tr=document.getElementById('trail'); tr.value='60';
      tr.dispatchEvent(new Event('input'));
      document.getElementById('conn').value='spiral';
      document.getElementById('conn').dispatchEvent(new Event('change'));
      document.querySelector('[data-zoom="3.5"]').click();
    """),
    "fine-24h": (1440, 900, """
      const j=document.getElementById('jump'); j.value='2024-12-24';
      j.dispatchEvent(new Event('change'));
      const sp=document.getElementById('span'); sp.value='86400';
      sp.dispatchEvent(new Event('change'));
      document.querySelector('[data-zoom="0.34"]').click();
    """),
    "fine-30d-narrow": (500, 900, """
      const sp=document.getElementById('span'); sp.value='2592000';
      sp.dispatchEvent(new Event('change'));
    """),
}


def run(name: str, width: int, height: int, script: str) -> str:
    html = PAGE.read_text()
    html = html.replace("<body>", "<body>" + FREEZE + CATCH, 1)
    driver = ""
    if script.strip():
        driver = ("<script>addEventListener('load',()=>setTimeout(()=>{try{" + script
                  + "}catch(e){window.__errors.push('driver '+e.message);}},260));</script>")
    html = html.replace("</body>", driver + REPORT + "</body>", 1)

    tmp = SHOTS / f"_{name}.html"
    tmp.write_text(html)
    win = str(tmp).replace("/mnt/c/", "C:\\").replace("/", "\\")
    url = "file:///" + str(tmp).replace("/mnt/c/", "C:/")
    shot = str(SHOTS / f"{name}.png").replace("/mnt/c/", "C:\\").replace("/", "\\")

    scale = 2 if width < 900 else 1
    size = f"{width},{height}"
    base = [EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
            "--virtual-time-budget=7000", f"--window-size={size}",
            f"--force-device-scale-factor={scale}"]
    png = SHOTS / f"{name}.png"
    if png.exists():
        png.unlink()
    edge(base + [f"--screenshot={shot}", url])
    dom = edge(base + ["--dump-dom", url])
    match = re.search(r'id="__report"[^>]*>([^<]*)<', dom)
    status = match.group(1) if match else "NO REPORT (page did not finish)"
    if not png.exists():
        status = "NO SCREENSHOT; " + status
    return status


if __name__ == "__main__":
    wanted = sys.argv[1:] or list(SCENARIOS)
    failed = False
    for name in wanted:
        width, height, script = SCENARIOS[name]
        result = run(name, width, height, script)
        print(f"{name:16s} asked {width}x{height:<6d} {result}")
        failed |= not result.startswith("OK")
    for leftover in SHOTS.glob("_*.html"):
        leftover.unlink()
    stray = SHOTS / "Dropdown.png"      # Edge sometimes emits this alongside a shot
    if stray.exists():
        stray.unlink()
    sys.exit(1 if failed else 0)
