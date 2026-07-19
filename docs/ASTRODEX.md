# Astrodex

Astrodex is your personal astrophotography logbook — a Pokédex-style catalogue of every deep-sky object you have imaged.

---

## Where to find it

**Astrodex tab → Astrodex sub-tab**

---

## Concepts

### Items and pictures

Each item represents **one target object** (a galaxy, nebula, cluster…). An item can have **multiple pictures** attached — one per session or per processing attempt.

Items are **per-user**: each account has its own private collection in `data/astrodex/<user_id>.json`. Items from different users sharing the same target are merged into a combined view when browsing.

### Catalogue integration

When you add an item by name, Astrodex looks up the name in the SkyTonight catalogue alias table (`observation/catalogue_aliases.py`) to find the canonical identifier. This allows adding "M31", "Andromeda Galaxy", "NGC 224", or "Andromeda" — and they all resolve to the same record, preventing duplicates.

The **check duplicate** endpoint (`GET /api/astrodex/check/<name>`) lets the UI warn before adding a name that already exists.

---

## Item data model

Each item stored in `data/astrodex/<user_id>.json` has the following fields:

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID string | Unique item identifier |
| `name` | string | Display name (e.g. "M31 - Andromeda Galaxy") |
| `type` | string | Object type: `Galaxy`, `Nebula`, `Cluster`, `Supernova Remnant`, `Unknown`, … |
| `catalogue` | string | Source catalogue: `NGC`, `IC`, `Messier`, `Sharpless`, `Barnard`, `vdB`, … |
| `constellation` | string | Constellation abbreviation (e.g. `And`, `Ori`) |
| `notes` | string | Free-text notes, processing ideas, next steps |
| `pictures` | array | List of picture objects (see below) |
| `location_id` | UUID string or `null` | v1.2: the location preset active when the item was created — best-effort link, only trusted while the preset still exists |
| `location_name` | string or `null` | v1.2: frozen plain-text snapshot of the location name at creation. The UI always trusts this field for display; it survives preset renames and deletions (Astrodex items are **never** deleted with a location — see [LOCATIONS.md](LOCATIONS.md)) |
| `created_at` | ISO 8601 | When the item was added to the collection |
| `updated_at` | ISO 8601 | Last modification time |

### Picture data model

Each picture attached to an item:

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID string | Unique picture identifier |
| `filename` | string | Stored filename under `data/astrodex/images/` |
| `is_main` | boolean | Whether this is the primary/cover picture |
| `caption` | string | Optional caption or session note |
| `owner_user_id` | UUID | The user who uploaded this picture |
| `created_at` | ISO 8601 | Upload timestamp |
| `combination_id` | UUID string or `null` | Linked [equipment combination](EQUIPMENT.md#equipment-combinations), resolved and access-checked server-side. Mutually exclusive with the free-text `device`/`filters` fields ("Other equipment" path) - never both. |
| `combination_used_components` | object or `null` | Frozen snapshot of which parts of the combination were actually used for this photo (e.g. `{"telescope": true, "camera": true, "filter_ids": [...]}`) - purely informational, set once at save time and never recomputed even if the combination is edited later. |
| `rating` | number or `null` | User's own 0.0-5.0 rating in 0.5 steps, or `null` if not yet rated. Feeds a combination's average-rating badge in the Equipment tab (see [EQUIPMENT.md](EQUIPMENT.md#equipment-combinations)). |

Images are stored in `data/astrodex/images/` and served by `GET /api/astrodex/images/<filename>`.

### Equipment on a picture

The Add/Edit Picture modal's Equipment section is a single select: your enabled combinations (own +
shared) plus an **"Other equipment"** option.

- Picking a combination saves `combination_id` and reveals a checklist of that combination's actual
  components (telescope / camera / guide camera / each filter) so you can mark which ones were used for
  this specific photo - purely optional, stored as `combination_used_components`.
- Picking **"Other equipment"** falls back to free-text `device`/`filters` fields (with autocomplete drawn
  from your equipment names and previously-typed values).
- If a picture's linked combination is later disabled, it still appears in that picture's edit dropdown
  (and stays selected) - the same "stays visible if already selected" rule the Equipment tab itself uses.
- A combination can't be deleted while any picture (yours or another user's) still references it.

---

## Features

### Browsing

The Astrodex grid shows all your objects with cover picture thumbnails. Items without pictures use a default placeholder image. Objects are sorted alphabetically by normalised name.

**Constellation filter**: Objects are grouped by constellation using `backend/constellation.py`. You can filter to show only objects in a specific constellation.

**Type filter**: Filter by object type (Galaxy, Nebula, Cluster…).

### Adding objects

Two ways to add an object:

1. **From SkyTonight**: Every target in the SkyTonight report tables has an "Add to Astrodex" button. The name, catalogue, and type are pre-filled.
2. **From Plan My Night**: A "Add to Astrodex" button is available for each target in the plan.
3. **Manually**: Use the "+" button in the Astrodex tab to add any object by name.

### Editing objects

The object editor allows updating:
- Name and catalogue reference
- Object type and constellation
- Notes

### Managing pictures

- Upload pictures with drag-and-drop or file picker.
- Reorder pictures; set one as the main (cover) picture.
- Delete individual pictures.
- Images larger than the display size are served at original resolution for download.
- Rate your own photos 0-5 stars (half-star steps) - lets you see which equipment combination
  produces your best results (average rating shown on the combination's card in the Equipment tab).
- Add/edit picture modal is organized into four sections: File, Date & Location, Equipment, and
  Photo information.

### Catalogue lookup

`GET /api/astrodex/catalogue-lookup?name=<name>` queries the SkyTonight target catalogue for coordinates, type, magnitude, and angular size for a given object name. This auto-fills metadata when adding a new item.

### Constellation list

`GET /api/astrodex/constellations` returns all constellations represented in the current user's collection, useful for building the constellation filter dropdown.

### Photo Map

**Astrodex tab → Photo Map sub-tab**

Shows every geotagged picture (one with `latitude`/`longitude` set via a location preset or manually-typed custom coordinates in the Add/Edit Picture modal) on a world map, with marker clustering: bubbles show a photo count and separate into individual pins as you zoom the map in, mirroring the Apple/Google Photos map view. Clicking a bubble opens the existing photo slideshow directly for every photo in that cluster; clicking a single pin opens the slideshow for that one photo.

This does **not** perform any EXIF GPS extraction — it only visualizes coordinates a user already entered manually. It is powered by a dedicated, lightweight endpoint:

`GET /api/astrodex/map` returns a flat list of geotagged pictures across all visible users, gated by its own **`config['astrodex']['map_private']`** flag (Configuration → Astrodex → "Photo map private", off by default) — deliberately **independent** from the general `config['astrodex']['private']` sharing flag used by `/api/astrodex`. When `map_private` is off (default), every shared user's pictures appear on the map with their real coordinates, even though `/api/astrodex` itself always strips other users' exact coordinates for privacy in its own merged view. This app targets small trusted deployments (family/astro-club), so exposing real-world photo locations to other users on the map is an explicit, separately-labeled opt-out rather than tied to the general sharing toggle.

---

## Shared items

When multiple users on the same instance image the same object, items are **merged** in the Astrodex view:

- Each user's pictures are listed under their own section.
- The `owner_username` field shows who added which picture.
- Users can only edit or delete their own items and pictures.
- The `is_owned_by_current_user` flag drives UI permissions.

---

## Storage and backup

- Per-user JSON file: `data/astrodex/<user_id>.json`
- Images directory: `data/astrodex/images/`
- Both are included in the **Backup / Restore** ZIP (see [CONFIGURATION.md](CONFIGURATION.md)).

### Write safety

`save_user_astrodex()` uses an atomic write pattern:
1. Write to a temporary file (`.json.tmp`)
2. Validate the temporary file's JSON
3. `os.replace()` — atomic rename on POSIX filesystems
4. Delete the backup on success; restore it on failure

Per-user write locks (`threading.Lock` per `user_id`) prevent concurrent save race conditions across Gunicorn workers.

---

## API endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/api/astrodex` | login | List all items (merged across users sharing same objects) |
| `GET` | `/api/astrodex/map` | login | Flat list of geotagged pictures for the Photo Map sub-tab, gated by its own `map_private` flag (never strips coordinates when off) |
| `POST` | `/api/astrodex/items` | login | Create a new item |
| `GET` | `/api/astrodex/items/<item_id>` | login | Get a single item |
| `PUT` | `/api/astrodex/items/<item_id>` | login | Update item fields |
| `DELETE` | `/api/astrodex/items/<item_id>` | login | Delete item and its pictures |
| `POST` | `/api/astrodex/items/<item_id>/pictures` | login | Upload a picture |
| `PUT` | `/api/astrodex/items/<item_id>/pictures/<picture_id>` | login | Update picture caption |
| `DELETE` | `/api/astrodex/items/<item_id>/pictures/<picture_id>` | login | Delete a picture |
| `POST` | `/api/astrodex/items/<item_id>/pictures/<picture_id>/main` | login | Set picture as main |
| `GET` | `/api/astrodex/images/<filename>` | login | Serve a picture file |
| `GET` | `/api/astrodex/check/<item_name>` | login | Check if name already exists |
| `GET` | `/api/astrodex/constellations` | login | List constellations in collection |
| `GET` | `/api/astrodex/catalogue-lookup` | login | Look up object in SkyTonight catalogue |
| `POST` | `/api/astrodex/items/<item_id>/catalogue-name` | login | Set canonical catalogue name |
| `POST` | `/api/astrodex/upload` | login | Upload image (alternative endpoint) |
