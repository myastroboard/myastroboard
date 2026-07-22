# Copilot Instructions for MyAstroBoard

This document provides comprehensive guidance for GitHub Copilot (or other AI assistants) when working on the MyAstroBoard project.

## Project Overview

MyAstroBoard is a web-based astronomy observation planning system with a fully built-in observability engine called **SkyTonight** that provides automated observation planning with a user-friendly dashboard - no external container dependency required.

### Core Concept
- Users configure their location via web dashboard
- **SkyTonight** internally computes all targets from international catalogues (OpenNGC, Messier, Caldwell, Herschel400, Pensack500, LBN, GaryImm, Arp, Sharpless, Barnard, vdB, comets, planets) using Astropy/Astroplan
- Scheduler runs at 1 hour after astronomical dawn local time + 1 hour before astronomical dusk (falls back to every 6 hours when clock is untrusted)
- Results (DSO, bodies, comets, sky map, altitude-time data) are cached as JSON and served through a REST API
- **Plan My Night** lets users build a private observation timeline from SkyTonight targets

## Architecture

### Technology Stack
- **Backend**: Python 3.13 + Flask
- **Frontend**: Vanilla HTML/CSS/JavaScript
- **Astronomy**: Astropy + Astroplan for calculations; Skyfield (`de421.bsp`) for planet/body ephemeris
- **Catalogues**: PyOngc (OpenNGC/OpenIC/Messier/Caldwell), Herschel 400 (static cross-ref), Pensack 500 (JSON cross-ref), LBN (JSON cross-ref), Minor Planet Center / JPL SBDB (comets), built-in solar system bodies
- **Visualization**: Chart.js (interactive, browser-side)
- **Containerization**: Docker + Docker Compose
- **Scheduler**: Custom Python threading-based scheduler (no Docker SDK dependency)
- **CI/CD**: GitHub Actions for image publishing

### Directory Structure
```
myastroboard/
├── backend/
│   ├── __pycache__/                 # Python bytecode cache
│   ├── app.py                       # Flask app factory: settings, extensions, blueprint registration, startup/scheduler init (no routes)
│   ├── utils/                       # Cross-cutting support modules (config, i18n, logging, auth, generic helpers)
│   │   ├── __init__.py                  # Common backend utility functions (includes slugify_location_name) - former utils.py
│   │   ├── route_helpers.py             # Shared cross-domain route helpers (_resolve_active_location, _active_location_cache)
│   │   ├── app_settings.py              # Persistent app settings (VAPID email, proxy headers)
│   │   ├── auth.py                      # Authentication and user management
│   │   ├── config_defaults.py           # Default config values
│   │   ├── constants.py                 # Shared constants (paths, URLs, timeouts)
│   │   ├── events_aggregator.py         # Unified upcoming events data
│   │   ├── i18n_utils.py                # Translation backend helpers
│   │   ├── logging_config.py            # Centralized logger setup
│   │   ├── metrics_collector.py         # Metrics collection service
│   │   ├── on_demand_translate.py       # On-demand DeepL/LibreTranslate integration
│   │   ├── push_manager.py              # VAPID key management, Web Push send wrapper
│   │   ├── push_scheduler.py            # Push notification scheduler (N1–N9 trigger evaluation)
│   │   ├── repo_config.py               # Config file load/save helpers
│   │   ├── txtconf_loader.py            # txtconf loader
│   │   └── version_checker.py           # GitHub release checks
│   ├── blueprints/                  # HTTP routes, one Flask Blueprint module per domain
│   │   ├── auth.py                  # /api/auth/*, /api/users/*
│   │   ├── push.py                  # /api/push/*
│   │   ├── locations.py             # /api/config, /api/locations/*
│   │   ├── connectors.py            # /api/connectors/* (AllSky)
│   │   ├── admin.py                 # /api/admin/*, /api/metrics, /api/backup/*, /api/logs/*, /api/config/export
│   │   ├── misc.py                  # /api/skyquality, /api/convert-coordinates, /api/timezones, /api/health, /api/cache, /api/version
│   │   ├── weather.py               # /api/weather/*, /api/moon/*, /api/aurora/predictions, /api/seeing-forecast
│   │   ├── tracking.py              # /api/object/*, /api/iss/*, /api/css/*, /api/spaceflight/*, /api/translate/on-demand
│   │   ├── astronomy.py             # /api/sky-widget, /api/sun/*, /api/events/*, /api/astro/*, /api/tonight/best-window
│   │   ├── plan_my_night.py         # /api/plan-my-night/*
│   │   ├── astrodex.py              # /api/astrodex/*, /api/beginner-catalog
│   │   ├── equipment.py             # /api/equipment/*
│   │   └── skytonight_api.py        # /api/skytonight/*, /api/catalogues (still skytonight_-prefixed; see backend/skytonight/ below)
│   ├── astroweather/                # Astronomical/atmospheric forecast services
│   │   ├── aurora_predictions.py        # Aurora forecast logic
│   │   ├── horizon_graph.py             # Horizon graph generation
│   │   ├── moon_astrotonight.py         # Best astrophotography window calculations
│   │   ├── moon_eclipse.py              # Lunar eclipse calculations
│   │   ├── moon_phases.py               # Moon phase calculations
│   │   ├── moon_planner.py              # Moon planner over date ranges
│   │   ├── seeing_forecast_7timer.py    # 7Timer ASTRO seeing and transparency forecast
│   │   ├── sun_eclipse.py               # Solar eclipse calculations
│   │   └── sun_phases.py                # Sun phase calculations
│   ├── weather/                     # Weather forecast clients and astrophotography weather analysis
│   │   ├── sky_quality.py               # Light pollution (Bortle/SQM) integration with AstroScore
│   │   ├── weather_astro.py             # Astro weather analysis
│   │   ├── weather_openmeteo.py         # Open-Meteo adapter
│   │   └── weather_utils.py             # Weather utility helpers
│   ├── observation/                 # Observation logbook, planning, and events business logic
│   │   ├── astrodex.py                  # Astrodex business logic and storage
│   │   ├── beginner_catalog.py          # Curated starter DSO list (loading, i18n, enrichment)
│   │   ├── catalogue_aliases.py         # Catalogue alias helpers (legacy, kept for astrodex cross-reference)
│   │   ├── object_info.py               # Single-object coordinate and catalogue lookup
│   │   ├── plan_my_night.py             # Plan My Night storage and business logic
│   │   ├── planetary_events.py          # Planetary events cache service
│   │   ├── sidereal_time.py             # Sidereal time service
│   │   ├── solar_system_events.py       # Solar system events (meteor showers are a curated annual set; comets are read from the live MPC-fed SkyTonight dataset - never hardcode dated comets)
│   │   └── special_phenomena.py         # Special phenomena cache service
│   ├── cache/                       # Shared JSON cache store and background scheduler/updater
│   │   ├── cache_scheduler.py           # Periodic cache scheduler
│   │   ├── cache_store.py               # Shared cache persistence
│   │   └── cache_updater.py             # Cache refresh orchestration
│   ├── space/                       # Spaceflight tracking
│   │   ├── css_passes.py                # CSS (China Space Station, NORAD 48274) passes – full parallel mirror of iss_passes.py
│   │   ├── iss_passes.py                # ISS passes, solar transit, and lunar transit integration
│   │   └── spaceflight_tracker.py       # Launch Library 2 client (launches, astronauts, events)
│   ├── equipment/                   # Equipment profiles business logic
│   │   └── equipment_profiles.py        # Equipment profiles API helpers
│   ├── skytonight/                  # SkyTonight calculation pipeline (routes live in blueprints/skytonight_api.py)
│   │   ├── skytonight_bodies.py         # SkyTonight: solar-system body target records
│   │   ├── skytonight_calculator.py     # SkyTonight: observability + AstroScore calculator
│   │   ├── skytonight_catalogue_builder.py # SkyTonight: dataset builder (PyOngc + comets + bodies)
│   │   ├── skytonight_comets.py         # SkyTonight: comet ingestion (MPC primary, JPL fallback)
│   │   ├── skytonight_models.py         # SkyTonight: data models (SkyTonightTarget, SkyTonightCoordinates)
│   │   ├── skytonight_scheduler.py      # SkyTonight: scheduler (smart time + 6h fallback)
│   │   ├── skytonight_scheduler_manager.py # SkyTonight: multi-worker scheduler coordination
│   │   ├── skytonight_storage.py        # SkyTonight: filesystem helpers for runtime state
│   │   └── skytonight_targets.py        # SkyTonight: dataset access, name resolution, lookup table
├── data/                            # Runtime persisted data (volume-mounted)
│   ├── astrodex/                    # Astrodex JSON + images
│   ├── cache/                       # Runtime cache payloads
│   ├── config.json                  # Main app config
│   ├── equipments/                  # Equipment profile JSON files
│   ├── myastroboard.log             # Application log file
│   ├── projects/                    # User project data
│   ├── skytonight/                  # SkyTonight runtime data (see below)
│   └── users.json                   # User accounts + preferences
├── docs/                            # Project documentation
│   ├── img/                         # Documentation images
│   ├── 1.INSTALLATION.md            # Installation guide
│   ├── 2.QUICKSTART.md              # Quick start guide
│   ├── 3.UPDATE.md                  # Update guide
│   ├── 4.RELEASE.md                 # Release process guide
│   ├── 5.ORGANIZATION.md            # Repository organization guide
│   ├── 6.REVERSE_PROXY.md           # Reverse proxy and HTTPS guide
│   ├── 7.TRANSLATIONS.md            # Translation contribution guide
│   ├── API_ENDPOINTS.md             # API endpoint inventory
│   ├── CACHE_SYSTEM.md              # Cache architecture documentation
│   ├── PLAN_MY_NIGHT.md             # Plan My Night documentation
│   ├── README.md                    # Documentation index
│   ├── SKYTONIGHT.md                # SkyTonight architecture + AstroScore documentation
│   └── VISUAL_TOUR.md               # Visual tour of the application
├── scripts/
│   ├── build_skytonight_catalogue.py # Offline dataset builder (generates data/skytonight/catalogues/targets.json)
│   ├── minify_static.py             # Static file minifier
│   ├── translate_checker.py         # Translation consistency checker
│   └── translate_i18n_values.py     # i18n value translation helper
├── static/
│   ├── css/                         # Stylesheets
│   ├── i18n/                        # Frontend translation dictionaries (en.json, fr.json)
│   ├── ico/                         # Platform-specific app icons
│   ├── img/                         # UI images and illustrations
│   ├── js/                          # Frontend JavaScript modules
│   │   ├── app.js                   # Main tab/subtab routing + startup
│   │   ├── astrodex.js              # Astrodex UI
│   │   ├── config.js                # Configuration UI
│   │   ├── domUtils.js              # Safe DOM helpers (DOMUtils)
│   │   ├── equipment.js             # Equipment profiles UI
│   │   ├── events_alerts.js         # Events & alerts UI
│   │   ├── horizon_graph.js         # Horizon chart
│   │   ├── i18n.js                  # Global i18n manager (loads early)
│   │   ├── language-selector.js     # Language dropdown handler
│   │   ├── lunar_eclipse.js         # Lunar eclipse chart
│   │   ├── metrics.js               # System metrics UI
│   │   ├── moon.js                  # Moon phase UI
│   │   ├── plan_my_night.js         # Plan My Night UI
│   │   ├── skytonight.js            # SkyTonight UI (tables, sky map, alttime popup)
│   │   ├── skytonightScheduler.js   # SkyTonight scheduler status UI
│   │   ├── solar_eclipse.js         # Solar eclipse chart
│   │   ├── weather.js               # Weather forecast charts
│   │   ├── weather_alerts.js        # Weather alert banners
│   │   └── weather_astro.js         # Astrophotography weather charts
│   ├── favicon.ico                  # Browser favicon (ICO)
│   ├── favicon.svg                  # Browser favicon (SVG)
│   ├── manifest.webmanifest         # PWA manifest
│   ├── offline.html                 # Offline fallback page
│   └── sw.js                        # Service worker
├── templates/
│   ├── index.html                   # Main dashboard page
│   └── login.html                   # Login page
├── tests/                            # Mirrors backend/'s package layout (backend/skytonight/foo.py -> tests/skytonight/test_foo.py)
│   ├── __pycache__/                 # Python bytecode cache for tests
│   ├── __init__.py                  # Tests package marker
│   ├── conftest.py                  # Shared pytest fixtures (applies to every subdirectory below)
│   ├── README.md                    # Testing notes
│   ├── blueprints/                  # Flask route/API-level tests (test_app_routes.py is the main route-coverage file)
│   ├── utils/                       # Tests for backend/utils/* (config, auth, i18n, logging, push, metrics, version checker...)
│   ├── cache/                       # Tests for backend/cache/* (cache_store, cache_scheduler, cache_updater)
│   ├── skytonight/                  # Tests for backend/skytonight/* (calculator, catalogue builder, scheduler, targets...)
│   ├── astroweather/                # Tests for backend/astroweather/* (moon/sun phases, eclipses, aurora, horizon graph...)
│   ├── weather/                     # Tests for backend/weather/* (sky_quality, weather_astro, weather_openmeteo...)
│   ├── observation/                 # Tests for backend/observation/* (astrodex, plan_my_night, events, object_info...)
│   ├── space/                       # Tests for backend/space/* (iss_passes, css_passes, spaceflight_tracker)
│   ├── equipment/                   # Tests for backend/equipment/* + exposure calculator
│   └── connectors/                  # Tests for backend/connectors/* (allsky_connector)
├── CODEOWNERS                       # Repository ownership rules
├── CODE_OF_CONDUCT.md               # Community code of conduct
├── CONTRIBUTING.md                  # Contribution guidelines
├── .github/
│   └── instructions/
│       └── copilot.instructions.md  # AI assistant working guidelines
├── docker-compose-dev.yml           # Development deployment
├── docker-compose.debug.yml         # Debug compose overlay
├── docker-compose.yml               # Production deployment
├── Dockerfile                       # Container build definition
├── entrypoint.sh                    # Container startup script
├── feature.md                       # Feature planning notes (not tracked in git)
├── LICENSE                          # Project license
├── pytest.ini                       # Pytest configuration
├── README.md                        # Main project documentation
├── requirements-dev.txt             # Development Python dependencies
├── requirements.txt                 # Runtime Python dependencies
├── ROADMAP.md                       # Product roadmap
├── SECURITY.md                      # Security policy
└── VERSION                          # Application version
```

### SkyTonight data directory layout (`data/skytonight/`)
```
skytonight/
├── calculations/
│   ├── calculation_results.json     # Metadata-only "all done" signal (written last)
│   ├── dso_results.json             # DSO results sorted by AstroScore desc
│   ├── bodies_results.json          # Solar-system body results
│   ├── comets_results.json          # Comet results
│   └── skymap_data.json             # Sky map trajectory data (az/alt per target)
├── catalogues/
│   └── targets.json                 # Built dataset (OpenNGC + Messier + Caldwell + H400 + Pensack500 + LBN + GaryImm + Arp + Sharpless + Barnard + vdB + comets + bodies)
├── logs/
│   └── last_calculation.log         # Last run log lines (JSONL)
├── outputs/
│   └── <target_id>_alttime.json     # Altitude-vs-time series (15-min resolution, popup chart data)
└── runtime/
    ├── scheduler_status.json        # Scheduler state, progress, last duration
    ├── scheduler_trigger            # Manual trigger file
    └── scheduler.lock               # File lock (prevents multiple workers running simultaneously)
```

## Code Style & Conventions

### General Guidelines
- **LANGUAGE REQUIREMENT**: All code, comments, documentation, and user-facing text MUST be in English
- This includes: variable names, function names, class names, comments, docstrings, error messages, UI text, and documentation
- Exception: Only external library names or technical terms that are internationally recognized

### Python
- Follow PEP 8 style guidelines
- Use type hints where beneficial for clarity
- Docstrings for all public functions/classes
- Maximum line length: 120 characters
- Use f-strings for string formatting
- Prefer explicit over implicit

### Unified Logging System
- **MANDATORY**: Use centralized logging configuration from `utils/logging_config.py`
- **NEVER** use `print()` statements for logging in backend code
- **NEVER** import `logging` directly - always use the centralized system

#### Logging Usage Pattern
```python
from logging_config import get_logger

# Initialize logger for this module (typically at module level)
logger = get_logger(__name__)

# Use appropriate log levels
logger.debug("Detailed information for debugging")
logger.info("General information about program execution")
logger.warning("Warning about something unexpected but not critical")
logger.error("Error occurred but program can continue")
logger.critical("Critical error - program may not be able to continue")

# For exceptions, use:
try:
    # some code
except Exception as e:
    logger.error(f"Descriptive error message: {e}")
    # or
    logger.exception("Descriptive error message")  # Automatically includes stack trace
```

#### Log Levels and Configuration
- **Default File Level**: INFO (set via LOG_LEVEL environment variable)
- **Default Console Level**: WARNING (set via CONSOLE_LOG_LEVEL environment variable)
- **Available Levels**: DEBUG, INFO, WARNING, ERROR, CRITICAL
- **Log File**: `/app/data/myastroboard.log` (with rotation)
- **Environment Control**:
  ```bash
  LOG_LEVEL=DEBUG          # Controls file output level
  CONSOLE_LOG_LEVEL=INFO   # Controls console output level
  ```

#### Logging Features
- **Automatic Rotation**: 10MB files, keeps 5 backups
- **Enhanced Format**: Includes module name, function name, and line number
- **UTF-8 Encoding**: Proper handling of special characters
- **Duplicate Prevention**: Logger registry prevents multiple handlers
- **Performance**: Different levels for console vs file output

#### Logging Guidelines
- Use **DEBUG** for detailed tracing and variable dumps
- Use **INFO** for normal program flow and important events
- Use **WARNING** for unexpected conditions that don't stop execution
- Use **ERROR** for exceptions and error conditions
- Use **CRITICAL** for severe errors that may stop the program
- Include relevant context in log messages (user input, file paths, etc.)
- Use f-strings for efficient string formatting in log messages

### JavaScript
- Use modern ES6+ syntax
- Async/await for asynchronous operations
- Clear, descriptive variable names
- Comment complex logic

#### Frontend XSS Security Rules (MANDATORY)
- **NEVER** use `innerHTML` in `static/js/**` (writes or reads for rendering).
- **NEVER** introduce new `DOMUtils.setTrustedHTML(...)` callsites.
- Build UI with explicit DOM APIs: `document.createElement`, `textContent`, `appendChild`, `setAttribute`.
- For text and API/user content, always use `textContent` (never HTML string interpolation).
- Before re-rendering containers, use `DOMUtils.clear(container)`.
- Preserve existing IDs/classes/data-attributes required by listeners and Bootstrap behavior.
- If a legacy HTML template must be kept temporarily, isolate it and prioritize migration to node-based rendering.

#### Existing Security Baseline (Do Not Regress)
- `innerHTML` has been removed from `static/js/**`.
- Major modules (`auth`, `app`, `astrodex`, `weather`, `weather_astro`, `equipment`, `moon`, `sun`, `iss`, `horizon_graph`, `aurora`, `solar_eclipse`, `lunar_eclipse`, `skytonight`, `skytonightScheduler`, `plan_my_night`) now follow node-based DOM updates.
- Any change reintroducing HTML sinks should be treated as a regression and rewritten.

### File Organization
- One class per file when possible
- Keep related functionality together
- Separate concerns (data loading, business logic, presentation)

## Key Design Patterns

### 1. Configuration Management
- **Pattern**: JSON file-based configuration with environment variable overrides
- **Location**: `data/config.json`
- **Structure**: Hierarchical with sections:
  - `locations`: List of admin-managed location presets (v1.2 multi-location profiles) - each with uuid4 `id`, name, latitude, longitude, elevation, timezone, bortle, sqm, per-preset `horizon_profile`, `is_install_default` flag. The legacy singular `location` key is auto-migrated on first load (see `docs/LOCATIONS.md`).
  - `constraints`: Altitude (min/max), airmass, size (min/max), moon separation, observability threshold, azimuth convention (under `skytonight.constraints`; `horizon_profile` moved to location presets in v1.2)
  - `skytonight`: Enabled flag, constraints_always_enabled, preferred_name_order, scheduler state, dataset sources
  - `astrodex`: Private flag
- **Default values**: Managed by `backend/utils/config_defaults.py` (`DEFAULT_CONFIG`, `DEFAULT_CONSTRAINTS`, `DEFAULT_SKYTONIGHT`)
- **Persistence**: Stored in Docker volume, survives container rebuilds
- **Why**: Simple, human-readable, easy to backup/restore, flexible
- **CRITICAL RULE (v1.2)**: Backend code MUST NEVER read `config["location"]` directly. Resolve the request's location with `repo_config.get_active_location(config, get_current_user())` (per-user active location), or `repo_config.get_install_default_location(config)` for install-wide jobs (SkyTonight calculation, scheduler anchors). The cache scheduler iterates `repo_config.get_scheduler_locations(config)`. Cap: `constants.MAX_LOCATIONS = 5` (hard-coded, never admin-configurable - rationale in `docs/LOCATIONS.md`).

### 1.1. User Management
- **Pattern**: JSON file-based user storage with hashed passwords
- **Location**: `data/users.json`
- **Structure**: Dictionary of users with:
  - `username`: Unique username
  - `password_hash`: Bcrypt hashed password (never stored in plaintext)
  - `role`: One of `admin`, `user`, `read-only`
  - `created_at`: ISO timestamp of user creation
  - `last_login`: ISO timestamp of last successful login
  - `preferences`: Per-user UI customization settings
- **Default User**: `admin:admin` created automatically on first run
- **Persistence**: Stored in Docker volume (`./data:/app/data`), survives container restarts/rebuilds
- **Security**: Passwords are hashed using Werkzeug's `generate_password_hash` (bcrypt)
- **Session Management**: Flask session-based authentication with secure cookies
- **Why**: Persistent user accounts, secure password storage, survives Docker restarts

### 1.2. User Customization Preferences
- **Pattern**: Per-user preference object persisted in `data/users.json`
- **Scope**: Preferences are always user-scoped; never shared globally across users
- **Current Keys**:
  - `startup_main_tab`: default main tab at login
  - `startup_subtab`: default sub-tab at login
  - `time_format`: `auto` | `12h` | `24h`
  - `density`: `comfortable` | `compact`
  - `theme_mode`: `auto` | `light` | `dark` | `red`
- **Backend Rules**:
  - Validate allowed keys and values before saving
  - Merge with defaults for missing keys
  - Persist via atomic + validated users save path (tmp + validate + replace + backup/restore)
- **Frontend Rules**:
  - Load preferences after authentication, then apply immediately
  - Use preferences as startup navigation source
  - Keep `customize-subtab` strictly user-level (no admin/global settings here)
  - On language change, re-render dynamic preference labels/options
- **Why**: Personalized UX without compromising role boundaries or data integrity

### 2. SkyTonight Target Dataset
- **Source catalogues**: OpenNGC + OpenIC (via PyOngc), Messier (subset of OpenNGC), Caldwell (cross-referenced from PyOngc), Herschel 400 (static cross-ref), Pensack 500 (JSON cross-ref from `backend/catalogues/pensack500.json`), LBN (JSON cross-ref from `backend/catalogues/lbn.json`), GaryImm (JSON cross-ref `garyimm_crossrefs.json` + standalone `garyimm_standalone.json`), Arp (JSON cross-ref from `backend/catalogues/arp.json`), Sharpless/Barnard/vdB (full standalone catalogues from `backend/catalogues/`), Abell PNe (`abell_pne.json`, 71 objects from SIMBAD), Abell Clusters (`abell_clusters.json`, 2712 clusters from VizieR VII/110A ACO 1989), comets (MPC primary + JPL enrichment), solar-system bodies (Skyfield `de421.bsp`)
- **Dataset file**: `data/skytonight/catalogues/targets.json` - generated offline by `scripts/build_skytonight_catalogue.py` or rebuilt on-demand via API
- **Model**: `SkyTonightTarget` dataclass (`skytonight_models.py`) - immutable, with `target_id`, `category`, `object_type`, `preferred_name`, `catalogue_names` (dict), `coordinates`, `magnitude`, `size_arcmin`, `source_catalogues`
- **Preferred name order**: `CommonName → Messier → OpenNGC → OpenIC → Caldwell → LBN → Herschel400 → Pensack500 → GaryImm → Arp → Sharpless → Barnard → vdB` (defined in `constants.SKYTONIGHT_PREFERRED_NAME_ORDER`)
- **Cross-ref catalogues** (H400, Pensack500, LBN, GaryImm, Arp): injected as extra `catalogue_names` keys on existing NGC/IC records by `_build_cross_ref_map()` + `_apply_cross_refs()` in `skytonight_catalogue_builder.py`. These never change the preferred display name (OpenNGC/Messier/Caldwell always take priority) but they do populate `source_catalogues` and appear in the catalogue filter dropdown in the DSO report.
- **Standalone catalogues** (GaryImm non-NGC/IC objects, Sharpless, Barnard, vdB): new records created by `_build_standalone_targets_from_json()` with coordinates from the JSON files. Objects in multiple catalogues use the `extra_catalogues` JSON field. NGC/IC key matching uses `_ngc_ic_match_key()` with zero-padding to 4 digits (e.g. "NGC 891" → key "ngc0891") to match PyOngc's internal format.
- **No duplicates**: Objects identifiable across catalogues are merged into one record with all `catalogue_names` entries
- **Stable IDs**: `target_id` is derived deterministically from catalogue identifiers (never changes between regenerations)
- **Why**: Stable, offline-capable, no per-request recalculation, extensible for more catalogues

### 3. SkyTonight Scheduler
- **Pattern**: Threading-based in-process scheduler
- **Smart schedule**: 06:00 local time + 1 hour before astronomical dusk + first startup (requires valid system clock)
- **Fallback**: Every 6 hours when `year < 2024` or timezone is untrusted
- **Multi-worker safety**: File lock at `data/skytonight/runtime/scheduler.lock` (one worker runs at a time)
- **Manual trigger**: Admin can write trigger file via `POST /api/skytonight/scheduler/trigger`
- **Constant**: `SKYTONIGHT_FALLBACK_INTERVAL_SECONDS = 21600` in `backend/skytonight/skytonight_scheduler.py`
- **Why**: No external dependencies, survives across container restarts, clock-aware

### 4. AstroScore
- **Purpose**: Dimensionless [0, 1] ranking of astrophotography suitability for the configured location
- **Calculation**: Weighted sum of 4 sub-scores - visibility (0.40), sky quality (0.25), object brightness (0.25), comfort (0.10)
- **Bonuses**: +0.20 for planet at opposition, +0.05 for Messier objects; final value clamped to [0.0, 1.0]
- **Full documentation**: `docs/SKYTONIGHT.md`
- **Implementation**: `backend/skytonight/skytonight_calculator.py`

### 5. API Design
- **Pattern**: RESTful JSON API with role-based access control
- **Endpoint Coverage**:
    - Routes are defined as Flask Blueprints in `backend/blueprints/*.py` (registered in `backend/app.py`), one module per domain: `auth.py` (auth+users), `push.py`, `locations.py` (config+locations), `connectors.py`, `admin.py` (app-settings/restart/metrics/backup/logs), `misc.py` (skyquality/convert-coordinates/timezones/health/cache/version), `weather.py` (weather+moon+aurora+seeing), `tracking.py` (object/iss/css/spaceflight/translate), `astronomy.py` (sky-widget/sun/events/astro/tonight), `plan_my_night.py`, `astrodex.py` (astrodex+beginner-catalog), `equipment.py`, `skytonight_api.py` (SkyTonight routes; the SkyTonight *calculation pipeline* it calls into still lives in `backend/skytonight/`). `app.py` itself only holds the Flask app factory, extension setup, static/PWA routes, and startup/scheduler init. Cross-domain route helpers (`_resolve_active_location`, `_active_location_cache`) live in `backend/utils/route_helpers.py`.
  - The current endpoint inventory is maintained in `docs/API_ENDPOINTS.md` and should be updated whenever a route is added, removed, or renamed.
  - Key security constraints:
    - Most `/api/*` routes require login (`@login_required`).
    - Admin-only routes use `@admin_required` (users CRUD, config write/export, logs clear, metrics, scheduler trigger).
    - User update/delete route is `/api/users/<user_id>` (not `<username>`).
    - Self-service endpoints include `/api/auth/change-password` and `/api/auth/preferences`.
- **SkyTonight endpoints** (all `@login_required`):
    - Legacy aliases also exist for scheduler compatibility: `GET /api/scheduler/status` and `POST /api/scheduler/trigger`.
  - `GET /api/skytonight/scheduler/status`
  - `POST /api/skytonight/scheduler/trigger` (`@admin_required`)
  - `GET /api/skytonight/dataset/status`
  - `POST /api/skytonight/dataset/rebuild` (`@admin_required`)
    - `POST /api/skytonight/combination-recommendations`
  - `GET /api/skytonight/data/dso`
  - `GET /api/skytonight/data/bodies`
  - `GET /api/skytonight/data/comets`
  - `GET /api/skytonight/alttime/<id>`
  - `GET /api/skytonight/skymap`
  - `GET /api/skytonight/log`
- **Other key feature endpoints** (`@login_required` unless noted):
    - Push notifications: `GET /api/push/vapid-public-key`, `GET /api/push/vapid-config-status`, `POST /api/push/subscribe`, `GET/DELETE /api/push/subscriptions`, `DELETE /api/push/unsubscribe`, `POST /api/push/test`, `POST /api/push/test/<trigger_id>`
    - Admin operations (`@admin_required`): `GET/POST /api/admin/app-settings`, `POST /api/admin/restart`
    - Seeing forecast: `GET /api/seeing-forecast`
    - ISS tracking: `GET /api/iss/passes` (returns passes, solar transits **and lunar transits**, all times in configured local TZ), `GET /api/iss/location`, `POST /api/iss/celestrak/restart` (`@admin_required`)
    - CSS tracking: `GET /api/css/passes` (same structure as ISS, includes `station: "CSS"`), `GET /api/css/location`, `POST /api/css/celestrak/restart` (`@admin_required`)
    - Moon details: `GET /api/moon/month-calendar`
    - On-demand translation: `POST /api/translate/on-demand`
    - Spaceflight: `GET /api/spaceflight/launches`, `GET /api/spaceflight/astronauts`, `GET /api/spaceflight/events`, `GET /api/spaceflight/img/<filename>`, `GET /api/spaceflight/launch/<launch_id>/vidurls`
    - Object lookup: `GET /api/object/<path:identifier>`
    - Astrodex helpers: `GET /api/astrodex/catalogue-lookup`
    - Plan My Night helpers: `GET /api/plan-my-night/list`, `PATCH /api/plan-my-night`, `DELETE /api/plan-my-night/clear-all`
    - SkyTonight debug helper: `GET /api/skytonight/target-debug`
    - Localized manifest route: `GET /manifest.<lang>.webmanifest` (public)
- **Error Handling**: Return appropriate HTTP status codes with JSON error objects
  - 401 Unauthorized - Not authenticated
  - 403 Forbidden - Insufficient permissions (not admin)
  - 400 Bad Request - Invalid input
  - 500 Internal Server Error - Server errors
- **Authentication Flow**:
  - Session-based authentication using Flask sessions
  - Credentials stored in `/app/data/users.json` with hashed passwords
  - Default admin user created on first run (username: admin, password: admin)
  - Password change warning shown when using default password
- **Why**: Clear separation, security through authentication, role-based access control

### 6. Modern UI/UX
- **Pattern**: Tab-based interface (main tabs + sub-tabs)
- **Main tabs**: Dashboard, SkyTonight, Plan My Night, Astrodex, Equipment, Weather, Configuration, Parameters
- **SkyTonight sub-tabs**:
  - **Plot**: Interactive sky map (azimuth/altitude polar projection, target trajectories, click-to-inspect)
  - **Deep Sky Objects**: Filterable/sortable table with AstroScore, magnitude, altitude, FOV score, add to Astrodex / Plan My Night
  - **Bodies**: Solar-system bodies table
  - **Comets**: Comets table
  - **Logs**: Last calculation log viewer
  - **Reports**: Formatted target reports
- **Altitude-vs-time popup**: Opens per-target modal with Chart.js line chart (astronomical night window, observable zone band); data fetched from `/api/skytonight/alttime/<id>`; chart destroyed on modal close
- **Styling**: Modern gradient design, smooth animations, accessibility-compliant
- **Why**: Professional appearance, better UX, easier navigation

## Important Implementation Details

### SkyTonight Calculation Flow
```
Scheduler trigger (startup / smart schedule / manual)
  ├─ ensure_skytonight_directories()
  ├─ run_calculations() ← skytonight/skytonight_calculator.py
  │     ├─ load_targets_dataset()  → DSOs (targets.json)
  │     ├─ load_comets_dataset()   → MPC comets
  │     ├─ build_body_targets()    → planets / Moon
  │     ├─ For each target:
  │     │    ├─ Compute alt/az time series (15-min steps, Astropy AltAz)
  │     │    ├─ Check observability constraints (altitude, airmass, size, moon sep, fraction)
  │     │    ├─ Compute AstroScore (4 sub-scores + bonuses)
  │     │    └─ Write <target_id>_alttime.json if target passes constraints
  │     ├─ Write dso_results.json, bodies_results.json, comets_results.json
  │     ├─ Write skymap_data.json
  │     └─ Write calculation_results.json (signals completion)
  └─ API reads from JSON files (never re-runs heavy calculation per request)
```

### Scheduler Behavior
```python
# Runs immediately on first startup
# Smart mode (valid clock): 1 h after astronomical dawn + 1 h before astronomical dusk
# Fallback mode (invalid/untrusted clock): every 6 h
# Constant: SKYTONIGHT_FALLBACK_INTERVAL_SECONDS = 21600
# Multi-worker safety: file lock at data/skytonight/runtime/scheduler.lock
```

### Location Name Sanitization
- `utils.slugify_location_name(name)` → URL-safe slug (e.g., `"Marnes la Coquette"` → `"marnes-la-coquette"`)
- Used for any per-location sub-directory inside `data/skytonight/`
- **Always use this function** when constructing location-specific paths; do not roll your own sanitizer

### Coordinate Format Conversion
- **Input / storage**: decimal degrees (float) in `SkyTonightCoordinates.ra_hours` / `dec_degrees`
- **API**: `/api/convert-coordinates` endpoint with DMS validation
- **Frontend**: Real-time conversion with error display
- **Why**: User-friendly input for astronomers familiar with DMS notation

### Chart.js Usage
- **Never** use `resizeDelay` option - it schedules a `requestAnimationFrame → setTimeout` chain that crashes if `chart.destroy()` is called before it resolves (e.g., on tab switch)
- Always call `chart.destroy()` before recreating a chart on the same canvas
- Use `cleanupTransientCharts()` in `app.js` which is already called on every tab / sub-tab switch

### Environment Configuration
Key environment variables (set in docker-compose.yml or .env):
- **DATA_DIR**: Configuration and data storage (default: `/app/data`)
- **SKYTONIGHT_DIR**: SkyTonight runtime data (default: `$DATA_DIR/skytonight`)
- **LOG_LEVEL**: File logging level - DEBUG, INFO, WARNING, ERROR, CRITICAL (default: INFO)
- **CONSOLE_LOG_LEVEL**: Console logging level - DEBUG, INFO, WARNING, ERROR, CRITICAL (default: WARNING)
- **TZ**: Container timezone
- **SECRET_KEY**: Flask session secret key (should be a random 64-character hex string)
- **TRUST_PROXY_HEADERS**: Set `true` when behind a reverse proxy with HTTPS termination
- **SESSION_COOKIE_SECURE**: Set `true` for HTTPS-only deployments

## Common Tasks

### Adding a New API Endpoint

1. Define the route in the matching domain module under `backend/blueprints/` (e.g. `backend/blueprints/misc.py` for a standalone utility endpoint) - do not add new routes to `backend/app.py` itself:
```python
@misc_bp.route('/api/new-endpoint', methods=['GET'])
@login_required
def new_endpoint():
    """Brief description"""
    try:
        # Implementation
        return jsonify({"status": "success", "data": result})
    except Exception as e:
        logger.error(f"Error in new endpoint: {e}")
        return jsonify({'error': 'Internal server error'}), 500
```

2. Add corresponding JavaScript in the relevant `static/js/*.js` file:
```javascript
async function callNewEndpoint() {
    const response = await fetchJSON(`${API_BASE}/api/new-endpoint`);
    // Handle data
}
```

3. Update API documentation in `docs/API_ENDPOINTS.md`

### Adding a New Configuration Parameter

1. Update default config in `backend/utils/config_defaults.py`:
```python
DEFAULT_CONFIG["section"]["new_parameter"] = default_value
```

2. Add form field in `templates/index.html`:
```html
<div class="form-group">
    <label data-i18n="section.new_parameter_label"></label>
    <input type="text" id="new-parameter">
</div>
```

3. Update save/load in the relevant JS config file using DOM APIs (no innerHTML):
```javascript
// In saveConfiguration()
new_parameter: document.getElementById('new-parameter').value
// In loadConfiguration()
document.getElementById('new-parameter').value = config.section.new_parameter
```

### Rebuilding the SkyTonight Dataset

The target dataset is pre-built by an offline script and stored in `data/skytonight/catalogues/targets.json`:
```bash
# From project root (with PyOngc and dependencies installed)
python scripts/build_skytonight_catalogue.py
```
Or trigger via API (admin only):
```
POST /api/skytonight/dataset/rebuild
```

### Triggering a SkyTonight Recalculation
```bash
# Via API (admin required)
curl -X POST http://localhost:5000/api/skytonight/scheduler/trigger
```
Or set `SKYTONIGHT_FALLBACK_INTERVAL_SECONDS` to a shorter value in `backend/skytonight/skytonight_scheduler.py` for testing.

### Updating the Application Version

1. Edit `VERSION` file: `1.0.0` → `1.1.0`
2. Commit and push to main branch
3. GitHub Actions will automatically build and publish new image
4. Users update with: `docker compose pull && docker compose up -d`

## Testing Guidelines

### Manual Testing Checklist
- [ ] Configuration save/load works
- [ ] SkyTonight scheduler triggers and completes
- [ ] DSO / bodies / comets results appear in the UI tables
- [ ] Sky map polar chart renders with target trajectories
- [ ] Altitude-vs-time popup opens and Chart.js renders without console errors
- [ ] Plan My Night adds, reorders, and clears targets correctly
- [ ] Weather API integration functions
- [ ] Version endpoint returns correct version
- [ ] Health endpoint responds

### Testing with Docker
```bash
# Build
docker compose build

# Start
docker compose up -d

# View logs
docker logs -f myastroboard

# Test API
curl http://localhost:5000/health
curl http://localhost:5000/api/version
curl http://localhost:5000/api/skytonight/scheduler/status

# Stop
docker compose down
```

### Testing Scheduler (Without Waiting)
Set `SKYTONIGHT_FALLBACK_INTERVAL_SECONDS` in `backend/skytonight/skytonight_scheduler.py` to a shorter value (e.g. 300 for 5 minutes), or use the manual trigger API endpoint.

## Code Validation Before Committing

Full details live in [CONTRIBUTING.md](../../CONTRIBUTING.md#before-submitting) - this is the quick-reference checklist an AI assistant must run (or tell the user to run) before treating a change as done.

### Required Commands
```bash
pytest                              # full test suite
black backend/                      # Python formatting (PEP 8, 120-char lines)
flake8 backend/                     # Python linting
pyright backend/                    # static type checking (reads pyrightconfig.json at repo root)
djlint templates/ static/offline.html --profile jinja --lint --ignore H021,H023,H030,H031,J004,J018
```
- `black` and `flake8` are declared in `requirements-dev.txt`; run them on every `backend/` change, not just new files.
- `pyright` mirrors the Pylance errors shown inline in VSCode - a clean `pyright backend/` run means Pylance should be clean too. If VSCode still shows stale errors after a config edit, run "Python: Restart Language Server".
- `djlint` lints `templates/` (Jinja2) and `static/offline.html`; the ignored rule codes are explained in [CONTRIBUTING.md](../../CONTRIBUTING.md#ignored-rules-and-why) - do not silently add more ignores without documenting why there.
- JavaScript has no standalone lint step: formatting is applied on save by VSCode's built-in formatter (`.vscode/settings.json` + `.editorconfig`). Just make sure the file was opened/saved in VSCode, or match the existing 4-space/single-quote style by hand.

### Route Inventory Check
If a change touches `app.py` or any `backend/blueprints/*.py` file (route added, removed, renamed, or its HTTP method changed):
```bash
pytest tests/blueprints/test_route_inventory.py
```
Update `EXPECTED_ROUTES` in that file to match, and document the change in `CHANGELOG_NEXT.md`. The failure output lists exactly which routes are unexpected or missing.

### Minimum Bar Before Calling a Change Done
- [ ] `pytest` passes
- [ ] `black backend/` produces no diff
- [ ] `flake8 backend/` reports no issues
- [ ] `pyright backend/` reports no errors
- [ ] `djlint` passes for any touched template
- [ ] `pytest tests/blueprints/test_route_inventory.py` passes if routes changed
- [ ] All code/comments/UI text in English (see Language Requirement above)
- [ ] No `print()` or direct `logging` import in backend code (use `logging_config.get_logger`)
- [ ] No `innerHTML` / new `DOMUtils.setTrustedHTML` in `static/js/**`

## Security Considerations

### No Docker Socket Access
- SkyTonight performs all calculations in-process (Python/Astropy) - no Docker-in-Docker, no privileged mode required
- `docker-compose.yml` runs with `privileged: false`

### Input Validation
- Always validate user input before:
  - Saving to config
  - Using in file paths (use `slugify_location_name` for location-derived paths)
  - Returning in API responses

### Dependency Security
- Keep dependencies updated
- Run security scans via GitHub Actions
- Pin versions in requirements.txt

## Performance Considerations

### Scheduler Efficiency
- One thread, sequential execution; file lock prevents multi-worker duplication
- Acceptable for personal use (thousands of targets processed in a single pass)
- For large deployments, consider async or queue-based approach

### Memory Usage
- SkyTonight calculations are done in-process (Astropy/NumPy); objects are released after each run
- Chart.js charts are created on-demand and destroyed on modal close or tab switch
- Astropy + Skyfield ephemeris loaded once and reused across calculations

## Debugging Tips

### Common Issues

**Scheduler not starting**
- Check logs: `docker logs myastroboard`
- Verify scheduler initialization in `app.py`
- Check `data/skytonight/runtime/scheduler_status.json` for last error

**SkyTonight results missing**
- Check `data/skytonight/logs/last_calculation.log` for calculation errors
- Verify `data/skytonight/catalogues/targets.json` exists (rebuild if missing)
- Check `data/skytonight/calculations/calculation_results.json` exists (signals all files complete)

**Altitude-time popup crashes with "Cannot read properties of null (reading 'addEventListener')"**
- This is caused by `resizeDelay` in Chart.js options - **never** add `resizeDelay` to any Chart.js config
- The delayed resize fires after `chart.destroy()` is called on tab switch, accessing a null canvas

**Targets not loading in UI**
- Check browser console for API errors
- Test `GET /api/skytonight/data/dso` directly
- Verify constraints are not filtering out all targets (e.g., `size_constraint_min` too large)

**Coordinate conversion errors**
- Check coordinates are stored as decimal degrees (not DMS) in config
- Validate using `GET /api/convert-coordinates`

### Enable Debug Logging
```bash
# In docker-compose.yml or .env file
LOG_LEVEL=DEBUG              # Enable debug logging to file
CONSOLE_LOG_LEVEL=DEBUG      # Enable debug logging to console
```

#### Dynamic Log Level Control
```python
from logging_config import set_global_log_level, get_current_log_level

current_level = get_current_log_level()
set_global_log_level('DEBUG')
```

### Useful Log Locations
- **Application Log**: `data/myastroboard.log` (mounted volume in `/app/data/`)
- **SkyTonight Calculation Log**: `data/skytonight/logs/last_calculation.log`
- **Docker Logs**: `docker logs myastroboard` (shows console output)
- **Container Logs**: `docker compose logs -f myastroboard`
- **Log Rotation**: Check `myastroboard.log.1`, `myastroboard.log.2`, etc. for older logs
- **Scheduler Events**: Look for module `skytonight_scheduler` in logs
- **Cache Updates**: Look for module `cache_updater` and `cache_scheduler` in logs
- **Weather API**: Look for module `weather_openmeteo` in logs

## UI/UX Graphing Standard

All interactive charts in the UI should follow a consistent, clean presentation format. Use the `horizon-graph.js` implementation as reference for the standard layout.

### Chart Component Structure

Every chart must be wrapped in a Bootstrap card container with the following structure:

```html
<div class="col mb-3"> <!-- Adjust col size based on grid requirement -->
    <div class="card h-100">
        <!-- Header with title -->
        <div class="card-header">
            <h5 class="mb-0">🔥 Chart Title</h5>
        </div>
        
        <!-- Chart container -->
        <div class="card-body">
            <canvas id="unique-chart-id" style="height: 350px;"></canvas>
        </div>
        
        <!-- Footer with legend and metadata -->
        <div class="card-footer text-muted small">
            <div class="row">
                <div class="col-auto">
                    <span class="badge" style="background-color: #COLOR1;">Legend Item 1</span>
                </div>
                <div class="col-auto">
                    <span class="badge" style="background-color: #COLOR2;">Legend Item 2</span>
                </div>
                <div class="col-auto">
                    <span class="text-muted">Additional metadata or unit information</span>
                </div>
            </div>
        </div>
    </div>
</div>
```

### Grid Sizes
- **Full width**: `col-12` (for wide charts like horizon-graph)
- **Two columns**: `col-6` (for standard side-by-side charts)
- **Three columns**: `col-4` (for compact displays)
- **Responsive**: Use Bootstrap responsive classes:
  - `row-cols-1 row-cols-sm-2 row-cols-lg-3 row-cols-xl-4`

### Chart Configuration Best Practices

When implementing charts with Chart.js:

1. **Always use card wrapper**: Don't render canvas directly without card styling
2. **Font sizing**: Use responsive units for labels/titles
3. **Colors**: Use consistent color scheme (reference existing charts)
4. **Legend**: Display in card footer as badges with color indicators
5. **Responsiveness**: Use device-aware options like `isCompactChart()` function
6. **Height**: Set canvas height in card-body or inline style (e.g., `max-height: 350px`)
7. **Destruction**: Always destroy previous chart instance before creating new one
8. **Tooltip formatting**: Round to 1 decimal place for readability

### Example Implementation Pattern

```javascript
/**
 * Render chart with standard card layout
 */
function renderMyChart(data) {
    const container = document.getElementById('my-chart-display');
    if (!container) return;

  // Create card structure with explicit DOM APIs (no innerHTML)
  DOMUtils.clear(container);
  const col = document.createElement('div');
  col.className = 'col-12 mb-3';

  const card = document.createElement('div');
  card.className = 'card h-100';

  const header = document.createElement('div');
  header.className = 'card-header';
  const title = document.createElement('h5');
  title.className = 'mb-0';
  title.textContent = '📊 My Chart Title';
  header.appendChild(title);

  const body = document.createElement('div');
  body.className = 'card-body';
  const canvas = document.createElement('canvas');
  canvas.id = 'myChartCanvas';
  canvas.style.height = '350px';
  body.appendChild(canvas);

  const footer = document.createElement('div');
  footer.className = 'card-footer text-muted small';
  const footerRow = document.createElement('div');
  footerRow.className = 'row';

  const badge1Col = document.createElement('div');
  badge1Col.className = 'col-auto';
  const badge1 = document.createElement('span');
  badge1.className = 'badge';
  badge1.style.backgroundColor = '#3b82f6';
  badge1.textContent = 'Series 1';
  badge1Col.appendChild(badge1);

  const badge2Col = document.createElement('div');
  badge2Col.className = 'col-auto';
  const badge2 = document.createElement('span');
  badge2.className = 'badge';
  badge2.style.backgroundColor = '#8b5cf6';
  badge2.textContent = 'Series 2';
  badge2Col.appendChild(badge2);

  footerRow.appendChild(badge1Col);
  footerRow.appendChild(badge2Col);
  footer.appendChild(footerRow);

  card.appendChild(header);
  card.appendChild(body);
  card.appendChild(footer);
  col.appendChild(card);
  container.appendChild(col);
    
    // Create Chart.js instance
    const ctx = document.getElementById('myChartCanvas');
    if (window.myChartInstance) {
        window.myChartInstance.destroy();
    }
    
    window.myChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: data.times,
            datasets: [
                {
                    label: 'Series 1',
                    data: data.series1,
                    borderColor: '#3b82f6',
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    // ... other options
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false
            // ... other options
        }
    });
}
```

### Files Requiring This Standard
- `weather_astro.js`: astro-seeing-chart, astro-clouds-chart, astro-conditions-chart
- `weather.js`: cloudConditionsChart, seeingConditionsChart
- `solar_eclipse.js`: solar-eclipse-altitude-chart
- `lunar_eclipse.js`: lunar-eclipse-altitude-chart
- `skytonight.js`: alttime-chart-canvas (altitude-vs-time popup chart)
- `horizon_graph.js`: horizonCanvas

## Internationalization (i18n) & Translations

### Overview
MyAstroBoard supports multiple languages through a structured i18n system. Currently supported languages: **English (en)**, **French (fr)**, **Spanish (es)**, **German (de)**, **Italian (it)**, **Portuguese (pt)**.

### Key Principles
- **All user-facing text must be translatable** - No hardcoded strings in UI
- **Keys use dot notation for organization** - `namespace.section.key` structure
- **Key naming respects file organization** - Keys grouped by component/file
- **Backend and Frontend coordination** - Consistent key naming across stack
- **Fallback to English** - Missing keys default to English
- **Browser language detection** - Automatically detects browser language preference
- **User preference persistence** - Stores language choice in localStorage
- **Translated API payloads required** - No hardcoded English messages in API responses when i18n keys exist
- **Parameterized keys must be resolved** - Always pass required placeholders (example: `{time}`) before returning payloads

### Directory Structure
```
static/i18n/
├── en.json          # English translations
├── fr.json          # French translations
└── [language].json  # Add new languages here

static/js/
└── i18n.js          # Global i18n manager (must load early)

backend/
└── utils/
    └── i18n_utils.py    # Backend translation utilities
```

### Frontend Usage

#### 1. HTML Elements with data-i18n attribute
```html
<!-- Static content translation -->
<h2 data-i18n="astro_weather.section_title">🌡️ Current Conditions</h2>
<p data-i18n="common.loading">Loading...</p>

<!-- Initialize i18n translations after page load -->
<script>
    window.addEventListener('load', () => {
        document.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.getAttribute('data-i18n');
            el.textContent = i18n.t(key);
        });
    });
</script>
```

#### 2. JavaScript Direct Translation Calls
```javascript
// Get translated string
const message = i18n.t('common.loading');

// Get translated string with parameters (placeholders)
const alertMsg = i18n.t('weather_alerts.critical_dew_risk', { time: '14:30' });

// Check if translation exists
if (i18n.has('my.key')) {
    console.log(i18n.t('my.key'));
}
```

#### 3. Language Switching

**Automatic (User-facing)**:
```html
<!-- Language selector dropdown in footer -->
<select id="language-select-footer" class="form-select form-select-sm">
    <option value="en">English</option>
    <option value="fr">Français</option>
</select>
```

The `LanguageSelector` class (in `static/js/language-selector.js`) automatically handles user interactions with this dropdown, switching the language and updating all UI elements.

**Programmatic (Developer)**:
```javascript
// Switch language programmatically
await i18n.setLanguage('fr');  // Switch to French

// Get current language
const currentLang = i18n.getCurrentLanguage();

// Get supported languages
const langs = i18n.getSupportedLanguages();  // Returns ['en', 'fr', 'es', 'de', 'it', 'pt']

// Listen for language changes (useful for components needing dynamic updates)
window.addEventListener('i18nLanguageChanged', (e) => {
    // Update UI elements here
    console.log(`Language changed to: ${e.detail.language}`);
});
```

**User Experience**:
- Footer contains language selector dropdown (next to theme selector)
- Users can click dropdown to switch between English and Français
- Language preference persists in browser localStorage
- All page content updates instantly to new language
- Browser language is auto-detected on first visit

#### 4. Dynamic Content Translation in JavaScript
```javascript
// Creating translated content dynamically
function renderAlert(alert) {
    const alertDiv = document.createElement('div');
    
    // Get translated alert message based on alert type
    let messageKey;
    switch(alert.type) {
        case 'DEW_WARNING':
            messageKey = 'weather_alerts.alert_dew_warning';
            break;
        case 'WIND_WARNING':
            messageKey = 'weather_alerts.alert_wind_warning';
            break;
        default:
            messageKey = 'weather_alerts.section_title';
    }
    
    alertDiv.textContent = i18n.t(messageKey);
    container.appendChild(alertDiv);
}
```

### Backend Usage

#### 1. Python Translation Utilities
```python
from i18n_utils import get_translated_message, I18nManager, create_translated_alert

# Simple translation
message = get_translated_message('common.loading', language='fr')

# Using manager instance
manager = I18nManager('en')
title = manager.t('astro_weather.section_title')

# Get translation with parameters
alert_msg = manager.t('weather_alerts.critical_dew_risk', time='14:30')

# Get entire namespace
weather_namespace = manager.get_namespace('weather_alerts')
```

#### 2. Translated API Responses
```python
from flask import jsonify
from i18n_utils import create_translated_alert, I18nManager

@app.route('/api/weather/alerts', methods=['GET'])
@login_required
def get_weather_alerts_api():
    """Get weather alerts with translation support"""
    
    # Get user's preferred language (could come from request headers or DB)
    language = request.args.get('lang', 'en')
    
    # Create alerts with translated messages
    alerts = [
        create_translated_alert(
            alert_type='DEW_WARNING',
            severity='HIGH',
            time=alert_time,
            language=language
        ),
        # ... more alerts
    ]
    
    return jsonify({'alerts': alerts})
```

#### 3. Request-Level i18n Initialization
```python
from i18n_utils import init_i18n_for_request

@app.before_request
def setup_i18n():
    """Initialize i18n for each request"""
    language = request.args.get('lang', 'en')
    g.i18n = init_i18n_for_request(language)

# Later in route handler
@app.route('/api/some-endpoint', methods=['GET'])
def some_endpoint():
    message = g.i18n.t('some.key')
    # ...
```

### Translation Key Structure

Keys are organized by component/namespace using dot notation. Hierarchy:
1. **Namespace** (top level) - Component or feature name
2. **Section** (optional) - Logical grouping within namespace
3. **Key** - Specific translation key

Example structure:
```json
{
  "common": {
    "loading": "Loading...",
    "error": "Error"
  },
  "astro_weather": {
    "section_title": "🌡️ Current Conditions",
    "loading_message": "☁️ Loading...",
    "no_data": "No data available"
  },
  "weather_alerts": {
    "alert_dew_warning": "Critical dew risk",
    "critical_dew_risk": "Critical dew risk starting at {time}"
  }
}
```

### Guidelines for Implementing Translations

#### When Adding New User-Facing Text
1. **Define translation keys** in all language files (`en.json`, `fr.json`, `es.json`, `de.json`, `it.json`, `pt.json`)
2. **Use descriptive key names** that reflect the content location
3. **Group related keys** in the same namespace
4. **Include context in comments** if key meaning is ambiguous

#### For HTML Templates
```html
<!-- GOOD: Static content with data-i18n attribute -->
<h2 data-i18n="page.section_name">Section Name</h2>

<!-- AVOID: Hardcoded strings -->
<h2>Section Name</h2>
```

#### For JavaScript Components
```javascript
// GOOD: Use i18n.t() for dynamic content
const element = document.createElement('div');
element.textContent = i18n.t('namespace.key');

// AVOID: Hardcoded strings
element.textContent = 'This is a message';
```

#### For Backend API Responses
```python
# GOOD: Use translated messages in API responses
return jsonify({
    'status': 'error',
    'message': i18n.t('common.error')
})

# AVOID: Hardcoded English strings
return jsonify({
    'status': 'error',
    'message': 'An error occurred'
})
```

#### API Language Propagation Rule

- Frontend must send current language via `?lang=<code>` for endpoints returning translated content.
- Backend must normalize language from query param first, then `Accept-Language`, then fallback to `en`.
- Applies to weather alerts, astro-analysis alerts, events, and any future translated API payload.

### Adding a New Language

Every step below is mandatory - missing any one of them causes a partial or broken language integration.

1. Add the language code to the `choices` list in `scripts/translate_i18n_values.py`
2. Run the translation script: `python scripts/translate_i18n_values.py --lang XX`; review output carefully
3. Add the language to `_TRANSLATION_FILENAMES` in `backend/utils/i18n_utils.py`
4. **Add the language code to the `allowed` set in `backend/app.py` → `web_manifest_localized()`** - omitting this returns 404 for the manifest and breaks the PWA service worker install
5. Add `'/manifest.XX.webmanifest'` and `'/static/i18n/XX.json'` to `APP_SHELL_URLS` in `static/sw.js`
6. Add a `<option value="XX">` to the language selector in `templates/index.html`
7. Add the language code to the `supported` array in the inline `<script>` block in `templates/index.html` (controls PWA manifest URL switching)
8. Create the translated webmanifest: copy `static/manifest.webmanifest` to `static/manifest.XX.webmanifest` and translate the required keys (`description`, `lang`, `screenshots[].label`, `shortcuts[].name/short_name/description`)

### Translation Quality Assurance
- **Scientific accuracy** - Translations must maintain accuracy for astronomical terms
- **Consistency** - Use consistent terminology across all translations
- **Testing** - Test UI with multiple languages before merging
- **Missing keys** - Check logs for any missing translation keys in production

### Common Issues & Troubleshooting

**Issue**: Text appears untranslated (shows key instead of value)
- Check if key exists in translation file
- Verify key path matches exactly (case-sensitive)
- Check browser console for i18n loading errors
- Verify `i18n.js` loads before dependent scripts

**Issue**: Translations not updating when language changes
- Ensure UI has listener for `i18nLanguageChanged` event
- Update static content using `data-i18n` attributes
- Update dynamic content by re-rendering components

**Issue**: Backend returns untranslated messages
- Check if `utils/i18n_utils.py` is imported correctly
- Verify language parameter is being passed properly
- Check translation files exist in `/app/static/i18n/`

## Cache System Rules

The background cache is **selective-refresh**: the scheduler polls every 25 min but only runs jobs whose individual TTL has elapsed. Full documentation: [docs/CACHE_SYSTEM.md](../../docs/CACHE_SYSTEM.md).

### Multi-location caches (v1.2)
- Location-dependent caches (moon/sun/eclipses/horizon/sidereal/aurora/ISS/CSS/planetary/phenomena/solar-system/seeing/weather/best-window) keep **one slot per location preset id**; on-disk keys in `astro_cache.json` are `"<name>:<location_id>"`. Access via `cache_store.get_location_cache_entry(name, location_id)` / `load_location_cache(...)` / `update_location_cache(...)` - the old module-level singletons (`_sun_report_cache`, …) no longer exist for these. The full name list is `cache_store.LOCATION_SCOPED_CACHE_TTLS`.
- Global caches (spaceflight, IERS, AllSky, version) keep the single-slot module-level shape and plain keys. The ISS/CSS TLE fetch stays global; only pass geometry is per-location.
- `check_and_handle_config_changes()` detects changes **per preset** and calls `reset_caches_for_location(id)` - never wipe all caches for a single preset edit. Deleting a preset calls `drop_location_caches(id)`.
- The scheduler expands each location-scoped job over `get_scheduler_locations(config)`; job × location units share the same ≤6-worker pool. The Open-Meteo single-flight lock/cooldown gate stays GLOBAL (one shared budget for all locations).
- API routes serve the requester's location via the `_active_location_cache(name)` / `_resolve_active_location()` helpers in `backend/utils/route_helpers.py`, imported by whichever `backend/blueprints/*.py` module needs them.

### Per-Job TTLs (defined in `backend/utils/constants.py`)
| Job | Constant | TTL |
|-----|----------|-----|
| `moon_report` | `CACHE_TTL_MOON_REPORT` | 1 hour |
| `dark_window` | `CACHE_TTL_DARK_WINDOW` | 1 hour |
| `moon_planner` | `CACHE_TTL_MOON_PLANNER` | 2 hours |
| `sun_report` | `CACHE_TTL_SUN_REPORT` | 1 hour |
| `best_window` | `CACHE_TTL_BEST_WINDOW` | 1 hour |
| `solar_eclipse` | `CACHE_TTL_SOLAR_ECLIPSE` | 24 hours |
| `lunar_eclipse` | `CACHE_TTL_LUNAR_ECLIPSE` | 24 hours |
| `horizon_graph` | `CACHE_TTL_HORIZON_GRAPH` | 1 hour |
| `aurora` | `CACHE_TTL_AURORA` | 1 hour |
| `iss_passes` | `CACHE_TTL_ISS_PASSES` | 6 hours |
| `css_passes` | `CACHE_TTL_CSS_PASSES` | 6 hours |
| `planetary_events` | `CACHE_TTL_PLANETARY_EVENTS` | 24 hours |
| `special_phenomena` | `CACHE_TTL_SPECIAL_PHENOMENA` | 24 hours |
| `solar_system_events` | `CACHE_TTL_SOLAR_SYSTEM_EVENTS` | 24 hours |
| `sidereal_time` | `CACHE_TTL_SIDEREAL_TIME` | 1 hour |
| `seeing_forecast` | `CACHE_TTL_SEEING_FORECAST` | 6 hours |
| `weather_forecast` | `WEATHER_CACHE_TTL` | 1 hour |

### Computation Optimisations (do not regress)
- **Config loaded once per cycle**: `fully_initialize_caches()` calls `load_config()` once and passes the result to every update function via `functools.partial(fn, config=config)`. All `update_*_cache()` functions accept `config=None` and fall back to `load_config()` only when called directly.
- **Moon caches merged**: `update_moon_caches(config=None)` in `cache/cache_updater.py` instantiates `MoonService` and calls `get_report()` once, then writes both `moon_report` and `dark_window` caches. The individual `update_moon_report_cache()` / `update_dark_window_cache()` functions delegate to it and exist only for direct/test compatibility.
- **Best-window single pass**: `AstroTonightService.best_windows_all_modes()` in `astroweather/moon_astrotonight.py` runs one 12-hour night-scan loop, computing Astropy AltAz transforms once per step while evaluating all three modes simultaneously. `best_window_tonight(mode)` delegates to it.
- Execution metrics for `moon_report` **and** `dark_window` are both recorded (same timing) because they are computed together - the `moon_report` job entry records both after success or failure.
- **ISS pass event extraction early exit**: `events_aggregator._extract_iss_pass_events()` breaks out of the passes loop as soon as `days_until > 7` since passes are generated in chronological order by Skyfield's `find_events`.
- **ISS lunar transit**: `iss_passes.ISSPassService` detects ISS transits across the **lunar** disk in addition to the solar disk. Detection requires the `de421.bsp` ephemeris (gracefully skipped if absent). The report includes `lunar_transits` (list), `next_lunar_transit`, and `total_lunar_transits`. Each entry carries `start_time`/`peak_time`/`end_time` in the configured local timezone, `minimum_separation_arcmin`, `lunar_radius_arcmin`, `moon_altitude_deg`, `moon_azimuth_deg`, `moon_illumination_pct`, `iss_altitude_deg`, `iss_azimuth_deg`. The `events_aggregator` converts these to `EventType.ISS_LUNAR_TRANSIT` events (importance: CRITICAL, score 9.0, icon `bi bi-moon-stars`, `structure_key="iss"`). All i18n keys (`events_api.iss_lunar_transit_title`, `events_api.iss_lunar_transit_description`) are provided for all 6 supported languages.
- **CSS parallel system**: `css_passes.CSSPassService` is a complete, independent mirror of `ISSPassService` for NORAD 48274 (Tiangong/CSS). All state is separate (`css_tle_cache.json`, `_css_*` functions). Both run as parallel jobs in `PARALLELIZABLE_JOBS` via `ThreadPoolExecutor`. The CSS cache key is `css_passes`; sample keys in observations use `css_altitude_deg`/`css_azimuth_deg`. The `events_aggregator` converts CSS events to `EventType.CSS_PASS`, `CSS_SOLAR_TRANSIT`, `CSS_LUNAR_TRANSIT` with `structure_key="css"`. Frontend at `#spaceflight/orbital-stations` shows both ISS and CSS side-by-side. N8 notification trigger handles CSS solar/lunar transits.

### Version Comparison
- `version_checker.is_newer_version()` uses `packaging.version.parse()` (from the `packaging` library, declared in `requirements.txt`) for correct PEP 440 semantic version comparison. Do not revert to manual string parsing.
- `version_checker._save_version_result(result)` is a private helper that writes a result dict to both the in-memory `_version_update_cache` and the shared on-disk cache - always use this helper instead of repeating the three-line save pattern.

### utils/__init__.py Conventions
- numpy is imported **once** at module level as `_np` with `_HAS_NUMPY` flag. Both `_NumpySafeEncoder` and `_sanitize_for_json` reference `_np` directly - never re-introduce per-call `import numpy` inside these functions.

### Mandatory Rules for New Cache Jobs
1. **Add a `CACHE_TTL_<NAME>` constant** in `utils/constants.py` - never reuse the generic `CACHE_TTL`; choose TTL based on how frequently the underlying data actually changes
2. **Register** in `cache/cache_updater.py` → `fully_initialize_caches()` `cache_jobs` list with `(name, shared_key, partial(fn, config=config), ttl, cache_entry_ref)`
3. **Accept `config=None`** in the update function and guard with `if config is None: config = load_config()`
4. **Add validity check** in `cache_store.is_astronomical_cache_ready()` and `get_cache_init_status()` using the job's own TTL constant
5. **Add to `reset_all_caches()`** and `_write_all_astronomical_caches_to_shared()` in `cache/cache_store.py`
6. **Document TTL rationale** in `docs/CACHE_SYSTEM.md` TTL table

### Cache Metrics
- Per-job execution timing is persisted to `data/cache/astro_cache.json` under `_cache_metrics`
- `cache_store.record_cache_execution(name, duration_s, success)` records each run
- `GET /api/cache` response includes `details.execution_metrics` and `details.ttls`
- The **Metrics** tab shows a **Cache Jobs** table with TTL, status (Valid/Stale), last run time, and duration
- **Never** remove `record_cache_execution()` calls from `fully_initialize_caches()`

## Resources & References
- [Astropy Documentation](https://docs.astropy.org/)
- [Astroplan Documentation](https://astroplan.readthedocs.io/)
- [Coordinate Systems](https://docs.astropy.org/en/stable/coordinates/)
- [Time Handling](https://docs.astropy.org/en/stable/time/)
- [Skyfield Documentation](https://rhodesmill.org/skyfield/)

### Catalogues
- [PyOngc (OpenNGC)](https://github.com/mattiaverga/PyOngc)
- [Minor Planet Center](https://minorplanetcenter.net/)
- [JPL Small-Body Database](https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html)

### SkyTonight Documentation
- [SkyTonight Architecture & AstroScore](../../docs/SKYTONIGHT.md)
- [Plan My Night](../../docs/PLAN_MY_NIGHT.md)
- [API Endpoints](../../docs/API_ENDPOINTS.md)
- [Cache System](../../docs/CACHE_SYSTEM.md)

### Docker
- [Docker Documentation](https://docs.docker.com/)

### Web Development
- [Flask Documentation](https://flask.palletsprojects.com/)
- [Chart.js Documentation](https://www.chartjs.org/docs/)
- [Fetch API](https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API)

## Contact & Support

- **GitHub Issues**: https://github.com/myastroboard/myastroboard/issues
- **Documentation**: https://github.com/myastroboard/myastroboard/tree/main/docs

## License

AGPL-3.0 License - See LICENSE file for details

---

**Last Updated**: 2026-06-03
**Maintainer**: WorldOfGZ
