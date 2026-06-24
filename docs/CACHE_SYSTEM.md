# Cache System - Server-Side Management

## Overview

The cache system is managed **entirely server-side** with per-job TTL-based expiration and intelligent cache invalidation when location parameters change.

The key design principle is **selective refresh**: the background scheduler polls every 5 minutes, but each job only executes when *its own TTL* has expired. Heavy computations (eclipses, planetary events) run at most once a day, while time-sensitive data (aurora, sidereal) refreshes hourly. This dramatically reduces CPU and memory pressure on low-resource machines.

## Key Features

### Server-Side Only Management
- **No browser-side refresh required** - F5 works normally
- All cache calculations happen on the server
- Cache is automatically refreshed on schedule (selective per-job TTL)

### Per-Job TTL Configuration
Each cache job has an individual TTL defined in `backend/constants.py`:

| Job | TTL | Rationale |
|-----|-----|-----------|
| `moon_report` | 2 hours | Moon phase changes gradually |
| `dark_window` | 2 hours | Derived from moon report |
| `moon_planner` | 2 hours | 7-night forecast, daily precision is sufficient |
| `sun_report` | 6 hours | Sunrise/sunset changes slowly |
| `best_window` | 3 hours | "Best window for tonight" |
| `solar_eclipse` | 24 hours | Next event is months away |
| `lunar_eclipse` | 24 hours | Next event is months away |
| `horizon_graph` | 6 hours | Daily arc of sun/moon |
| `aurora` | 1 hour | Geomagnetic forecast updates hourly |
| `iss_passes` | 6 hours | 20-day prediction window, stable |
| `css_passes` | 6 hours | 20-day prediction window, stable (CSS NORAD 48274) |
| `planetary_events` | 24 hours | 365-day planetary forecast |
| `special_phenomena` | 24 hours | Annual events (equinoxes, solstices…) |
| `solar_system_events` | 24 hours | Annual events (meteor showers, comets…) |
| `sidereal_time` | 1 hour | Hourly precision is sufficient |
| `seeing_forecast` | 6 hours | 7Timer API update frequency |
| `weather_forecast` | 1 hour | Suitable for UI display |
| `spaceflight_launches` | 2 hours | Launch Library API budget and cadence |
| `spaceflight_astronauts` | 6 hours | Crew roster changes are less frequent |
| `spaceflight_events` | 2 hours | Event feed changes but does not require minute-level polling |
| `iers` | 21 days | Earth-orientation data is long-lived |

**Note on Weather Data:**
- **UI Weather Forecast**: Cached for 1 hour (suitable for display)
- **SkyTonight Conditions**: NOT cached - always fetches fresh real-time data
  - SkyTonight requires accurate current conditions (temperature, pressure, humidity)
  - Each SkyTonight run bypasses cache to get live conditions from Open-Meteo API

### Selective Refresh (Resource Efficiency)
`fully_initialize_caches()` in `cache_updater.py` now:
1. Syncs each in-memory cache entry from the shared JSON file (gets persisted timestamp)
2. Checks each job's TTL individually
3. **Skips jobs whose TTL has not yet expired**
4. Only runs stale jobs - often just 2-4 jobs per poll cycle

On a typical steady-state machine, most 5-minute poll cycles skip all jobs because TTLs are still valid. Hourly-class jobs run only when their own TTL expires; daily jobs run at most once every 24 hours.

### Automatic Location Change Detection
When any of these location parameters change, **all astronomical caches are immediately reset** (timestamps zeroed), forcing a full refresh on the next scheduler cycle:
- Latitude
- Longitude
- Elevation
- Timezone

### Background Cache Scheduler
- Runs in a dedicated daemon thread
- Starts automatically on app/container startup
- Updates all caches immediately on first run (all timestamps = 0)
- Then polls every 300 seconds (5 minutes), running only expired jobs
- Uses file locking to ensure only one scheduler runs across multiple workers

## Architecture

### Components

#### 1. **`cache_store.py`** - Cache Storage & Validation
- Maintains in-memory cache entries with timestamps
- Persists cache entries to `data/cache/astro_cache.json` for cross-worker visibility
- Tracks location configuration changes
- Provides TTL validation using per-job constants
- **New**: `record_cache_execution(job_name, duration_s, success)` - persists per-job timing
- **New**: `get_cache_metrics()` - returns per-job execution metrics from shared cache
- Key functions:
  - `is_cache_valid(cache_entry, ttl_seconds)` - check if cache is still fresh
  - `is_astronomical_cache_ready()` - check if all caches are valid (uses per-job TTLs)
  - `has_location_changed(location_config)` - detect location parameter changes
  - `reset_all_caches()` - immediately reset all astronomical caches
  - `get_cache_init_status()` - detailed cache status including `ttls` and `execution_metrics`

#### 2. **`cache_updater.py`** - Cache Calculation (Selective)
- Contains all individual cache update functions
- `fully_initialize_caches()` - **selective**: syncs timestamps, skips valid caches, records per-job timing
- `check_and_handle_config_changes()` - detects and resets caches on location change

#### 3. **`cache_scheduler.py`** - Background Task Management
- `CacheScheduler` class polls at 300-second interval
- Uses file locking to prevent multiple instances
- Calls `fully_initialize_caches()` which handles selective execution
- Sets `cache_ready_event` after the first successful cycle

#### 4. **`constants.py`** - TTL Constants
- `CACHE_TTL_<JOB_NAME>` constants define the TTL for each job
- `WEATHER_CACHE_TTL` = 3600s (1 hour) for weather
- `CACHE_TTL` = 1800s kept for backward compatibility only (not used for job scheduling)

#### 5. **`weather_utils.py`** - Dual Weather Client System
- **Cached Client** (`create_weather_client()`): 1-hour HTTP-level cache for UI forecasts
- **Fresh Client** (`create_fresh_weather_client()`): no caching, used by SkyTonight for real-time conditions

### Cache Flow

```
App Startup
  ↓
Cache Scheduler starts
  ↓
Initial cache population (all timestamps = 0 → all jobs run)
  ├─ Check location config
  ├─ Run all registered jobs
  └─ Record timing per job, set timestamps
  ↓
Wait 300s (5 min)
  ↓
Periodic poll
  ├─ Sync in-memory timestamps from shared JSON file
  ├─ For each job: check if TTL elapsed
  │   ├─ TTL not elapsed → skip job
  │   └─ TTL elapsed → run job, record duration, update timestamp
  └─ Log: "X/N jobs ran, Y/X succeeded in Z.Zs"
  ↓
Next poll (300s later)...
```

## Configuration Changes

When location is updated via `/api/config` POST endpoint:

1. **System detects change** in latitude, longitude, elevation, or timezone
2. **All cache timestamps zeroed** (`reset_all_caches()`)
3. **Configuration saved** to file
4. **Next scheduler poll** will run all 16 jobs (all timestamps = 0)
5. **Browser receives confirmation** including `"cache_reset": true`

## API Endpoints

### `/api/cache` - Cache Status (GET)
**Purpose**: Informational - allows UI to display cache status and job metrics
**Returns**:
```json
{
  "cache_status": true,
  "in_progress": false,
  "current_step": 0,
  "total_steps": 0,
  "step_name": "",
  "progress_percent": 0,
  "details": {
    "moon_report": true,
    "sun_report": true,
    "best_window_strict": true,
    "best_window_practical": true,
    "best_window_illumination": true,
    "moon_planner": true,
    "dark_window": true,
    "solar_eclipse": true,
    "lunar_eclipse": true,
    "horizon_graph": true,
    "aurora": true,
    "iss_passes": true,
    "css_passes": true,
    "planetary_events": true,
    "special_phenomena": true,
    "solar_system_events": true,
    "sidereal_time": true,
    "seeing_forecast": true,
    "weather_forecast": true,
    "all_ready": true,
    "ttls": {
      "moon_report": 7200,
      "dark_window": 7200,
      "moon_planner": 7200,
      "sun_report": 21600,
      "best_window": 10800,
      "solar_eclipse": 86400,
      "lunar_eclipse": 86400,
      "horizon_graph": 21600,
      "aurora": 3600,
      "iss_passes": 21600,
      "css_passes": 21600,
      "planetary_events": 86400,
      "special_phenomena": 86400,
      "solar_system_events": 86400,
      "sidereal_time": 3600,
      "seeing_forecast": 21600,
      "weather_forecast": 3600,
      "spaceflight_launches": 7200,
      "spaceflight_astronauts": 21600,
      "spaceflight_events": 7200,
      "iers": 1814400
    },
    "execution_metrics": {
      "moon_report": {
        "last_run_at": "2026-05-01T20:00:01.123",
        "last_duration_s": 0.842,
        "last_success": true
      }
    }
  }
}
```

### `/api/config` - Configuration Update (POST)
- Detects if latitude, longitude, elevation, or timezone changed
- Immediately resets all caches (timestamps to 0)
- Returns `"cache_reset": true` when location changed

### Data Endpoints (Astronomical Data)
These endpoints return **from cache only**:
- `GET /api/moon/report` - Moon report
- `GET /api/moon/dark-window` - Dark window
- `GET /api/moon/next-7-nights` - Moon planner
- `GET /api/sun/today` - Sun report
- `GET /api/tonight/best-window` - Best observation window

**Response codes**:
- `200`: Data returned (cache is valid)
- `202`: Pending - cache being prepared (retry shortly)

## Metrics Dashboard (Cache Jobs section)

The **Metrics** tab in the UI (admin only) includes a **Cache Jobs** table populated from `GET /api/cache`:

| Column | Description |
|--------|-------------|
| Job | Human-readable job name |
| TTL | Configured TTL for this job |
| Status | Valid (green) / Stale (yellow) based on current TTL |
| Last run | ISO timestamp of last execution |
| Duration | Wall-clock time of last execution |

A "Failed" badge appears in the Duration column if the last execution threw an exception.

## Performance Impact

### Benefits
- **No browser delays** - F5 is instant
- **Low-resource friendly** - heavy jobs (eclipses, planetary events) run at most once a day instead of every scheduler poll
- **Typical steady-state**: most 5-min polls run 0 jobs (all TTLs intact); hourly-class jobs run only on expiry; daily jobs run ~once per day
- **Automatic location handling** - no stale data when location changes
- **Full observability** - per-job last run time and duration visible in Metrics tab

### Cache Sizes (Typical)
- Moon report: ~5-10 KB
- Sun report: ~3-5 KB
- Best windows: ~5-8 KB each (×3 modes)
- Moon planner: ~20-30 KB
- Dark window: ~1-2 KB
- Total: ~50-100 KB in memory + shared JSON file on disk

## Troubleshooting

### Cache Always Shows "Pending"
1. Check cache scheduler is running: `GET /api/skytonight/scheduler/status`
2. Check server logs for errors in cache calculations
3. Verify location configuration is complete
4. Check Metrics → Cache Jobs for failed jobs

### Cache Not Updating After Location Change
1. Verify location parameters actually changed
2. Watch server logs for "Location configuration changed" message
3. Check `/api/cache` shows caches as not ready (timestamps zeroed)
4. Wait for next scheduler poll (max 5 minutes)

### Multiple Cache Updates Running
- Should not happen - file locking prevents it
- If it does, check `data/cache/cache_scheduler.lock` for stale lock

### SkyTonight Getting Stale Weather Conditions
- **This should NOT happen** - SkyTonight always fetches fresh data via `create_fresh_weather_client()`
- Each SkyTonight run bypasses the weather cache
- If conditions seem old, check Open-Meteo API availability

## Technical Implementation Details

### Selective Refresh Logic (`fully_initialize_caches`)
```python
for job_name, shared_key, update_fn, ttl, cache_entry in cache_jobs:
    cache_store.sync_cache_from_shared(shared_key, cache_entry)
    if cache_store.is_cache_valid(cache_entry, ttl):
        continue   # skip - still fresh
    # run the job and record timing
    t0 = time.time()
    update_fn()
    cache_store.record_cache_execution(job_name, time.time() - t0, success=True)
```

### Execution Metrics Storage
Per-job metrics are stored under the `_cache_metrics` key in `data/cache/astro_cache.json`:
```json
{
  "_cache_metrics": {
    "moon_report": {
      "last_run_at": "2026-05-01T20:00:01.123",
      "last_duration_s": 0.842,
      "last_success": true
    }
  }
}
```

### Location Change Detection
```python
# Signature-based comparison
new_signature = {
    "latitude": 45.5,
    "longitude": -73.5,
    "elevation": 100,
    "timezone": "America/Montreal"
}
# If any value differs → reset_all_caches() → all timestamps zeroed
```

### Adding a New Cache Job
1. Add a `CACHE_TTL_<NAME>` constant in `constants.py` with a justified value
2. Add a `_<name>_cache` entry in `cache_store.py`
3. Add `update_<name>_cache(config=None)` in `cache_updater.py` - guard with `if config is None: config = load_config()`
4. Register it in the `cache_jobs` list in `fully_initialize_caches()` using `partial(update_<name>_cache, config=config)`
5. Add it to `is_astronomical_cache_ready()` and `get_cache_init_status()` with its TTL constant
6. Add it to `reset_all_caches()` and `_write_all_astronomical_caches_to_shared()`
7. Document the TTL rationale in this file and `.github/instructions/copilot.instructions.md`

### Computation Optimisations
To keep CPU and memory usage low on single-worker Docker deployments, the cache system applies three computation-level optimisations on each refresh cycle:

| Optimisation | Where | Saving |
|---|---|---|
| **Config loaded once** | `fully_initialize_caches()` calls `load_config()` once and forwards it to all update functions via `functools.partial` | Eliminates ~14 redundant disk reads per cycle |
| **Moon caches merged** | `update_moon_caches()` instantiates `MoonService` and calls `get_report()` once; both `moon_report` and `dark_window` caches are written from the same result | Saves one full `MoonService.get_report()` Astropy computation per cycle |
| **Best-window single pass** | `AstroTonightService.best_windows_all_modes()` runs one 12-hour night-scan loop; AltAz transforms are computed once per step while all three modes (`strict`, `practical`, `illumination`) are evaluated simultaneously | Reduces Astropy AltAz transforms by ~66% (144 instead of 432) |

These optimisations are enforced by the `config=None` parameter pattern and must not be removed when adding or modifying cache jobs.

