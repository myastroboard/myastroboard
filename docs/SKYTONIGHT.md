# SkyTonight

SkyTonight is the built-in observability calculator. It computes, for every target in the dataset, which objects are worth imaging tonight - ranked by **AstroScore** - and exposes the results through a cached JSON API.

---

## Architecture overview

```
Scheduler (backend/skytonight/skytonight_scheduler.py)
  └─ run_calculations()  (backend/skytonight/skytonight_calculator.py)
       ├─ load_targets_dataset()       ← DSOs (OpenNGC / OpenIC / Caldwell / Messier / Herschel400 / Pensack500 / LBN)
       ├─ load_comets_dataset()        ← MPC / JPL comets (auto-updated)
       ├─ Solar-system bodies          ← Skyfield ephemeris (de421.bsp)
       └─ Writes shared JSON to /data/skytonight/
              calculations/dso_results.json
              calculations/bodies_results.json
              calculations/comets_results.json
              calculations/skymap_data.json
              calculations/calculation_results.json   ← metadata-only "all done" signal
              outputs/<target_id>_alttime.json        ← altitude-vs-time graph data
```

The API (`app.py`) reads these JSON files; it never re-runs the heavy calculation per request.

---

## Scheduler

| Condition | Schedule |
|---|---|
| System clock is valid (NTP / correct date-time) | 1 hour after nautical dawn + 1 hour before nautical dusk + on first startup |
| System clock is invalid / unknown | Every 6 hours |

Multiple Gunicorn workers are protected by a file-level lock so only one worker runs the calculator at a time.

---

## Target catalogues

| Catalogue | Source | Notes |
|---|---|---|
| OpenNGC | [PyOngc](https://github.com/mattiaverga/PyOngc) | NGC objects |
| OpenIC | [PyOngc](https://github.com/mattiaverga/PyOngc) | IC objects |
| Messier | subset of OpenNGC | flagged via `identifiers[0]` |
| Caldwell | subset of OpenNGC | extracted from PyOngc `other_identifiers` |
| Herschel 400 | static list in `skytonight_catalogue_builder.py` | Astronomical League H400 program - cross-ref tag injected on matching NGC records |
| Pensack 500 | `backend/catalogues/pensack500.json` | 502 NGC/IC objects - cross-ref tag injected on matching records |
| LBN | `backend/catalogues/lbn.json` | Lynds' Bright Nebulae - 94 cross-refs injected on matching NGC/IC records |
| GaryImm | `backend/catalogues/garyimm_crossrefs.json` + `garyimm_standalone.json` | 206-object astrophotography list by Gary Imm - 133 cross-refs on existing records + 33 standalone objects with no NGC/IC ID (Arp groups, LBN/LDN standalone, etc.) |
| Arp | `backend/catalogues/arp.json` | Arp Atlas of Peculiar Galaxies - 120 NGC/IC cross-refs injected on matching records |
| Sharpless | `backend/catalogues/sharpless.json` | 313 HII emission nebulae (Sh2 catalogue, Sharpless 1959) - all standalone records |
| Barnard | `backend/catalogues/barnard.json` | 343 dark nebulae (Barnard 1927 catalogue) - all standalone records |
| vdB | `backend/catalogues/vdb.json` | 158 reflection nebulae (van den Bergh 1966 catalogue) - all standalone records |
| Abell PNe | `backend/catalogues/abell_pne.json` | 71 large planetary nebulae (Abell 1966 catalogue) - all standalone records |
| Abell Clusters | `backend/catalogues/abell_clusters.json` | 2,712 rich galaxy clusters (Abell, Corwin & Olowin 1989) - all standalone records, size bypassed (null) |
| Comets | [Minor Planet Center](https://minorplanetcenter.net/) / JPL SBDB | auto-refreshed |
| Planets / Moon / Sun | Skyfield `de421.bsp` | already computed elsewhere |

Cross-ref catalogues (Herschel400, Pensack500, LBN, GaryImm, Arp) add a `catalogue_names` entry and a `source_catalogues` tag to existing NGC/IC records; they never add new coordinates or change the preferred display name.  Standalone catalogues (GaryImm, Sharpless, Barnard, vdB, AbellPNe, AbellClusters) create new records for objects with no NGC/IC identifier.  Objects selected by Gary Imm in the Sharpless/Barnard/vdB catalogues receive both the catalogue tag and the GaryImm tag via `extra_catalogues`.

Target names are preferred in this order: **CommonName → Messier → OpenNGC → OpenIC → Caldwell → LBN → Herschel400 → Pensack500 → GaryImm → Arp → Sharpless → Barnard → vdB → AbellPNe → AbellClusters**.

---

## Observability constraints

All constraints are always active (no on/off toggle).

| Parameter | Default | Description |
|---|---|---|
| `altitude_constraint_min` | 30° | Minimum altitude above horizon |
| `altitude_constraint_max` | 80° | Maximum altitude (avoids zenith blind spot) |
| `airmass_constraint` | 2.0 | ≈ 30°+ elevation |
| `size_constraint_min` | 0 arcmin | Minimum angular size (DSOs only); 0 = no lower limit |
| `size_constraint_max` | 300 arcmin | Maximum angular size (DSOs only) |
| `moon_separation_min` | 45° | Minimum angular distance from Moon |
| `moon_separation_use_illumination` | true | When enabled, overrides `moon_separation_min` with Moon illumination % → degrees (1 % = 1°) |
| `fraction_of_time_observable_threshold` | 0.50 | DSOs must be within constraints for ≥ 50 % of the night |
| `north_to_east_ccw` | false | Azimuth convention; false = clockwise (standard) |

> **Bodies** (planets, Moon) use a relaxed minimum fraction of **0.05** (≈ 22 min) instead of the DSO threshold, because a planet visible for 3 h in a 7 h night is still a prime target.

---

## AstroScore

AstroScore is a dimensionless number in **[0, 1]** that ranks targets by their suitability for astrophotography tonight from the configured location.

### Normalisation helper

All sub-scores use a linear clamp:

$$\text{normalise}(x, x_{\min}, x_{\max}) = \max\!\left(0,\;\min\!\left(1,\;\frac{x - x_{\min}}{x_{\max} - x_{\min}}\right)\right)$$

### 1 - Visibility score (weight 0.40)

Measures how well-placed the target is in the sky:

$$\text{scoreVisibility} = 0.5 \cdot \text{normalise}(\text{altMax},\;20°,\;90°) + 0.3 \cdot \text{normalise}(\text{obsHours},\;0\text{ h},\;8\text{ h}) + 0.2 \cdot \text{normalise}(\text{altMeridian},\;20°,\;90°)$$

| Input | Description |
|---|---|
| `alt_max` | Peak altitude reached during the night (degrees) |
| `obs_hours` | Total hours within all constraints |
| `alt_meridian` | Altitude at meridian transit (degrees) |

### 2 - Sky quality score (weight 0.25)

Penalises Moon interference:

$$\text{moonImpact} = \text{moonPhase} \times \left(1 - \frac{\text{angularDistMoon}}{180°}\right)$$

$$\text{scoreSky} = \max(0,\;1 - \text{moonImpact})$$

| Input | Description |
|---|---|
| `moon_phase` | Illuminated fraction of Moon disk, 0 (new) - 1 (full) |
| `angular_dist_moon` | Angular separation between target and Moon (degrees); defaults to 180° when unavailable |

### 3 - Object score (weight 0.25)

Rewards intrinsically bright, high-contrast targets using surface brightness:

$$\text{SB} \approx \text{magnitude} + 2.5 \times \log_{10}\!\left(\pi \times \left(\frac{\text{sizeArcmin}}{2}\right)^2\right)$$

$$\text{scoreObject} = 1 - \text{normalise}(\text{SB},\;12,\;22)$$

Inverting the normalisation means a **low SB value** (brighter, easier to image) → **high score**.

| Range | Meaning |
|---|---|
| SB ≤ 12 | Very bright extended object → score = 1.0 |
| SB = 17 | Mid-range → score ≈ 0.5 |
| SB ≥ 22 | Very faint/diffuse → score = 0.0 |

When magnitude or size data are unavailable, a neutral value of **0.5** is used.

### 4 - Comfort score (weight 0.10)

Rewards targets that are observable during convenient evening hours:

$$\text{timeBonus} = \begin{cases} 1.0 & \text{if transit window starts between 21:00-01:00} \\ 0.5 & \text{if 01:00-03:00} \\ 0.0 & \text{otherwise} \end{cases}$$

$$\text{scoreComfort} = 0.5 \times \text{normalise}(\text{obsHoursInWindow},\;0\text{ h},\;6\text{ h}) + 0.5 \times \text{timeBonus}$$

`obs_hours_in_window` is the subset of observable hours that fall within the prime-time window, not the total observable hours.

### 5 - Final weighted sum

$$\text{astroScore} = 0.40 \times \text{scoreVisibility} + 0.25 \times \text{scoreSky} + 0.25 \times \text{scoreObject} + 0.10 \times \text{scoreComfort}$$

### 6 - Bonuses

Applied after the weighted sum, before final clamping:

| Condition | Bonus |
|---|---|
| Planet at opposition (`is_planet=True` AND `is_opposition=True`) | +0.20 |
| Object in Messier catalogue | +0.05 |

The final value is clamped to **[0.0, 1.0]** and rounded to 4 decimal places.

### Score interpretation

| AstroScore | Interpretation |
|---|---|
| 0.85 - 1.00 | Exceptional - ideal conditions |
| 0.65 - 0.84 | Good - recommended target |
| 0.45 - 0.64 | Average - worth imaging if nothing better |
| < 0.45 | Poor - significant limitation (moon, low altitude, faint object) |

### Difficulty rating

Alongside AstroScore, every target also gets a static `difficulty_score` (0-100) and `difficulty`
label (`beginner` / `intermediate` / `advanced`), computed once per calculation run from
magnitude, angular size, and surface brightness. Unlike AstroScore, difficulty does not depend on
location, date, or Bortle class - the same object is always the same difficulty everywhere. It
powers the SkyTonight difficulty filter/badges, the "Tonight for you" recommendations panel, and
the Beginner Catalog. Full model and thresholds: [BEGINNER_EXPERIENCE.md](BEGINNER_EXPERIENCE.md).

---

## Equipment combination recommendations

For any target, `POST /api/skytonight/combination-recommendations` rates how well each of the user's enabled and valid equipment combinations (own + shared, see [EQUIPMENT.md](EQUIPMENT.md#equipment-combinations)) suits that target, on a 1-5 scale.

Unlike AstroScore (which rates the *night*), this rates the *gear* - it runs on demand per target, independent of the scheduler-based calculations above.

### Scoring factors

| Factor | Weight (no camera) | Weight (with camera) | Basis |
|---|---|---|---|
| Focal length vs. ideal range | 50% | 30% | Target apparent size/type -> an ideal focal-length band |
| Field-of-view match | - | 30% | Real sensor FOV (via `calculate_fov`) vs. target apparent size - only when the combination's camera has sensor dimensions |
| Aperture vs. brightness | 35% | 25% | Target magnitude -> ideal aperture range |
| Optical speed (f-ratio) | 15% | 15% | Faster f-ratios favor nebulae/wide-field targets |

A combination without a telescope but with `lens_focal_length_mm`/`lens_focal_ratio` set (e.g. a DSLR + lens on a star tracker) is scored the same way, using the lens specs in place of a telescope's optics. A combination that resolves neither a telescope nor usable lens specs is omitted from the results rather than scored arbitrarily.

Disabled or invalid combinations (see [EQUIPMENT.md](EQUIPMENT.md#disabling-equipment)) never appear in recommendations.

---

## Output files

All paths are relative to `/data/skytonight/`.

| File | Description |
|---|---|
| `calculations/dso_results.json` | Deep-sky objects passing all constraints, sorted by AstroScore desc. Each entry also carries `surface_brightness` (mean mag/arcmin^2 from integrated magnitude + catalogue size, or `null`) and `hourly_altitude` (a compact `[{h, alt}]` vector, altitude linearly interpolated to the top of each local hour spanned by the night grid) - both feed the v1.4 advanced DSO filters without re-reading per-target alttime files |
| `calculations/bodies_results.json` | Solar-system bodies (planets, Moon, etc.) |
| `calculations/comets_results.json` | Comets from MPC |
| `calculations/skymap_data.json` | Sky map trajectory data (az/alt arrays per visible target) |
| `calculations/calculation_results.json` | Metadata-only file written last; signals that all calculation files are complete |
| `outputs/<id>_alttime.json` | Altitude-vs-time series for the popup chart (15-min resolution) |
| `runtime/scheduler_status.json` | Scheduler run state, progress, last duration |
| `logs/last_calculation.log` | Last run log lines (JSONL format: one entry per phase) |

---

## API endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/skytonight/scheduler/status` | Scheduler status, progress, last run time |
| `POST` | `/api/skytonight/scheduler/trigger` | Manually trigger a recalculation (admin) |
| `GET` | `/api/skytonight/dataset/status` | Dataset build status and catalogue counts |
| `POST` | `/api/skytonight/dataset/rebuild` | Force a dataset rebuild |
| `GET` | `/api/skytonight/data/dso` | Deep-sky results for the UI (reactive, per-section) - optional `?catalogue=` filter, plus the v1.4 advanced filters below |
| `GET` | `/api/skytonight/data/bodies` | Solar-system body results (reactive, per-section) |
| `GET` | `/api/skytonight/data/comets` | Comet results (reactive, per-section) |
| `POST` | `/api/skytonight/combination-recommendations` | Rate the user's equipment combinations (1-5) for one target |
| `GET` | `/api/skytonight/visibility-calendar` | 12-month visibility calendar for one fixed deep-sky target - see below |
| `GET` | `/api/skytonight/framing` | Framing simulator data for one fixed deep-sky target - see [Framing simulator](#framing-simulator) |
| `GET` | `/api/skytonight/framing/image/<filename>` | Cached DSS2 background image of the framing simulator |
| `GET` | `/api/skytonight/alttime/<id>` | Altitude-time data for one target |
| `GET` | `/api/skytonight/skymap` | Sky map trajectory data |
| `GET` | `/api/skytonight/log` | Last calculation log content (JSONL) |

Full parameter details: [API_ENDPOINTS.md](API_ENDPOINTS.md)

---

## Target visibility calendar

`GET /api/skytonight/visibility-calendar?target=<id_or_name>&year=<yyyy>` answers "when is this
object best this year?" for the user's active location. It is computed on demand (the SkyTonight
pipeline only ever covers *tonight*) and cached in a small bounded in-process LRU keyed
`(target, location, year)` - deliberately not a scheduler cache job, because the key space (any
target x any location) is unbounded and the underlying ephemeris changes only once a year.

**Deep-sky objects only.** Planets and comets move measurably over a year, so a fixed-RA calendar
is meaningless for them - the response returns `supported: false` with `reason: "moving_target"`.
`reason: "not_found"` means the identifier could not be resolved to coordinates (SkyTonight dataset
first, then a SIMBAD fallback for Astrodex items outside the dataset).

### Sampling scheme

- **24 sample nights**: the 1st and 15th of each month across the requested year. Two samples per
  month keep a single unlucky Moon phase from dominating the monthly figure.
- Per sample night, the Sun and Moon altitude grid (18:00 -> 06:00 local, 10-minute steps) is built
  once via the shared `astroweather.moon_planner.night_body_altitude_grid` helper (one Astropy AltAz
  transform per body).
- The **target's own altitude/azimuth is analytic**, from the hour angle
  `H = LST - RA` -> `alt = asin(sin(dec)*sin(lat) + cos(dec)*cos(lat)*cos(H))`, with LST from the
  same time grid. Arcminute accuracy at O(1) trig per sample.

### Constraint gates (kept in sync with the live calculator)

A sample step counts toward `observable_hours` when the Sun is below -18 deg (astronomical dark) and
the target sits between the effective altitude floor and `altitude_constraint_max`. The floor is the
stricter of `altitude_constraint_min`, the airmass-derived altitude
(`asin(1 / airmass_constraint)`), and the active location preset's custom `horizon_profile` at the
target's azimuth (same `_horizon_floor_array` helper the calculator uses).
`moonless_observable_hours` additionally requires the Moon below the horizon.

### Response shape

```
{
  target:   { id, name, type },
  location: { id, name },
  year, supported, reason?,
  months:  [ { month, dark_hours, observable_hours, moonless_observable_hours,
               max_altitude, moon_illumination_pct, score, bucket } ],   // 12 aggregates
  samples: [ { date, dark_hours, observable_hours, moonless_observable_hours,
               max_altitude, transit_local_time, moon_illumination_pct } ], // 24 raw nights
  constraints: { altitude_min, altitude_max, has_horizon_profile }
}
```

`score` is `moonless_observable_hours` normalized against the best month of the year (falling back to
`observable_hours` when the target is never moonless-observable); `bucket` is `score` mapped to
0-5 for the heatmap cell colour. The 24 raw samples drive the per-month tooltip.

---

## Advanced DSO filters

The Deep Sky Objects tab has a collapsible **Advanced filters** panel above the table. Unlike the
text / constellation / type / catalogue / difficulty filters (which run client-side over the rows
already on screen), these five run **server-side in `_build_dso_section_payload`, applied before the
`max_deep_sky_rows` truncation cut** - so a filtered result set is a genuine catalogue-wide search,
not a filter over the top N by AstroScore. They are passed as query params on
`GET /api/skytonight/data/dso` and debounced (~400 ms) with a spinner.

| Param | Filter | Notes |
|---|---|---|
| `size_min`, `size_max` | Angular size (arcmin) | A view filter *inside* the configured `size_constraint_min/max` band, which the panel shows as "within your configured N-M arcmin". |
| `sb_max` | Surface brightness threshold (mag/arcmin^2) | Keeps only targets at or brighter than the threshold (lower number = brighter). |
| `alt_window_min_deg` + `alt_window_start` + `alt_window_end` | Best altitude window | "above X deg between HHh and HHh". Evaluated against the row's `hourly_altitude` vector; the window may wrap past midnight. |
| `combination_id` + `fov_fit` | FOV fit | Needs a chosen equipment combination. Per row: `fov_fit: {fits, fill_pct}` with `fill_pct = size_arcmin / min(fov_h_arcmin, fov_v_arcmin)`. The guide camera is never part of FOV math; a camera-only combination uses its lens fields. |
| `combination_id` + `max_integration_h` | Estimated minimum integration time | Needs a chosen combination. See [EXPOSURE_CALC.md](EXPOSURE_CALC.md#estimated-minimum-integration-time-v14). |

**Unknown values are never silently dropped.** A target with no magnitude or size (so no surface
brightness, no FOV fill, no integration estimate) stays in the result and is shown as unknown; a
size / SB / integration filter only excludes a target whose value is *present and fails*. The
response echoes `advanced_filters.size_band` and the resolved combination so the UI can label the
result set and state how many targets were considered after filtering.

---

## Framing simulator

**What does my sensor see on this target?** The framing simulator shows a real image of the sky
around a deep-sky object with the sensor rectangle of an equipment combination drawn to scale. It
opens from the frame icon next to a target in the Deep Sky Objects table, from a Wishlist item, from
a Plan My Night entry, and as a **Framing** section in an Astrodex item detail.

- Select up to three combinations to compare them on the same image.
- Rotate the sensor (position angle, from north through east) and drag the frame - or use the
  arrow keys - to move it off the target. The coordinates of the frame centre are shown.
- A dashed circle marks the target's apparent size, when the catalogue gives one.
- Each selected combination gets a verdict from the ratio "target size / short side of the field":
  below 10% *small* (with the target's width in pixels), 10-60% *good fit*, 60-100% *tight*, above
  *larger than the field*. In that last case an approximate mosaic grid is given, assuming 15%
  overlap; only the target's longest dimension is known, so it is an upper bound for an elongated
  object and is labelled as an estimate.
- **Download image** saves the view as a PNG with the target name, the combinations and the image
  credit.

A combination appears when it is enabled and valid (own or shared), has a camera with sensor
dimensions and pixel size, and a focal length - the telescope's effective one, or the lens of a
camera-only combination. Planets and comets are not supported: they move against the stars, so a
fixed image of the sky does not apply (`supported: false`, `reason: "moving_target"`).

### Sky image

The background is a 1000 px DSS2 colour cut-out from CDS hips2fits, north up and east left, in
gnomonic (TAN) projection centred on the target. A camera sensor is a gnomonic projection too, so
the frame is an exact rectangle on the image whatever the field of view.

The server downloads each image once and keeps it in `data/cache/framing_images/` (trimmed to
200 MiB, oldest first); the browser never calls CDS. To bound that cache, the field of view of a
background is one of a fixed ladder (0.25 to 45 degrees): the page picks the smallest step that is
about 2.2 times wider than the widest selected frame. The request carries the target's catalogue
coordinates and nothing about the user. When CDS cannot be reached the frame is still drawn to
scale on a dark background, and CDS is not retried for a few minutes.

### API

- `GET /api/skytonight/framing?target=<id_or_name>` - the resolved target (coordinates, apparent
  size), the image key and allowed fields of view, and one frame per usable combination: field of
  view, image scale, half extent in tangent-plane units, verdict, fill ratio, target size in pixels
  and the mosaic estimate.
- `GET /api/skytonight/framing/image/<ra>_<dec>_<fov>.jpg` - the cached background image.

Implementation: `backend/observation/sky_framing.py` (target resolution, image cache),
`backend/equipment/framing.py` (sensor geometry and verdict), `static/js/framing.js`.

---

## Source references

- **OpenNGC / OpenIC**: Mattia Verga, [PyOngc](https://github.com/mattiaverga/PyOngc), CC BY-SA 4.0
- **Herschel 400**: [Astronomical League Herschel 400 Observing Program](https://www.astroleague.org/herschel-400-observing-program/)
- **Pensack 500**: original list by Pensack, [Cloudy Nights - 500 Best DSO List](https://www.cloudynights.com/forums/topic/472872-500-best-dso-list)
- **LBN cross-refs**: Lynds' Bright Nebulae catalogue, YAML source via [uptonight](https://github.com/mawinkler/uptonight)
- **GaryImm**: astrophotography list compiled by Gary Imm, YAML source via [uptonight](https://github.com/mawinkler/uptonight)
- **Arp Atlas of Peculiar Galaxies**: Halton Arp (1966); NGC/IC cross-refs from NASA/IPAC Extragalactic Database (NED)
- **Sharpless catalogue**: Sharpless (1959), VizieR VII/20
---

## Light Pollution Integration

AstroScore includes an optional light pollution penalty based on your site's **Bortle class** or a direct **SQM** (Sky Quality Meter) reading.

### Configuration

Set your site's Bortle class in **Settings → Configuration → Sky Quality (Light Pollution)**:

- **Bortle Class** (dropdown 1–9): choose the class that matches your observing site. You can look up your location on [lightpollutionmap.info](https://www.lightpollutionmap.info) using the *World Atlas* layer.
- **SQM** (optional, mag/arcsec²): enter if you have a real SQM-meter reading. This overrides the Bortle midpoint estimate and gives more precise weighting.

Leaving both fields empty disables the feature entirely - AstroScore behaves exactly as before.

### How it affects AstroScore

The LP factor is applied to the **sky score** component (weight 0.25) of AstroScore, which already accounts for moon phase and angular distance. The combined factor degrades the sky score in proportion to your light pollution level.

Different object types respond differently to light pollution:

| Object type | LP sensitivity | Notes |
|---|---|---|
| Galaxy | 1.0 (full) | Very sensitive to sky gradient |
| Nebula | 0.85 | Broadband is affected |
| Cluster | 0.50 | Moderately affected |
| Comet | 0.70 | Moderately affected |
| Planet | 0.05 | Effectively immune |
| Moon | 0.00 | Completely immune |

At a Bortle 5 (suburban) site, a galaxy loses roughly 20–25 % of its sky score compared to a Bortle 2 site, while planets are unaffected.

### API

`GET /api/skyquality` returns the current sky quality configuration:

```json
{
  "bortle": 5,
  "sqm": 20.55,
  "sqm_source": "bortle_midpoint",
  "light_pollution_factor": 0.5196,
  "description": "Suburban"
}
```

`sqm_source` is one of `"user_measured"`, `"bortle_midpoint"`, or `"not_configured"`.

---

- **Barnard dark nebulae**: Barnard (1927), VizieR VII/220A
- **van den Bergh reflection nebulae**: van den Bergh (1966), VizieR VII/21
- **Abell planetary nebulae**: Abell (1966), ApJS 12, 391; coordinates from SIMBAD (CDS, Strasbourg)
- **Abell galaxy clusters**: Abell, Corwin & Olowin (1989), ApJS 70, 1; VizieR VII/110A
- **Minor Planet Center comet elements**: [minorplanetcenter.net](https://minorplanetcenter.net/)
- **JPL Small-Body Database**: [NASA JPL](https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html)
- **Skyfield ephemeris**: DE421 / DE430 via [Skyfield](https://rhodesmill.org/skyfield/)
- **Astropy / Astroplan**: coordinate transforms, moon illumination
