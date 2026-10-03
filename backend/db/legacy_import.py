"""One-shot import of the pre-1.7 JSON data files into the database.

Steps, all under the bootstrap lock (see ``db/bootstrap.py``):

1. Discover the legacy files. Nothing found -> nothing to do (the normal case after 1.7).
2. Archive them all into ``DATA_DIR/backups/pre-1.7-<timestamp>.zip`` and re-read the
   archive to check it (every member present, same SHA-256). No archive, no import.
3. Read every file. An unreadable *critical* file (users, config) fails the import; an
   unreadable per-user document is quarantined under ``backups/unreadable/`` (the 1.6
   code already treated such a file as empty). A per-user file whose user id is not a
   known account is an orphan, moved to ``backups/orphans/`` and not imported.
4. Write everything in ONE transaction.
5. Read every record back from the database and compare it with the source.
6. Only then delete the legacy files. Each file's fate is recorded in ``legacy_import``,
   so a crash between 4 and 6 is finished on the next start.

Any failure before 6 rolls the transaction back and leaves every legacy file untouched;
the caller then keeps the instance in maintenance mode.
"""

import hashlib
import json
import os
import shutil
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from db import schema
from db.engine import data_dir, read, transaction
from utils.logging_config import get_logger

logger = get_logger(__name__)

BACKUPS_DIRNAME = 'backups'
ARCHIVE_PREFIX = 'pre-1.7-'
REPORT_PREFIX = 'import-report-'
# Folders the import moves files it could not import into
QUARANTINE_FOLDERS = ('orphans', 'unreadable')
# Leftovers of the 1.6 atomic-write protocol, archived and deleted with their file.
_SIDECAR_SUFFIXES = ('.backup', '.tmp')
_CORRUPTED_MARKER = '.corrupted.'


class LegacyImportError(Exception):
    """A legacy file cannot be imported; the whole import is abandoned."""


class UnreadableDocument(Exception):
    """A non-critical legacy file cannot be parsed; it is quarantined, the import goes on."""


# --- Records produced by the sources -------------------------------------------------


@dataclass
class UserRecord:
    """One account, as ``User.to_dict()`` stores it."""

    user: dict[str, Any]


@dataclass
class DocumentRecord:
    """One per-user document."""

    user_id: str
    kind: str
    data: dict[str, Any]
    doc_key: str = ''


@dataclass
class SettingRecord:
    """One install-wide setting."""

    key: str
    value: Any


Record = UserRecord | DocumentRecord | SettingRecord


@dataclass
class LegacySource:
    """One family of legacy files.

    ``discover(data_dir)`` returns absolute paths; ``convert(path)`` returns the records
    of one file. ``critical`` sources fail the import when a file cannot be read.
    """

    name: str
    discover: Callable[[str], list[str]]
    convert: Callable[[str], list[Record]]
    critical: bool = False


@dataclass
class ImportReport:
    """Outcome of :func:`run_if_needed`."""

    succeeded: bool = True
    failure: str | None = None
    archive_path: str | None = None
    imported: list[str] = field(default_factory=list)
    orphaned: list[str] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    delete_errors: list[str] = field(default_factory=list)


def _sources() -> list[LegacySource]:
    """Every registered legacy source (see db/legacy_sources.py)."""
    from db.legacy_sources import SOURCES

    return SOURCES


# --- Helpers ---------------------------------------------------------------------------


def read_json_file(path: str) -> Any:
    """Parse a legacy JSON file (UTF-8, tolerating a BOM)."""
    with open(path, encoding='utf-8-sig') as handle:
        return json.load(handle)


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(65536), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _relative(path: str, root: str) -> str:
    return os.path.relpath(path, root).replace(os.sep, '/')


def _sidecars(path: str) -> list[str]:
    """``.backup``/``.tmp``/``.corrupted.*`` leftovers next to ``path``."""
    directory, name = os.path.split(path)
    found = [path + suffix for suffix in _SIDECAR_SUFFIXES if os.path.isfile(path + suffix)]
    if os.path.isdir(directory):
        prefix = name + _CORRUPTED_MARKER
        found.extend(
            os.path.join(directory, other) for other in sorted(os.listdir(directory)) if other.startswith(prefix)
        )
    return found


def resolve_legacy_file(path: str) -> str | None:
    """The file to read for ``path``: itself, or its ``.backup`` when a 1.6 save crashed mid-way."""
    if os.path.isfile(path):
        return path
    if os.path.isfile(path + '.backup'):
        return path + '.backup'
    return None


def _known_user_ids(records: list[Record]) -> set:
    ids = {record.user['user_id'] for record in records if isinstance(record, UserRecord)}
    with read() as conn:
        ids.update(conn.execute(select(schema.users.c.user_id)).scalars())
    return ids


def _move_aside(path: str, root: str, folder: str) -> str:
    target = os.path.join(root, BACKUPS_DIRNAME, folder, _relative(path, root))
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.move(path, target)
    return target


# --- Writing and verifying -------------------------------------------------------------


def _write_record(record: Record) -> None:
    # Lazy: the stores import db, db must not import them at module level.
    from db import documents, settings_store, users_store

    if isinstance(record, UserRecord):
        users_store.insert_imported_user(record.user)
    elif isinstance(record, DocumentRecord):
        documents.put_document(record.user_id, record.kind, record.data, record.doc_key)
    else:
        settings_store.put_setting(record.key, record.value)


def _read_back(record: Record) -> Any:
    from db import documents, settings_store, users_store

    if isinstance(record, UserRecord):
        return users_store.get_user(record.user['user_id'])
    if isinstance(record, DocumentRecord):
        return documents.get_document(record.user_id, record.kind, record.doc_key)
    return settings_store.get_setting(record.key)


def _expected(record: Record) -> Any:
    if isinstance(record, UserRecord):
        return record.user
    if isinstance(record, DocumentRecord):
        return record.data
    return record.value


def _record_status(conn, rel_path: str, sha: str | None, status: str, detail: str | None = None) -> None:
    now = _now()
    values: dict[str, Any] = {'path': rel_path, 'sha256': sha, 'status': status, 'detail': detail}
    if status == 'deleted':
        values['deleted_at'] = now
    else:
        values['imported_at'] = now
    stmt = insert(schema.legacy_import).values(**values)
    update = {key: value for key, value in values.items() if key != 'path'}
    conn.execute(stmt.on_conflict_do_update(index_elements=[schema.legacy_import.c.path], set_=update))


def _previous_imports() -> dict[str, dict[str, Any]]:
    table = schema.legacy_import
    with read() as conn:
        return {row.path: {'sha256': row.sha256, 'status': row.status} for row in conn.execute(select(table))}


# --- Archive ---------------------------------------------------------------------------


def _write_archive(root: str, files: list[str]) -> str:
    backups_dir = os.path.join(root, BACKUPS_DIRNAME)
    os.makedirs(backups_dir, exist_ok=True)
    stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
    archive_path = os.path.join(backups_dir, f'{ARCHIVE_PREFIX}{stamp}.zip')
    expected = {_relative(path, root): _sha256(path) for path in files}
    with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, _relative(path, root))
    # Re-read what was written: an archive that cannot be trusted stops the import.
    with zipfile.ZipFile(archive_path, 'r') as archive:
        bad_member = archive.testzip()
        if bad_member is not None:
            raise LegacyImportError(f'archive member {bad_member} is corrupt')
        if set(archive.namelist()) != set(expected):
            raise LegacyImportError('archive does not contain every legacy file')
        for name, sha in expected.items():
            if hashlib.sha256(archive.read(name)).hexdigest() != sha:
                raise LegacyImportError(f'archive copy of {name} differs from the original')
    return archive_path


# --- Entry point -----------------------------------------------------------------------


def discover_all(root: str | None = None) -> dict[str, LegacySource]:
    """Every legacy file still on disk, mapped to its source."""
    root = root or data_dir()
    found: dict[str, LegacySource] = {}
    for source in _sources():
        for path in source.discover(root):
            found[os.path.abspath(path)] = source
    return found


def run_if_needed(root: str | None = None) -> ImportReport | None:
    """Import the legacy files still on disk; ``None`` when there were none."""
    root = root or data_dir()
    found = discover_all(root)
    if not found:
        return None
    report = ImportReport()
    try:
        _run(root, found, report)
    except Exception as error:  # every failure lands in maintenance mode, never a crash loop
        report.succeeded = False
        report.failure = str(error) or type(error).__name__
        logger.exception('Legacy JSON import failed; legacy files left untouched')
    _write_report_file(root, report)
    return report


def _run(root: str, found: dict[str, LegacySource], report: ImportReport) -> None:
    previous = _previous_imports()
    files = sorted(found)
    _refuse_files_already_migrated(root, files, previous)
    to_archive: list[str] = []
    for path in files:
        source_file = resolve_legacy_file(path)
        if source_file:
            to_archive.append(source_file)
        to_archive.extend(other for other in _sidecars(path) if other != source_file)
    report.archive_path = _write_archive(root, sorted(set(to_archive)))
    logger.info(f'Archived {len(to_archive)} legacy data file(s) to {report.archive_path}')

    records_by_file: dict[str, list[Record]] = {}
    hashes: dict[str, str] = {}
    unreadable: list[str] = []
    # Imported by an earlier start that crashed before deleting them: verified again, not rewritten.
    already_imported: set = set()
    for path in files:
        source = found[path]
        source_file = resolve_legacy_file(path)
        if source_file is None:
            continue
        rel = _relative(path, root)
        hashes[path] = _sha256(source_file)
        done = previous.get(rel)
        if done and done['status'] == 'imported':
            if done['sha256'] != hashes[path]:
                raise LegacyImportError(f'{rel} changed after it was imported; remove it or restore the database')
            already_imported.add(path)
        try:
            records_by_file[path] = source.convert(source_file)
        except UnreadableDocument as error:
            if source.critical:
                raise LegacyImportError(f'{rel}: {error}') from error
            unreadable.append(path)
            logger.warning(f'Legacy file {rel} is unreadable and will be quarantined: {error}')
        except (ValueError, OSError) as error:
            if source.critical:
                raise LegacyImportError(f'{rel}: {error}') from error
            unreadable.append(path)
            logger.warning(f'Legacy file {rel} is unreadable and will be quarantined: {error}')

    all_records = [record for records in records_by_file.values() for record in records]
    known_users = _known_user_ids(all_records)
    orphans = [
        path
        for path, records in records_by_file.items()
        if any(isinstance(record, DocumentRecord) and record.user_id not in known_users for record in records)
    ]
    for path in orphans:
        records_by_file.pop(path)

    # One transaction: users first (documents reference them), then everything else. The
    # read-back check runs inside it, so a mismatch rolls every write back.
    with transaction() as conn:
        ordered = sorted(
            (
                (path, record)
                for path, records in records_by_file.items()
                if path not in already_imported
                for record in records
            ),
            key=lambda item: 0 if isinstance(item[1], UserRecord) else 1,
        )
        for _path, record in ordered:
            _write_record(record)
        for path, records in records_by_file.items():
            for record in records:
                if _canonical(_read_back(record)) != _canonical(_expected(record)):
                    raise LegacyImportError(f'{_relative(path, root)}: data read back from the database differs')
            _record_status(conn, _relative(path, root), hashes[path], 'imported')
            report.imported.append(_relative(path, root))
    logger.info(f'Imported and verified {len(report.imported)} legacy data file(s)')

    with transaction() as conn:
        for path in orphans:
            report.orphaned.append(_relative(path, root))
            _quarantine(root, path, 'orphans')
            _record_status(conn, _relative(path, root), hashes.get(path), 'orphaned', 'unknown user id')
        for path in unreadable:
            report.unreadable.append(_relative(path, root))
            _quarantine(root, path, 'unreadable')
            _record_status(conn, _relative(path, root), hashes.get(path), 'unreadable')

    for path in records_by_file:
        rel = _relative(path, root)
        try:
            for leftover in [path] + _sidecars(path):
                if os.path.isfile(leftover):
                    os.remove(leftover)
            with transaction() as conn:
                _record_status(conn, rel, hashes[path], 'deleted')
            report.deleted.append(rel)
        except OSError as error:
            # Data is safely in the database; the next start retries the deletion.
            report.delete_errors.append(f'{rel}: {error}')
            logger.warning(f'Could not delete imported legacy file {rel}: {error}')


def _refuse_files_already_migrated(root: str, files: list[str], previous: dict[str, dict[str, Any]]) -> None:
    """Stop when legacy files reappear next to a database that already took over from them.

    That happens after going back to 1.6 (unzipping the pre-1.7 archive) and upgrading again:
    the files may be newer than the database, or older - only the operator can tell, so
    nothing is overwritten either way.
    """
    reappeared = [
        _relative(path, root) for path in files if previous.get(_relative(path, root), {}).get('status') == 'deleted'
    ]
    if reappeared:
        raise LegacyImportError(
            f"{len(reappeared)} pre-1.7 data file(s) reappeared after they were imported (e.g. {reappeared[0]}). "
            "To import them again, stop the application and delete myastroboard.db; to keep the database, "
            "delete or move the files."
        )


def _quarantine(root: str, path: str, folder: str) -> None:
    for leftover in [path] + _sidecars(path):
        if os.path.isfile(leftover):
            _move_aside(leftover, root, folder)


def _write_report_file(root: str, report: ImportReport) -> None:
    """A human-readable report next to the archive, for the operator."""
    try:
        backups_dir = os.path.join(root, BACKUPS_DIRNAME)
        os.makedirs(backups_dir, exist_ok=True)
        stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
        lines = [
            'MyAstroBoard 1.7 - import of the legacy JSON data files',
            f'Date: {_now()}',
            f"Result: {'SUCCESS' if report.succeeded else 'FAILED - legacy files left untouched'}",
        ]
        if report.failure:
            lines.append(f'Failure: {report.failure}')
        if report.archive_path:
            lines.append(f'Archive of the original files: {report.archive_path}')
        for title, items in (
            ('Imported', report.imported),
            ('Orphaned (unknown user, moved to backups/orphans/)', report.orphaned),
            ('Unreadable (moved to backups/unreadable/)', report.unreadable),
            ('Could not delete (retried on next start)', report.delete_errors),
        ):
            if items:
                lines.append(f'{title}:')
                lines.extend(f'  {item}' for item in items)
        with open(os.path.join(backups_dir, f'{REPORT_PREFIX}{stamp}.txt'), 'w', encoding='utf-8') as handle:
            handle.write('\n'.join(lines) + '\n')
    except OSError as error:
        logger.warning(f'Could not write the legacy import report: {error}')


# --- What the import left in data/backups/ (shown and deletable from the admin page) ------


def _backups_dir(root: str | None = None) -> str:
    return os.path.realpath(os.path.join(root or data_dir(), BACKUPS_DIRNAME))


def _managed_entries(backups_dir: str) -> list[str]:
    """The entries of ``backups_dir`` the import wrote: archives, reports, quarantine folders."""
    if not os.path.isdir(backups_dir):
        return []
    entries = []
    for name in sorted(os.listdir(backups_dir)):
        path = os.path.join(backups_dir, name)
        if os.path.isfile(path) and (
            (name.startswith(ARCHIVE_PREFIX) and name.endswith('.zip'))
            or (name.startswith(REPORT_PREFIX) and name.endswith('.txt'))
        ):
            entries.append(path)
        elif os.path.isdir(path) and name in QUARANTINE_FOLDERS:
            entries.append(path)
    return entries


def _files_under(path: str) -> list[str]:
    if os.path.isfile(path):
        return [path]
    return [os.path.join(folder, name) for folder, _dirs, names in os.walk(path) for name in names]


def migration_backups_summary(root: str | None = None) -> dict[str, Any]:
    """What the 1.7 upgrade left in ``data/backups/``: archives, reports, files set aside, total size."""
    backups_dir = _backups_dir(root)
    entries = _managed_entries(backups_dir)
    archives, reports, set_aside = [], [], {}
    total_size = 0
    for path in entries:
        name = os.path.basename(path)
        files = _files_under(path)
        size = sum(os.path.getsize(file) for file in files)
        total_size += size
        if name.startswith(ARCHIVE_PREFIX):
            modified = datetime.fromtimestamp(os.path.getmtime(path), UTC).isoformat()
            archives.append({'name': name, 'size': size, 'created_at': modified})
        elif name.startswith(REPORT_PREFIX):
            reports.append(name)
        else:
            set_aside[name] = len(files)
    return {
        'exists': bool(entries),
        'archives': archives,
        'reports': reports,
        'orphans': set_aside.get('orphans', 0),
        'unreadable': set_aside.get('unreadable', 0),
        'total_size': total_size,
    }


def latest_report_path(root: str | None = None) -> str | None:
    """The newest import report, or None."""
    reports = [
        path for path in _managed_entries(_backups_dir(root)) if os.path.basename(path).startswith(REPORT_PREFIX)
    ]
    return reports[-1] if reports else None


def delete_migration_backups(root: str | None = None) -> int:
    """Delete what the import left in ``data/backups/`` (and the folder once empty); return files removed.

    Only the import's own entries are touched: anything else an operator put there stays.
    """
    backups_dir = _backups_dir(root)
    removed = 0
    for path in _managed_entries(backups_dir):
        if not os.path.realpath(path).startswith(backups_dir + os.sep):  # pragma: no cover - listdir names
            continue
        removed += len(_files_under(path))
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
    if os.path.isdir(backups_dir) and not os.listdir(backups_dir):
        os.rmdir(backups_dir)
    logger.info(f'Deleted the pre-1.7 migration backups ({removed} file(s))')
    return removed
