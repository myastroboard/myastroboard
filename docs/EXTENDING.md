# Extending MyAstroBoard

MyAstroBoard is an **opinionated core, not a plugin platform** (see
[ROADMAP.md - Architecture direction](../ROADMAP.md#architecture-direction)). You extend it
through a small set of **narrow, well-bounded extension points**. Each is a self-contained unit
a contributor can add, and a maintainer can review, without having to learn the whole codebase.

If what you want to add is a whole new vertical feature - its own tab, its own storage, its own
i18n namespace, its own cache jobs - that is a core change, not an extension. Open a
[discussion](https://github.com/myastroboard/myastroboard/discussions) first.

| Extension point | What it adds | Status | Recipe |
|---|---|---|---|
| Translation | A new UI language, or fixes to an existing one | Available | [7.TRANSLATIONS.md](7.TRANSLATIONS.md) |
| Target catalogue | Cross-references or standalone deep-sky objects in SkyTonight | Available | [below](#target-catalogue) |
| Connector | A read-only bridge to an external astronomy tool, surfaced in the app tabs it declares | Available; formal public SDK planned for v1.6 | [CONNECTORS.md - Adding a new connector](CONNECTORS.md#adding-a-new-connector) |
| Export formatter | A new "export Plan My Night / SkyTonight as X" format (Stellarium, SkySafari, NINA...) | Planned for v2.1 - no stable contract yet | - |

Every extension follows the project-wide rules in
[CONTRIBUTING.md](../CONTRIBUTING.md): English only, all 6 i18n files, centralized logging, tests
that mirror the backend layout, and the validation block before you call it done.

---

## Target catalogue

Two shapes, depending on whether your catalogue *tags existing objects* or *adds new ones*.

### Cross-reference catalogue

Adds a `catalogue_names` entry and a `source_catalogues` tag to existing NGC/IC records. It
never adds coordinates and never changes the preferred display name (OpenNGC / Messier /
Caldwell always win). Examples: Herschel 400, Pensack 500, LBN, Arp.

1. Add `backend/catalogues/<name>.json`, in one of the two existing formats:
   - a **map** `{ "NGC 1234": "<Cat> 5", ... }` (LBN, Arp style), or
   - a **list** `[ "NGC 1234", "IC 5678", ... ]` when the source name is not needed (Pensack 500
     style).
2. Register it in `_build_cross_ref_map()` in
   `backend/skytonight/skytonight_catalogue_builder.py` - one `_load_json_catalogue(...)` block
   modelled on the existing ones, keying with `_ngc_ic_match_key()`.
3. Add the catalogue id to `SKYTONIGHT_PREFERRED_NAME_ORDER` in `backend/utils/constants.py`.
   Position matters: put it after the authoritative catalogues, near the other cross-refs.
4. Add a row to the catalogue table and a source note in [SKYTONIGHT.md](SKYTONIGHT.md).
5. Add a test in `tests/skytonight/test_skytonight_catalogue_builder.py`: a known NGC record
   gains the tag.

### Standalone catalogue

Creates new target records with their own coordinates, for objects with no NGC/IC identifier.
Examples: Sharpless, Barnard, vdB, Abell PNe.

1. Add `backend/catalogues/<name>.json` as a list of objects:
   ```json
   {
     "name": "Sh2-155",
     "ra_hours": 22.951,
     "dec_degrees": 62.616,
     "size_arcmin": 50.0,
     "type": "Emission Nebula",
     "description": "Cave Nebula",
     "mag": null,
     "constellation": "Cepheus",
     "extra_catalogues": []
   }
   ```
2. Register it with `_build_standalone_targets_from_json('<name>.json', '<Cat>')` in
   `skytonight_catalogue_builder.py` (next to the existing `standalone_*` calls).
3. Steps 3-5 are the same as for a cross-reference catalogue.

### After either

```bash
python scripts/build_skytonight_catalogue.py      # or POST /api/skytonight/dataset/rebuild
pytest tests/skytonight/
```

Catalogue data must be verifiable against a published source - cite it in the SKYTONIGHT.md
note and in the PR description.

---

## Connector

A connector is a Python class extending `BaseConnector`
(`backend/connectors/base_connector.py`), registered in `backend/connectors/__init__.py`,
exposing one or more independently-toggleable modules. Its data appears in the app tabs it
names in `target_modules` — `["observatory"]` for AllSky, and legitimately `[]` for a
self-contained connector that feeds no existing tab.
Full recipe: [CONNECTORS.md - Adding a new connector](CONNECTORS.md#adding-a-new-connector).

A connector is the safest kind of third-party contribution because its contract is narrow: talk
to an external system, return data. It does **not** own UI, user storage, or an i18n namespace
of its own beyond its settings labels.

v1.6 turns `BaseConnector` into a documented, versioned public SDK with a separate
`myastroboard/mab-plugins` repository and a curated (reviewed-PR) distribution model. Until then,
new connectors land directly in `backend/connectors/` by PR.

> **A connector is a connector.** MyAstroShine
> ([MYASTROSHINE.md](MYASTROSHINE.md)) is bidirectional and owns UI in the Astrodex tab, but it
> is still an optional bridge to an external service that the user switches on or off - so it is
> a `BaseConnector` in the `REGISTRY`, listed by `GET /api/connectors`, and rendered by the same
> card as AllSky. What differs is carried declaratively: `SECRET_FIELDS` for its credentials,
> `CONFIG_FIELDS` for its extra settings, `target_modules = ["astrodex"]` for where its data
> lands, and an empty `MODULES` because the round-trip has no independently-toggleable parts.
>
> Anything that writes back into MyAstroBoard data or owns its own screen still needs a core
> change alongside the connector - open a discussion first.

---

## Export formatter

Planned for v2.1. Today, Plan My Night has two hard-coded export routes
(`/api/plan-my-night/export.csv`, `/api/plan-my-night/export.pdf`). v2.1 introduces a small
registry of formatters (Stellarium `.stel`, SkySafari `.skylist`, NINA target-list XML, extended
CSV) so a new format is one formatter class plus a test. This section will carry the recipe once
that contract exists.

---

## The one hard rule: no new cross-feature dependency cycles

The backend is split into per-domain packages (`skytonight/`, `observation/`, `equipment/`,
`weather/`, `astroweather/`, `space/`, `cache/`, `utils/`). A handful of import cycles between
these already exist and are being unwound one at a time. **Do not add new ones.**

- A shared helper two features both need belongs in `utils/` (or a new small shared module), not
  imported feature-to-feature.
- If feature A genuinely must call into feature B at request time and B does not already depend
  on A, a **lazy import inside the function** is acceptable as a deliberate, commented exception
  (this is how `plan_my_night` reaches `equipment_profiles` today). A new module-level
  `import` that closes a cycle is not.
- When in doubt, ask in the PR - a reviewer will tell you whether the edge is already there or
  you are creating one.

This keeps every feature reviewable and testable on its own, which is the whole point of the
extension-point model above.
