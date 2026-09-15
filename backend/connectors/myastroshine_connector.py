"""
MyAstroShine connector — send an AstroDex photo out for re-processing and bring
the enhanced result back as a new picture on the same object.

Declared here, alongside the other connectors and with the same attribute block,
so a connector's identity always has exactly one place to read it from.

It is deliberately **not** a ``BaseConnector`` and **not** in ``REGISTRY``:

- the exchange is bidirectional (the browser hands a photo to MyAstroShine, the
  MyAstroShine container posts the result back), so ``get_module_urls()`` and
  ``fetch_sensor_data()`` — "resolve URLs the browser will read" and "poll live
  sensor values" — have no meaning here;
- it exposes no independently-toggleable modules, so the MODULES machinery would
  stay empty;
- its card needs token / signing-secret / callback-override / copy-rating fields
  that the generic card does not render.

So the card and its config live on ``/api/astrodex/integration/*`` instead, and
``GET /api/connectors`` stays the list of BaseConnector-backed cards. Only the
metadata below is shared with them — see ``docs/MYASTROSHINE.md``.
"""


class MyAstroShineConnector:
    name = "myastroshine"
    label = "MyAstroShine"
    description = "Send an AstroDex photo to MyAstroShine for re-processing, then bring the result back"
    # Oldest release implementing the pull + webhook round-trip. Informational, exactly like
    # BaseConnector.min_version: MyAstroShine reports its own version only once a handoff
    # completes, where it is stored per picture as enhanced_source_version.
    min_version = "v0.4.0"
    homepage = "https://github.com/myastroboard/myastroshine"
    target_modules = ["astrodex"]
