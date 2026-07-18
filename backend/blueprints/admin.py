"""Admin operations Blueprint. Routes: /api/admin/*, /api/metrics, /api/config/export,
/api/backup/*, /api/logs/*
"""

import io
import json
import os
import shutil
import time
import zipfile
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify, send_file, session, current_app
from werkzeug.utils import secure_filename

from utils import app_settings as _app_settings
from utils.auth import admin_required
from utils.constants import CONFIG_FILE, DATA_DIR, SKYTONIGHT_LOGS_DIR, SKYTONIGHT_SCHEDULER_STATUS_FILE
from utils.logging_config import get_logger
from utils.metrics_collector import collect_metrics

logger = get_logger(__name__)

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/api/admin/app-settings', methods=['GET'])
@admin_required
def get_app_settings_api():
    """Return current persistent app settings (excludes secret key)."""
    settings = _app_settings.get_app_settings()
    return jsonify(
        {
            'vapid_contact_email': settings.get('vapid_contact_email', ''),
            'trust_proxy_headers': settings.get('trust_proxy_headers', False),
            'session_cookie_secure': settings.get('session_cookie_secure', False),
        }
    )


@admin_bp.route('/api/admin/app-settings', methods=['POST'])
@admin_required
def update_app_settings_api():
    """Update persistent app settings. Returns requires_restart=True when proxy settings changed."""
    data = request.get_json(silent=True) or {}
    old_settings = _app_settings.get_app_settings()

    new_settings = {
        'vapid_contact_email': str(
            data.get('vapid_contact_email', old_settings.get('vapid_contact_email', ''))
        ).strip(),
        'trust_proxy_headers': bool(data.get('trust_proxy_headers', old_settings.get('trust_proxy_headers', False))),
        'session_cookie_secure': bool(
            data.get('session_cookie_secure', old_settings.get('session_cookie_secure', False))
        ),
    }

    _app_settings.save_app_settings(new_settings)

    # SESSION_COOKIE_SECURE can be applied live without restart
    current_app.config['SESSION_COOKIE_SECURE'] = new_settings['session_cookie_secure']

    # trust_proxy_headers requires restart (ProxyFix is applied to wsgi_app at startup)
    requires_restart = new_settings['trust_proxy_headers'] != old_settings.get('trust_proxy_headers', False)

    logger.info(
        f"App settings updated by {session.get('username', '?')}: "
        f"vapid_email={'set' if new_settings['vapid_contact_email'] else 'empty'}, "
        f"trust_proxy={new_settings['trust_proxy_headers']}, "
        f"session_secure={new_settings['session_cookie_secure']}"
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
    """Download the raw CONFIG_FILE JSON"""
    try:
        if not os.path.isfile(CONFIG_FILE):
            return jsonify({"error": "Config file not found"}), 404

        return send_file(CONFIG_FILE, mimetype="application/json", as_attachment=True, download_name="config.json")

    except Exception as e:
        logger.error(f"Error exporting config: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@admin_bp.route('/api/backup/download', methods=['GET'])
@admin_required
def backup_download_api():
    """
    Create and stream a ZIP archive containing key user data files:
      - data/config.json
      - data/users.json
      - data/astrodex/  (full directory)
      - data/equipments/ (full directory)
    The archive is built in memory so no temporary file is left on disk.
    """
    # Evolutive list: each entry is (source_path, archive_name, is_dir)
    BACKUP_ENTRIES = [
        (os.path.join(DATA_DIR, 'config.json'), 'config.json', False),
        (os.path.join(DATA_DIR, 'users.json'), 'users.json', False),
        (os.path.join(DATA_DIR, 'app_settings.json'), 'app_settings.json', False),
        (os.path.join(DATA_DIR, 'astrodex'), 'astrodex', True),
        (os.path.join(DATA_DIR, 'equipments'), 'equipments', True),
    ]
    try:
        buf = io.BytesIO()
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        zip_filename = f"myastroboard_backup_{timestamp}.zip"

        with zipfile.ZipFile(buf, mode='w', compression=zipfile.ZIP_DEFLATED) as zf:
            for source_path, arc_name, is_dir in BACKUP_ENTRIES:
                if is_dir:
                    if os.path.isdir(source_path):
                        for root, _dirs, files in os.walk(source_path):
                            for fname in files:
                                full_path = os.path.join(root, fname)
                                rel = os.path.relpath(full_path, os.path.dirname(source_path))
                                zf.write(full_path, rel)
                else:
                    if os.path.isfile(source_path):
                        zf.write(source_path, arc_name)

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
    Restore user data from a previously created backup ZIP archive.
    The ZIP must contain the files/folders produced by /api/backup/download.
    Supported top-level entries: config.json, users.json, astrodex/, equipments/
    Unknown entries are silently ignored (forward-compatible).

    Validation performed before any write:
      1. Extension must be .zip
      2. Must be a valid ZIP magic
      3. Must contain at least one recognised entry
      4. JSON files (config.json, users.json) must be valid JSON

    No size cap is enforced: Astrodex portfolios containing many large
    astrophotography images can legitimately exceed hundreds of MB.  The
    endpoint is admin-only and operates on the user's own data.

    Restore is atomic per directory:
      - astrodex/ and equipments/ are cleared before the new files are written
        so stale files from the previous state do not survive the restore.
      - config.json and users.json are written directly (they are complete files).
    """
    # Evolutive allow-list: archive paths that are accepted during restore
    # Format: normalized_prefix -> destination base path
    # Entries whose value is a directory will have that directory cleared first.
    RESTORE_ALLOWED_PREFIXES = {
        'config.json': os.path.join(DATA_DIR, 'config.json'),
        'users.json': os.path.join(DATA_DIR, 'users.json'),
        'app_settings.json': os.path.join(DATA_DIR, 'app_settings.json'),
        'astrodex': os.path.join(DATA_DIR, 'astrodex'),
        'equipments': os.path.join(DATA_DIR, 'equipments'),
    }
    # Directories that must be cleared before restoring their contents
    RESTORE_CLEAR_DIRS = {'astrodex', 'equipments'}
    # JSON files whose content must be valid JSON
    RESTORE_VALIDATE_JSON = {'config.json', 'users.json', 'app_settings.json'}

    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    upload = request.files['file']
    if not upload.filename or not upload.filename.lower().endswith('.zip'):
        return jsonify({'error': 'Uploaded file must be a .zip archive'}), 400

    try:
        raw = upload.read()
        buf = io.BytesIO(raw)
        if not zipfile.is_zipfile(buf):
            return jsonify({'error': 'File is not a valid ZIP archive'}), 400
        buf.seek(0)

        # --- Phase 1: validation (no writes yet) ---
        recognised_entries = []  # (info, top_prefix, arc_path, rel_parts)
        json_blobs = {}  # arc_path -> bytes  (only for JSON-validated files)

        with zipfile.ZipFile(buf, 'r') as zf:
            for info in zf.infolist():
                arc_path = info.filename.replace('\\', '/').lstrip('/')

                if arc_path.endswith('/'):
                    continue  # directory entry

                # Match against allow-list; sanitize each path component with secure_filename
                # so no tainted data from the ZIP flows into the destination path.
                top_prefix = None
                rel_parts = []
                for prefix in RESTORE_ALLOWED_PREFIXES:
                    if arc_path == prefix or arc_path.startswith(prefix + '/'):
                        top_prefix = prefix
                        rel = arc_path[len(prefix) :].lstrip('/')
                        if rel:
                            parts = [secure_filename(p) for p in rel.split('/') if p]
                            if not all(parts):  # reject if any component empty after sanitization
                                top_prefix = None
                                continue
                            rel_parts = parts
                        break

                if top_prefix is None:
                    continue  # silently skip unrecognised entries

                # Validate JSON content before accepting
                if arc_path in RESTORE_VALIDATE_JSON:
                    blob = zf.read(info.filename)
                    try:
                        json.loads(blob)
                    except Exception:
                        return jsonify({'error': f'{arc_path} is not valid JSON - archive may be corrupt'}), 400
                    json_blobs[arc_path] = blob

                recognised_entries.append((info, top_prefix, arc_path, rel_parts))

        if not recognised_entries:
            return (
                jsonify(
                    {
                        'error': 'Archive contains no recognised backup entries '
                        '(expected config.json, users.json, app_settings.json, astrodex/ or equipments/)'
                    }
                ),
                400,
            )

        # --- Phase 2: clear target directories ---
        buf.seek(0)
        cleared_dirs = set()
        for _info, top_prefix, _arc_path, _rel_parts in recognised_entries:
            if top_prefix in RESTORE_CLEAR_DIRS and top_prefix not in cleared_dirs:
                # Derive target_dir from the static allowlist (breaks the user-data taint chain)
                target_dir = os.path.abspath(RESTORE_ALLOWED_PREFIXES[top_prefix])
                if os.path.isdir(target_dir):
                    shutil.rmtree(target_dir)
                os.makedirs(target_dir, exist_ok=True)
                cleared_dirs.add(top_prefix)
                logger.info(f"Restore: cleared directory {target_dir}")

        # --- Phase 3: write files ---
        restored_files = []
        skipped_files = []

        with zipfile.ZipFile(buf, 'r') as zf:
            for info, top_prefix, arc_path, rel_parts in recognised_entries:
                # Reconstruct destination entirely from trusted sources - no tainted data used
                base_dest = os.path.abspath(RESTORE_ALLOWED_PREFIXES[top_prefix])
                safe_dest = os.path.join(base_dest, *rel_parts) if rel_parts else base_dest
                os.makedirs(os.path.dirname(safe_dest), exist_ok=True)

                if arc_path in json_blobs:
                    # Already read and validated - write directly
                    with open(safe_dest, 'wb') as dst:
                        dst.write(json_blobs[arc_path])
                else:
                    with zf.open(info) as src, open(safe_dest, 'wb') as dst:
                        shutil.copyfileobj(src, dst)
                restored_files.append(arc_path)

        # Reload app_settings cache if it was part of the restore
        if any('app_settings.json' in f for f in restored_files):
            _app_settings.reload_app_settings()
            current_app.config['SESSION_COOKIE_SECURE'] = _app_settings.get_app_settings()['session_cookie_secure']

        logger.info(
            f"Backup restore completed: {len(restored_files)} files restored, "
            f"{len(skipped_files)} skipped, dirs cleared: {sorted(cleared_dirs)}"
        )
        return jsonify(
            {
                'status': 'success',
                'restored': len(restored_files),
                'skipped': len(skipped_files),
                'message': f'{len(restored_files)} file(s) restored successfully',
            }
        )

    except Exception as e:  # pragma: no cover
        logger.error(f"Error restoring backup: {e}")
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
    """Return the current active log level for the file handler"""
    from utils.logging_config import get_current_log_level

    return jsonify({'level': get_current_log_level()})


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

        # If the file exists, clear it
        if os.path.exists(log_file):
            open(log_file, "w").close()

        return jsonify({"status": "success", "message": "Logs cleared"})

    except Exception as e:
        logger.error(f"Error clearing logs: {e}")
        return jsonify({'error': 'Internal server error'}), 500
