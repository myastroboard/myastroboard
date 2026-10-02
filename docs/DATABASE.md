# Database

Since 1.7, MyAstroBoard keeps its persistent state in one SQLite database,
`data/myastroboard.db`, instead of JSON files. This page is for operators (upgrade,
backup, recovery) and contributors (schema changes, tests).

## What is stored where

| In the database (`data/myastroboard.db`) | Still files under `data/` |
|---|---|
| Accounts, preferences, 2FA, push subscriptions | Astrodex pictures (`astrodex/images/`) |
| Astrodex, observation log, wishlist, equipment, Plan My Night plans | Session attachments (`observation_sessions/attachments/`) |
| Configuration (locations, SkyTonight, connectors) | Caches (`cache/`) and SkyTonight results (`skytonight/`) |
| App settings, security settings, connector secrets, VAPID keys, session secret key | Logs |

Caches and SkyTonight results are recomputed by the schedulers, so they stay files.

## Upgrading from 1.6

Nothing to do: on the first start of 1.7 the application

1. archives every 1.6 data file into `data/backups/pre-1.7-<date>.zip` and checks the archive,
2. imports them all into the database in a single transaction,
3. reads every record back and compares it with the original file,
4. only then deletes the JSON files,
5. writes a report next to the archive: `data/backups/import-report-<date>.txt`.

Files that cannot be imported are never lost:

- a per-user file whose account no longer exists is moved to `data/backups/orphans/`,
- an unreadable per-user file (1.6 already treated it as empty) is moved to `data/backups/unreadable/`.

If `users.json` or `config.json` cannot be read, or anything else goes wrong, nothing is
imported, no file is deleted, and the instance starts in **maintenance mode**: every page
answers "503" with an explanation, `/health` keeps answering. Check the log and the import
report, fix the cause, restart. You can also go back to the 1.6 image: your files are untouched.

### Going back to 1.6 after a successful upgrade

The migration is one-way. To return to 1.6, stop the container, unzip
`data/backups/pre-1.7-<date>.zip` into `data/` and start the 1.6 image. Anything changed
since the upgrade is not in that archive - take an Admin backup first if you need it.

### Deleting the upgrade archive

`data/backups/` is never cleaned up on its own: it is the only way back to 1.6. It also holds
sensitive data (password hashes, two-factor and connector secrets, the data of accounts
deleted since), so delete it once 1.7 is validated: **Parameters -> Backup / Restore -> 1.7
upgrade archive** shows the archive, its size and the files set aside, offers the import
report for download, and deletes it all. The section is only shown while there is something
to delete; only the files the import wrote are removed, anything else you put in
`data/backups/` stays.

## Backups

**Parameters → Backup / Restore** still produces a ZIP with the same layout as in 1.6
(`config.json`, `users.json`, `astrodex/`, `equipments/`, ...), readable with any text
editor, and restores both 1.7 and 1.6 backups. As before, the security settings, connector
secrets, VAPID keys and session key are not in it.

For a file-level copy of the whole database, stop the container first, or copy
`myastroboard.db` together with its `-wal` and `-shm` companions.

## Recovery from the command line

Hand-editing `users.json` (lost admin password, lost authenticator) is replaced by a
small command line, run inside the container as the application user:

```bash
docker exec -u appuser myastroboard python backend/db/manage.py status
docker exec -u appuser myastroboard python backend/db/manage.py list-users
docker exec -u appuser myastroboard python backend/db/manage.py reset-password admin
docker exec -u appuser myastroboard python backend/db/manage.py disable-2fa admin
```

`reset-password` prints a generated password unless `--password` is given.

## Network shares

SQLite uses a write-ahead log (WAL) that needs a local file system. On NFS or SMB the
database falls back to a slower journal mode and logs a warning at start; keep `data/` on a
local disk (the Home Assistant app always does).

## For contributors

### Layout

- `backend/db/schema.py` - table definitions (SQLAlchemy Core).
- `backend/db/migrations/versions/` - Alembic revisions, applied automatically at start
  (`db/bootstrap.py`, under a cross-process lock so only one gunicorn worker migrates).
- `backend/db/documents.py` - per-user data, as the dicts the feature modules work on
  (`load_x(user_id) -> dict` / `save_x(user_id, dict)`).
- `backend/db/collections.py` - splits those dicts into relational tables, one row per object
  (Astrodex item and picture, observation session, night, entry and attachment, wishlist item,
  piece of equipment, combination and its filters/accessories, plan and plan entry), with
  parent -> child foreign keys and indexes, and assembles them back. Each row also keeps the
  object as JSON (`data`), so a field the schema does not know yet is never lost; the other
  columns are copies used for searching.
- `backend/db/queries.py` - the searches across users (delete guards, shared equipment,
  picture visibility...) as SQL queries.
- `backend/db/settings_store.py` - install-wide settings (one JSON value per key).
- `backend/db/users_store.py` - accounts.
- `backend/db/legacy_import.py`, `legacy_sources.py`, `json_layout.py` - the 1.6 import and
  the JSON file layout shared with the backup and the personal data export.

### Writing data

- Read-modify-write goes in one `db.engine.transaction()` (`BEGIN IMMEDIATE`): it
  serializes the gunicorn workers, so no file lock is needed. Nested calls join the outer
  transaction. `documents.modify_document()` and `settings_store.modify_setting()` wrap the
  common case.
- Per-process caches compare a **store revision** (`get_revision()`), bumped in the same
  transaction as every write, to see other workers' changes - never a file mtime.
- Deleting an account (`users_store.delete_user`) deletes all of its rows in the same
  transaction; foreign keys with `ON DELETE CASCADE` back it up.
- A save rewrites the user's rows of that kind in one transaction; a natural id that appears
  twice in one list is refused (unique constraint), and the whole save rolls back.
- A new search across users belongs in `db/queries.py` (SQL on the indexed columns), never in a
  loop over every user's data.

### Changing the schema

1. Edit `backend/db/schema.py`.
2. Generate a revision, then read and fix it (SQLite needs batch mode for most `ALTER`s,
   already enabled):

   ```bash
   alembic -c backend/db/alembic.ini revision --autogenerate -m "describe the change"
   ```

3. Name the file `NNNN_<slug>.py` with the next number, set `revision = 'NNNN'`, and write a
   working `downgrade()`.
4. `pytest tests/db/` checks that upgrade/downgrade work and that the migrations match
   `schema.py`.

A data change (reshaping rows) is also a revision: use `op.get_bind()` to read and
rewrite rows inside `upgrade()`.

### Tests

Every test runs on its own copy of a template database (`tests/conftest.py`,
`isolated_database`), so tests never share state. Foreign keys are off by default there,
since most tests store data for made-up user ids; add the `enforce_foreign_keys`
fixture to a test about account deletion or cascades.
