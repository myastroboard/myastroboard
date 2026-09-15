#### Connectors

- Each connector card now shows an "Appears in" row: translated badges naming the app tabs the
  connector feeds. AllSky shows *Observatory*, MyAstroShine shows *AstroDex* - previously the
  page implied every connector fed the Observatory, which was never true.
- A connector that feeds no tab (a self-contained one, e.g. a future MQTT bridge) shows a
  *Standalone* badge instead. Connectors declare this through the new `target_modules`
  attribute on `BaseConnector`, also exposed by `GET /api/connectors`.
- The MyAstroShine card now states its minimum requirement (*Requires v0.4.0*), the same way
  the AllSky card does.
