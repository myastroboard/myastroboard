# SkyTonight

SkyTonight is the built-in observability calculator. It computes, for every target in the dataset, which objects are worth imaging tonight — ranked by **AstroScore** — and exposes the results through a cached JSON API.

---

## Architecture overview

```
Scheduler (skytonight_scheduler.py)
  └─ run_calculations()  (skytonight_calculator.py)
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
| Herschel 400 | static list in `skytonight_catalogue_builder.py` | Astronomical League H400 program — cross-ref tag injected on matching NGC records |
| Pensack 500 | `backend/catalogues/pensack500.json` | 502 NGC/IC objects — cross-ref tag injected on matching records |
| LBN | `backend/catalogues/lbn.json` | Lynds' Bright Nebulae — 94 cross-refs injected on matching NGC/IC records |
| Comets | [Minor Planet Center](https://minorplanetcenter.net/) / JPL SBDB | auto-refreshed |
| Planets / Moon / Sun | Skyfield `de421.bsp` | already computed elsewhere |

Cross-ref catalogues (Herschel400, Pensack500, LBN) add a `catalogue_names` entry and a `source_catalogues` tag to existing NGC/IC records; they never add new coordinates or change the preferred display name.

Target names are preferred in this order: **CommonName → Messier → OpenNGC → OpenIC → Caldwell → LBN → Herschel400 → Pensack500**.

---

## Observability constraints

All constraints are always active (no on/off toggle).

| Parameter | Default | Description |
|---|---|---|
| `altitude_constraint_min` | 30° | Minimum altitude above horizon |
| `altitude_constraint_max` | 80° | Maximum altitude (avoids zenith blind spot) |
| `airmass_constraint` | 2.0 | ≈ 30°+ elevation |
| `size_constraint_min` | 10 arcmin | Minimum angular size (DSOs only) |
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

### 1 — Visibility score (weight 0.40)

Measures how well-placed the target is in the sky:

$$\text{scoreVisibility} = 0.5 \cdot \text{normalise}(\text{altMax},\;20°,\;90°) + 0.3 \cdot \text{normalise}(\text{obsHours},\;0\text{ h},\;8\text{ h}) + 0.2 \cdot \text{normalise}(\text{altMeridian},\;20°,\;90°)$$

| Input | Description |
|---|---|
| `alt_max` | Peak altitude reached during the night (degrees) |
| `obs_hours` | Total hours within all constraints |
| `alt_meridian` | Altitude at meridian transit (degrees) |

### 2 — Sky quality score (weight 0.25)

Penalises Moon interference:

$$\text{moonImpact} = \text{moonPhase} \times \left(1 - \frac{\text{angularDistMoon}}{180°}\right)$$

$$\text{scoreSky} = \max(0,\;1 - \text{moonImpact})$$

| Input | Description |
|---|---|
| `moon_phase` | Illuminated fraction of Moon disk, 0 (new) - 1 (full) |
| `angular_dist_moon` | Angular separation between target and Moon (degrees); defaults to 180° when unavailable |

### 3 — Object score (weight 0.25)

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

### 4 — Comfort score (weight 0.10)

Rewards targets that are observable during convenient evening hours:

$$\text{timeBonus} = \begin{cases} 1.0 & \text{if transit window starts between 21:00-01:00} \\ 0.5 & \text{if 01:00-03:00} \\ 0.0 & \text{otherwise} \end{cases}$$

$$\text{scoreComfort} = 0.5 \times \text{normalise}(\text{obsHoursInWindow},\;0\text{ h},\;6\text{ h}) + 0.5 \times \text{timeBonus}$$

`obs_hours_in_window` is the subset of observable hours that fall within the prime-time window, not the total observable hours.

### 5 — Final weighted sum

$$\text{astroScore} = 0.40 \times \text{scoreVisibility} + 0.25 \times \text{scoreSky} + 0.25 \times \text{scoreObject} + 0.10 \times \text{scoreComfort}$$

### 6 — Bonuses

Applied after the weighted sum, before final clamping:

| Condition | Bonus |
|---|---|
| Planet at opposition (`is_planet=True` AND `is_opposition=True`) | +0.20 |
| Object in Messier catalogue | +0.05 |

The final value is clamped to **[0.0, 1.0]** and rounded to 4 decimal places.

### Score interpretation

| AstroScore | Interpretation |
|---|---|
| 0.85 - 1.00 | Exceptional — ideal conditions |
| 0.65 - 0.84 | Good — recommended target |
| 0.45 - 0.64 | Average — worth imaging if nothing better |
| < 0.45 | Poor — significant limitation (moon, low altitude, faint object) |

---

## Output files

All paths are relative to `/data/skytonight/`.

| File | Description |
|---|---|
| `calculations/dso_results.json` | Deep-sky objects passing all constraints, sorted by AstroScore desc |
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
| `GET` | `/api/skytonight/data/dso` | Deep-sky results for the UI (reactive, per-section) — optional `?catalogue=` filter |
| `GET` | `/api/skytonight/data/bodies` | Solar-system body results (reactive, per-section) |
| `GET` | `/api/skytonight/data/comets` | Comet results (reactive, per-section) |
| `GET` | `/api/skytonight/alttime/<id>` | Altitude-time data for one target |
| `GET` | `/api/skytonight/skymap` | Sky map trajectory data |
| `GET` | `/api/skytonight/log` | Last calculation log content (JSONL) |

Full parameter details: [API_ENDPOINTS.md](API_ENDPOINTS.md)

---

## Source references

- **OpenNGC / OpenIC**: Mattia Verga, [PyOngc](https://github.com/mattiaverga/PyOngc), CC BY-SA 4.0
- **Herschel 400**: [Astronomical League Herschel 400 Observing Program](https://www.astroleague.org/herschel-400-observing-program/)
- **Pensack 500**: original list by Pensack, [Cloudy Nights — 500 Best DSO List](https://www.cloudynights.com/forums/topic/472872-500-best-dso-list)
- **LBN cross-refs**: Lynds' Bright Nebulae catalogue, YAML source via [uptonight](https://github.com/mawinkler/uptonight)
- **Minor Planet Center comet elements**: [minorplanetcenter.net](https://minorplanetcenter.net/)
- **JPL Small-Body Database**: [NASA JPL](https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html)
- **Skyfield ephemeris**: DE421 / DE430 via [Skyfield](https://rhodesmill.org/skyfield/)
- **Astropy / Astroplan**: coordinate transforms, moon illumination
