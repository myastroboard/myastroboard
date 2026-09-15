# API Endpoints

This page lists the HTTP routes currently declared across `backend/blueprints/*.py` (registered in `backend/app.py`), including `backend/blueprints/skytonight_api.py`.

## Web & PWA Routes

- `GET /`
- `GET /login`
- `GET /manifest.webmanifest`
- `GET /manifest.<lang>.webmanifest`
- `GET /sw.js`
- `GET /offline.html`
- `GET /robots.txt`

## Authentication

- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/status`
- `POST /api/auth/change-password`
- `GET /api/auth/preferences`
- `PUT /api/auth/preferences`

## Push Notifications

- `GET /api/push/vapid-public-key`
- `GET /api/push/vapid-config-status`
- `POST /api/push/subscribe`
- `GET /api/push/subscriptions`
- `DELETE /api/push/subscriptions`
- `DELETE /api/push/unsubscribe`
- `POST /api/push/test`
- `POST /api/push/test/<trigger_id>`

## User Management (admin)

- `GET /api/users`
- `POST /api/users`
- `PUT /api/users/<user_id>`
- `DELETE /api/users/<user_id>`

## Administration (admin)

- `GET /api/admin/app-settings`
- `POST /api/admin/app-settings`
- `POST /api/admin/restart`

## Configuration

- `GET /api/config`
- `POST /api/config`
- `GET /api/config/export`
- `GET /api/skyquality`

## Locations (multi-location profiles, v1.2 - see docs/LOCATIONS.md)

- `GET /api/locations` (admin)
- `POST /api/locations` (admin, capped at MAX_LOCATIONS)
- `PUT /api/locations/<location_id>` (admin)
- `DELETE /api/locations/<location_id>?plans=cascade|orphan` (admin)
- `GET /api/locations/<location_id>/references` (admin)
- `POST /api/locations/<location_id>/attribute` (admin)
- `GET /api/locations/mine`
- `POST /api/locations/active`

## Backup & Restore

- `GET /api/backup/download` - Download a ZIP archive (config.json, users.json, astrodex/, equipments/)
- `POST /api/backup/restore` - Restore from a previously created backup ZIP (`multipart/form-data`, field `file`)

## Platform & Utility

- `GET /api/metrics`
- `GET /api/logs`
- `GET /api/logs/level`
- `POST /api/logs/clear`
- `GET /api/logs/export` - Download a ZIP archive of all log files (myastroboard.log + skytonight/logs/)
- `POST /api/convert-coordinates`
- `GET /api/timezones`
- `POST /api/translate/on-demand`
- `GET /api/health`
- `GET /health`
- `GET /api/cache`
- `GET /api/version`
- `GET /api/version/check-updates`
- `GET /api/catalogues`

## Scheduler

- `GET /api/scheduler/status` (legacy alias mapped to SkyTonight scheduler status)
- `POST /api/scheduler/trigger` (legacy alias mapped to SkyTonight scheduler trigger)

## SkyTonight

- `GET /api/skytonight/scheduler/status`
- `POST /api/skytonight/scheduler/trigger`
- `GET /api/skytonight/dataset/status`
- `POST /api/skytonight/dataset/rebuild`
- `GET /api/skytonight/log`
- `GET /api/skytonight/reports`
- `GET /api/skytonight/reports/<catalogue>`
- `GET /api/skytonight/alttime/<target_id>`
- `POST /api/skytonight/combination-recommendations`
- `GET /api/skytonight/visibility-calendar` - 12-month "best months to image this target" calendar for a fixed deep-sky object at the active location. Params: `target` (catalogue id or name, required), `year` (4-digit, defaults to the current year, clamped to [current-1, current+5]). Returns `supported: false` for solar-system bodies and comets.
- `GET /api/skytonight/skymap`
- `GET /api/skytonight/data/dso` - Optional `catalogue` filter, plus the v1.4 advanced filters applied server-side before the result-set truncation: `size_min`, `size_max`, `sb_max`, `alt_window_min_deg`, `alt_window_start`, `alt_window_end`, `combination_id`, `fov_fit`, `max_integration_h`. Malformed values are ignored rather than rejected. See [SKYTONIGHT.md](SKYTONIGHT.md#advanced-dso-filters).
- `GET /api/skytonight/data/bodies`
- `GET /api/skytonight/data/comets`
- `GET /api/skytonight/logs/<catalogue>`
- `GET /api/skytonight/logs/<catalogue>/exists`
- `GET /api/skytonight/target-debug`
- `GET /api/skytonight/recommendations` - Difficulty-aware "what to shoot tonight" recommendations, filtered by the user's `experience_level` preference. Params: `limit` (default 5, max 10), `lang` (mandatory for translated content).

## Weather, Moon, Sun, and Astronomy

- `GET /api/weather/forecast`
- `GET /api/weather/astro-analysis`
- `GET /api/weather/astro-current`
- `GET /api/weather/alerts`
- `GET /api/seeing-forecast`
- `GET /api/moon/report`
- `GET /api/moon/dark-window`
- `GET /api/moon/next-7-nights`
- `GET /api/moon/phase-calendar` - Full calendar month of Moon phases (illumination, waxing/waning, near-new-moon flag) plus the month's principal phase timestamps, for the active location. Params: `year`, `month` (1-12); both are clamped to the allowed 2-month window (current month and the next one), and missing or malformed values fall back to the current month. Response includes `is_current_month`, `can_go_prev`, `can_go_next`, `today`, `days`, `principal_phases`.
- `GET /api/aurora/predictions`
- `GET /api/iss/passes` - Returns ISS passes, solar transits, and lunar transits; all times in configured local TZ. Response includes `passes`, `solar_transits`, `lunar_transits`, `next_visible_passage`, `next_solar_transit`, `next_lunar_transit`, `total_passes`, `total_solar_transits`, `total_lunar_transits`.
- `GET /api/iss/location`
- `POST /api/iss/celestrak/restart`
- `GET /api/css/passes` - Returns CSS (China Space Station, NORAD 48274/Tiangong) passes, solar transits, and lunar transits. Same response structure as ISS; includes `station: "CSS"` field.
- `GET /api/css/location`
- `POST /api/css/celestrak/restart`
- `GET /api/sun/today`
- `GET /api/sun/next-eclipse`
- `GET /api/moon/next-eclipse`
- `GET /api/events/upcoming`
- `GET /api/events/planetary`
- `GET /api/events/phenomena`
- `GET /api/events/solarsystem`
- `GET /api/astro/sidereal-time`
- `GET /api/astro/horizon-graph`
- `GET /api/tonight/best-window`

## Spaceflight

- `GET /api/spaceflight/launches`
- `GET /api/spaceflight/astronauts`
- `GET /api/spaceflight/events`
- `GET /api/spaceflight/img/<filename>`
- `GET /api/spaceflight/launch/<launch_id>/vidurls`

## Connectors

- `GET /api/connectors` — List all registered connectors with installed/enabled state, module config, `target_modules` (app tabs the connector surfaces in), and a config block whose `SECRET_FIELDS` are masked (`****` + last 4, plus a `has_<field>` boolean)
- `POST /api/connectors/<name>/config` (admin) — Save one connector's config; merged server-side, and a blank or still-masked secret means "keep current"
- `GET /api/connectors/allsky/status` — Return cached AllSky sensor data (`allskydata.json`); requires `sensor_data` module enabled
- `GET /api/connectors/allsky/health` — Run a per-module health check against the AllSky instance; accepts `?fresh=1` to bypass cache
- `GET /api/connectors/allsky/urls` — Return proxy URLs for all enabled AllSky modules; accepts `?date=YYYYMMDD`
- `GET /api/connectors/allsky/proxy` — Proxy an AllSky resource through the backend; params: `module=<slug>` and optional `date=YYYYMMDD`

## Object Lookup

- `GET /api/object/<path:identifier>`

## Beginner Catalog

- `GET /api/beginner-catalog` - Curated beginner-friendly DSO catalog, enriched with `visible_tonight`/`astro_score`/`in_astrodex`/`in_plan`. Params: `lang` (mandatory), `visible_only` (default true; ignored if no SkyTonight results are cached yet).

## Astrodex

- `GET /api/astrodex`
- `GET /api/astrodex/map` - Flat list of geotagged pictures for the Photo Map sub-tab, gated by its own `map_private` config flag (independent from the general `private` sharing flag)
- `POST /api/astrodex/items`
- `POST /api/astrodex/items/<item_id>/catalogue-name`
- `GET /api/astrodex/items/<item_id>`
- `PUT /api/astrodex/items/<item_id>`
- `DELETE /api/astrodex/items/<item_id>`
- `POST /api/astrodex/items/<item_id>/pictures`
- `PUT /api/astrodex/items/<item_id>/pictures/<picture_id>`
- `DELETE /api/astrodex/items/<item_id>/pictures/<picture_id>`
- `POST /api/astrodex/items/<item_id>/pictures/<picture_id>/main`
- `POST /api/astrodex/upload`
- `GET /api/astrodex/images/<filename>`
- `GET /api/astrodex/check/<item_name>`
- `GET /api/astrodex/constellations`
- `GET /api/astrodex/catalogue-lookup`
- `GET /api/astrodex/collection/catalogues`
- `GET /api/astrodex/collection`

## MyAstroShine integration (see docs/MYASTROSHINE.md)

AstroDex <-> MyAstroShine image round-trip. Not a `BaseConnector` - config lives under `config.connectors.myastroshine` but the routes and UI are AstroDex-side.

- `GET /api/astrodex/integration/status` - `{ enabled: bool }` - drives the per-photo "Send to MyAstroShine" button
- `GET|POST /api/connectors/myastroshine/health` - Best-effort reachability probe of `<url>/api/health` (loopback / link-local / unspecified / multicast refused). GET probes the saved URL, POST the one in the body. The card's config is served by the shared connector routes above
- `POST /api/astrodex/integration/handoff` - Mint a signed, single-use handoff token for one of the caller's own pictures; returns `{ handoff, myastroshine_url, open_url }`
- `GET /api/astrodex/integration/source?handoff=<token>` - **No session cookie** (MyAstroShine container calls it). Source picture metadata for a valid handoff
- `GET /api/astrodex/integration/source/image?handoff=<token>` - **No session cookie.** Source image bytes
- `POST /api/astrodex/integration/enhanced` - **No session cookie.** `multipart/form-data` (`handoff`, `payload`, `image`) + `X-Webhook-Signature: sha256=<hex>`. Creates a duplicated picture on the same item; `201` / `401` bad signature or handoff / `409` handoff already consumed / `404` item or picture gone / `413` image too large

## Plan My Night

- `GET /api/plan-my-night/list`
- `GET /api/plan-my-night`
- `PATCH /api/plan-my-night`
- `POST /api/plan-my-night/targets`
- `PUT /api/plan-my-night/targets/<entry_id>`
- `POST /api/plan-my-night/targets/<entry_id>/reorder`
- `DELETE /api/plan-my-night/targets/<entry_id>`
- `DELETE /api/plan-my-night/clear`
- `DELETE /api/plan-my-night/clear-all`
- `POST /api/plan-my-night/targets/<entry_id>/add-to-astrodex`
- `GET /api/plan-my-night/export.csv`
- `GET /api/plan-my-night/export.pdf`

## Observation Log (v1.3 - see docs/OBSERVATION_LOG.md)

- `GET /api/observation-sessions` - Own sessions (newest observation date first) + minimal stats
- `POST /api/observation-sessions`
- `GET /api/observation-sessions/<session_id>`
- `PUT /api/observation-sessions/<session_id>`
- `DELETE /api/observation-sessions/<session_id>` - Deletes the session and its entries; linked Astrodex items/pictures are never touched
- `POST /api/observation-sessions/from-plan` - Seed/merge a session from a Plan My Night plan (works on `current` **and** `previous` plans); reuses an existing night of the same date, or appends a new one
- `POST /api/observation-sessions/<session_id>/nights` - Add another night to a multi-night session (v1.3.1)
- `PUT /api/observation-sessions/<session_id>/nights/<night_id>` - Update one night's conditions/notes (v1.3.1)
- `DELETE /api/observation-sessions/<session_id>/nights/<night_id>` - Refused while it's the session's last remaining night, or while any entry still points at it (v1.3.1)
- `POST /api/observation-sessions/<session_id>/entries` - Side effect: auto-registers the target in Astrodex when `frame_count > 0`
- `PUT /api/observation-sessions/<session_id>/entries/<entry_id>` - Same auto-registration whenever `frame_count` newly becomes `> 0`
- `DELETE /api/observation-sessions/<session_id>/entries/<entry_id>`
- `POST /api/observation-sessions/<session_id>/entries/<entry_id>/astrodex-picture` - Manual attach of an image already uploaded through `POST /api/astrodex/upload`
- `POST /api/observation-sessions/<session_id>/attachments` - Upload + record a generic session attachment (image/PDF/text/Word) in one step (v1.3.1)
- `GET /api/observation-sessions/attachments/<filename>` - Serve an attachment file, ownership-checked (v1.3.1)
- `PUT /api/observation-sessions/<session_id>/attachments/<attachment_id>` - Set/clear an attachment's custom display name (v1.3.1)
- `DELETE /api/observation-sessions/<session_id>/attachments/<attachment_id>` - Remove an attachment's record and file (v1.3.1)
- `GET /api/observation-sessions/<session_id>/export.pdf` - One session as a PDF (common info + every logged target, with its attached photo when there is one)
- `GET /api/observation-sessions/export.pdf` - Every own session as one PDF (cover + summary + per-session pages); optional `from_date`/`to_date`/`order` (`asc`/`desc`, default `asc`)

## Equipment

- `GET /api/equipment/telescopes`
- `POST /api/equipment/telescopes`
- `GET /api/equipment/telescopes/<telescope_id>`
- `PUT /api/equipment/telescopes/<telescope_id>`
- `DELETE /api/equipment/telescopes/<telescope_id>`
- `GET /api/equipment/cameras`
- `POST /api/equipment/cameras`
- `GET /api/equipment/cameras/<camera_id>`
- `PUT /api/equipment/cameras/<camera_id>`
- `DELETE /api/equipment/cameras/<camera_id>`
- `GET /api/equipment/mounts`
- `POST /api/equipment/mounts`
- `GET /api/equipment/mounts/<mount_id>`
- `PUT /api/equipment/mounts/<mount_id>`
- `DELETE /api/equipment/mounts/<mount_id>`
- `GET /api/equipment/filters`
- `POST /api/equipment/filters`
- `GET /api/equipment/filters/<filter_id>`
- `PUT /api/equipment/filters/<filter_id>`
- `DELETE /api/equipment/filters/<filter_id>`
- `GET /api/equipment/accessories`
- `POST /api/equipment/accessories`
- `GET /api/equipment/accessories/<accessory_id>`
- `PUT /api/equipment/accessories/<accessory_id>`
- `DELETE /api/equipment/accessories/<accessory_id>`
- `GET /api/equipment/combinations`
- `POST /api/equipment/combinations`
- `GET /api/equipment/combinations/<combination_id>`
- `PUT /api/equipment/combinations/<combination_id>`
- `DELETE /api/equipment/combinations/<combination_id>`
- `POST /api/equipment/fov-calculator`
- `GET /api/equipment/summary`

