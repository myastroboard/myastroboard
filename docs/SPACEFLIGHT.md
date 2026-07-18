# Spaceflight Tracker

The **Spaceflight** tab keeps you connected to what is happening above the atmosphere: rocket launches, current ISS crew, orbital transits, and upcoming space events.

---

## Tab layout

| Sub-tab | Content |
|---------|---------|
| **Launches** | Upcoming and recent rocket launches with details and video links |
| **Astronauts** | Crew currently in orbit |
| **Space Events** | Spacewalks, dockings, and mission milestones |
| **ISS** | Real-time ISS position + pass predictions for your location |

---

## Launches

**Module**: `backend/space/spaceflight_tracker.py`

**Data source**: [Launch Library 2 (The Space Devs)](https://thespacedevs.com/llapi)

**API base**: `https://ll.thespacedevs.com/2.2.0/`

**Cache TTL**: 2 hours (`CACHE_TTL_SPACEFLIGHT_LAUNCHES`).

Launch Library 2 is the de-facto standard for launch data. The free tier allows ~15 requests/hour; MyAstroBoard's cache keeps live calls minimal.

### What is displayed

| Field | Description |
|-------|-------------|
| Mission name | Launch or payload name |
| Agency/provider | Launch operator (SpaceX, ULA, Roscosmos…) |
| Vehicle | Rocket family and variant |
| Launch site | Pad location |
| NET | No Earlier Than date-time (in your local timezone) |
| Status | `Go`, `TBD`, `Hold`, `Success`, `Failure`, `Partial Failure` |
| Launch video | Embedded webcast URL (YouTube, SpaceflightNow…) |
| Mission image | Launch patch or vehicle image (cached locally) |

### Image caching

Launch images from the LL2 CDN are downloaded and served locally via `GET /api/spaceflight/img/<filename>`. This avoids CORS issues and makes the UI work without external CDN access. A `.url` sidecar file is written alongside each image so it can be re-fetched if deleted.

### Rate limiting

If the LL2 API returns HTTP 429 (rate limit), all further calls to the same endpoint are suppressed for 1 hour (`_BACKOFF_TTL = 3600 s`) to respect the free-tier quota.

### Video URLs

`GET /api/spaceflight/launch/<launch_id>/vidurls` returns available video stream URLs for a given launch, fetched on demand (not cached) to ensure the latest live-stream link is returned.

---

## Astronauts

**Module**: `backend/space/spaceflight_tracker.py`

**Cache TTL**: 6 hours (`CACHE_TTL_SPACEFLIGHT_ASTRONAUTS`).

Fetches from Launch Library 2 the list of all people currently in orbit:

| Field | Description |
|-------|-------------|
| Name | Astronaut full name |
| Agency | Space agency |
| Vehicle | Spacecraft they arrived on |
| Role | Mission role (Commander, Flight Engineer…) |
| Days in space | Days since launch |
| Profile image | Locally cached from LL2 CDN |

**API**: `GET /api/spaceflight/astronauts`

---

## Space events

**Module**: `backend/space/spaceflight_tracker.py`

**Cache TTL**: 2 hours (`CACHE_TTL_SPACEFLIGHT_EVENTS`).

Space events include EVAs (spacewalks), dockings, undockings, and other mission milestones tracked by Launch Library 2.

**API**: `GET /api/spaceflight/events`

---

## ISS passes

**Module**: `backend/space/iss_passes.py`

**Cache TTL**: 6 hours (`CACHE_TTL_ISS_PASSES`).

### TLE data

Pass prediction requires up-to-date Two-Line Element (TLE) data. The service tries three sources in priority order:

| Priority | Source | Notes |
|----------|--------|-------|
| 1 | Celestrak GP catalog | Authoritative, NORAD #25544 |
| 2 | api.wheretheiss.at | Independent aggregator |
| 3 | tle.ivanstanojevic.me | Independent aggregator |

TLE data is cached locally in `data/cache/iss_tle_cache.json` for up to **6 hours**. (Skyfield's own ephemeris files are stored separately under `data/cache/skyfield/`.) If all sources fail, the last valid TLE is used for up to 3 hours before the prediction is considered unreliable.

The TLE cache can be force-refreshed via `POST /api/iss/celestrak/restart`.

### Pass prediction algorithm

**Library**: [Skyfield](https://rhodesmill.org/skyfield/) with `EarthSatellite` propagation (SGP4 model).

The service predicts passes over a **20-day window** (max 30) from the configured location.

For each pass:

| Field | Description |
|-------|-------------|
| `start_time` / `end_time` | Rise and set in local timezone |
| `duration_seconds` | Total pass duration |
| `max_altitude_deg` | Maximum elevation above the horizon |
| `start_azimuth_deg` / `end_azimuth_deg` | Direction at rise and set |
| `visibility_class` | `visible` (ISS in sunlight, ground in darkness), `daylight`, `night_only`, `below_horizon` |
| `visibility_score` | 0–100 quality score |

Passes with max altitude < 10° (`MIN_EVENT_ALTITUDE_DEG`) are filtered out.

**Visible passes** require:
- ISS illuminated by the Sun
- Observer in darkness (Sun altitude < −4°, `MAX_VISIBLE_SKY_SUN_ALTITUDE_DEG`)

### Solar transits

A **solar transit** occurs when the ISS passes directly in front of the solar disk. This is a rare photographic opportunity.

The service refines transit timing to 0.1 s resolution (`SOLAR_TRANSIT_REFINE_SAMPLE_SECONDS`) and checks whether the ISS angular path crosses the Sun's angular disk (radius ≈ 0.267°).

### Lunar transits

Similarly, a **lunar transit** occurs when the ISS crosses the lunar disk. Both transit types are returned separately in the API response.

### ISS real-time location

`GET /api/iss/location` returns the current ISS ground position (latitude, longitude, altitude, velocity). The ground track ±50 minutes is computed once per **5 minutes** (server-side cache `_TRACK_CACHE_TTL_SECONDS = 300`) to reduce SGP4 computation.

### API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/iss/passes` | Upcoming passes, solar transits, and lunar transits |
| `GET` | `/api/iss/location` | Real-time ISS position and ground track |
| `POST` | `/api/iss/celestrak/restart` | Force TLE re-fetch |

The `/api/iss/passes` response includes:

| Key | Content |
|-----|---------|
| `passes` | List of predicted passes |
| `solar_transits` | List of solar transit events |
| `lunar_transits` | List of lunar transit events |
| `next_visible_passage` | Next pass with `visibility_class = visible` |
| `next_solar_transit` | Next solar transit |
| `next_lunar_transit` | Next lunar transit |
| `total_passes` / `total_solar_transits` / `total_lunar_transits` | Counts |

---

## Push notification triggers

| Trigger | Event | Default lead |
|---------|-------|-------------|
| N3 | ISS solar or lunar transit | 10 min |

See [NOTIFICATIONS.md](NOTIFICATIONS.md) for the full notification system.
