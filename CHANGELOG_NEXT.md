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
