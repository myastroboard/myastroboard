# Plan My Night

Plan My Night lets each `admin` or `user` build a private target timeline for a single observing night.

## Access Rules

- `admin` and `user` can create, edit, reorder, complete, and clear plans.
- `read-only` users can view the Astrodex tab but cannot access Plan My Night actions.
- Plans are stored per user, one file per equipment combination: `data/projects/<user_id>_plan_<combination_id>.json` (or `data/projects/<user_id>_plan_my_night.json` for the default plan when no combination is selected). A user can hold a separate plan per combination at once.

## Equipment Combination Selector

When a user owns or shares more than one equipment combination, adding a target from SkyTonight shows a picker to choose which combination's plan to target (badges show each combination's plan state: active/expired/no plan). With exactly one combination, it's picked automatically. Only enabled and valid combinations (see [EQUIPMENT.md](EQUIPMENT.md#disabling-equipment)) are offered for a *new* plan; an existing plan on a combination that's since been disabled still shows correctly instead of disappearing.

A combination used by any plan can't be deleted while that plan exists (see [EQUIPMENT.md](EQUIPMENT.md#deletion)) - plans are never silently orphaned by a combination going away.

## SkyTonight Integration

From SkyTonight report tables (deep sky, bodies, comets), a dedicated **Plan My Night** column is available:

- If no plan exists, first add creates the plan automatically.
- If a current-night plan exists, add appends the target.
- If only a previous-night plan exists, add is disabled until plan is cleared.
- Alias matching is powered by `catalogue_aliases` to avoid duplicates.

## Plan States

- `none`: no plan currently stored.
- `current`: plan can be edited.
- `previous`: plan is locked for edits; targets can still be added to Astrodex; plan can be cleared.

## Pinned Location (v1.2)

A plan is **pinned to the user's active location at creation time** (`location_id` + a frozen `location_name` snapshot in the plan payload). Its altitude/timeline math is never silently recomputed against different coordinates:

- The plan view shows which location the plan was computed for.
- If the viewer's *current* active location differs from the plan's pinned location, a non-blocking warning banner appears (altitudes shown may not match what you'll actually see).
- When an admin deletes a location preset, plans pinned to it are cascade-deleted by default (`DELETE /api/locations/<id>?plans=cascade`), or kept orphaned with the stale-location banner (`?plans=orphan`). See [LOCATIONS.md](LOCATIONS.md).

## Editing Features

- Per-target planned duration (`HH:MM`).
- Reorder targets (up/down) inside night timeline.
- Mark targets done / undo.
- Remove targets.
- Add target to Astrodex directly.
- Timeline progress bar and current-target banner while within night timeframe.

## Legacy Plan Purge

Plans are daily/ephemeral, so the pre-combination (telescope-keyed) plan schema is never migrated: on every app startup, any plan file whose `plan` dict still contains the old `telescope_id` key is deleted outright rather than converted.

## Exports

- CSV export: `GET /api/plan-my-night/export.csv`
- PDF export: `GET /api/plan-my-night/export.pdf`

## API Summary

See [API_ENDPOINTS.md](API_ENDPOINTS.md) for the full list.
