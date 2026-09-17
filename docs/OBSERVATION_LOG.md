# Observation Log

The Observation Log (v1.3) is the **Log** step of the `Plan → Observe → Log → Astrodex` loop: a
private, chronological record of what actually happened on a given night, and what was actually
captured.

It lives as the 5th sub-tab of the **Astrodex** main tab, next to Astrodex, Plan My Night, Photo Map
and Catalogue Collection - so the whole loop stays under one navigational roof.

## Table of Contents

1. [Concept](#concept)
2. [Multi-night sessions](#multi-night-sessions)
3. [The one-directional Astrodex relationship](#the-one-directional-astrodex-relationship)
4. [Data model](#data-model)
5. [Attachments](#attachments)
6. [Storage and write safety](#storage-and-write-safety)
7. [API endpoints](#api-endpoints)
8. [PDF export](#pdf-export)
9. [Import from Plan](#import-from-plan)
10. [Deletion and reference counting](#deletion-and-reference-counting)
11. [Out of scope for v1.3](#out-of-scope-for-v13)

---

## Concept

| Question | Answered by |
|---|---|
| "What do I want to shoot tonight?" | **Plan My Night** (planned durations, timeline, per-combination) |
| "What did I actually do on the night of X?" | **Observation Log** (this feature) |
| "Everything I have ever captured, as a gallery" | **Astrodex** |

A **session** is a trip: location, equipment combination and free-text (trip-level) notes, plus one
or more **nights** - each with its own actual start/end times and sky conditions (SQM, seeing,
transparency, moon illumination) and its own notes. The common case is one night; a multi-night dark-sky
trip is just a session with more than one. Within the session, an ordered list of **entries** (one
per target) each records the real numbers - frame count, sub-exposure length, integration minutes, a
0-5 rating and per-target notes - and is attributed to whichever night it was captured on. An entry can
also optionally override the session's own equipment combination, for the common case of switching
telescopes/cameras partway through a night - see [Multi-night sessions](#multi-night-sessions).

Sessions are **permanently private**. There is no `private_mode` toggle and no cross-user merged
view: this is a personal logbook, not a second Astrodex. (The storage mechanics are copied from
`astrodex.py`; the sharing model deliberately is not.)

### Access rules

- `admin` and `user` can create, edit and delete their own sessions and entries.
- `read-only` users can view the Observation Log but cannot mutate anything (the two list/detail
  routes are `@login_required`; every mutating route is `@user_required`).
- A session is only ever visible to its owner - there is no admin-wide view.

---

## Multi-night sessions

A session always has **at least one night** and can have more - a week at a dark site is one session,
not one per night, so the trip stays grouped and its total integration is one number.

- **Location is session-level** (fixed for the whole trip), not per-night - a deliberate
  simplification: relocating mid-trip means starting a new session.
- **Every entry records its own equipment** (`entry.combination_id`), frozen from the session's own
  default at add time and editable afterwards - the session-level `combination_id` stays the trip's
  "usual" equipment, while an individual entry's own field is what actually gets displayed and counted
  for that target, whether or not it was changed from the default.
- **Everything that changes night to night lives on the night**: date, actual start/end, SQM, seeing,
  transparency, moon illumination, and a per-night notes field (weather, mishaps specific to that
  night). The session's own `notes` field stays trip-level (gear problems, overall impressions).
- **Every entry is attributed to a night** via `night_id`. The same target can appear on several
  different nights of the same trip as separate entries - nothing dedupes across nights, matching
  "log what actually happened," not "log each object once."
- **Moon illumination is computed automatically**, never typed in. Unlike seeing/transparency (a
  7Timer *forecast*, only available same-day), it is a pure ephemeris calculation
  (`astroweather/moon_planner.py`'s `moon_illumination_percent()` - the same engine behind the 7-night
  Moon Planner forecast, for consistency app-wide), so it works for any date including the past -
  recomputed server-side whenever a night's date changes.
- **A night can be added, edited or deleted** independently
  (`POST`/`PUT`/`DELETE /api/observation-sessions/<id>/nights[/<night_id>]`). Deleting a night is
  refused while it's the session's last remaining one, or while any entry still points at it - move or
  delete those entries first. This mirrors the app's established delete-guard convention (blocked
  while referenced) rather than leaving a dangling `night_id` behind.
- **Existing single-night sessions upgrade transparently.** A session written before this existed has
  no `nights` field; `load_user_sessions()` synthesizes one `nights[0]` from its old scalar
  `date`/`start_time`/`end_time`/`sqm`/`seeing`/`transparency` fields (and stamps every entry with that
  night's id) on read. This is lazy - nothing is rewritten to disk until the session is next saved for
  any reason - and idempotent, so there is no separate migration step to run.
- **Importing a Plan My Night plan reuses a night of the same date** within the target session rather
  than duplicating it - see [Import from Plan](#import-from-plan).

---

## The one-directional Astrodex relationship

This is the decision most likely to be re-litigated later, so it is stated explicitly.

**A session entry is its own record.** It is the source of truth for "what happened this session",
independent of whether the target was ever processed into a keeper image. It is *not* a view onto an
Astrodex picture, and the two are never kept in sync.

Two distinct links exist, with deliberately different triggers:

### 1. Astrodex *item* registration is automatic

The moment an entry gets real capture evidence - `frame_count > 0`, or a picture attached - the
matching Astrodex item is found-or-created silently in the background (same dedup rules as Plan My
Night's existing `add-to-astrodex`), and its id is stored on the entry as `astrodex_item_id`.

There is no button for this. "Catch them all" is a keypoint of the app, and a manual push button
could simply be forgotten, silently defeating it. Auto-linking the *item* costs nothing (no picture
required - it is purely a catalogue-membership fact).

**It is never auto-reversed.** Editing `frame_count` back down to 0 leaves `astrodex_item_id` in
place. Once catalogued, always catalogued; removing an Astrodex item stays a deliberate, guarded
user action and no automated process undoes it.

### 2. Attaching the actual picture stays manual

Processing and stacking genuinely happen days after the session, so the photo is attached separately
via `POST /api/observation-sessions/<id>/entries/<id>/astrodex-picture`. (Astrodex picture location
was made editable rather than frozen for exactly this reason.)

**No picture ever lives in Observation Log storage.** The only place an image file is uploaded is
the existing, unchanged `POST /api/astrodex/upload` route, which writes straight into Astrodex's own
image directory; the attach route then calls `add_picture_to_item()` and stores the resulting
`astrodex_picture_id` on the entry.

### Both links are one-shot, never a sync

Editing the entry afterwards does **not** update the linked Astrodex item/picture, and vice versa -
mirroring Plan My Night's existing one-shot copy behavior. If the linked item or picture is later
deleted through Astrodex's own UI, the entry's pointer simply stops resolving; nothing is repaired
or cascaded, and no reverse delete-guard is added to `astrodex.py`.

### The reverse link is display-only

The forward link (entry -> item/picture) is the only thing ever stored. Astrodex's own item/picture
detail views additionally show a **read-only "Logged on \<date\>" backlink** back to the session that
produced them, computed on every `GET /api/astrodex` request via
`observation_sessions.build_astrodex_session_backlink_index()` (a one-pass reverse scan of the
caller's own sessions, keyed by `astrodex_item_id`/`astrodex_picture_id`). This is purely a
navigation convenience - nothing is written back to either side, and it never crosses users (sessions
are private, so the scan only ever covers the requesting user's own sessions, regardless of whether
the item view itself is a merged multi-owner one).

### Consequence for v1.5 Session Analytics

Aggregation ("total integration hours", "objects captured") should read from Observation Log
sessions/entries as the **primary** source, not from Astrodex pictures. Astrodex's
`frames` / `exposition_time` / `integration_minutes` (v1.3+: validated numeric fields, mirroring
this module's own trio - see `docs/ASTRODEX.md`) are a *per-photo* record and may not cover every
entry (attaching a picture is a manual, optional step), whereas an entry's own
`frame_count` / `sub_exposure_seconds` / `integration_minutes` are set for every logged target.
Pre-v1.3 pictures may also still carry a legacy free-text `exposition_time` value that predates the
numeric field. Cross-reference Astrodex only for gallery/photo display.

---

## Data model

### Session object

| Field | Type | Notes |
|---|---|---|
| `id` | str (uuid4) | |
| `location_id` | str \| null | Access-checked location preset id, resolved server-side |
| `location_name` | str \| null | Frozen snapshot: preset name, or a free-text "somewhere else" label |
| `location_latitude` / `location_longitude` / `location_elevation` | float \| null | Same 3-state preset/custom/none pattern as an Astrodex picture's location |
| `combination_id` | str \| null | Owned or shared equipment combination, access-checked server-side |
| `combination_name` | str \| null | Frozen snapshot |
| `notes` | str | Trip-level notes (gear problems, overall impressions) - distinct from each night's own `notes` |
| `nights` | list[night] | See below. **Never empty** - a session always has at least one. Storage order is insertion order; sort/display always go through the earliest-date-first helpers (`_sorted_nights()`, `_primary_night()`, `session_date_range()`) rather than assuming list order is chronological |
| `entries` | list[entry] | See below. List order is entry order; there is no explicit position field (same convention as Plan My Night) |
| `imported_from_plan_combination_id` | str \| null | Provenance marker set by "Import from Plan" (`'default'` for the no-combination plan). Never re-resolved live |
| `created_at` / `updated_at` | iso8601 str | |

A session's "date" for sorting, filtering and display purposes is always **derived**, never stored:
the earliest night's date (`session_date_range(session)[0]`) for a single value, or the full
`[earliest, latest]` range where a range makes sense (list card, PDF summary table).

### Night object

| Field | Type | Notes |
|---|---|---|
| `id` | str (uuid4) | |
| `date` | str `YYYY-MM-DD` | Usually in the past (sessions are logged the morning after). **Required** - a night can never be undated, mirroring the pre-v1.3.1 session-level rule this replaced |
| `start_time` / `end_time` | str (iso8601) \| null | *Actual* observing start/end - distinct from Plan My Night's *planned* `night_start`/`night_end` |
| `sqm` | float \| null | Measured/estimated sky quality; pre-filled from the location preset's own `sqm` when the night is created, always editable |
| `seeing` | int 1-8 \| null | Same scale as `astroweather/seeing_forecast_7timer.py`'s `SEEING_SCALE` (1 = best … 8 = worst) |
| `transparency` | int 1-8 \| null | Same scale as 7Timer's `TRANSPARENCY_SCALE` (1 = worst … 8 = best - inverted vs. seeing, per 7Timer's own convention) |
| `moon_illumination_percent` | float 0-100 \| null | **Server-computed**, never client-supplied - see [Multi-night sessions](#multi-night-sessions) |
| `notes` | str | This night's own notes (weather, mishaps specific to it) |
| `created_at` / `updated_at` | iso8601 str | |

### Entry object (one per target)

| Field | Type | Notes |
|---|---|---|
| `id` | str (uuid4) | |
| `night_id` | str \| null | Which of the session's nights this entry belongs to. Defaults to the most recently added night when the client doesn't specify one; validated server-side to resolve within the same session |
| `name`, `catalogue`, `type`, `constellation`, `ra`, `dec`, `mag`, `size` | mirrors Plan My Night's `_build_target_payload()` | **Frozen snapshot at add time** - never re-resolved live against SkyTonight |
| `catalogue_group_id`, `catalogue_aliases` | str / dict | Cross-catalogue identity (dedup + alias display), same purpose as in Plan My Night entries |
| `alttime_file` | str \| null | Key (not the embedded series) for the `GET /api/skytonight/alttime/<id>?location_id=` popup chart, exactly like Plan My Night. The underlying JSON is recalculated for "tonight" on every SkyTonight run and old files are purged, so the frontend only shows the chart button while `now` is within *this entry's own night's* `start_time`/`end_time` window - past that, the file no longer represents the logged observation |
| `source_plan_entry_id` | str \| null | Set only on Import from Plan; makes re-import idempotent |
| `planned_minutes` | float \| null | Frozen snapshot of the plan target's scheduled duration, carried straight from Plan My Night's own `planned_minutes` on import; `null` for a manually-added entry with no plan origin. Shown next to `integration_minutes` so what was scheduled can be compared against what was actually captured - never recomputed or reconciled server-side |
| `frame_count` | int \| null | |
| `sub_exposure_seconds` | float \| null | Optional; when present alongside `frame_count`, the frontend auto-computes `integration_minutes` as a convenience. Never recomputed server-side |
| `integration_minutes` | float \| null | The one guaranteed-summable value for future aggregation, regardless of whether sub-exposure length was tracked |
| `rating` | float \| null | 0-5 in 0.5 steps - the same widget and validation contract as Astrodex picture ratings (a deliberate correction of the roadmap's "1-5", so the app has exactly one rating convention) |
| `notes` | str | Per-target notes |
| `combination_id` | str \| null | The equipment actually used for this one target (e.g. switched telescopes mid-session). Resolved/access-checked server-side exactly like the session's own field. The Observation Log UI pre-selects and freezes the session's own combination as this value at add time - never a live reference - so editing the session's default equipment afterwards never silently reshapes an already-logged target's equipment history; `null` is only the fallback for entries added directly through the API without one, or logged before this field existed, and is displayed as "whatever the session's own equipment currently is" |
| `combination_name` | str \| null | Frozen snapshot of `combination_id`'s name at the time it was set |
| `combination_used_components` | dict \| null | Optional checklist of which parts of the *effective* combination were used (the entry's own override if it has one, else the session's) - e.g. a filter swapped mid-session. Same shape as Astrodex's picture field; `null` means "everything in the effective combination" |
| `astrodex_item_id` | str \| null | **Auto-populated** on first capture evidence; never auto-cleared (see above) |
| `astrodex_picture_id` | str \| null | Set only by the manual attach-picture action; `null` is the normal state for an entry with no keeper image yet |
| `created_at` / `updated_at` | iso8601 str | |

Only the "what actually happened" fields (`night_id`, `frame_count`, `sub_exposure_seconds`,
`integration_minutes`, `rating`, `notes`, `combination_id`, `combination_name`,
`combination_used_components`) are writable through the update route - `night_id` is reassignable both
when adding an entry and afterwards (unlike the frozen identity fields), so a target logged under the
wrong night can be moved. The target identity snapshot is frozen, and the two `astrodex_*` pointers are
set through `link_entry_to_astrodex()` rather than by a client payload.

### Attachment object

| Field | Type | Notes |
|---|---|---|
| `id` | str (uuid4) | |
| `filename` | str | The regenerated on-disk name (`{user_id}_{uuid4()}.{ext}`) - never the original, mirroring Astrodex's own upload convention |
| `original_name` | str | The filename as the user's browser sent it |
| `content_type` | str | Best-effort MIME type from the upload, used only to pick a display icon - never trusted for validation (the extension allow-list is what's actually enforced) |
| `display_name` | str or null | Optional user-set custom name, shown in the UI (and used as the download filename) in place of `original_name` when set. `null` by default - upload never sets it, only the rename route does |
| `uploaded_at` | iso8601 str | |

Attachments are **session-level**, not per-night or per-entry - a guiding graph or a subframe log
belongs to the whole night's session, not one specific target. See [Attachments](#attachments) below.

---

## Attachments

A session can hold generic files - guiding graphs, subframe logs, planning notes exported from
another tool - separate from the entry → Astrodex picture link above: an attachment never lives in
Astrodex, and the actual keeper photo attached through `.../astrodex-picture` never lives here. Two
independent upload paths into two different places, on purpose.

- **Allowed types**: `jpg`, `jpeg`, `png`, `webp`, `pdf`, `txt`, `doc`, `docx` - extension-only
  validation via `secure_filename()`, the same allow-list mechanism as Astrodex's own image upload
  (just a different, wider set of extensions). No MIME sniffing, no size cap - matches Astrodex's own
  upload route, which has neither either.
- **Storage**: `data/observation_sessions/attachments/` (flat, mirroring `data/astrodex/images/`),
  filenames regenerated as `{user_id}_{uuid4()}.{ext}`, never the original name. The directory path is
  computed by `observation_sessions.attachments_dir()` - a function, not a module-level constant, so
  it re-reads `OBSERVATION_SESSIONS_DIR` on every call and stays correct for test fixtures (and any
  future runtime reconfiguration) that swap that directory out.
- **Upload is one combined step** (`POST .../attachments`, multipart), unlike Astrodex's own
  upload-then-attach split - an attachment only ever belongs to the one session it's uploaded to, so
  there's no reason to separate "store the file" from "record it."
- **Download is ownership-checked**, not just login-checked: `GET /api/observation-sessions/
  attachments/<filename>` verifies the filename appears in one of the *caller's own* sessions before
  serving it (sessions are never shared, so this is simpler than Astrodex's own private/shared-mode
  check on `can_user_view_image()`). An unrecognized filename and someone else's real file both get
  the same 403, so the response never confirms whether a given filename exists. The response's
  `Content-Disposition` filename is `display_name` (with the real extension re-attached if the custom
  name omits it) or else `original_name` - never the on-disk `{uuid}.{ext}` storage name, which is what
  a browser would otherwise suggest since it's the last path segment of the URL.
- **Renaming** (`PUT /api/observation-sessions/<session_id>/attachments/<attachment_id>`, `{"name":
  "..."}`) only ever writes `display_name`. It never touches `filename` or `original_name`, so the file
  on disk and its storage key are untouched - purely a cosmetic label plus the download filename above.
  An empty/blank name clears `display_name` back to `null`, reverting the UI to `original_name`.
- **Deleting a session deletes its attachment files too** - unlike the entry → Astrodex link (a soft
  reference into a *different* feature's data, deliberately left untouched on delete), an attachment
  file is owned entirely by its session, so `delete_session()` removes them from disk before removing
  the session record. A missing file on disk (already cleaned up by other means) doesn't block the
  deletion - only logged.
- **Already covered by the admin backup ZIP with zero extra code**: `data/observation_sessions/` was
  already a full recursive entry in `admin.py`'s `BACKUP_ENTRIES`/`RESTORE_ALLOWED_PREFIXES` before
  attachments existed, so the new `attachments/` subdirectory is picked up automatically. Verified with
  an actual backup → delete → restore round trip in the test suite, not just assumed.

---

## Storage and write safety

Mechanically identical to `backend/observation/astrodex.py`:

- Directory: `data/observation_sessions/` (top-level, mirroring `data/astrodex/`).
- One file per user: `data/observation_sessions/<user_id>_sessions.json`.
- Attachment files: `data/observation_sessions/attachments/` (flat, mirroring `data/astrodex/images/`)
  - see [Attachments](#attachments).
- File shape: `{user_id, username, created_at, updated_at, sessions: [...]}`.
- `load_user_sessions()` never raises to the caller: a corrupted file is copied to
  `.corrupted.<timestamp>` and an empty payload returned (the file is overwritten on the next save).
- `save_user_sessions()` takes a per-user `threading.Lock` and runs the full atomic sequence: stamp
  `updated_at` → `.backup` copy → write `.tmp` → `validate_sessions_json()` (root is a dict, has
  `username`, has a list `sessions`; each session has `id` and a non-empty `nights` list, each night
  has `id` and `date`; any entry's `night_id`, if set, must resolve within that session's own nights) →
  `os.replace()` → drop the backup on success, restore from it on any exception.
- All path expressions go through `_safe_sessions_path()` (realpath + containment check).
- `data/observation_sessions/` is included in the admin backup ZIP (`GET /api/backup/download`) and
  in the restore allow-list.

`backend/observation/observation_sessions.py` never imports `astrodex` or `plan_my_night` at module
scope - resolving an entry to an Astrodex item is the blueprint layer's job.

---

## API endpoints

All routes are self-scoped to the caller. Mutating routes return
`{"status": "success", "data": ...}` on success and `{"error": "..."}` with the matching HTTP status
on failure.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET` | `/api/observation-sessions` | login | List own sessions (newest date first) + `stats` |
| `GET` | `/api/observation-sessions/<session_id>` | login | One session with nights + entries (bare object; 404 if not owned) |
| `POST` | `/api/observation-sessions` | user | Create a session manually (201). Body's `date`/`start_time`/`end_time`/`sqm`/`seeing`/`transparency` seed its first night |
| `PUT` | `/api/observation-sessions/<session_id>` | user | Update trip-level fields only (location, equipment, notes) - a night's own fields go through the routes below |
| `DELETE` | `/api/observation-sessions/<session_id>` | user | Delete session + all nights/entries (Astrodex untouched) |
| `POST` | `/api/observation-sessions/from-plan` | user | Seed/merge a session from a Plan My Night plan; reuses an existing night of the same date or appends a new one |
| `POST` | `/api/observation-sessions/<session_id>/nights` | user | Add another night (201). `date` required; `moon_illumination_percent` always server-computed |
| `PUT` | `/api/observation-sessions/<session_id>/nights/<night_id>` | user | Update one night's conditions/notes |
| `DELETE` | `/api/observation-sessions/<session_id>/nights/<night_id>` | user | Refused (400) while it's the session's last remaining night, or while any entry still points at it |
| `POST` | `/api/observation-sessions/<session_id>/entries` | user | Add one entry. **Side effect**: auto-links the Astrodex item when `frame_count > 0`. `night_id` optional - defaults to the most recently added night |
| `PUT` | `/api/observation-sessions/<session_id>/entries/<entry_id>` | user | Update one entry. **Side effect**: same auto-link whenever `frame_count` newly becomes `> 0` |
| `DELETE` | `/api/observation-sessions/<session_id>/entries/<entry_id>` | user | Remove one entry (linked Astrodex item/picture kept) |
| `POST` | `/api/observation-sessions/<session_id>/entries/<entry_id>/astrodex-picture` | user | Manual attach-picture action; body `{filename}` plus optional metadata overrides |
| `POST` | `/api/observation-sessions/<session_id>/attachments` | user | Upload + record a session attachment in one step (201); multipart `file` field |
| `GET` | `/api/observation-sessions/attachments/<filename>` | login | Serve an attachment file - ownership-checked, not just login-checked |
| `DELETE` | `/api/observation-sessions/<session_id>/attachments/<attachment_id>` | user | Remove the attachment record and its file |

`GET /api/observation-sessions` also returns a deliberately minimal `stats` block -
`{total_sessions, total_entries, total_integration_minutes, average_rating}` (`average_rating` is
`None` until at least one entry has been rated). Full analytics is v1.5 Session Analytics' job, not
this feature's.

---

## PDF export

Two routes, both built on the same page-rendering code
(`backend/observation/observation_sessions.py`'s `_render_session_section()`), styled to match
Plan My Night's own PDF export (same header/footer bar, palette and A4 layout):

| Method | Path | Produces |
|---|---|---|
| `GET` | `/api/observation-sessions/<session_id>/export.pdf` | One session |
| `GET` | `/api/observation-sessions/export.pdf` | Every own session in an optional date range |

**Per-session PDF** — a button on the session detail view. First page: a common-information card,
then the logged targets. The card's shape depends on the session:

- **Single night** (still the overwhelmingly common case): unchanged from the original layout - date,
  location, equipment, start/end time, SQM, seeing, transparency, trip notes, plus a one-line summary
  (target count, average rating). Targets follow as a flat list.
- **Multiple nights**: a shorter card with only location, equipment, total integration (across every
  night) and night count, plus trip notes. Targets are grouped: each night that has at least one
  logged target gets its own compact sub-header (date, start/end, SQM, seeing, transparency, moon
  illumination, that night's own notes) immediately before its targets; an entry whose `night_id`
  doesn't resolve to any of the session's nights falls back to a final "Other" group rather than
  being silently dropped. Long nights/target lists paginate onto further pages exactly like the
  single-night list always did, without repeating a night's sub-header on the continuation page.

Every target row shows its attached Astrodex photo when it has one (a neutral "No photo" placeholder
otherwise) alongside its identity, capture numbers (frames, sub-exposure, integration) and notes -
this part is unchanged by the multi-night breakdown.

**Global PDF** — a button on the session list, shown only once at least one session exists (nothing
to configure otherwise). It opens a modal asking for a date range - prefilled with the earliest and
latest night dates across all of the user's sessions, so the untouched default is "every session" -
and a sort order (`asc`/oldest-first is the default, `desc` available). The resulting PDF is: a cover
page (title, date range or "All sessions", generation timestamp, and aggregate stats -
sessions/targets/integration/average rating), a summary table (one row per session: date **range**
for a multi-night session or a single date otherwise, location, equipment, target count, integration,
rating), then every session in the range rendered exactly like the per-session export, in the
requested order.

Both routes are `@login_required` (read action, no `@user_required` gate) and only ever operate on
the caller's own sessions. `from_date`/`to_date` match a session when **any** of its nights falls in
range (inclusive, string comparison against `YYYY-MM-DD`) - a multi-night trip straddling a filter
boundary still matches, and every one of its nights still renders regardless of which of them
individually fell inside the window. An empty range means every session. `lang` (or
`Accept-Language`) selects the PDF's own translated labels, independently of the query's paging.

An entry's photo is resolved by the blueprint layer (`_resolve_entry_image_path()`), never by the
storage module - `observation/observation_sessions.py` never imports `astrodex` (see its module
docstring), so the PDF generators receive a pre-built `{entry_id: absolute_file_path}` map instead of
resolving Astrodex links themselves. A picture whose file has since been deleted, or whose linked
Astrodex item/picture no longer resolves, degrades to the "No photo" placeholder rather than failing
the export.

---

## Import from Plan

`POST /api/observation-sessions/from-plan`, body `{combination_id, session_id?}`:

1. Loads the plan via `plan_my_night.get_plan_with_timeline()`.
2. **Both `'current'` and `'previous'` plans are importable.** A plan flips to `'previous'` the
   moment `night_end` passes - which is exactly when a user sits down to log what they captured.
   Importing is a read operation from the plan's perspective; only `'none'` (nothing to import) is
   refused with a 404.
3. **No target session** (`session_id` omitted): creates a new session, seeding its location and
   combination from the plan's frozen fields, with one night built from the plan's date and
   nautical-twilight window.
4. **Existing target session** (`session_id` given): finds-or-creates the night matching the plan's
   date within that session (`_find_or_create_night_for_date()`) - reusing an existing night of the
   same date refreshes its start/end from the plan rather than creating a duplicate, so importing
   "day 2" of a multi-night trip's plan just adds a second night to the ongoing session. A different
   date always appends a new night.
5. Every imported entry is attributed to that night. Re-import is **idempotent** at the entry level
   too: any plan entry whose id already appears as a `source_plan_entry_id` in the target session is
   skipped.

`plan_my_night.py` itself is unchanged - this is a new blueprint route only.

In the UI, Plan My Night gains a **"Log this session"** button rendered in its own row (gated only
on the plan having entries, independent of state - unlike the CSV/PDF export block, which is
`'current'`-only). The Observation Log list has an equivalent **"Import from Plan"** entry point,
shown only when at least one importable plan exists. When exactly one session created today already
came from the same plan, the user is offered a merge into it instead of a second session for the
same night.

---

## Deletion and reference counting

| Deleted object | Effect on sessions |
|---|---|
| **Equipment combination** | **Blocked** while any session (any user) references it - either as its own `combination_id` or as any entry's per-target override - `delete_combination()` returns `in_use_by_session`, joining the existing `in_use_by_picture` / `in_use_by_plan` guards |
| **Location preset** | **Never cascaded, never orphan-flagged.** `GET /api/locations/<id>/references` reports the count under `observation_sessions` for information only |
| **Astrodex item / picture** | Nothing happens to the session. The entry's pointer just stops resolving |
| **Night** | **Blocked** while it's the session's last remaining night, or while any entry still references it via `night_id` - move or delete those entries first (see [Multi-night sessions](#multi-night-sessions)) |
| **Session** | Its nights and entries go with it. Any Astrodex item or picture it linked to is left completely untouched |

The location choice is deliberate: a session, like an Astrodex picture, is a **historical record** -
its frozen `location_name` snapshot stays valid as display-only history. That is different from a
Plan My Night plan, which is an *active* object that needs a live location to keep computing
altitude data against, and is therefore cascade-deleted.

The reference scans (`count_sessions_for_combination`, `count_sessions_for_location`) are
**fail-open**: an unreadable file is skipped rather than aborting the scan, matching
`count_pictures_for_combination` / `count_plans_for_combination`.

`count_sessions_for_combination` counts a session once whether the match is its own session-level
`combination_id`, any entry's own per-target `combination_id` override, or both - a single session can
reference more than one combination across its different targets. An entry's separate
`combination_used_components` field is unrelated: it's a checklist of which parts of whichever
combination is *effective* for that entry (its own override, or the session's) were actually used.

---

## Out of scope for v1.3

- **Per-filter sub-exposure breakdown** (Ha 20×300s + OIII 15×300s within one entry). v1 keeps one
  aggregate `frame_count` / `integration_minutes` per entry.
- **Session sharing / multi-user visibility.** Sessions are always private; there is no
  `private_mode` toggle and no merged view.
- **Full analytics** (integration hours over time, equipment usage breakdowns, sky-coverage maps) -
  shipped in v1.5 Session Analytics, built on this module; see
  [SESSION_ANALYTICS.md](SESSION_ANALYTICS.md).

---

## Related documentation

- [SESSION_ANALYTICS.md](SESSION_ANALYTICS.md) - the v1.5 aggregations built on this log
- [PLAN_MY_NIGHT.md](PLAN_MY_NIGHT.md) - the plan this log imports from
- [EQUIPMENT.md](EQUIPMENT.md) - combination deletion guards
- [LOCATIONS.md](LOCATIONS.md) - preset deletion workflow
- [API_ENDPOINTS.md](API_ENDPOINTS.md) - full endpoint inventory
