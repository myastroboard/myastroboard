# API Endpoints

This page lists the HTTP routes currently declared in `backend/app.py` and `backend/skytonight_api.py`.

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

## User Management (admin)

- `GET /api/users`
- `POST /api/users`
- `PUT /api/users/<user_id>`
- `DELETE /api/users/<user_id>`

## Configuration

- `GET /api/config`
- `POST /api/config`
- `GET /api/config/export`
- `GET /api/skyquality`

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
- `POST /api/skytonight/telescope-recommendations`
- `GET /api/skytonight/skymap`
- `GET /api/skytonight/data/dso`
- `GET /api/skytonight/data/bodies`
- `GET /api/skytonight/data/comets`
- `GET /api/skytonight/logs/<catalogue>`
- `GET /api/skytonight/logs/<catalogue>/exists`

## Weather, Moon, Sun, and Astronomy

- `GET /api/weather/forecast`
- `GET /api/weather/astro-analysis`
- `GET /api/weather/astro-current`
- `GET /api/weather/alerts`
- `GET /api/seeing-forecast`
- `GET /api/moon/report`
- `GET /api/moon/dark-window`
- `GET /api/moon/next-7-nights`
- `GET /api/aurora/predictions`
- `GET /api/iss/passes` - Returns passes, solar transits, and lunar transits; all times in configured local TZ. Response includes `passes`, `solar_transits`, `lunar_transits`, `next_visible_passage`, `next_solar_transit`, `next_lunar_transit`, `total_passes`, `total_solar_transits`, `total_lunar_transits`.
- `GET /api/iss/location`
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

## Object Lookup

- `GET /api/object/<path:identifier>`

## Astrodex

- `GET /api/astrodex`
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

