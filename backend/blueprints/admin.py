"""Admin operations Blueprint. Routes: /api/admin/*, /api/metrics, /api/config/export,
/api/backup/*, /api/logs/*
"""

import io
import json
import os
import time
import zipfile
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify, send_file, session, current_app

from db import legacy_import
from utils import app_settings as _app_settings
from utils import backup_archive
from utils import repo_config
from utils.auth import admin_required
from utils.constants import DATA_DIR, SKYTONIGHT_LOGS_DIR, SKYTONIGHT_SCHEDULER_STATUS_FILE
from utils.file_lock import interprocess_lock
from utils.logging_config import apply_log_retention, env_log_level, get_logger, refresh_log_levels
from utils.metrics_collector import collect_metrics

logger = get_logger(__name__)

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/api/admin/app-settings', methods=['GET'])
@admin_required
def get_app_settings_api():
    """Return current persistent app settings (excludes secret key)."""
    settings = _app_settings.get_app_settings()
    log_level, console_log_level = _app_settings.get_log_levels()
    return jsonify(
        {
            'vapid_contact_email': settings.get('vapid_contact_email', ''),
            'trust_proxy_headers': settings.get('trust_proxy_headers', False),
            'session_cookie_secure': settings.get('session_cookie_secure', False),
            'search_engine_indexing': settings.get('search_engine_indexing', False),
            'external_base_url': _app_settings.get_external_base_url(),
            'log_retention_days': _app_settings.get_log_retention_days(),
            'log_level': log_level,
            'console_log_level': console_log_level,
            # Set when an environment variable overrides the saved level
            'log_level_env': env_log_level('LOG_LEVEL'),
            'console_log_level_env': env_log_level('CONSOLE_LOG_LEVEL'),
        }
    )


@admin_bp.route('/api/admin/app-settings', methods=['POST'])
@admin_required
def update_app_settings_api():
    """Update persistent app settings. Returns requires_restart=True when proxy settings changed."""
    data = request.get_json(silent=True) or {}
    old_settings = _app_settings.get_app_settings()
    old_log_level, old_console_log_level = _app_settings.get_log_levels()

    external_base_url = _app_settings.normalize_external_base_url(
        data.get('external_base_url', old_settings.get('external_base_url', ''))
    )
    if external_base_url is None:
        return jsonify({'error': 'external_base_url must be an http(s):// address'}), 400

    new_settings = {
        'vapid_contact_email': str(
            data.get('vapid_contact_email', old_settings.get('vapid_contact_email', ''))
        ).strip(),
        'trust_proxy_headers': bool(data.get('trust_proxy_headers', old_settings.get('trust_proxy_headers', False))),
        'session_cookie_secure': bool(
            data.get('session_cookie_secure', old_settings.get('session_cookie_secure', False))
        ),
        'search_engine_indexing': bool(
            data.get('search_engine_indexing', old_settings.get('search_engine_indexing', False))
        ),
        'log_retention_days': _app_settings.normalize_log_retention_days(
            data.get('log_retention_days', old_settings.get('log_retention_days')),
            fallback=_app_settings.get_log_retention_days(),
        ),
        'log_level': _app_settings.normalize_log_level(data.get('log_level'), old_log_level),
        'console_log_level': _app_settings.normalize_log_level(data.get('console_log_level'), old_console_log_level),
        'external_base_url': external_base_url,
    }

    _app_settings.save_app_settings(new_settings)

    # Log levels apply right away in this worker; the other workers follow within seconds
    refresh_log_levels(force=True)

    # A shorter retention applies right away rather than at the next daily pass
    if new_settings['log_retention_days'] != _app_settings.normalize_log_retention_days(
        old_settings.get('log_retention_days')
    ):
        apply_log_retention(new_settings['log_retention_days'])

    # SESSION_COOKIE_SECURE can be applied live without restart
    current_app.config['SESSION_COOKIE_SECURE'] = new_settings['session_cookie_secure']

    # trust_proxy_headers requires restart (ProxyFix is applied to wsgi_app at startup)
    requires_restart = new_settings['trust_proxy_headers'] != old_settings.get('trust_proxy_headers', False)

    logger.info(
        f"App settings updated by {session.get('username', '?')}: "
        f"vapid_email={'set' if new_settings['vapid_contact_email'] else 'empty'}, "
        f"trust_proxy={new_settings['trust_proxy_headers']}, "
        f"session_secure={new_settings['session_cookie_secure']}, "
        f"search_engine_indexing={new_settings['search_engine_indexing']}, "
        f"external_base_url={new_settings['external_base_url'] or 'unset'}, "
        f"log_retention_days={new_settings['log_retention_days']}, "
        f"log_level={new_settings['log_level']}, "
        f"console_log_level={new_settings['console_log_level']}"
    )
    return jsonify({'status': 'success', 'requires_restart': requires_restart})


@admin_bp.route('/api/admin/restart', methods=['POST'])
@admin_required
def restart_app_api():
    """Gracefully restart the container process. Docker restart policy handles the relaunch."""
    import signal as _signal
    import threading

    # Capture session data before leaving the request context — threads have no context.
    username = session.get('username', '?')

    def _deferred_restart():  # pragma: no cover
        time.sleep(1.5)
        logger.info(f"Container restart requested by {username} via admin UI")
        if os.path.exists('/.dockerenv'):
            # Inside Docker: kill PID 1 (gunicorn master / container entrypoint) so the
            # container exits and Docker's restart policy brings it back up.
            # Killing only the current worker PID would just cause gunicorn to replace it.
            os.kill(1, _signal.SIGTERM)
        else:
            # Local / non-Docker run: kill the current process directly.
            os.kill(os.getpid(), _signal.SIGTERM)

    threading.Thread(target=_deferred_restart, daemon=True).start()
    return jsonify({'status': 'restarting'})


@admin_bp.route('/api/metrics', methods=['GET'])
@admin_required
def get_system_metrics():
    """
    Get comprehensive system metrics including:
    - Container/VM detection with environment info
    - CPU, memory, swap, and disk information
    - Detailed disk space per folder with gauges
    - Environment process list with CPU/memory/uptime insights
    - Network statistics
    - Platform information
    """
    try:
        metrics = collect_metrics()
        return jsonify(metrics)
    except Exception:
        logger.error("Error getting system metrics")
        return jsonify({'error': 'Failed to retrieve system metrics'}), 500


@admin_bp.route('/api/config/export', methods=['GET'])
@admin_required
def export_config_api():
    """Download the stored configuration as config.json"""
    try:
        raw = repo_config.read_raw_config()
        if raw is None:
            return jsonify({"error": "Config file not found"}), 404

        payload = io.BytesIO(json.dumps(raw, indent=2, ensure_ascii=False).encode('utf-8'))
        return send_file(payload, mimetype="application/json", as_attachment=True, download_name="config.json")

    except Exception as e:
        logger.error(f"Error exporting config: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/api/backup/download', methods=['GET'])
@admin_required
def backup_download_api():
    """
    Stream a ZIP archive of the user data: configuration, accounts, Astrodex (with pictures),
    equipment, observation log (with attachments) and wishlists, in the pre-1.7 JSON layout
    (see utils/backup_archive.py). Built in memory so no temporary file is left on disk.
    """
    try:
        buf = io.BytesIO()
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        zip_filename = f"myastroboard_backup_{timestamp}.zip"
        backup_archive.write_backup(buf)
        buf.seek(0)
        logger.info(f"Backup archive created: {zip_filename}")
        return send_file(buf, mimetype='application/zip', as_attachment=True, download_name=zip_filename)
    except Exception as e:
        logger.error(f"Error creating backup archive: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/api/backup/restore', methods=['POST'])
@admin_required
def backup_restore_api():
    """
    Restore user data from a backup ZIP produced by /api/backup/download (1.7, or 1.6 - same
    layout). Recognised entries: config.json, users.json, app_settings.json, astrodex/,
    equipments/, observation_sessions/, wishlist/. Unknown entries are silently ignored.

    Every recognised entry is parsed and validated before anything is written; the database
    part is then written in one transaction. A folder present in the archive replaces that
    whole kind of data (stale documents or pictures from the previous state do not survive);
    users.json replaces the account list (accounts absent from it are deleted with their data).

    No size cap is enforced: Astrodex portfolios containing many large astrophotography
    images can legitimately exceed hundreds of MB. The endpoint is admin-only.
    """
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    upload = request.files['file']
    if not upload.filename or not upload.filename.lower().endswith('.zip'):
        return jsonify({'error': 'Uploaded file must be a .zip archive'}), 400

    try:
        buf = io.BytesIO(upload.read())
        if not zipfile.is_zipfile(buf):
            return jsonify({'error': 'File is not a valid ZIP archive'}), 400
        buf.seek(0)

        with zipfile.ZipFile(buf, 'r') as archive:
            try:
                plan = backup_archive.plan_restore(archive)
            except backup_archive.BackupArchiveError as error:
                return jsonify({'error': str(error)}), 400
            if plan.empty:
                return (
                    jsonify(
                        {
                            'error': 'Archive contains no recognised backup entries '
                            '(expected config.json, users.json, app_settings.json, astrodex/, '
                            'equipments/ or observation_sessions/)'
                        }
                    ),
                    400,
                )
            report = backup_archive.apply_restore(archive, plan)

        if 'app_settings' in plan.settings:
            _app_settings.reload_app_settings()
            current_app.config['SESSION_COOKIE_SECURE'] = _app_settings.get_app_settings()['session_cookie_secure']
            refresh_log_levels(force=True)

        logger.info(f"Backup restore completed: {report.restored} item(s) restored, {len(report.skipped)} skipped")
        return jsonify(
            {
                'status': 'success',
                'restored': report.restored,
                'skipped': len(report.skipped),
                'message': f'{report.restored} file(s) restored successfully',
            }
        )

    except Exception as e:  # pragma: no cover
        logger.error(f"Error restoring backup: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/api/admin/database/integrity-check', methods=['POST'])
@admin_required
def database_integrity_check_api():
    """Run SQLite's integrity and foreign key checks on demand (Metrics page)."""
    try:
        from db.health import integrity_check

        return jsonify(integrity_check())
    except Exception as e:
        logger.error(f"Error checking database integrity: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/api/admin/migration-backups', methods=['GET'])
@admin_required
def get_migration_backups_api():
    """What the 1.7 upgrade left in data/backups/ (archive of the 1.6 files, report, files set aside)."""
    try:
        return jsonify(legacy_import.migration_backups_summary())
    except Exception as e:
        logger.error(f"Error reading migration backups: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/api/admin/migration-backups/report', methods=['GET'])
@admin_required
def download_migration_report_api():
    """Download the newest import report as a text file."""
    try:
        path = legacy_import.latest_report_path()
        if path is None:
            return jsonify({'error': 'No import report'}), 404
        return send_file(path, mimetype='text/plain', as_attachment=True, download_name=os.path.basename(path))
    except Exception as e:
        logger.error(f"Error sending the import report: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/api/admin/migration-backups', methods=['DELETE'])
@admin_required
def delete_migration_backups_api():
    """Delete the 1.7 upgrade leftovers. Irreversible: the archive is the only way back to 1.6."""
    try:
        removed = legacy_import.delete_migration_backups()
        logger.info(f"Admin {session.get('username')} deleted the pre-1.7 migration backups")
        return jsonify({'status': 'success', 'removed': removed})
    except Exception as e:
        logger.error(f"Error deleting migration backups: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/api/logs/export', methods=['GET'])
@admin_required
def logs_export_api():
    """
    Create and stream a ZIP archive of log files:
      - data/myastroboard.log (and rotated variants *.log.1 … *.log.5)
      - data/skytonight/logs/ (full directory)
    Built in memory - no temporary file left on disk.
    """
    # Evolutive list: each entry is (source_path, archive_folder, is_dir)
    LOG_EXPORT_ENTRIES = [
        (os.path.join(DATA_DIR, 'myastroboard.log'), 'logs', False),
        (SKYTONIGHT_LOGS_DIR, 'skytonight/logs', True),
        (SKYTONIGHT_SCHEDULER_STATUS_FILE, 'skytonight/runtime', False),
    ]
    try:
        buf = io.BytesIO()
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        zip_filename = f"myastroboard_logs_{timestamp}.zip"

        with zipfile.ZipFile(buf, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
            for source_path, arc_folder, is_dir in LOG_EXPORT_ENTRIES:
                if is_dir:
                    if os.path.isdir(source_path):
                        for root, _dirs, files in os.walk(source_path):
                            for fname in files:
                                full_path = os.path.join(root, fname)
                                rel = os.path.relpath(full_path, source_path)
                                zf.write(full_path, os.path.join(arc_folder, rel))
                else:
                    # Include rotated log files (e.g. myastroboard.log.1 … .5)
                    base_dir = os.path.dirname(source_path)
                    base_name = os.path.basename(source_path)
                    candidates = [source_path] + [os.path.join(base_dir, f"{base_name}.{i}") for i in range(1, 6)]
                    for candidate in candidates:
                        if os.path.isfile(candidate):
                            zf.write(candidate, os.path.join(arc_folder, os.path.basename(candidate)))

        buf.seek(0)
        logger.info(f"Log export archive created: {zip_filename}")
        return send_file(buf, mimetype='application/zip', as_attachment=True, download_name=zip_filename)
    except Exception as e:
        logger.error(f"Error creating log export archive: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/api/logs/level', methods=['GET'])
@admin_required
def get_log_level_api():
    """Return the active log levels of the log file and of the console"""
    from utils.logging_config import get_current_console_log_level, get_current_log_level

    refresh_log_levels()
    return jsonify({'level': get_current_log_level(), 'console_level': get_current_console_log_level()})


@admin_bp.route('/api/logs', methods=['GET'])
@admin_required
def get_logs_api():
    """Get application logs"""
    try:
        log_file = os.path.join(DATA_DIR, 'myastroboard.log')

        # Read log file if it exists
        if os.path.exists(log_file):
            with open(log_file, 'r', encoding='utf-8') as f:
                logs = f.readlines()

            # Get parameters
            limit = int(request.args.get('limit', 500))
            level = request.args.get('level', 'all').upper()
            offset = int(request.args.get('offset', 0))

            # Filter by level if specified
            if level != 'ALL':
                filtered_logs = []
                for log_line in logs:
                    if level in log_line:
                        filtered_logs.append(log_line.strip())
                logs = filtered_logs
            else:
                logs = [log.strip() for log in logs]

            # Apply pagination (limit=0 means return all)
            total_logs = len(logs)
            if limit <= 0:
                paginated_logs = logs
            else:
                start_idx = max(0, total_logs - limit - offset)
                end_idx = total_logs - offset
                paginated_logs = logs[start_idx:end_idx] if end_idx > start_idx else []

            return jsonify(
                {
                    "status": "success",
                    "logs": paginated_logs,
                    "total": total_logs,
                    "showing": len(paginated_logs),
                    "offset": offset,
                }
            )
        else:
            return jsonify(
                {
                    "status": "success",
                    "logs": [],
                    "total": 0,
                    "showing": 0,
                    "offset": 0,
                    "message": "No log file found yet",
                }
            )
    except Exception as e:  # pragma: no cover
        logger.error(f"Error reading logs: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route("/api/logs/clear", methods=["POST"])
@admin_required
def clear_logs_api():
    """Clear application log file"""
    try:
        log_file = os.path.join(DATA_DIR, "myastroboard.log")

        # If the file exists, clear it - under the log handler's own lock so it
        # cannot interleave with a rotation done by another gunicorn worker
        with interprocess_lock(log_file + ".lock"):
            if os.path.exists(log_file):
                open(log_file, "w").close()

        return jsonify({"status": "success", "message": "Logs cleared"})

    except Exception as e:
        logger.error(f"Error clearing logs: {e}")
        return jsonify({'error': 'Internal server error'}), 500
