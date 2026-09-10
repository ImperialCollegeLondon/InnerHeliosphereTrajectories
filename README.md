# Relative Trajectories

All Claude's work. A simple HTML-based viewer for inner heliosphere spacecraft trajectories. Can lock to the longitude of particulr spacecraft or planets. Should work on desktop or mobile. 

Tim Horbury, 10 Sept 2026. 

Builds a single self-contained HTML page — **`heliotrajectories.html`** (~330 kB, no
network access once built) — showing the 3-D trajectories of Solar Orbiter, Parker
Solar Probe, L1/Earth, BepiColombo and STEREO-A in the solar equatorial frame,
with any one spacecraft's longitude held fixed so the others move relative to it.

Open the file in any modern browser, desktop or mobile. Nothing else is needed.
Light and dark themes, following the system preference unless you override it.

## Using the page

| | |
|---|---|
| **Fixed longitude** | The `fix` button beside any object in the list — planets included — or the header dropdown. The chosen object is pinned at 0° longitude and everything else drifts relative to it. Latitudes are never touched. `Inertial (HCI)` is the unrotated frame; `Co-rotating` fixes the frame to the Sun's 25.38-day sidereal rotation. The dropdown lists the spacecraft only, to stay short; a pinned planet appears in it while it is the active frame. |
| **Time** | Slider, `◀`/`▶` step buttons, the date box, or the arrow keys (`⇧` = ten steps, `⌥`/`alt` = 1 hour). Space plays/pauses; playback speed is selectable from ¼ to 90 days/s. |
| **Precision** | The **range** box sets how much time the slider spans — full window, 5/2/1 years, 90/30/7 days or 24 hours — so the slider is as fine as you need (a 24-hour range is about a minute per pixel on a phone). The strip beneath the slider always shows the whole mission: tap or drag it to jump anywhere, and the highlighted box marks the slider's window. `◀`/`▶` step by an amount that follows the range, from 1 day down to 5 minutes. Your choice is remembered. |
| **Theme** | The header button cycles **auto → light → dark** (auto follows the operating system). Remembered between visits. |
| **Trails** | 0–120 days, from the Display section. Trails are computed *in the current frame*, so in a fixed-longitude frame they show genuine relative motion. |
| **Labels** | Markers within ten pixels of one another share a single label naming each of them, so BepiColombo reads as `Bepi · Mercury` once it is in orbit there. Labels are placed in a fixed object order rather than in depth order, and each keeps last frame's position while it remains free, so they stay put during playback. |
| **View** | Drag to rotate, scroll or pinch to zoom, `+`/`-` keys. `Pole` looks down the solar rotation axis, `Edge-on` sits in the solar equator. Zoom presets on the right run from 0.1 AU (Parker perihelion) to the full field. |
| **Connectivity** | Optional radial line or nominal Parker spiral from each spacecraft back to the Sun, with an adjustable solar wind speed (200–900 km/s). |
| **Coverage bars** | The coloured bars in the overview strip show each spacecraft's data span; hatched portions are predicted (see below). |

## Frame

Heliocentric inertial (**HCI**): the solar equatorial plane, with longitude measured
from the ascending node of the solar equator on the J2000 ecliptic. Built directly
from the IAU solar rotation axis (α = 286.13°, δ = 63.87°), which reproduces the
standard `i = 7.2517°`, `Ω = 75.766°`. Latitude is heliographic. Validated against
the known B₀ curve: Earth's latitude peaks at +7.251° on 7 September and −7.252° on
6 March, crossing zero in early June and early December.

Fixing an object's longitude subtracts its longitude from every object's at each
instant — including at every point along the trails and full paths, so the tracks
are true relative trajectories rather than a rotated snapshot.

## Data

Geometric state vectors about the Sun's centre from
[JPL Horizons](https://ssd.jpl.nasa.gov/api/horizons.api), ICRF, rotated to HCI here.

| Object | Horizons ID | Coverage |
|---|---|---|
| Solar Orbiter | −144 | 2020-02-11 → 2030-11-20, then propagated |
| Parker Solar Probe | −96 | 2018-08-13 → 2030-01-01, then propagated |
| L1 (Earth) | 399 | full window |
| BepiColombo | −121 | 2018-10-21 → 2027-04-11, then Mercury |
| STEREO-A | −234 | 2018-01-01 → 2026-12-18, then propagated |
| Mercury, Venus, Mars | 199, 299, 499 | full window |

**L1** is Earth's position moved 1.5 million km sunward; its longitude and latitude
are Earth's.

**Predicted extensions** past the end of an SPK run to the end of 2030, and are
marked with a dashed marker ring and a `†` in the readout; the coverage bars hatch
the same stretch. Three of the four are two-body (Keplerian) propagations of the
object's final Horizons state, sampled on the same adaptive grid as the real data:

| | Propagated from | Length | Accuracy |
|---|---|---|---|
| Parker Solar Probe | 2030-01-01 | 365 d | 0.9–7.4 × 10³ km, ≤ 0.003° of longitude |
| Solar Orbiter | 2030-11-20 | 41 d | 0.1–1.6 × 10³ km, ≤ 0.001° of longitude |
| STEREO-A | 2026-12-18 | 4 yr | drift vs Earth holds at 22.1–22.6°/yr across the join |
| BepiColombo | 2027-04-11 | 3.7 yr | becomes Mercury, by which time it is in orbit there |

The accuracy figures are **back-tested**, not assumed: `validate.py` anchors a
propagation on a state Horizons *does* have, runs it for the same length as the real
extension, and compares. Parker's extension is the most trustworthy of the three —
it has no further Venus assists after November 2024, so its orbit is fixed, and its
four extension perihelia all sit at 0.0458 AU like the real ones.

The obvious hazard is a gravity assist inside an extension, which two-body
propagation knows nothing about. The same back-test across Solar Orbiter's June 2029
Venus assist is wrong by 17 million km (8.8° of longitude) after 41 days, which is
what such an error looks like. So `validate.py` also checks for encounters inside
each extension window, and there are none: Solar Orbiter's last assist is
2030-09-03 at 12 000 km, *before* its cut-off, and during the extensions the closest
either object comes to a planet is 12 million km — against ~40 000 km for a real
assist. All four joins are verified kink-free, judged against how much the step
length varies in the real data either side.

Manoeuvres are a different matter: these are baseline orbits, so any future
trajectory-correction burn or unannounced assist is not in them. Treat the hatched
stretches as "where it would be if nothing changes".

Times are UTC. Horizons reports TDB, which is not corrected for (a ~69 s offset,
i.e. ~0.01 AU·°⁻¹ … negligible at any plotted scale, and ~13 000 km even for Parker
at perihelion).

### Sampling

One-day cadence throughout, refined to **4-hourly** wherever the heliocentric
angular rate exceeds 5°/day and **hourly** above 40°/day — chiefly Parker's
perihelia, also Solar Orbiter's and BepiColombo's. The page interpolates between
samples with a non-uniform cubic Hermite (Catmull–Rom) spline on (r, longitude,
latitude), longitude stored unwrapped so it interpolates without wrap artefacts.

This is worth doing: checked against an independently fetched 5-minute ephemeris,
plain one-day sampling misplaces Parker by up to **1.6 million km (11.5° of
longitude)** at perihelion, whereas the refined dataset is good to **4 300 km
(0.01°)**. Solar Orbiter and L1 land within 5 km, STEREO-A within 52 km.

45 937 samples over the eight objects, stored as second-order differences of scaled
integers → LEB128 varints → base64, which fits the whole 13-year dataset in 280 kB.
The builder verifies the round-trip before writing the page.

## Rebuilding

```
python3 src/build_data.py     # download from Horizons -> data/trajectories.json
python3 src/build_page.py     # encode + inject into src/template.html -> heliotrajectories.html
python3 src/validate.py       # interpolation accuracy, extension back-tests, continuity
python3 src/shoot.py          # headless screenshots of the UI (needs Edge/Chrome)
python3 src/labelcheck.py     # label stability while time runs (needs Edge/Chrome)
```

No third-party packages; standard library only. Raw Horizons responses are cached
under `data/raw/`, so re-running `build_data.py` costs nothing and edits to the
page only need `build_page.py`. To change the window, edit `WINDOW_START` /
`WINDOW_END` in `src/build_data.py`; coverage is discovered automatically from
Horizons and clamped per object.

| File | |
|---|---|
| `src/horizons.py` | caching JPL Horizons client |
| `src/astro.py` | HCI frame, time conversion, two-body propagation |
| `src/build_data.py` | fetch, adaptive refinement, extensions, reduction |
| `src/template.html` | the page: renderer, UI, decoder |
| `src/build_page.py` | compact encoder + page assembly |
| `src/validate.py` | checks against independent Horizons fetches |
| `src/shoot.py` | headless render harness |
| `src/labelcheck.py` | steps the slider frame by frame and reports labels that jump |
