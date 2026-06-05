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

When you add an item by name, Astrodex looks up the name in the SkyTonight catalogue alias table (`catalogue_aliases.py`) to find the canonical identifier. This allows adding "M31", "Andromeda Galaxy", "NGC 224", or "Andromeda" — and they all resolve to the same record, preventing duplicates.

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

Images are stored in `data/astrodex/images/` and served by `GET /api/astrodex/images/<filename>`.

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

### Catalogue lookup

`GET /api/astrodex/catalogue-lookup?name=<name>` queries the SkyTonight target catalogue for coordinates, type, magnitude, and angular size for a given object name. This auto-fills metadata when adding a new item.

### Constellation list

`GET /api/astrodex/constellations` returns all constellations represented in the current user's collection, useful for building the constellation filter dropdown.

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
