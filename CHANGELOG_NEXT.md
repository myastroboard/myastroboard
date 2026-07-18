#### 1.2 Version - Multi-location Profiles

Observers travel - to the backyard, to the club field, to that dark-sky site three hours away. Until now, MyAstroBoard only knew about one of those places at a time.

This release introduces multi-location profiles: admins can create up to 5 location presets (each with its own coordinates, timezone, Bortle/SQM sky quality and custom horizon profile) and attribute them to users. Every user picks a favorite default and can switch the active location instantly from the sky status widget - forecasts, SkyTonight, ISS/CSS passes, events and notifications all follow. Switching is instant because every location keeps its own warm cache; no recompute, no waiting.

#### Notable change

- Add admin-managed location presets (Parameters -> Locations): create/edit/delete up to `MAX_LOCATIONS = 5` presets, each with name, coordinates, elevation, timezone, Bortle/SQM and a per-preset custom horizon profile (moved from Advanced constraints) - see docs/LOCATIONS.md
- Add per-user location attribution (admin assigns presets to users, many-to-many), per-user default location ("what I see when I connect"), per-user ordering, and a session-scoped active location reset to the default on each fresh login
- Add location switcher inside the sky status widget panel: users with more than one attributed location can switch the active location in one tap; single-location installs see no visual change. The panel opens on click/tap only (no hover), shows each location's current observation score, and flags when the active location's timezone differs from yours
- Add a minimap preview (Leaflet) to each admin location card (Parameters -> Locations)
- Add per-location breakdown to the Cache Jobs metrics table: multi-location jobs show an aggregated status plus an expandable per-location detail row (last run, duration, TTL validity)
- Add per-location cache slots: editing one preset's coordinates invalidates only that preset's caches, and switching locations serves already-warm data instantly (see docs/CACHE_SYSTEM.md)
- Add per-location SkyTonight: the nightly calculation runs once per scheduler location (shared dataset build, per-preset night tables, alt-time graphs, skymap and horizon overlays), every /api/skytonight endpoint serves the requester's active location, and existing results migrate automatically to the new per-location layout
- Add location pinning to Plan My Night plans (created against the active location, with a warning banner when viewing from a different location) and plain-text location snapshots on Astrodex items (never deleted with the preset)
- Add per-location push notification handling: messages mention the location name when a user has several locations, and each location can be muted individually in My Settings -> Notifications
- Add `GET/POST /api/locations`, `PUT/DELETE /api/locations/<id>`, `GET /api/locations/<id>/references`, `POST /api/locations/<id>/attribute`, `GET /api/locations/mine`, `POST /api/locations/active` endpoints (see docs/API_ENDPOINTS.md)
- Automatic one-time migration: existing single-location installs are converted to a one-preset setup with zero manual action; all user preferences keep working
- Add an optimizer service for a plan in plan-my-night
- Complete reorganization of `backend` folder because app grow too much to don't be organized!
