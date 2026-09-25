# Changelog

All notable changes to MyAstroBoard are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project aims to
adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Features

- None.

### Fixes

- Release process: `v1.6.2`'s Docker image was built from the commit just before the `VERSION`
  bump, so the running app reported itself as `1.6.1` even though it was published under the
  `1.6.2`/`latest` tags. This release has no functional changes beyond correcting that mismatch -
  if you're on a correctly-versioned `1.6.2` already, there is nothing new for you here.

### Breaking changes

- None.

## 1.6.2 (2026-09-25)

### Features

- None.

### Fixes

- MQTT / Home Assistant `next_event` sensor: `title`/`description` were silently composed in
  English regardless of the viewer's language (the connector never had a `language` setting to
  begin with). Now hardcoded English on purpose, with the event's raw variable piece
  (`eclipse_type`, `planet`/`planet2`, `shower_name`, `comet_name`) exposed as new attributes so
  MQTT consumers (e.g. a Lovelace card) can translate client-side instead of showing mixed-language
  text.
- Machine-translation bugs found while building that client-side translation table:
  `skytonight.type_ass` (an OpenNGC catalogue code, not a word) had been translated as slang for
  "buttocks" in `de`/`es`/`it`/`pt`, `de.json`'s `skytonight.type_open_cluster` read as an
  imperative ("open the cluster!") instead of the noun phrase, `de.json`'s `eclipse_type.total`/
  `.partial` used "Gesamt" (sum/aggregate) and an adverb instead of the astronomy adjectives, and
  `it`/`pt.json`'s entire `planets.*` namespace was left as literal English words. All corrected.

### Breaking changes

- None.

## 1.6.1 (2026-09-25)

### Features

- MQTT / Home Assistant board device: the update indicator is now a native Home Assistant
  `update` entity (installed/latest version, a link to the changelog) instead of a diagnostic
  binary sensor + a separate version sensor, so it shows up in HA's own Updates list and sidebar
  badge. No remote install (MyAstroBoard is a Docker image you update yourself), so there is no
  Install button - the entity is informational only.

### Fixes

- None.

### Breaking changes

- None.

## 1.6.0 (2026-09-23)

### Features

- Two-factor authentication (TOTP) available per account, off by default: an admin enables it
  instance-wide under Parameters -> Users (requires at least one trusted network), then each user
  opts in from My Settings -> Security. Setup shows a QR code plus the raw secret as a fallback.
- Trusted networks list (Parameters -> Users): CIDR blocks or IPs that skip the 2FA prompt;
  127.0.0.1 and ::1 are always trusted. An account can be restricted to sign in only from a
  trusted network (local vs. global scope), defaulting to global for every account.
- MQTT / Home Assistant connector (Parameters -> Connectors): publishes sky conditions, weather-
  for-astro numbers, upcoming events, a user's own activity (opt-in), the latest Astrodex picture
  and diagnostics as Home Assistant devices - publish-only, no YAML required. See
  [docs/HOME_ASSISTANT.md](docs/HOME_ASSISTANT.md).
- Astrodex Stream connector (Parameters -> Connectors): a personal, auto-refreshing photo
  slideshow URL for Home Assistant's Generic Camera integration (or any still-image viewer),
  cropped to your chosen aspect ratio with an object-name-and-date banner. Every user gets their
  own signed URL; an admin can rotate the signing key at any time. See
  [docs/ASTRODEX_STREAM.md](docs/ASTRODEX_STREAM.md).

### Fixes

- Multi-worker reliability: the log file and its rotated backups no longer lose or reorder
  lines, and concurrent account changes (password, 2FA, push subscription) no longer undo each
  other.
- Astrodex, Observation Log, Wishlist and Plan My Night saves no longer overwrite each other when
  two saves for the same user land at the same time.
- Push notification keys, the default location, and connector credential migration are now
  created/migrated exactly once instead of racing across the two server workers.
- MyAstroShine handoff links can no longer be reused twice, and a failed enhancement can be
  retried with the same link. Visibility calendars and the SkyTonight target list now refresh
  correctly right after an edit or a dataset rebuild.
- Connector cards: the test button now sends the credentials as typed (never the stored ones),
  and a failed test shows why (refused, timeout, not authorized...) instead of a bare
  "Unreachable".
- Add additional tests to improve coverage

### Breaking changes

- Connector credentials (the MQTT password, the MyAstroShine token and signing secret) are now
  stored outside `config.json` and are no longer part of backups or the config export. Existing
  installs migrate automatically; after restoring a backup on another machine, re-enter the
  connector credentials once.

## 1.5.0 (2026-09-17)

### Features

- Session Analytics: new **Your Sky** sub-tab under Astrodex (lifetime/yearly/monthly
  integration hours, objects/constellations captured, integration over time, per-combination
  hours), a sky coverage map (captured objects on an RA/Dec chart, coloured by type or capture
  year), conditions-vs-results plots (ratings against logged seeing/transparency/SQM/Moon
  illumination), and a best-months chart (dark/moonless-dark hours per month) - all computed
  from the Observation Log.
- Headline figures plate: Astrodex, Observation Log and Your Sky now share one hero-figure-plus-
  context-row layout instead of a grid of identical stat cards.
- Wishlist sub-tab: objects you want to capture, with priority, notes and a progress bar; add
  from SkyTonight, the Catalogue Collection or the Beginner Catalog. Captured state is
  recomputed live from your log and Astrodex, duplicate detection is cross-catalogue, and the
  list is sorted by upcoming visibility by default. Private per user, included in backups.

### Fixes

- A zero-duration session displayed as a bare "0" with no unit.
- DMS-to-decimal coordinate conversion mis-signed a negative-zero degrees field (e.g.
  `-0d30m00s` came back as `+0.5` instead of `-0.5`).

### Breaking changes

- None.

## 1.4.3 (2026-09-13)

### Features

- Search-engine indexing is now off by default everywhere, including the login page, for
  privacy; an opt-in setting is available if you need it.

### Fixes

- Login page style issue on small mobile screens.

### Breaking changes

- None.

## 1.4.2 (2026-09-10)

### Features

- None.

### Fixes

- Duplicate notifications: with background Web Push active, N1-N9 alerts were delivered twice
  (once by the server-side push scheduler, once by the in-app poller). The in-app poller now
  steps aside whenever a working push subscription exists.
- The astronomical-night (N6) in-app message now matches the push wording exactly, including the
  dusk time, and fixes missing accents in the FR/ES/PT strings.
- Astrodex: the equipment combination dropdown is now sorted alphabetically; adding a new object
  opens its detail view immediately; fixed a false "already in your Astrodex" match between two
  different objects sharing a catalogue common name (e.g. NGC 6992 and NGC 6995, both "Eastern
  Veil").
- SkyTonight: the sky map's minimum-AstroScore slider now updates on release instead of on every
  step of the drag.

### Breaking changes

- None.

## 1.4.1 (2026-09-09)

### Features

- MyAstroShine integration: round-trip an Astrodex photo through
  [MyAstroShine](https://github.com/myastroboard/myastroshine) for re-processing and get the
  enhanced result back as a new picture on the same object - the original is never modified. New
  connector card (Parameters -> Connectors) with URL/token/signing secret and a reachability
  test; a "Send to MyAstroShine" action on any owned photo; the Astrodex view refreshes itself
  when you switch back. Pull-and-webhook architecture using a signed, single-use, 12-hour
  handoff token. See [docs/MYASTROSHINE.md](docs/MYASTROSHINE.md).

### Fixes

- Astrodex photo card and detail view now show the linked equipment combination name
  (previously could show no equipment at all when only a combination was set).
- The photo action row now wraps cleanly on narrow cards instead of overflowing.
- Offline page styling improved for responsiveness and accessibility.

### Breaking changes

- None.

## 1.4.0 (2026-09-03)

### Features

- Target visibility calendar: a 12-month heatmap of dark, observable and moonless-observable
  hours for a deep-sky object, opened from SkyTonight or an Astrodex item
  (`GET /api/skytonight/visibility-calendar`).
- Advanced SkyTonight filters: angular size, surface brightness, best altitude window, "fits my
  sensor" for a chosen equipment combination, and a maximum estimated integration time - all
  server-side, catalogue-wide (see [docs/EXPOSURE_CALC.md](docs/EXPOSURE_CALC.md)).
- Meridian flip estimator: mount profiles gain flip-required/tracking-allowance/duration fields;
  Plan My Night's timeline, optimizer preview and PDF export show a coloured flip indicator.
- Flip-aware schedule optimizer: when several targets become observable close together, the one
  whose meridian flip comes soonest is scheduled first.
- Lunar phase calendar: a full month calendar under "Moon next days" with a phase icon per day
  and near-new-moon nights shaded (`GET /api/moon/phase-calendar`).
- Plan My Night cleanup: removed the moon-calendar strip and seeing-forecast week (now covered
  by the Moon and Seeing Forecast tabs) and the now-unused `GET /api/moon/month-calendar`
  endpoint.

### Fixes

- Celestrak reliability: the ISS/CSS TLE is now downloaded once per cycle instead of once per
  location in multi-location setups, logging is more detailed when Celestrak is struggling, and
  the ISS/CSS fallback now actually falls back to mirror TLE sources.
- Mobile modals: the Back button / swipe-back now closes the open popup instead of switching
  tabs; fixed popups getting stuck open, frozen page scrolling, or a stray blur layer left
  behind; close buttons stay reachable on small screens; the equipment-set picker is now a
  proper trapped-focus dialog.
- Unified night score: the navbar widget, location switcher, Weather tab and "Score de la Nuit"
  cards now all show the same jet-stream-aware score (previously the switcher and Weather tab
  used a simpler score that could disagree by several points); fixed a 0-1 vs 0-100 scale bug in
  the transparency component that suppressed its contribution to the score.

### Breaking changes

- None.

## 1.3.2 (2026-08-29)

### Features

- UI: premium polish pass across cards, tabs, badges and modal/card composition.
- Maps: replaced CARTO tiles with no-key providers, with a persistent light/dark basemap switch
  on key maps.

### Fixes

- SkyTonight recommendation-panel thumbnail cards render as proper card image tops again.
- Mobile navbar: faster collapse/dropdown close by reducing/disabling costly animations.

### Breaking changes

- None.

## 1.3.1 (2026-08-29)

### Features

- Docker image now runs Python 3.14 (up from 3.13); the build no longer needs a C/Rust compiler
  toolchain, since every dependency ships a prebuilt wheel for it.

### Fixes

- Eclipse forecasts no longer show a finished eclipse as "next" for up to a day afterwards (the
  cache now expires when the eclipse ends), and an eclipse in progress no longer disappears at
  its midpoint.
- Solar/lunar eclipse dates now show a year whenever the eclipse isn't in the current year,
  instead of an ambiguous day/month-only date.
- Eclipse push notifications (N4/N5, "eclipse peak in X minutes") now actually fire - they were
  reading a cache key that no longer existed and silently skipped every cycle.

### Breaking changes

- None.

## 1.3.0 (2026-08-04)

### Features

- Observation Log: new sub-tab (Astrodex, next to Plan My Night) - a private, per-night record
  of what you actually captured. A session holds the date, real start/end times, location,
  equipment combination and sky conditions; each entry records frame count, sub-exposure,
  integration minutes, a 0-5 rating and notes, with the shared altitude-vs-time chart. An entry
  with a frame count auto-registers its target in Astrodex; attaching the photo stays a manual
  step. Plan My Night gains a "Log this session" button. Sessions are private and included in
  the admin backup ZIP. See [docs/OBSERVATION_LOG.md](docs/OBSERVATION_LOG.md).
- Observation Log, since shipping: night start/end carried over from imported plans, a
  redesigned "Add target" search, auto-filling frame count/sub-exposure/integration fields,
  photo thumbnails on entries, average rating as the 4th header stat, PDF export (single session
  or the whole log), a "Logged on <date>" backlink from Astrodex, multi-night sessions with
  per-night conditions, and generic session attachments (guiding graphs, subframe logs...).
- Astrodex: picture exposure fields (Frames / Exposure time / Integration) are now structured
  and auto-fill each other; new "Milky Way", "Nightscape / Wide-field" and "Star Trail" types.

### Fixes

- Admin-created or reset passwords now enforce the same 6-character minimum as self-service
  password changes.
- Input validation audit: SkyTonight observability constraints, equipment profile numeric
  fields, the AllSky connector's date parameter, and notification lead-time/Kp-threshold
  preferences are now range/format-checked server-side (some previously accepted values the UI
  would never send).
- Equipment combinations can no longer be deleted while referenced by an Observation Log
  session.
- Comet peak calculation switched from perihelion peak to brightness peak; notable comet events
  now flag (instead of silently disappearing) when a target never clears the site's
  altitude/airmass constraint.

### Breaking changes

- None.

## 1.2.1 (2026-07-30)

### Features

- External aliases support for SIMBAD-resolved stars in Astrodex.

### Fixes

- Moon glow animation dimensions.

### Breaking changes

- None.

## 1.2.0 (2026-07-22)

### Features

- Multi-location profiles: admins create up to 5 location presets (coordinates, timezone,
  Bortle/SQM, custom horizon profile) and attribute them to users; each user picks a default and
  switches the active location instantly from the sky status widget - forecasts, SkyTonight,
  ISS/CSS passes, events and notifications all follow, with per-location warm caches. See
  [docs/LOCATIONS.md](docs/LOCATIONS.md) and [docs/CACHE_SYSTEM.md](docs/CACHE_SYSTEM.md).
- Equipment combinations replace "telescope-only" as the core planning unit: SkyTonight and Plan
  My Night now compute against the full combination (telescope, camera, mount, guide...), and a
  combination can be linked to a photo. Combination-aware SkyTonight recommendations
  (`/api/skytonight/combination-recommendations`, renamed from `telescope-recommendations`)
  score camera-only rigs too.
- Astrodex: photos link to location, combination and your own rating; a new World Photo Map
  shows your capture spots (manual GPS override supported), and a new Catalogue Collection
  sub-tab shows a full catalogue (Messier, Caldwell, Herschel 400, Sharpless, NGC, Solar System)
  as a wall of cards - captured objects in colour, the rest behind a DSS2 preview - with
  search/filter/sort and a difficulty badge computed for every object.
- Plan My Night: new plan optimizer service; plans are now keyed by equipment combination
  instead of telescope alone.
- Notification for meteor showers; precipitation now factors into AstroScore.
- Backend folder fully reorganized into per-domain packages.

### Fixes

- The "notable comets" list is now derived live from the SkyTonight/MPC dataset instead of a
  hardcoded, year-stamped list that silently went empty after its year passed.
- Zodiacal light windows work again (the visibility check compared the Sun's own below-horizon
  altitude, a condition that could never pass).
- Sunrise/sunset now use the standard -0.833 degree horizon with sub-minute interpolation
  (previously a few minutes off); civil/nautical/astronomical twilight were unaffected.
- Equinox/solstice instants corrected (were off by about 9 hours from using the J2000 equator
  instead of the equinox of date).
- Meteor shower, conjunction/appulse and general event timing accuracy improved (correct night
  window, finer sampling, consistent ordering across daylight-saving changes).
- Silenced two spurious warning floods (a zodiacal-light frame mismatch, ERFA/IERS eclipse-
  lookup warnings) without changing any computed values.
- Sidereal time is now nutation-aware; the "circumpolar" flag is actually computed instead of
  always false.
- Caching/concurrency hardening: atomic cache writes, locked metrics reads, per-timezone "today"
  validity, shared ephemeris reuse, serialized TLE/aurora fetches, safe spaceflight image
  pruning.
- ISS/CSS solar/lunar transit detection vectorised (about 30x faster).

### Breaking changes

- None.

## 1.1.1 (2026-07-03)

### Features

- None.

### Fixes

- Stop `.gitignore` from excluding the vendored Leaflet dist assets.

### Breaking changes

- None.

## 1.1.0 (2026-07-03)

### Features

- Beginner experience: guided setup wizard, difficulty ratings, personalized "Tonight for you"
  recommendations, and a curated Beginner Catalog for newcomers. See
  [docs/BEGINNER_EXPERIENCE.md](docs/BEGINNER_EXPERIENCE.md).
- "Start from a preset" picker in the Equipment tab's New Telescope/Camera/Mount/Filter/
  Accessory forms, sharing the wizard's preset catalog. See
  [docs/EQUIPMENT.md#presets](docs/EQUIPMENT.md#presets).
- Moon conjunction events added to astronomical events.
- Sky status widget showing the current situation at the active location (groundwork for the
  multi-location selector).

### Fixes

- None.

### Breaking changes

- None.

## 1.0.1 (2026-06-24)

### Features

- CSS (China Space Station) pass tracking alongside ISS.
- Civil, nautical and astronomical twilight lines and badges on the horizon graph.
- RASA, APO Refractor and EdgeHD telescope types; removed the aperture limit and allowed 2
  decimal places on reducer/barlow and camera sensor dimensions.
- Server-side numeric validation for telescope and camera equipment.

### Fixes

- Log display on mobile view.
- Notification showing NaN minutes when there is no astronomical night.

### Breaking changes

- None.

## 1.0.0 (2026-06-14)

### Features

- Connectors & Observatory: new Observatory tab shows live data from enabled connectors (hidden
  until at least one is active); AllSky connector integrates an
  [AllSky](https://github.com/AllskyTeam/allsky) all-sky camera (v2024.12+) - live image with
  30s auto-refresh, sensor data, keogram/startrails/timelapse, all proxied through the backend
  so it works behind HTTPS reverse proxies. Extensible `BaseConnector` framework for future
  integrations.
- Development now follows a standard release cycle based on the Roadmap.

### Fixes

- Aurora notifications: better localization and a cooldown period.
- Forecast night with a quick-glance score; improved AstroScore hero cards and weather/moon/
  aurora cards.

### Breaking changes

- None.

## 0.9.0 (2026-06-04)

### Features

- Credits and acknowledgements section on About.

### Fixes

- Notification language now follows the user's saved preference instead of browser storage.
- Date calculation fixed for the UTC timezone default introduced with the previous release.
- Improved offline detection and retry.

### Breaking changes

- Project migrated to the `myastroboard/myastroboard` GitHub organization; old `WorldOfGZ`
  packages were removed, and only v0.9+ images are published under the new organization.

## 0.8.4 (2026-06-03)

### Features

- First-run setup modal for zero-config installs.
- Parameters -> Advanced: new Notifications (VAPID contact email) and Reverse proxy (trust
  headers / HTTPS-only cookies) sections, with a one-click restart when proxy settings change.
- Notifications are now translated into the user's language.

### Fixes

- None.

### Breaking changes

- ENV variables removed: `docker compose up` now works with zero manual configuration.
  `SECRET_KEY` is auto-generated and stored in `data/secret_key.txt` (reconnect required after
  the first build). `VAPID_CONTACT_EMAIL`, `TRUST_PROXY_HEADERS` and `SESSION_COOKIE_SECURE`
  moved to the admin UI (Parameters -> Advanced). `TZ` default changed from `Europe/Paris` to
  `UTC`.

## 0.8.3 (2026-06-02)

### Features

- None.

### Fixes

- Improved error handling in the push notification test endpoint.
- File-based locking for the push scheduler so only one worker runs it across multiple server
  processes.

### Breaking changes

- None.

## 0.8.2 (2026-06-01)

### Features

- None.

### Fixes

- More logging in the notification service; encoding fix for Google notifications; added log
  search to help find specific errors.

### Breaking changes

- None.

## 0.8.1 (2026-05-31)

### Features

- New telescope selector UI in Plan My Night.

### Fixes

- Normalized CSV export for compatibility with other software.

### Breaking changes

- Push notifications now require a valid contact email (`VAPID_CONTACT_EMAIL`) on some systems,
  or notifications are silently dropped. See [docs/1.INSTALLATION.md](docs/1.INSTALLATION.md).

## 0.8.0 (2026-05-30)

### Features

- Shared equipment: any gear can be shared instance-wide with a toggle; shared items show
  "Shared" / "Shared by [name]" badges and feed into combinations, the Field of View Calculator,
  Plan My Night's telescope picker, SkyTonight recommendations and Astrodex.
- SkyTonight: Bortle/SQM light-pollution integration weights AstroScore by sky darkness; solar
  elongation in reports; the alt/time graph accounts for nautical and astronomical night; a new
  "DSO not found?" sub-tab explains why a target was filtered out; filter by catalogue; new
  catalogues (Abell PNe, Abell Clusters, Arp, Barnard, GaryImm, Sharpless, vdB).
- Plan My Night: an altitude-time summary graph replaces the progress bars; a richer PDF export.
- Notifications: 7 configurable event triggers (session start, next target, ISS/CSS transit,
  lunar/solar eclipse, astronomical darkness, aurora Kp threshold), in-app and background Web
  Push modes, smart polling, and per-user settings with a test button.
- Moon calendar in Plan My Night; multi-catalogue search in Astrodex.

### Fixes

- Date calculation issue when there is no dark night.

### Breaking changes

- None.

## 0.1.0 to 0.7.9 - Early development (2026-02-04 to 2026-05-24)

This project's changelog only starts tracking notable changes release by release from 0.8.0
onward. The releases before that were not documented individually; the highlights below cover
the period as a whole. The full commit history and the original GitHub Release notes for every
tag remain available under
[github.com/myastroboard/myastroboard/releases](https://github.com/myastroboard/myastroboard/releases).

- First public releases: Dockerized deployment, built-in configuration UI, initial astronomy
  calculations.
- SkyTonight introduced (0.6.0), replacing the earlier Docker-in-Docker UpTonight integration -
  the start of the in-process observability engine the project is now built around.
- Internationalization (i18n) rolled out across the app (0.5.x).
- Multiple telescope management and calendar events (e.g. Milky Way visibility) added to
  SkyTonight (0.7.0).
- Early reliability fixes for running multiple server workers (cache correctness, 0.2.7).
