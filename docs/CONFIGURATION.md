# Configuration

MyAstroBoard stores its runtime configuration in `data/config.json`. All settings are managed through the **Parameters** tab (admin only) in the UI or via the `/api/config` endpoint.

---

## Parameters tab layout

| Sub-tab | Content |
|---------|---------|
| **Locations** | Location presets: coordinates, timezone, sky quality, horizon profile, user attribution (v1.2 — see [LOCATIONS.md](LOCATIONS.md)) |
| **Configuration** | Global app settings (Astrodex privacy) |
| **Advanced** | SkyTonight constraints, scheduler, app settings |
| **Connectors** | External tool connectors (AllSky, etc.) |
| **Logs** | Live log viewer and export |
| **Users** | User management (admin only) |
| **Metrics** | Scheduler and cache performance dashboard |
| **Backup & Restore** | Download and restore configuration archives |

---

## Locations (v1.2 — multi-location profiles)

Since v1.2, `config.json` holds an admin-managed `locations` list (up to `MAX_LOCATIONS = 5` presets) instead of a single `location` object. At least one preset is **required** before most calculations can run; editing a preset's coordinates resets only that preset's caches.

Full reference — data model, attribution, per-user default/active location, rate-limit analysis behind the cap: **[LOCATIONS.md](LOCATIONS.md)**.

Each preset carries:

| Field | Description | Default |
|-------|-------------|---------|
| `id` | Server-generated uuid4, immutable | — |
| `name` | Human-readable site name | `"Paris"` |
| `latitude` | Decimal degrees, −90 to +90 | `48.866669` |
| `longitude` | Decimal degrees, −180 to +180 | `2.33333` |
| `elevation` | Altitude above sea level in metres | `35` |
| `timezone` | IANA timezone string (e.g. `Europe/Paris`) | `"Europe/Paris"` |
| `bortle` / `sqm` | Sky quality (see below) | `null` |
| `horizon_profile` | Per-preset horizon mask (see below) | `[]` |
| `is_install_default` | Exactly one preset carries `true` | first preset |

The timezone field determines how all local times (moonrise, sunset, event times…) are displayed throughout the app for users observing from that preset. `GET /api/timezones` returns all valid IANA timezone strings for the dropdown.

A coordinate converter is available at `POST /api/convert-coordinates` to translate between decimal degrees and DMS (degrees/minutes/seconds).

Legacy single-location configs are migrated automatically on first load after upgrade (the old `location` key and the old global horizon profile move onto the first preset — zero manual action required).

### Sky quality (light pollution)

Set per location preset:

| Field | Description |
|-------|-------------|
| `bortle` | Bortle class 1–9 (optional). Determines the SQM midpoint estimate. |
| `sqm` | Sky Quality Meter reading in mag/arcsec² (optional, overrides Bortle midpoint). |

See [SKYTONIGHT.md — Light Pollution Integration](SKYTONIGHT.md) for how these values affect AstroScore.

---

## SkyTonight constraints

These values live under `config.json → skytonight.constraints`. They define which objects are considered observable. All constraints are always active.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `altitude_constraint_min` | 30° | Minimum target altitude above the horizon |
| `altitude_constraint_max` | 80° | Maximum target altitude (avoids zenith blind spot for some mounts) |
| `airmass_constraint` | 2.0 | Maximum airmass (≈ 30°+ elevation) |
| `size_constraint_min` | 0 arcmin | Minimum angular size for DSOs (0 = no lower limit) |
| `size_constraint_max` | 300 arcmin | Maximum angular size |
| `moon_separation_min` | 45° | Minimum angular distance from the Moon |
| `moon_separation_use_illumination` | `true` | When `true`, overrides `moon_separation_min` with Moon illumination % → degrees (e.g. 60 % full Moon → 60° separation required) |
| `fraction_of_time_observable_threshold` | 0.50 | DSOs must be within all constraints for ≥ 50 % of the night to appear in results |
| `north_to_east_ccw` | `false` | Azimuth convention: `false` = clockwise from North (standard); `true` = counter-clockwise |

---

## Custom horizon profile

Since v1.2 the horizon profile is a **per-location preset field** (`locations[].horizon_profile`, edited in the location's edit modal) instead of the former global `skytonight.constraints.horizon_profile`. It stores an array of `[azimuth, altitude]` pairs that describe the site's local horizon mask — mountains, buildings, or trees that block the view at specific azimuths.

```json
"horizon_profile": [
  [0, 5],
  [45, 15],
  [90, 8],
  [180, 2],
  [270, 6],
  [315, 10]
]
```

SkyTonight evaluates each target against the horizon profile: if the object's altitude at a given azimuth is below the profile altitude for that direction, it counts as blocked. Targets are scored only during the fraction of time they clear both the global `altitude_constraint_min` and the horizon profile.

The profile is set in **Parameters → Locations → (edit a preset) → Custom Horizon Profile**. Enter points manually per location.

---

## Scheduler configuration

`config.json → skytonight.scheduler`

| Field | Description |
|-------|-------------|
| `mode` | `"astro"` (runs at dawn+1h and dusk−1h) or `"fallback-6h"` (runs every 6 hours when clock is unreliable) |
| `server_time_valid` | `true` when the system clock is considered accurate (NTP synced) |

See [SKYTONIGHT.md — Scheduler](SKYTONIGHT.md) for scheduling logic.

---

## Dataset configuration

`config.json → skytonight.datasets`

| Field | Default | Description |
|-------|---------|-------------|
| `datasets.catalogues.deep_sky` | `true` | Enable DSO catalogue processing |
| `datasets.catalogues.bodies` | `true` | Enable solar-system body calculations |
| `datasets.catalogues.comets` | `true` | Enable comet processing |
| `datasets.comets.source` | `"mpc+jpl"` | Comet orbital data source: `"mpc"`, `"jpl"`, or `"mpc+jpl"` |
| `datasets.comets.auto_update` | `true` | Automatically refresh comet elements before each calculation |

---

## Application settings (admin)

Stored separately in `data/app_settings.json` (see [AUTHENTICATION.md](AUTHENTICATION.md)):

| Setting | Default | Description |
|---------|---------|-------------|
| `vapid_contact_email` | `""` | Contact email for Web Push VAPID tokens (required for iOS push) |
| `trust_proxy_headers` | `false` | Enable `X-Forwarded-For` / `X-Forwarded-Proto` forwarding (reverse proxy deployments) |
| `session_cookie_secure` | `false` | Require HTTPS for session cookie |

---

## Connectors

**Sub-tab**: Parameters → Connectors

Connector configuration is stored in `config.json → connectors.<name>`. See [CONNECTORS.md](CONNECTORS.md) for the full reference.

```json
"connectors": {
  "allsky": {
    "url": "http://allsky.local",
    "label": "My AllSky",
    "enabled": true,
    "image_path": "current/tmp",
    "image_filename": "image.jpg",
    "export_json_path": "allskydata.json",
    "modules": {
      "live_image":      { "enabled": true },
      "sensor_data":     { "enabled": false },
      "keogram":         { "enabled": true },
      "startrails":      { "enabled": false },
      "daily_timelapse": { "enabled": false },
      "mini_timelapse":  { "enabled": false }
    }
  }
}
```

---

## Backup and restore

**Sub-tab**: Parameters → Backup & Restore

### Download backup

`GET /api/backup/download` produces a ZIP archive containing:

| File / folder | Content |
|---------------|---------|
| `config.json` | All site configuration |
| `users.json` | All user accounts (with password hashes) |
| `astrodex/` | All Astrodex collections (one JSON per user + `images/` subdirectory) |
| `equipments/` | All equipment profiles (one JSON per user per equipment type) |

The archive is named `myastroboard_backup_<timestamp>.zip`.

### Restore backup

`POST /api/backup/restore` (multipart form, field `file`) accepts a backup ZIP and restores its contents. The existing files are overwritten.

> **After a restore**: The app re-reads configuration from disk on the next request. Cache is reset automatically. A page reload is required to reflect restored user accounts.

---

## Logs

**Sub-tab**: Parameters → Logs

### Live log viewer

`GET /api/logs` returns the tail of `data/logs/myastroboard.log` for live viewing in the browser. The log level shown can be checked with `GET /api/logs/level`.

Log lines are JSONL-formatted (one JSON object per line): `{"level": "INFO", "time": "...", "msg": "...", "module": "..."}`.

### Export logs

`GET /api/logs/export` downloads a ZIP archive containing:
- `myastroboard.log` — main application log
- `skytonight/logs/last_calculation.log` — last SkyTonight run log

Attach this file to GitHub issues to help maintainers diagnose problems.

### Clear logs

`POST /api/logs/clear` truncates the main log file (admin only).

---

## Metrics

**Sub-tab**: Parameters → Metrics (admin only)

`GET /api/metrics` returns system metrics including:

| Section | Content |
|---------|---------|
| **Cache jobs** | Per-job TTL, last run time, duration, success/failure |
| **Scheduler** | SkyTonight scheduler status and last run |
| **System** | Uptime, Python version, worker count |

The metrics tab is the first place to check if a cache job is repeatedly failing or taking unexpectedly long.

---

## App restart

`POST /api/admin/restart` (admin only) triggers a graceful application restart. This is needed after changes to `app_settings.json` that affect Flask configuration (e.g. enabling `session_cookie_secure`).

---

## Configuration API

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/api/config` | login | Read full config; also exposes the caller's *active* location under `location` (compat shim) |
| `POST` | `/api/config` | admin | Save global config; a legacy `location` payload updates the install default preset (its caches only are reset) |
| — | `/api/locations*` | admin/login | Location preset CRUD, attribution, switcher — see [LOCATIONS.md](LOCATIONS.md) and [API_ENDPOINTS.md](API_ENDPOINTS.md) |
| `GET` | `/api/config/export` | admin | Download `config.json` directly |
| `GET` | `/api/skyquality` | login | Current sky quality parameters and computed LP factor |
| `GET` | `/api/admin/app-settings` | admin | Read `app_settings.json` |
| `POST` | `/api/admin/app-settings` | admin | Save `app_settings.json` |
| `POST` | `/api/admin/restart` | admin | Restart the app |
| `GET` | `/api/backup/download` | admin | Download backup ZIP |
| `POST` | `/api/backup/restore` | admin | Restore from backup ZIP |
| `GET` | `/api/logs` | admin | Tail of main log file |
| `GET` | `/api/logs/level` | admin | Current log level |
| `POST` | `/api/logs/clear` | admin | Truncate log file |
| `GET` | `/api/logs/export` | admin | Download log ZIP |
| `GET` | `/api/metrics` | admin | System and cache metrics |
| `GET` | `/api/version` | login | Current app version from `VERSION` file |
| `GET` | `/api/version/check-updates` | login | Compare against latest GitHub release |
| `GET` | `/api/timezones` | login | All valid IANA timezone strings |
| `POST` | `/api/convert-coordinates` | login | Convert DMS ↔ decimal degrees |
| `GET` | `/api/health` | Public | Health check (returns `{"status": "ok"}`) |
| `GET` | `/api/catalogues` | login | List all loaded SkyTonight catalogue counts |
