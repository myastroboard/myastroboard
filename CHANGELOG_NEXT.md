#### Session Analytics (v1.5)

- New **Analytics** sub-tab under Astrodex: total integration hours (lifetime / this year / this
  month), objects and constellations captured, integration over time, object-type and
  constellation breakdowns, and hours per equipment combination - all computed from your
  Observation Log.
- **Sky coverage map**: every object you have captured placed on an RA/Dec grid, coloured by type
  or by capture year, with the band of sky that never rises at your location shaded in. Objects
  whose coordinates cannot be resolved are counted and named rather than silently dropped.
  It is drawn as a sky chart, not a scatter plot: the Milky Way is filled behind the data, the
  ecliptic and the celestial equator are marked, each object's dot grows with the integration
  time behind it, and the top axis reads the same right ascension as the month the object is at
  its best. The plot area follows the theme, red night-vision mode included.
- **Conditions and results**: your ratings plotted against the seeing, transparency, SQM and Moon
  illumination you recorded for each night. Strictly descriptive - every bucket shows its own
  sample count, and a bucket with fewer than five samples says so instead of being plotted.
- **Best months**: how much dark and moonless-dark time your site offers each month, next to the
  hours you actually logged. Computed live from the Sun and Moon; it is not a weather statistic
  (MyAstroBoard stores no historical weather, so it never claims to say when the sky is clear).
- Figures come from the Observation Log, not from Astrodex pictures - attaching a photo is
  optional, so picture metadata covers an unknown subset of what was captured. Your Astrodex
  collection size is reported as its own separate figure.

#### Wishlist (v1.5)

- New **Wishlist** sub-tab: objects you want to capture, with priority, notes, and a progress bar.
  Add them from the SkyTonight tables (through each row's *More* popup), the Catalogue Collection
  or the Beginner Catalog.
- Whether a wish has been captured is **recomputed on every read** from your log and your
  Astrodex, never stored - so editing a session is reflected immediately instead of leaving a
  stale badge behind. Captured wishes stay on the list so the progress counter keeps its
  denominator, with a "Remove captured" action when you want them gone.
- Sorted by upcoming visibility by default: each item shows its observable hours tonight and its
  best month ahead, computed for your active location. The full twelve-month answer stays one
  click away in the existing per-object visibility calendar.
- Duplicate detection is cross-catalogue - adding "NGC 224" when "M 31" is already listed is
  recognised as the same object. Planets and comets can be wished for but never get a frozen
  position, since a fixed RA/Dec would be wrong within weeks.
- Wishlists are private per user and are included in the admin backup archive.

#### Coordinate conversion

- **Fixed**: the DMS to decimal converter mis-signed any coordinate whose degrees field is a
  negative zero. `-0d30m00s` - half an arcminute west of Greenwich, an ordinary longitude -
  came back as `+0.5` instead of `-0.5`, because the sign was read back from the parsed number
  rather than from the string. The sign is now captured by the pattern itself.
- The route's tests only asserted that a request returned 200 or 400, never what it converted
  to, which is how this survived. They now check the values.
- Removed `utils.dms_to_decimal`, `utils.decimal_to_dms` and `utils.DMS_PATTERN`: dead code
  with no production caller (only their own tests), duplicating - and carrying the same sign
  bug as - the converter the coordinate-entry route actually uses.

#### Internal

- New `backend/utils/constellation_names.py` replaces four separate copies of the IAU
  abbreviation -> full name table (`observation/beginner_catalog.py`,
  `observation/catalogue_collection.py`, `blueprints/skytonight_api.py`, and an inline one rebuilt
  on every `/api/astrodex/catalogue-lookup` request).
- New `backend/observation/target_coordinates.py` is the single resolver for a frozen target's
  coordinates. The stored `ra`/`dec` on a plan or log entry is a decimal-hours float on one
  SkyTonight path and a formatted `"21h 31m 48.32s"` string on another, and Astrodex items carry
  none at all - so everything now resolves through the SkyTonight dataset first and parses the
  stored value only as a fallback.
- `observation/visibility_calendar.py` gained a reusable night context: the Sun/Moon grid, which
  is the expensive part of a visibility sample and is identical for every target on a given night,
  is built once and folded over many targets. A 500-item wishlist therefore costs the same few
  grids as a single object would. The v1.4 per-object calendar is unchanged.
- **New routes**: `GET /api/session-analytics/{summary,sky-coverage,conditions,best-months}`,
  `GET|POST /api/wishlist`, `PATCH|DELETE /api/wishlist/<item_id>`,
  `POST /api/wishlist/archive-captured`. No existing route changed.

#### Connectors

- Each connector card now shows an "Appears in" row: translated badges naming the app tabs the
  connector feeds. AllSky shows *Observatory*, MyAstroShine shows *AstroDex* - previously the
  page implied every connector fed the Observatory, which was never true.
- A connector that feeds no tab (a self-contained one, e.g. a future MQTT bridge) shows a
  *Standalone* badge instead. Connectors declare this through the new `target_modules`
  attribute on `BaseConnector`, also exposed by `GET /api/connectors`.
- The MyAstroShine card now states its minimum requirement (*Requires v0.4.0*), the same way
  the AllSky card does.

#### Internal

- Connector code now follows one module-per-connector layout on both sides:
  `blueprints/connectors.py` keeps only the registry listing, with
  `blueprints/connectors_allsky.py` and `blueprints/connectors_myastroshine.py` (renamed from
  `myastroshine_integration.py`) alongside it, and the tests mirror the same names. No route
  URL changed.
- MyAstroShine's identity (label, description, homepage, minimum version, target modules) is
  declared on `MyAstroShineConnector` in `backend/connectors/`, like every other connector,
  instead of being spread across a constant, a route literal and a hardcoded URL in the JS.

#### Documentation

- Connector docs had drifted from the code: a `mini_timelapse` AllSky module that has never
  existed was documented in three files, the stated AllSky minimum version (v2023.1) and
  upstream repo link were both out of date, and the Observatory layout tables did not match
  what the tab actually renders. All corrected, plus a file-layout table in CONNECTORS.md.

#### Connectors - MyAstroShine is now a first-class connector

- MyAstroShine was half a connector: stored under `config.connectors`, switched on and off from
  the same screen, but absent from the registry and rendered by a card of its own. It is now a
  `BaseConnector` like AllSky - in `REGISTRY`, listed by `GET /api/connectors`, and drawn by the
  same card, which also means it gains the health-check button.
- What is specific to it is declared rather than special-cased: `SECRET_FIELDS` (token, signing
  secret), `CONFIG_FIELDS`, `URL_FIELDS`, an empty `MODULES`, and an `is_configured()` that
  requires the credentials, not just a URL - so the card now says *Not installed* until all
  three are set, instead of *Installed* with a URL alone.
- Connector settings are saved through a new `POST /api/connectors/<name>/config` (admin),
  merged server-side. It replaces the previous client-side round-trip through `GET/POST
  /api/config`, which sent the board's whole configuration to the browser and back on every
  connector save, and it only accepts the keys a connector declares.
- `GET /api/connectors` masks every connector's `SECRET_FIELDS` (`****` + last 4, plus a
  `has_<field>` flag). The endpoint is readable by any signed-in user, so MyAstroShine's token
  and signing secret never reach the browser.
- **Route changes**: `GET|POST /api/astrodex/integration/config` and
  `POST /api/astrodex/integration/test` are removed, replaced by the shared connector config
  route and `GET|POST /api/connectors/myastroshine/health`. Both were browser-only; the routes
  the MyAstroShine container calls (`/handoff`, `/source`, `/source/image`, `/enhanced`) and the
  `/status` route used by the AstroDex tab are untouched, so no MyAstroShine instance needs
  updating.
- Connector-specific constants moved out of the project-wide `utils/constants.py` onto the
  connector that owns them: MyAstroShine's handoff TTL, max upload size, rate limit and window,
  and AllSky's two cache TTLs (`CACHE_TTL_ALLSKY_SENSOR` / `_HEALTH` become
  `AllSkyConnector.SENSOR_CACHE_TTL` / `.HEALTH_CACHE_TTL`). Adding a connector no longer means
  editing a shared constants file.
