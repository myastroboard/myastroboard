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

#### Connectors — MyAstroShine is now a first-class connector

- MyAstroShine was half a connector: stored under `config.connectors`, switched on and off from
  the same screen, but absent from the registry and rendered by a card of its own. It is now a
  `BaseConnector` like AllSky — in `REGISTRY`, listed by `GET /api/connectors`, and drawn by the
  same card, which also means it gains the health-check button.
- What is specific to it is declared rather than special-cased: `SECRET_FIELDS` (token, signing
  secret), `CONFIG_FIELDS`, `URL_FIELDS`, an empty `MODULES`, and an `is_configured()` that
  requires the credentials, not just a URL — so the card now says *Not installed* until all
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
