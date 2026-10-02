# Plan My Night

Plan My Night lets each `admin` or `user` build a private target timeline for a single observing night.

## Access Rules

- `admin` and `user` can create, edit, reorder, complete, and clear plans.
- `read-only` users can view the Astrodex tab but cannot access Plan My Night actions.
- Plans are stored per user, one per equipment combination (database tables `plans` and `plan_entries`, keyed by the combination id, or `default` for the plan with no combination selected). A user can hold a separate plan per combination at once.

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

## Meridian flip

Each timeline entry shows a meridian-flip indicator when the plan is pinned to a location and its
equipment combination has a mount. The flip time is derived at read time from the entry's stored RA
plus the plan's pinned location, offset by the mount's `meridian_flip_delay_min` - old plans need no
migration. The transit is projected in O(1) from a single local-sidereal-time reading at the start
of the night (`skytonight_calculator._meridian_transit_from_lst`), computed once per plan rather
than per entry, since the timeline is polled every 30-60 s. Pre-v1.4 mount files with no
`meridian_flip_required` key are backfilled on read (`equipment_profiles.normalize_mount_flip_fields`),
so the indicator works for existing mounts without a re-save.

| State | Meaning | Colour |
|-------|---------|--------|
| `none` | Flip not required, no meridian transit tonight, or the flip falls before this slot starts | no badge |
| `after` | Flip at or after the slot end | green |
| `mid` | Flip strictly inside the slot | orange |
| `early` | Flip within the first 10 minutes of the slot | red |
| `unknown` | The plan's combination has no resolvable mount - no flip is guessed | grey |

The tooltip carries the flip time and the mount's `meridian_flip_duration_min` (minutes lost to the
flip). The indicator also appears in the schedule-optimizer preview and the PDF export.

## Schedule optimizer

`GET /api/plan-my-night/optimize` previews a target order plus a single pre-first-target delay,
derived from each target's real altitude-based visibility window; `POST
/api/plan-my-night/optimize/apply` applies it (rejected if the plan changed since the preview). As of
v1.4 the ordering is **flip-aware**: targets are clustered by observable-run start (those within
`_FLIP_TIE_BREAK_WINDOW_MINUTES`, ~20 min, of the earliest in the cluster), and inside each cluster
the one whose meridian flip comes sooner is scheduled first, so it can finish before flipping.
Targets with no flip or an unknown mount keep their prior order at the back of the cluster. A
`flip_mid_session` plan warning is raised when a target still ends up straddling its flip.

## Legacy Plan Purge

Plans are daily/ephemeral, so the pre-combination (telescope-keyed) plan schema is never migrated: on every app startup, any plan file whose `plan` dict still contains the old `telescope_id` key is deleted outright rather than converted.

## Log this session (v1.3)

Once a plan has targets, a **Log this session** button copies them into an Observation Log session
(`POST /api/observation-sessions/from-plan`), then switches to the Observation Log sub-tab.

- It works on **both** `current` and `previous` plans. A plan flips to `previous` the moment
  `night_end` passes — which is exactly when a user sits down to log what they actually captured, so
  the button is deliberately *not* gated the way the `current`-only CSV/PDF export buttons are.
  Importing is a read operation from the plan's perspective; the plan itself is never modified.
- Re-importing is idempotent: a plan entry already imported into the target session is skipped, so
  pressing the button twice never duplicates targets.
- If exactly one session created today already came from this same plan, the user is offered a merge
  into it instead of starting a second session for the same night.

See [OBSERVATION_LOG.md](OBSERVATION_LOG.md#import-from-plan) for the full contract.

## Exports

- CSV export: `GET /api/plan-my-night/export.csv`
- PDF export: `GET /api/plan-my-night/export.pdf`

## API Summary

See [API_ENDPOINTS.md](API_ENDPOINTS.md) for the full list.
