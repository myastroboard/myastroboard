"""Plan My Night Blueprint. Routes: /api/plan-my-night/*"""

import io
import os
import re
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from flask import Blueprint, request, jsonify, send_file

from observation import astrodex
from observation import plan_my_night
from utils.auth import login_required, user_required, get_current_user
from utils.i18n_utils import I18nManager
from utils.logging_config import get_logger
from utils.route_helpers import _resolve_active_location
from skytonight.skytonight_calculator import load_calculation_results
from astroweather.sun_phases import SunService

logger = get_logger(__name__)

plan_my_night_bp = Blueprint('plan_my_night', __name__)


def _resolve_observing_night_for_plan() -> Optional[dict]:
    """Return the nautical night window for Plan My Night.

    Uses nautical dusk/dawn (sun at -12 deg) so the observing session starts
    when bright stars, planets and clusters become visible, before full
    astronomical darkness.  Falls back to SkyTonight calculation metadata
    (astronomical window) when the location is not configured or the sun
    service fails.
    """
    location = None
    try:
        location = _resolve_active_location()
        lat = location.get('latitude')
        lon = location.get('longitude')
        tz_name = location.get('timezone')
        if lat is not None and lon is not None and tz_name:
            tz = ZoneInfo(str(tz_name))
            sun_service = SunService(latitude=float(lat), longitude=float(lon), timezone=str(tz_name))

            def _parse(time_str: str) -> Optional[datetime]:
                text = str(time_str or '').strip()
                if not text or text == 'Not found':
                    return None
                try:
                    return datetime.strptime(text, '%Y-%m-%d %H:%M').replace(tzinfo=tz)
                except ValueError:
                    return None

            report = sun_service.get_today_report()
            dusk = _parse(report.nautical_dusk)
            dawn = _parse(report.nautical_dawn)

            if dusk is None or dawn is None or dawn <= dusk:
                report_tomorrow = sun_service.get_tomorrow_report()
                dusk = _parse(report_tomorrow.nautical_dusk)
                dawn = _parse(report_tomorrow.nautical_dawn)

            if dusk is not None and dawn is not None and dawn > dusk:
                duration_hours = (dawn - dusk).total_seconds() / 3600.0
                return {
                    'start': dusk.isoformat(),
                    'end': dawn.isoformat(),
                    'duration_hours': round(duration_hours, 2),
                }
    except Exception as error:
        logger.error(f'Error resolving observing night for plan: {error}')

    # Fallback: use SkyTonight calculation metadata (astronomical window)
    try:
        calc = load_calculation_results(location.get('id') if isinstance(location, dict) else None)
        metadata = calc.get('metadata') or {}
        night_start = metadata.get('night_start')
        night_end = metadata.get('night_end')
        if not night_start or not night_end:
            return None
        start_dt = datetime.fromisoformat(night_start)
        end_dt = datetime.fromisoformat(night_end)
        duration_hours = (end_dt - start_dt).total_seconds() / 3600.0
        return {
            'start': night_start,
            'end': night_end,
            'duration_hours': round(duration_hours, 2),
        }
    except Exception as error:
        logger.error(f'Error resolving fallback night for plan: {error}')
    return None


def _enrich_plan_entries_with_astrodex_status(plan_payload: dict, user_id: str) -> dict:
    """Attach Astrodex presence flag to each plan entry for UI actions."""
    if not isinstance(plan_payload, dict):
        return plan_payload

    plan = plan_payload.get('plan')
    if not isinstance(plan, dict):
        return plan_payload

    entries = plan.get('entries', [])
    if not isinstance(entries, list):
        return plan_payload

    for entry in entries:
        if not isinstance(entry, dict):
            continue

        item_name = str(entry.get('name') or entry.get('target_name') or '').strip()
        catalogue = str(entry.get('catalogue') or '').strip()
        if item_name:
            entry['in_astrodex'] = astrodex.is_item_in_astrodex(user_id, item_name, catalogue)
        else:
            entry['in_astrodex'] = False

    return plan_payload


def _parse_duration_minutes(value: object) -> int:
    text = str(value or '').strip()
    if not text:
        return 0

    parts = text.split(':')
    if len(parts) != 2:
        return 0

    try:
        hours = int(parts[0])
        minutes = int(parts[1])
    except ValueError:
        return 0

    if hours < 0 or minutes < 0 or minutes > 59:
        return 0

    return (hours * 60) + minutes


def _format_minutes_hhmm(minutes: int) -> str:
    safe = max(0, int(minutes))
    return f"{safe // 60}h{safe % 60:02d}"


def _compute_plan_fill_metrics(plan: dict) -> dict:
    entries = plan.get('entries', []) if isinstance(plan, dict) else []
    if not isinstance(entries, list):
        entries = []

    planned_minutes = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        planned_raw = entry.get('planned_minutes')
        try:
            planned_minutes += max(0, int(str(planned_raw)))
            continue
        except (TypeError, ValueError):
            pass  # planned_minutes is not a plain integer — fall through to duration string parse
        planned_minutes += _parse_duration_minutes(entry.get('planned_duration'))

    night_start = plan_my_night._parse_datetime(plan.get('night_start')) if isinstance(plan, dict) else None
    night_end = plan_my_night._parse_datetime(plan.get('night_end')) if isinstance(plan, dict) else None
    night_minutes = 0
    if night_start and night_end and night_end > night_start:
        night_minutes = int((night_end - night_start).total_seconds() // 60)
    # Subtract start delay - usable observing window is shorter
    start_delay = max(0, int(plan.get('start_delay_minutes') or 0)) if isinstance(plan, dict) else 0
    night_minutes = max(0, night_minutes - start_delay)

    fill_percent = (planned_minutes / night_minutes) * 100.0 if night_minutes > 0 else 0.0
    overflow_minutes = max(0, planned_minutes - night_minutes)

    return {
        'planned_minutes': planned_minutes,
        'night_minutes': night_minutes,
        'fill_percent': fill_percent,
        'overflow_minutes': overflow_minutes,
    }


def _resolve_requested_language() -> str:
    requested_language = request.args.get('lang') or request.headers.get('Accept-Language', 'en')
    requested_language = str(requested_language).split(',')[0].split('-')[0].lower()
    supported_languages = I18nManager.get_supported_languages()
    return requested_language if requested_language in supported_languages else 'en'


@plan_my_night_bp.route('/api/plan-my-night/list', methods=['GET'])
@login_required
def list_plan_my_night():
    """Return per-combination plan summaries for the combination selector UI."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        from equipment import equipment_profiles as _ep

        combinations_data = _ep.load_user_combinations(user.user_id)
        own = []
        for combo in combinations_data.get('items', []):
            validity = _ep.compute_combination_validity_status(combo, user.user_id)
            own.append({**combo, **validity, 'is_own': True, 'owner_username': None})
        # Shared combinations already carry is_valid/is_disabled from load_all_shared_combinations.
        shared = [{**c, 'is_own': False} for c in _ep.load_all_shared_combinations(user.user_id)]
        all_combinations = own + shared
        states = plan_my_night.get_all_plan_states(user.user_id, user.username, all_combinations)
        return jsonify({'status': 'success', 'plans': states, 'combination_count': len(all_combinations)})
    except Exception as error:
        logger.error(f'Error listing plans: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@plan_my_night_bp.route('/api/plan-my-night', methods=['GET'])
@login_required
def get_plan_my_night():
    """Get the current user's Plan My Night payload."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        combination_id = request.args.get('combination_id') or None
        plan_payload = plan_my_night.get_plan_with_timeline(user.user_id, user.username, combination_id=combination_id)
        plan_payload = _enrich_plan_entries_with_astrodex_status(plan_payload, user.user_id)
        return jsonify(
            {
                'role': user.role,
                'can_edit': user.is_admin() or user.is_user(),
                **plan_payload,
            }
        )
    except Exception as error:
        logger.error(f'Error loading Plan My Night: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@plan_my_night_bp.route('/api/plan-my-night/targets', methods=['POST'])
@user_required
def add_target_to_plan_my_night():
    """Add a target to Plan My Night, creating the plan on first add."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        data = request.json or {}
        item_raw = data.get('item')
        item = dict(item_raw) if isinstance(item_raw, dict) else {}
        catalogue = str(data.get('catalogue') or item.get('catalogue') or '').strip()
        if not catalogue:
            return jsonify({'error': 'Catalogue is required'}), 400

        astro_night = _resolve_observing_night_for_plan()
        start_value = astro_night.get('start') if astro_night else None
        end_value = astro_night.get('end') if astro_night else None
        duration_hours = astro_night.get('duration_hours', 0.0) if astro_night else 0.0

        if not start_value or not end_value:
            return jsonify({'error': 'Night window unavailable'}), 409

        combination_id = data.get('combination_id') or None
        combination_name = str(data.get('combination_name') or '').strip() or None

        # New plans are pinned to the creator's CURRENT active location (v1.2)
        active_location = _resolve_active_location()

        success, reason, payload, entry = plan_my_night.create_or_add_target(
            user_id=user.user_id,
            username=user.username,
            item_data=item,
            catalogue=catalogue,
            night_start=start_value,
            night_end=end_value,
            duration_hours=duration_hours,
            combination_id=combination_id,
            combination_name=combination_name,
            location_id=active_location.get('id'),
            location_name=active_location.get('name'),
        )

        if not success:
            if reason == 'previous_plan_locked':
                return jsonify({'error': 'Plan belongs to previous night'}), 409
            if reason == 'invalid_night_window':
                return jsonify({'error': 'Invalid night window'}), 409
            return jsonify({'error': 'Failed to add target'}), 500

        return jsonify(
            {
                'status': 'success',
                'reason': reason,
                'entry': entry,
                'plan': plan_my_night.get_plan_with_timeline(
                    user.user_id, user.username, combination_id=combination_id
                ),
            }
        )
    except Exception as error:
        logger.error(f'Error adding target to Plan My Night: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@plan_my_night_bp.route('/api/plan-my-night', methods=['PATCH'])
@user_required
def patch_plan_my_night():
    """Update plan-level metadata (e.g. start_delay_minutes)."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        updates = request.json or {}
        combination_id = updates.pop('combination_id', None) or None
        updated = plan_my_night.update_plan_meta(user.user_id, user.username, updates, combination_id=combination_id)
        if updated is None:
            return jsonify({'error': 'Plan not found or locked'}), 404

        return jsonify(
            {
                'status': 'success',
                'plan': plan_my_night.get_plan_with_timeline(
                    user.user_id, user.username, combination_id=combination_id
                ),
            }
        )
    except Exception as error:
        logger.error(f'Error patching Plan My Night meta: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@plan_my_night_bp.route('/api/plan-my-night/targets/<entry_id>', methods=['PUT'])
@user_required
def update_plan_my_night_target(entry_id):
    """Update target planned duration or done status."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        updates = request.json or {}
        combination_id = updates.pop('combination_id', None) or None
        updated = plan_my_night.update_target(
            user.user_id, user.username, entry_id, updates, combination_id=combination_id
        )
        if not updated:
            return jsonify({'error': 'Target not found or plan locked'}), 404

        return jsonify(
            {
                'status': 'success',
                'entry': updated,
                'plan': plan_my_night.get_plan_with_timeline(
                    user.user_id, user.username, combination_id=combination_id
                ),
            }
        )
    except Exception as error:
        logger.error(f'Error updating Plan My Night target {entry_id}: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@plan_my_night_bp.route('/api/plan-my-night/targets/<entry_id>/reorder', methods=['POST'])
@user_required
def reorder_plan_my_night_target(entry_id):
    """Reorder plan targets within the current night timeline."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        data = request.json or {}
        new_index = data.get('new_index')
        if new_index is None:
            return jsonify({'error': 'new_index is required'}), 400
        combination_id = data.get('combination_id') or None

        success = plan_my_night.reorder_target(
            user.user_id, user.username, entry_id, int(new_index), combination_id=combination_id
        )
        if not success:
            return jsonify({'error': 'Failed to reorder target'}), 404

        return jsonify(
            {
                'status': 'success',
                'plan': plan_my_night.get_plan_with_timeline(
                    user.user_id, user.username, combination_id=combination_id
                ),
            }
        )
    except Exception as error:
        logger.error(f'Error reordering Plan My Night target {entry_id}: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@plan_my_night_bp.route('/api/plan-my-night/optimize', methods=['GET'])
@user_required
def optimize_plan_my_night():
    """Preview a reordering + initial delay that maximizes each target's overlap
    with its real (altitude-based) visibility window for the night."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        combination_id = request.args.get('combination_id') or None
        plan_load = plan_my_night.load_user_plan(user.user_id, user.username, combination_id=combination_id)
        plan = plan_load.get('plan')
        if not plan or not plan.get('entries'):
            return jsonify({'error': 'No plan or targets to optimize'}), 404
        if plan_my_night.get_plan_state(plan) == 'previous':
            return jsonify({'error': 'Plan belongs to previous night'}), 409

        result = plan_my_night.compute_optimized_schedule(user.user_id, user.username, combination_id=combination_id)
        if result is None:
            return jsonify({'error': 'No plan or targets to optimize'}), 404

        return jsonify({'status': 'success', **result})
    except Exception as error:
        logger.error(f'Error optimizing Plan My Night: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@plan_my_night_bp.route('/api/plan-my-night/optimize/apply', methods=['POST'])
@user_required
def apply_plan_my_night_optimization():
    """Apply a previously-previewed optimized order + initial delay to the plan."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        data = request.json or {}
        combination_id = data.get('combination_id') or None
        order = data.get('order')
        start_delay_minutes = data.get('start_delay_minutes')
        if not isinstance(order, list) or not order or start_delay_minutes is None:
            return jsonify({'error': 'order and start_delay_minutes are required'}), 400

        success = plan_my_night.apply_optimized_schedule(
            user.user_id, user.username, combination_id, order, int(start_delay_minutes)
        )
        if not success:
            return jsonify({'error': 'Failed to apply optimized schedule (plan may have changed)'}), 409

        return jsonify(
            {
                'status': 'success',
                'plan': plan_my_night.get_plan_with_timeline(
                    user.user_id, user.username, combination_id=combination_id
                ),
            }
        )
    except Exception as error:
        logger.error(f'Error applying Plan My Night optimization: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@plan_my_night_bp.route('/api/plan-my-night/targets/<entry_id>', methods=['DELETE'])
@user_required
def delete_plan_my_night_target(entry_id):
    """Delete a target from the active plan."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        combination_id = request.args.get('combination_id') or None
        success = plan_my_night.remove_target(user.user_id, user.username, entry_id, combination_id=combination_id)
        if not success:
            return jsonify({'error': 'Target not found or plan locked'}), 404

        return jsonify(
            {
                'status': 'success',
                'plan': plan_my_night.get_plan_with_timeline(
                    user.user_id, user.username, combination_id=combination_id
                ),
            }
        )
    except Exception as error:
        logger.error(f'Error deleting Plan My Night target {entry_id}: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@plan_my_night_bp.route('/api/plan-my-night/clear', methods=['DELETE'])
@user_required
def clear_plan_my_night():
    """Clear current plan so a new night plan can be created."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        combination_id = request.args.get('combination_id') or None
        if not plan_my_night.clear_plan(user.user_id, user.username, combination_id=combination_id):
            return jsonify({'error': 'Failed to clear plan'}), 500

        return jsonify({'status': 'success'})
    except Exception as error:
        logger.error(f'Error clearing Plan My Night: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@plan_my_night_bp.route('/api/plan-my-night/clear-all', methods=['DELETE'])
@user_required
def clear_all_plans_my_night():
    """Clear all per-combination plans for the current user."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        deleted = plan_my_night.clear_all_plans(user.user_id)
        return jsonify({'status': 'success', 'deleted': deleted})
    except Exception as error:
        logger.error(f'Error clearing all plans: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@plan_my_night_bp.route('/api/plan-my-night/targets/<entry_id>/add-to-astrodex', methods=['POST'])
@user_required
def add_plan_target_to_astrodex(entry_id):
    """Add an existing plan target to Astrodex if not already present."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        plan_payload = plan_my_night.get_plan_with_timeline(user.user_id, user.username)
        plan = plan_payload.get('plan') or {}
        entry = next((candidate for candidate in plan.get('entries', []) if candidate.get('id') == entry_id), None)
        if not entry:
            # Try searching across all plans if not found in default
            for file_path in plan_my_night.get_all_plan_files(user.user_id):
                tid = None
                fname = os.path.basename(file_path)
                if fname != f'{user.user_id}_plan_my_night.json':
                    tid = fname.replace(f'{user.user_id}_plan_', '').replace('.json', '')
                sub_payload = plan_my_night.load_user_plan(user.user_id, user.username, combination_id=tid)
                sub_plan = sub_payload.get('plan') or {}
                candidate = next((e for e in sub_plan.get('entries', []) if e.get('id') == entry_id), None)
                if candidate:
                    entry = candidate
                    break
        if not entry:
            return jsonify({'error': 'Target not found'}), 404

        item_name = entry.get('name', '')
        catalogue = entry.get('catalogue', '')
        if astrodex.is_item_in_astrodex(user.user_id, item_name, catalogue):
            return jsonify({'status': 'success', 'reason': 'already_in_astrodex'})

        item_data = {
            'name': item_name,
            'type': entry.get('type', 'Unknown'),
            'catalogue': catalogue,
            'constellation': entry.get('constellation', ''),
            'notes': entry.get('notes', ''),
        }

        created_item = astrodex.create_astrodex_item(user.user_id, item_data, user.username)
        if not created_item:
            return jsonify({'error': 'Failed to create Astrodex item'}), 500

        return jsonify({'status': 'success', 'reason': 'created'})
    except Exception as error:
        logger.error(f'Error adding plan target to Astrodex {entry_id}: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@plan_my_night_bp.route('/api/plan-my-night/export.csv', methods=['GET'])
@login_required
def export_plan_my_night_csv():
    """Export the current plan as CSV."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        payload = plan_my_night.get_plan_with_timeline(
            user.user_id, user.username, combination_id=request.args.get('combination_id') or None
        )
        language = _resolve_requested_language()
        i18n = I18nManager(language)
        csv_labels = {
            'order': i18n.t('plan_my_night.export_csv_order'),
            'name': i18n.t('plan_my_night.export_csv_name'),
            'catalogue': i18n.t('plan_my_night.export_csv_catalogue'),
            'target_name': i18n.t('plan_my_night.export_csv_target_name'),
            'type': i18n.t('plan_my_night.export_csv_type'),
            'constellation': i18n.t('plan_my_night.export_csv_constellation'),
            'ra': i18n.t('plan_my_night.export_csv_ra'),
            'dec': i18n.t('plan_my_night.export_csv_dec'),
            'mag': i18n.t('plan_my_night.export_csv_mag'),
            'size': i18n.t('plan_my_night.export_csv_size'),
            'observable_pct': i18n.t('plan_my_night.export_csv_observable_pct'),
            'planned_minutes': i18n.t('plan_my_night.export_csv_planned_minutes'),
            'timeline_start': i18n.t('plan_my_night.export_csv_timeline_start'),
            'timeline_end': i18n.t('plan_my_night.export_csv_timeline_end'),
            'done': i18n.t('plan_my_night.export_csv_done'),
            'done_yes': i18n.t('plan_my_night.export_csv_done_yes'),
            'done_no': i18n.t('plan_my_night.export_csv_done_no'),
        }
        csv_content = plan_my_night.serialize_plan_csv(payload, csv_labels)
        buffer = io.BytesIO(csv_content.encode('utf-8'))

        _plan_meta = payload.get('plan') or {}
        _csv_date = (_plan_meta.get('plan_date') or '').replace('-', '') or 'unknown'
        _csv_scope = re.sub(r'[^\w\-]', '_', (_plan_meta.get('combination_name') or '').strip()) or None
        _csv_name = f'plan-my-night_{_csv_date}_{_csv_scope}.csv' if _csv_scope else f'plan-my-night_{_csv_date}.csv'

        return send_file(buffer, as_attachment=True, mimetype='text/csv', download_name=_csv_name)
    except Exception as error:
        logger.error(f'Error exporting Plan My Night CSV: {error}')
        return jsonify({'error': 'Internal server error'}), 500


@plan_my_night_bp.route('/api/plan-my-night/export.pdf', methods=['GET'])
@login_required
def export_plan_my_night_pdf():
    """Export the current plan as a polished, print-friendly PDF."""
    try:
        user = get_current_user()
        if not user:  # pragma: no cover
            return jsonify({'error': 'User not authenticated'}), 401

        language = _resolve_requested_language()
        i18n = I18nManager(language)
        payload = plan_my_night.get_plan_with_timeline(
            user.user_id,
            user.username,
            combination_id=request.args.get('combination_id') or None,
        )
        metrics = _compute_plan_fill_metrics(payload.get('plan') or {})
        buffer = plan_my_night.generate_plan_pdf(payload, metrics, i18n)

        plan = payload.get('plan')
        _pdf_date = (plan.get('plan_date') or '').replace('-', '') if plan else 'unknown'
        _pdf_scope = re.sub(r'[^\w\-]', '_', (plan.get('combination_name') or '').strip()) if plan else None
        _pdf_name = f'plan-my-night_{_pdf_date}_{_pdf_scope}.pdf' if _pdf_scope else f'plan-my-night_{_pdf_date}.pdf'

        return send_file(buffer, as_attachment=True, mimetype='application/pdf', download_name=_pdf_name)
    except Exception as error:
        logger.error(f'Error exporting Plan My Night PDF: {error}')
        return jsonify({'error': 'Internal server error'}), 500
