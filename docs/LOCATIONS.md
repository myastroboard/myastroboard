# Multi-location Profiles (v1.2)

MyAstroBoard supports up to **5 observing location presets** per install. Locations are
created and managed by an administrator, attributed to users, and each user picks which
attributed location is *active* — the active location drives every location-dependent
calculation (weather, astro forecasts, aurora, ISS/CSS passes, seeing, events, sky widget).

---

## Table of contents

1. [Concepts](#concepts)
2. [Data model](#data-model)
3. [Active-location resolution](#active-location-resolution)
4. [API endpoints](#api-endpoints)
5. [Cache architecture](#cache-architecture)
6. [Rate-limit analysis & the MAX_LOCATIONS cap](#rate-limit-analysis--the-max_locations-cap)
7. [SkyTonight scope in v1.2](#skytonight-scope-in-v12)
8. [Astrodex & Plan My Night](#astrodex--plan-my-night)
9. [Notifications](#notifications)
10. [Deletion workflow](#deletion-workflow)
11. [Migration from single-location installs](#migration-from-single-location-installs)

---

## Concepts

| Term | Meaning |
|---|---|
| **Location preset** | Admin-created record: name, lat/lon, elevation, timezone, Bortle/SQM, per-location horizon profile. Stored in `config.json` under `locations[]`. |
| **Install default** | Exactly one preset carries `is_install_default: true` at all times. It is the fallback for users with no attributed location, the cadence anchor for the nightly SkyTonight batch, and the anchor for legacy compatibility. |
| **Attribution** | Admin-controlled many-to-many: a preset can be attributed to several users, a user can hold several presets. Admins implicitly have access to every preset. |
| **Default location** (per user) | The durable preference "what should be shown when I connect" (`preferences.location.default_location_id`). |
| **Active location** (per user) | What actually drives calculations *right now*, this session (`preferences.location.active_location_id`). Changed via the sky-widget switcher; reset to the default on every fresh login. |

The sky-widget switcher panel opens on click/tap only (never hover - a hover-open panel is unreachable by pointer once the location list needs to be clicked). Each row shows the location's current observation score (0-10, read from that location's warm `weather_forecast` cache - never a live fetch). When the active location's timezone differs from the viewer's browser timezone, the widget shows a small offset badge and an explanatory note: every time displayed anywhere in the app (sun/moon times, forecasts, passes) is the **location's own local time**, not the viewer's.

## Data model

### `config.json` — presets (admin-managed, global)

```jsonc
{
  "locations": [
    {
      "id": "3f1c9e2a-…-uuid4",        // server-generated, immutable, never client-supplied
      "name": "Paris",
      "latitude": 48.866669,
      "longitude": 2.33333,
      "elevation": 35,
      "timezone": "Europe/Paris",
      "bortle": null,
      "sqm": null,
      "horizon_profile": [],            // per-preset custom horizon (moved from skytonight.constraints)
      "is_install_default": true,
      "created_at": "2026-07-15T00:00:00Z",
      "updated_at": "2026-07-15T00:00:00Z"
    }
  ]
}
```

The legacy singular `location` key is migrated to `locations[]` on first load after
upgrade (see [Migration](#migration-from-single-location-installs)). `id` is the foreign
key used by user preferences, cache slots, Astrodex items and Plan My Night plans — it
survives renames.

### `users.json` — per-user selection (`preferences.location`)

```jsonc
"location": {
  "attributed_location_ids": ["<id>"],  // admin-assigned; empty = install default only
  "default_location_id": "<id>",         // shown when the user connects
  "active_location_id": "<id>",           // drives calculations right now
  "order": ["<id>"]                        // display order in the quick switcher
}
```

On each successful login, `active_location_id` is reset to `default_location_id` — a
mid-session switch never outlives the session.

## Active-location resolution

Every backend consumer calls `repo_config.get_active_location(config, user)` instead of
reading `config["location"]`. Fallback chain:

```
user's active → user's default → install default → first attributed
```

Only ids that still exist in `config["locations"]` are trusted. Admins bypass
attribution entirely (every preset is implicitly theirs).

The set of locations the cache scheduler keeps warm is
`repo_config.get_scheduler_locations(config)`: the install default + every preset
attributed to at least one user + any preset currently selected as someone's
active/default. An unattributed, unused preset costs nothing until someone selects it.

## API endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/locations` | admin | List all presets with attribution info + `max_locations` |
| `POST` | `/api/locations` | admin | Create preset (enforces `MAX_LOCATIONS`) |
| `PUT` | `/api/locations/<id>` | admin | Edit preset; coordinate/timezone change resets only that preset's caches. `is_install_default: true` promotes atomically. |
| `GET` | `/api/locations/<id>/references` | admin | Pre-delete check: attributed users, Astrodex item count, Plan My Night plan count |
| `DELETE` | `/api/locations/<id>?plans=cascade\|orphan` | admin | Delete (blocked while install default). `cascade` (default) deletes pinned plans; `orphan` keeps them with a stale-location banner. |
| `POST` | `/api/locations/<id>/attribute` | admin | `{user_ids: [...]}` — attach to exactly these users |
| `GET` | `/api/locations/mine` | any user | Caller's attributed locations (id/name/bortle/sqm only — no live sky data), active + default ids |
| `POST` | `/api/locations/active` | any user | `{location_id}` — set the caller's active location |

Compatibility: `GET /api/config` still exposes the **caller's active location** under
the legacy `location` key; `POST /api/config` with a legacy `location` payload updates
the **install default** preset (used by the setup wizard).

## Cache architecture

See also `docs/CACHE_SYSTEM.md`. Caches are split into two buckets:

- **Location-scoped** (one slot per preset id, on-disk key `"<name>:<location_id>"` in
  `astro_cache.json`): `moon_report`, `dark_window`, `moon_planner`, `sun_report`,
  `best_window_*`, `solar_eclipse`, `lunar_eclipse`, `horizon_graph`, `aurora`,
  `iss_passes`, `css_passes`, `planetary_events`, `special_phenomena`,
  `solar_system_events`, `sidereal_time`, `seeing_forecast`, `weather_forecast`.
- **Global** (single slot, external data does not vary by observer): `spaceflight_*`,
  `iers`, AllSky connector, version check. The ISS/CSS **TLE fetch** is also global
  (satellite-specific, has its own on-disk cache); only the local pass-visibility
  computation runs per location.

The scheduler expands every location-scoped job into one work unit per scheduler
location, each gated by its own `(job, location)` TTL. Job × location units feed the
same fixed-size `ThreadPoolExecutor(max_workers≤6)` pool, so total in-flight requests
never exceed the pre-v1.2 ceiling regardless of location count.

Editing one preset's coordinates invalidates only that preset's caches
(`cache_store.reset_caches_for_location(id)`), not the whole install. Metrics rows for
non-default locations are recorded as `"<job>@<location-slug>"`.

The Open-Meteo single-flight lock, failure cooldown and shared concurrency gate stay
**global** (not per-location) so multi-location installs respect the provider's
concurrency limit as one shared budget.

`weather/weather_astro.py`'s in-memory analysis cache is keyed by
`(hours, language, location_id)` — pre-v1.2 it lacked the location dimension, which
would have served one location's analysis to another location's tab.

## Rate-limit analysis & the MAX_LOCATIONS cap

`MAX_LOCATIONS = 5` (`backend/utils/constants.py`). **Not admin-configurable**: every
self-hosted MyAstroBoard instance shares the same free, keyless Open-Meteo/7Timer
capacity pool. This is a collective-good constraint (avoid provider-side blacklisting
for everyone), not a per-install tuning knob.

### Which APIs scale with location count?

Only two external services take lat/lon as request parameters:

| API | Scales with N locations? |
|---|---|
| **Open-Meteo** (weather + astro analysis + live conditions) | **Yes** |
| **7Timer** (seeing) | **Yes** |
| NOAA SWPC (Kp), Celestrak/TLE mirrors, Launch Library 2, IERS | No — global data fetched once |

### Recompute this if a provider publishes a quota

Neither provider publishes a hard numeric quota today; the documented Open-Meteo
protection is *concurrency*-based (single-flight + 90 s shared cooldown in
`weather/weather_utils.py` / `weather/weather_openmeteo.py`).

```
calls_per_hour_per_location(job) = 3600 / TTL_seconds(job)

Open-Meteo, per location, per hour:
  scheduled hourly-forecast job     (TTL 3600s)  → 1.0 call/h
  astro-analysis job                (TTL 1800s)  → 2.0 call/h  [only while viewed]
  live-conditions fetch             (debounced)  → ≤ 12 call/h worst case
      (SKYTONIGHT_LIVE_CONDITIONS_DEBOUNCE_SECONDS = 300, per-location server-side)
  ⇒ steady state ≈ 3 calls/h/location; bounded worst case ≈ 15 calls/h/location

7Timer, per location, per hour:
  seeing-forecast job               (TTL 21600s) → 0.167 call/h (negligible)

total_calls_per_hour(N) ≈ N × 15   [Open-Meteo, pathological worst case]
                        ≈ N × 3    [Open-Meteo, realistic steady state]

If a provider publishes an explicit quota Q (calls/hour):
  N_max     = floor(Q / calls_per_hour_per_location)
  final cap = min(N_max, concurrency-safety cap)
```

At N=5, Open-Meteo sees ≈15–75 calls/hour — trivial volume. The real risk is N
locations' jobs firing concurrently in the same scheduler tick, which is bounded by the
fixed worker pool and the global single-flight/cooldown gate described above.

## SkyTonight per location (v1.2)

The nightly SkyTonight calculation runs **once per scheduler location** (install
default + attributed/active presets, bounded by `MAX_LOCATIONS`). Two opposite
locations therefore get genuinely different night tables, and the alt-time graph
overlays the right site's horizon.

- Each run builds the targets dataset **once** (catalogue ingestion is
  location-independent), then executes `run_calculations(config, location=preset)` for
  every scheduler location sequentially.
- Result files are stored per preset id:
  `data/skytonight/calculations/<location_id>/{calculation_results,dso_results,bodies_results,comets_results,skymap_data}.json`
  and `data/skytonight/outputs/<location_id>/<target>_alttime.json`. Pre-v1.2 flat
  files are deleted at container startup (`entrypoint.sh`); a location with no
  results yet is simply picked up by the scheduler's next run.
- Every `/api/skytonight/*` endpoint resolves the requesting user's **active
  location** (`get_active_location`) and serves that preset's results — including
  `horizon_profile` overlays (alt-time, skymap) and `target-debug` diagnostics.
- The scheduler's dawn/dusk **cadence anchors** stay on the install default preset
  (one nightly batch window); the loop also fires whenever any scheduler location has
  no results yet (new preset, or results dropped after a coordinate change).
- Creating/attributing a preset makes it part of the next batch automatically;
  updating a preset's coordinates or deleting it drops its result files
  (`skytonight_storage.drop_location_results`).
- The **live conditions** fetch (`get_skytonight_conditions`) uses the requester's
  active location, debounced server-side per location.

The nightly pass is a minutes-long Astropy computation, so the batch cost scales with
the number of scheduler locations — this is pure local CPU (no external API quota) and
bounded by `MAX_LOCATIONS = 5`.

## Astrodex & Plan My Night

- **Astrodex pictures** (not items) carry the location - `location_id` (best-effort live
  link, or `null` for a free-text "somewhere else" label the uploader typed instead of
  picking a preset) and `location_name` (frozen snapshot, resolved from the preset or
  typed by the uploader). Coordinates (`latitude`/`longitude`/`elevation`) are resolved
  server-side from the preset and are **private to the picture's owner** - the
  shared/merged Astrodex view strips them from every other user's pictures, keeping only
  `location_name` visible. An item itself has no location field: the same object is
  commonly re-photographed from different sites across sessions, so the UI derives an
  "observed at" summary from the item's own pictures instead of storing one redundant,
  potentially-stale value on the item. Unlike items, a picture's location is editable
  after the fact (via the same add/edit picture form) - a photo is often uploaded well
  after the session, and older pictures predate this field entirely. Astrodex is
  **never** cascade-deleted with a preset.
- **Plan My Night plans** are pinned at creation to the creator's current active
  location (`plan.location_id` + `plan.location_name`). The plan is never silently
  recomputed against different coordinates; the UI shows a warning banner when the
  viewer's active location differs from the plan's pinned location. Plans pinned to a
  deleted preset are cascade-deleted by default.

## Notifications

Location-scoped triggers (N3 ISS, N4/N5 eclipses, N6 darkness, N7 aurora, N8 CSS) run
once per **(user, attributed location)** pair, reading that location's caches. Cooldown
keys include the location id so two watched locations don't suppress each other.

- The location name is appended to the push body **only for users with more than one
  attributed location** (`settings.push_location_suffix` i18n key) — single-location
  installs keep messages exactly as before.
- Plan triggers (N1/N2) stay per-plan and mention the plan's pinned location name.
- Users can mute individual locations via
  `preferences.notifications.disabled_location_ids` (My Settings → Notifications →
  Locations; the block only appears with >1 attributed location).

## Deletion workflow

1. Deleting the preset flagged `is_install_default` is **refused** until another preset
   is promoted (there must always be exactly one install default).
2. User pointers (`attributed_location_ids`, `default_location_id`,
   `active_location_id`, `order`) are cleaned **eagerly** at delete time; default/active
   pointers are reset to the install default.
3. **Astrodex is never touched** — pictures referencing the deleted preset keep their
   frozen `location_name` snapshot (`location_id` just stops resolving live).
4. **Plan My Night** plans pinned to the preset are cascade-deleted by default
   (`?plans=orphan` keeps them; the UI then shows the stale-location banner).
5. The preset's cache slots and tracked signature are dropped
   (`cache_store.drop_location_caches`).

## Migration from single-location installs

Automatic, one-time, on the first `load_config()` after upgrade
(`repo_config._ensure_locations`):

1. The legacy `location` dict is wrapped into `locations: [{…, id: <uuid4>, is_install_default: true}]`
   and the singular key removed.
2. A legacy global `skytonight.constraints.horizon_profile` is moved onto that preset.
3. The migrated config is saved immediately so the preset id stays stable across
   workers/restarts.
4. On the first scheduler cycle, `cache_updater.check_and_handle_config_changes()`
   renames the pre-v1.2 plain cache keys (`"sun_report"` → `"sun_report:<id>"`) so the
   warm cache survives the upgrade with **no recompute/refetch storm**, and transfers
   the legacy location-change signature onto the preset id.
5. Users need no migration: the resolver's fallback chain sends users without a
   `preferences.location` block to the install default, which matches pre-v1.2
   behavior exactly.

Rollback note: the migration is one-way (the singular key is removed). Downgrading to a
pre-v1.2 image requires restoring `data/config.json` from a backup.
