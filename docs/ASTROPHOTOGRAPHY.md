# Astrophotography Tab

The **Astrophotography** tab is the central planning dashboard. It consolidates every piece of data an astrophotographer needs to decide whether to observe tonight and what to expect.

---

## Tab layout

| Sub-tab | Content |
|---------|---------|
| **Astro weather** | Summary conditions card + best imaging window |
| **Window** | Detailed best-window breakdown (3 modes) |
| **Moon** | Lunar phase, position, 7-night planner, month calendar |
| **Sun** | Solar times, twilight windows, next eclipse |
| **Aurora** | Kp index, geomagnetic forecast, visibility assessment |
| **Calendar** | Upcoming celestial events (planetary, meteor showers, phenomena) |

---

## Best imaging window

**Module**: `backend/astroweather/moon_astrotonight.py`

**Class**: `AstroTonightService`

**Cache TTL**: 3 hours (`CACHE_TTL_BEST_WINDOW`).

The best imaging window is the longest continuous block of time where the sky is **astronomically dark** and **moonlight is minimal**, according to three selectable modes.

### What "astronomical night" means

Astronomical night begins when the Sun's altitude drops below **−18°** (astronomical dusk) and ends at **−18°** on the way back up (astronomical dawn). Only during this window can faint deep-sky objects be properly imaged.

| Twilight type | Sun altitude | Notes |
|---------------|-------------|-------|
| Civil twilight | 0° to −6° | Sky still blue |
| Nautical twilight | −6° to −12° | Horizon visible at sea |
| Astronomical twilight | −12° to −18° | Sky not yet fully dark |
| **True astronomical night** | **< −18°** | Required for deep-sky imaging |

### The three window modes

| Mode | Moon constraint | Use case |
|------|----------------|----------|
| `strict` | Moon must be **below the horizon** | Maximum darkness; works well near full moon |
| `practical` | Moon altitude **< 5°** | 30-min margin for moonrise/moonset |
| `illumination` | Moon illumination **< 15%** | New moon neighbourhood; moon may be above horizon but is dim |

All three modes use Sun < −18° as the primary constraint. The API returns all three simultaneously — the UI shows the one that gives the longest usable window.

### Score

The window score (0–100) reflects how good the dark window is:

- 100: No moon interference during full astronomical night.
- 0: No dark window exists (full moon, high latitude in summer, polar day).

### API endpoint

`GET /api/tonight/best-window` returns:

```json
{
  "best_window": {
    "strict": { "start": "22:15", "end": "04:40", "duration_hours": 6.4, "score": 100 },
    "practical": { "start": "22:15", "end": "04:40", "duration_hours": 6.4, "score": 100 },
    "illumination": { "start": "22:15", "end": "04:40", "duration_hours": 6.4, "score": 100 }
  }
}
```

---

## Moon

**Modules**: `backend/astroweather/moon_phases.py`, `backend/astroweather/moon_planner.py`, `backend/astroweather/moon_eclipse.py`

**Cache TTL**: 2 hours (`CACHE_TTL_MOON_REPORT`).

### Moon report (`astroweather/moon_phases.py`)

`MoonService` computes:

| Field | Description |
|-------|-------------|
| `phase_name` | Named phase (New Moon, Waxing Crescent, First Quarter…) |
| `illumination_percent` | Fraction of disk illuminated (0–100 %) |
| `distance_km` | Geocentric distance |
| `altitude_deg` / `azimuth_deg` | Current topocentric position |
| `next_moonrise` / `next_moonset` | Next rise and set times |
| `next_full_moon` / `next_new_moon` | Timestamps of next phase extremes |
| `next_dark_night_start/end` | Next window where Sun < −18° AND Moon below horizon |

**Libraries used**: `astronomy` (Astronomy Engine) for rise/set and phase search; `astropy` for AltAz position.

### Moon planner (`astroweather/moon_planner.py`)

7-night forecast table. For each night it computes moonrise, moonset, illumination, and whether there is a usable dark window. This lets astrophotographers pick the best night within the coming week.

**API**: `GET /api/moon/next-7-nights`

### Moon calendar (`astroweather/moon_planner.py`)

Monthly calendar view with phase icons and illumination values for each day.

**API**: `GET /api/moon/month-calendar`

### Lunar eclipse (`astroweather/moon_eclipse.py`)

`LunarEclipseService` finds the **next lunar eclipse** visible from the configured location.

| Field | Description |
|-------|-------------|
| `type` | `Total`, `Partial`, or `Penumbral` |
| `peak_time` | Local time of maximum eclipse |
| `partial_begin` / `total_begin` / `total_end` / `partial_end` | Contact times |
| `peak_altitude_deg` | Moon altitude at peak (negative = below horizon = not visible) |
| `total_duration_minutes` / `partial_duration_minutes` | Duration of each phase |
| `astrophotography_score` | 0–10 score for imaging value |
| `altitude_vs_time` | Array of alt/az at 5-min resolution for chart display |

**Astrophotography score** factors in: eclipse type (total > partial > penumbral), altitude at peak, and total duration.

**API**: `GET /api/moon/next-eclipse`

---

## Sun

**Modules**: `backend/astroweather/sun_phases.py`, `backend/astroweather/sun_eclipse.py`

**Cache TTL**: 6 hours (`CACHE_TTL_SUN_REPORT`).

### Sun report (`astroweather/sun_phases.py`)

`SunService` computes for the current date at the configured location:

| Field | Description |
|-------|-------------|
| `sunrise` / `sunset` | Local times |
| `civil_dusk` / `civil_dawn` | Sun = −6° |
| `nautical_dusk` / `nautical_dawn` | Sun = −12° |
| `astronomical_dusk` / `astronomical_dawn` | Sun = −18° |
| `true_night_hours` | Duration of full astronomical night |

**Library**: `astropy` — `get_sun()` + `AltAz` transforms over a dense time grid to find threshold crossings.

**API**: `GET /api/sun/today`

### Solar eclipse (`astroweather/sun_eclipse.py`)

`SolarEclipseService` finds the **next solar eclipse** visible from the configured location.

| Field | Description |
|-------|-------------|
| `type` | `Total`, `Annular`, `Partial`, or `Hybrid` |
| `maximum_time` | Local time of maximum coverage |
| `obscuration_percent` | Fraction of solar disk covered at maximum |
| `altitude_deg` | Sun altitude at maximum |
| `magnitude` | Eclipse magnitude (fraction of solar diameter covered by Moon) |
| `duration_minutes` | Duration of partial phase |
| `altitude_vs_time` | Alt/az array for chart display |

**API**: `GET /api/sun/next-eclipse`

---

## Horizon graph

**Module**: `backend/astroweather/horizon_graph.py`

**Cache TTL**: 6 hours (`CACHE_TTL_HORIZON_GRAPH`).

The horizon graph displays the **altitude vs. time curves** for the Sun and Moon throughout the current day. This gives a quick visual of when targets are above the horizon and allows users to identify the dark window at a glance.

`HorizonGraphService` samples altitude and azimuth at **1-hour resolution** using `astropy`'s `get_sun()` and `get_body('moon')` with AltAz transforms.

**API**: `GET /api/astro/horizon-graph`

---

## Sidereal time

**Module**: `backend/observation/sidereal_time.py`

**Cache TTL**: 1 hour (`CACHE_TTL_SIDEREAL_TIME`).

Local Apparent Sidereal Time (LAST) is displayed as a quick reference. LAST equals the Right Ascension (RA) of objects currently on the meridian — useful when manually slewing to targets.

**API**: `GET /api/astro/sidereal-time`

---

## Aurora

**Module**: `backend/astroweather/aurora_predictions.py`

**Class**: `AuroraService`

**Cache TTL**: 1 hour (`CACHE_TTL_AURORA`).

**Data source**: [NOAA Space Weather Prediction Center](https://www.swpc.noaa.gov/)

### Kp index

The **Kp index** (0–9) is the primary indicator of global geomagnetic activity. Higher Kp = larger aurora oval extending further toward the equator.

| Kp | Activity level | Typical aurora visibility |
|----|---------------|--------------------------|
| 0–1 | Quiet | Polar regions only (> ~70° lat) |
| 2–3 | Unsettled | High latitudes (~65–70°) |
| 4 | Active | Mid-high latitudes (~60–65°) |
| 5 | Minor storm (G1) | Visible ~55° |
| 6 | Moderate storm (G2) | Visible ~50° |
| 7 | Strong storm (G3) | Visible ~45°, sometimes ~40° |
| 8–9 | Severe/Extreme | Mid-latitude aurora possible |

**NOAA API**: `https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json` (current), `noaa-planetary-k-index-forecast.json` (3-day forecast).

### Aurora visibility probability

`AuroraService.calculate_aurora_probability()` estimates aurora probability (0–100 %) from the current Kp and observer latitude:

```
aurora_edge_latitude = 67° - (Kp × 3.5°)
```

- Observer **poleward of the edge** → probability = 25% + Kp × 7 (max 88%)
- Observer **near the edge** → probability = 15% + Kp × 6
- Observer **5° equatorward** → probability = 5% + Kp × 4
- Observer **far equatorward** → probability = max(0, (Kp − 3) × 6)

The latitude of 67° is an approximation of the mean auroral oval edge during quiet conditions; the factor of 3.5°/Kp unit is a well-known empirical rule of thumb.

### Best aurora window

Auroras are most visible between **22:00 and 02:00 local time** (midnight maximum). The service reports whether the current night has a suitable window given Kp and darkness.

**API**: `GET /api/aurora/predictions`

---

## Celestial events

Three separate services feed the **Calendar** sub-tab.

### Planetary events

**Module**: `backend/observation/planetary_events.py`

**Class**: `PlanetaryEventsService`

**Cache TTL**: 24 hours (`CACHE_TTL_PLANETARY_EVENTS`).

Covers all seven naked-eye planets (Mercury, Venus, Mars, Jupiter, Saturn, Uranus, Neptune).

| Event type | Description | Which planets |
|------------|-------------|---------------|
| **Opposition** | Planet is 180° from the Sun — closest approach, highest altitude at midnight | Outer planets only (Mars and beyond) |
| **Conjunction** | Planet appears very close to another planet or the Sun | All |
| **Greatest elongation** | Maximum angular distance from the Sun — best for inner planets | Mercury (18°), Venus (46°) |
| **Retrograde begin/end** | Apparent backward motion as Earth overtakes an outer planet | All outer planets |

Events are computed over a **365-day rolling window** from today using `astropy` body positions.

**API**: `GET /api/events/planetary`

### Special phenomena

**Module**: `backend/observation/special_phenomena.py`

**Class**: `SpecialPhenomenaService`

**Cache TTL**: 24 hours (`CACHE_TTL_SPECIAL_PHENOMENA`).

| Event | Description |
|-------|-------------|
| **Vernal equinox** | Sun crosses the celestial equator northward (≈ March 20) |
| **Summer solstice** | Longest day in the northern hemisphere (≈ June 21) |
| **Autumnal equinox** | Sun crosses the celestial equator southward (≈ September 22) |
| **Winter solstice** | Shortest day (≈ December 21) |
| **Zodiacal light window** | Best period to see the faint dust band in the ecliptic (western sky after dusk in spring, eastern sky before dawn in autumn) |
| **Milky Way core visibility** | Period when the galactic centre (Sagittarius) rises and sets in darkness |

**Library**: `astropy` — `get_sun()` position for equinox/solstice crossing detection; `SkyCoord` for galactic-plane altitudes.

**API**: `GET /api/events/phenomena`

### Solar system events (meteor showers)

**Module**: `backend/observation/solar_system_events.py`

**Class**: `SolarSystemEventsService`

**Cache TTL**: 24 hours (`CACHE_TTL_SOLAR_SYSTEM_EVENTS`).

Contains a curated database of annual meteor showers with:

| Field | Description |
|-------|-------------|
| `name` | Shower name |
| `peak_date` | Date of peak activity |
| `zenith_hourly_rate` | ZHR at peak |
| `parent_body` | Comet or asteroid producing the shower |
| `radiant_ra` / `radiant_dec` | Radiant position |
| `radiant_altitude` | Radiant altitude at peak local midnight from configured location |
| `hemisphere` | `north`, `south`, or `both` |

Major showers included: Quadrantids, Lyrids, Eta Aquariids, Delta Aquariids, Perseids, Orionids, Leonids, Geminids, Ursids.

Radiant altitude is computed using `astropy` AltAz transforms — a shower with a radiant below the horizon is flagged as not visible from the configured location.

**API**: `GET /api/events/solarsystem`

### Upcoming events aggregator

**Module**: `backend/utils/events_aggregator.py`

`GET /api/events/upcoming` merges all three event sources and returns a single sorted list of events in the coming days/weeks — used for the Calendar sub-tab and for push notification triggers N4 and N5.

---

## Push notification triggers

Two astrophotography events feed the push notification system (see [NOTIFICATIONS.md](NOTIFICATIONS.md)):

| Trigger | Event | Default lead |
|---------|-------|-------------|
| N4 | Lunar eclipse totality begins | 30 min |
| N5 | Solar eclipse maximum | 30 min |
| N6 | Astronomical darkness begins | 20 min |
