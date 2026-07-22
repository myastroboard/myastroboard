"""Route inventory test — v1.0 API stability contract.

Fails if any route is added, removed, renamed, or changes its HTTP method.
To update intentionally: modify EXPECTED_ROUTES below and document the
breaking change in CHANGELOG_NEXT.md.
"""
import sys
import types

import pytest

if 'psutil' not in sys.modules:
    sys.modules['psutil'] = types.ModuleType('psutil')

from app import app


EXPECTED_ROUTES = {
    # --- static / pages ---
    ('/', ('GET',)),
    ('/login', ('GET',)),
    ('/manifest.webmanifest', ('GET',)),
    ('/manifest.<lang>.webmanifest', ('GET',)),
    ('/offline.html', ('GET',)),
    ('/robots.txt', ('GET',)),
    ('/static/<path:filename>', ('GET',)),
    ('/sw.js', ('GET',)),

    # --- auth ---
    ('/api/auth/change-password', ('POST',)),
    ('/api/auth/login', ('POST',)),
    ('/api/auth/logout', ('POST',)),
    ('/api/auth/preferences', ('GET',)),
    ('/api/auth/preferences', ('PUT',)),
    ('/api/auth/status', ('GET',)),

    # --- push notifications ---
    ('/api/push/subscribe', ('POST',)),
    ('/api/push/subscriptions', ('DELETE',)),
    ('/api/push/subscriptions', ('GET',)),
    ('/api/push/test', ('POST',)),
    ('/api/push/test/<trigger_id>', ('POST',)),
    ('/api/push/unsubscribe', ('DELETE',)),
    ('/api/push/vapid-config-status', ('GET',)),
    ('/api/push/vapid-public-key', ('GET',)),

    # --- users ---
    ('/api/users', ('GET',)),
    ('/api/users', ('POST',)),
    ('/api/users/<user_id>', ('DELETE',)),
    ('/api/users/<user_id>', ('PUT',)),

    # --- config ---
    ('/api/config', ('GET',)),
    ('/api/config', ('POST',)),
    ('/api/config/export', ('GET',)),

    # --- locations (multi-location profiles, v1.2 - see CHANGELOG_NEXT.md) ---
    ('/api/locations', ('GET',)),
    ('/api/locations', ('POST',)),
    ('/api/locations/<location_id>', ('PUT',)),
    ('/api/locations/<location_id>', ('DELETE',)),
    ('/api/locations/<location_id>/references', ('GET',)),
    ('/api/locations/<location_id>/attribute', ('POST',)),
    ('/api/locations/mine', ('GET',)),
    ('/api/locations/active', ('POST',)),

    # --- admin ---
    ('/api/admin/app-settings', ('GET',)),
    ('/api/admin/app-settings', ('POST',)),
    ('/api/admin/restart', ('POST',)),

    # --- system ---
    ('/api/backup/download', ('GET',)),
    ('/api/backup/restore', ('POST',)),
    ('/api/cache', ('GET',)),
    ('/api/convert-coordinates', ('POST',)),
    ('/api/health', ('GET',)),
    ('/api/logs', ('GET',)),
    ('/api/logs/clear', ('POST',)),
    ('/api/logs/export', ('GET',)),
    ('/api/logs/level', ('GET',)),
    ('/api/metrics', ('GET',)),
    ('/api/timezones', ('GET',)),
    ('/api/version', ('GET',)),
    ('/api/version/check-updates', ('GET',)),
    ('/health', ('GET',)),

    # --- weather ---
    ('/api/weather/alerts', ('GET',)),
    ('/api/weather/astro-analysis', ('GET',)),
    ('/api/weather/astro-current', ('GET',)),
    ('/api/weather/forecast', ('GET',)),

    # --- astronomy ---
    ('/api/astro/horizon-graph', ('GET',)),
    ('/api/astro/sidereal-time', ('GET',)),
    ('/api/aurora/predictions', ('GET',)),
    ('/api/moon/dark-window', ('GET',)),
    ('/api/moon/month-calendar', ('GET',)),
    ('/api/moon/next-7-nights', ('GET',)),
    ('/api/moon/next-eclipse', ('GET',)),
    ('/api/moon/report', ('GET',)),
    ('/api/object/<path:identifier>', ('GET',)),
    ('/api/seeing-forecast', ('GET',)),
    ('/api/sky-widget', ('GET',)),
    ('/api/skyquality', ('GET',)),
    ('/api/sun/next-eclipse', ('GET',)),
    ('/api/sun/today', ('GET',)),
    ('/api/tonight/best-window', ('GET',)),

    # --- events ---
    ('/api/events/phenomena', ('GET',)),
    ('/api/events/planetary', ('GET',)),
    ('/api/events/solarsystem', ('GET',)),
    ('/api/events/upcoming', ('GET',)),

    # --- ISS / spaceflight ---
    ('/api/css/celestrak/restart', ('POST',)),
    ('/api/css/location', ('GET',)),
    ('/api/css/passes', ('GET',)),
    ('/api/iss/celestrak/restart', ('POST',)),
    ('/api/iss/location', ('GET',)),
    ('/api/iss/passes', ('GET',)),
    ('/api/spaceflight/astronauts', ('GET',)),
    ('/api/spaceflight/events', ('GET',)),
    ('/api/spaceflight/img/<filename>', ('GET',)),
    ('/api/spaceflight/launch/<launch_id>/vidurls', ('GET',)),
    ('/api/spaceflight/launches', ('GET',)),

    # --- i18n ---
    ('/api/translate/on-demand', ('POST',)),

    # --- plan my night ---
    ('/api/plan-my-night', ('GET',)),
    ('/api/plan-my-night', ('PATCH',)),
    ('/api/plan-my-night/clear', ('DELETE',)),
    ('/api/plan-my-night/clear-all', ('DELETE',)),
    ('/api/plan-my-night/export.csv', ('GET',)),
    ('/api/plan-my-night/export.pdf', ('GET',)),
    ('/api/plan-my-night/list', ('GET',)),
    ('/api/plan-my-night/optimize', ('GET',)),
    ('/api/plan-my-night/optimize/apply', ('POST',)),
    ('/api/plan-my-night/targets', ('POST',)),
    ('/api/plan-my-night/targets/<entry_id>', ('DELETE',)),
    ('/api/plan-my-night/targets/<entry_id>', ('PUT',)),
    ('/api/plan-my-night/targets/<entry_id>/add-to-astrodex', ('POST',)),
    ('/api/plan-my-night/targets/<entry_id>/reorder', ('POST',)),

    # --- beginner catalog ---
    ('/api/beginner-catalog', ('GET',)),
    ('/api/object-image/<filename>', ('GET',)),

    # --- astrodex ---
    ('/api/astrodex', ('GET',)),
    ('/api/astrodex/catalogue-lookup', ('GET',)),
    ('/api/astrodex/check/<item_name>', ('GET',)),
    ('/api/astrodex/constellations', ('GET',)),
    ('/api/astrodex/images/<filename>', ('GET',)),
    ('/api/astrodex/items', ('POST',)),
    ('/api/astrodex/items/<item_id>', ('DELETE',)),
    ('/api/astrodex/items/<item_id>', ('GET',)),
    ('/api/astrodex/items/<item_id>', ('PUT',)),
    ('/api/astrodex/items/<item_id>/catalogue-name', ('POST',)),
    ('/api/astrodex/items/<item_id>/pictures', ('POST',)),
    ('/api/astrodex/items/<item_id>/pictures/<picture_id>', ('DELETE',)),
    ('/api/astrodex/items/<item_id>/pictures/<picture_id>', ('PUT',)),
    ('/api/astrodex/items/<item_id>/pictures/<picture_id>/main', ('POST',)),
    ('/api/astrodex/map', ('GET',)),
    ('/api/astrodex/upload', ('POST',)),

    # --- equipment ---
    ('/api/equipment/accessories', ('GET',)),
    ('/api/equipment/accessories', ('POST',)),
    ('/api/equipment/accessories/<accessory_id>', ('DELETE',)),
    ('/api/equipment/accessories/<accessory_id>', ('GET',)),
    ('/api/equipment/accessories/<accessory_id>', ('PUT',)),
    ('/api/equipment/cameras', ('GET',)),
    ('/api/equipment/cameras', ('POST',)),
    ('/api/equipment/cameras/<camera_id>', ('DELETE',)),
    ('/api/equipment/cameras/<camera_id>', ('GET',)),
    ('/api/equipment/cameras/<camera_id>', ('PUT',)),
    ('/api/equipment/combinations', ('GET',)),
    ('/api/equipment/combinations', ('POST',)),
    ('/api/equipment/combinations/<combination_id>', ('DELETE',)),
    ('/api/equipment/combinations/<combination_id>', ('GET',)),
    ('/api/equipment/combinations/<combination_id>', ('PUT',)),
    ('/api/equipment/filters', ('GET',)),
    ('/api/equipment/filters', ('POST',)),
    ('/api/equipment/filters/<filter_id>', ('DELETE',)),
    ('/api/equipment/filters/<filter_id>', ('GET',)),
    ('/api/equipment/filters/<filter_id>', ('PUT',)),
    ('/api/equipment/fov-calculator', ('POST',)),
    ('/api/equipment/mounts', ('GET',)),
    ('/api/equipment/mounts', ('POST',)),
    ('/api/equipment/mounts/<mount_id>', ('DELETE',)),
    ('/api/equipment/mounts/<mount_id>', ('GET',)),
    ('/api/equipment/mounts/<mount_id>', ('PUT',)),
    ('/api/equipment/summary', ('GET',)),
    ('/api/equipment/telescopes', ('GET',)),
    ('/api/equipment/telescopes', ('POST',)),
    ('/api/equipment/telescopes/<telescope_id>', ('DELETE',)),
    ('/api/equipment/telescopes/<telescope_id>', ('GET',)),
    ('/api/equipment/telescopes/<telescope_id>', ('PUT',)),

    # --- connectors ---
    ('/api/connectors', ('GET',)),
    ('/api/connectors/allsky/health', ('GET', 'POST')),
    ('/api/connectors/allsky/proxy', ('GET',)),
    ('/api/connectors/allsky/status', ('GET',)),
    ('/api/connectors/allsky/urls', ('GET',)),

    # --- skytonight (blueprint) ---
    ('/api/catalogues', ('GET',)),
    ('/api/scheduler/status', ('GET',)),
    ('/api/scheduler/trigger', ('POST',)),
    ('/api/skytonight/alttime/<target_id>', ('GET',)),
    ('/api/skytonight/data/bodies', ('GET',)),
    ('/api/skytonight/data/comets', ('GET',)),
    ('/api/skytonight/data/dso', ('GET',)),
    ('/api/skytonight/dataset/rebuild', ('POST',)),
    ('/api/skytonight/dataset/status', ('GET',)),
    ('/api/skytonight/log', ('GET',)),
    ('/api/skytonight/logs/<catalogue>', ('GET',)),
    ('/api/skytonight/logs/<catalogue>/exists', ('GET',)),
    ('/api/skytonight/recommendations', ('GET',)),
    ('/api/skytonight/reports', ('GET',)),
    ('/api/skytonight/reports/<catalogue>', ('GET',)),
    ('/api/skytonight/scheduler/status', ('GET',)),
    ('/api/skytonight/scheduler/trigger', ('POST',)),
    ('/api/skytonight/skymap', ('GET',)),
    ('/api/skytonight/target-debug', ('GET',)),
    ('/api/skytonight/combination-recommendations', ('POST',)),
}


def _actual_routes(flask_app):
    routes = set()
    for rule in flask_app.url_map.iter_rules():
        methods = tuple(sorted(m for m in rule.methods if m not in ('HEAD', 'OPTIONS')))
        if methods:
            routes.add((rule.rule, methods))
    return routes


@pytest.mark.unit
def test_no_breaking_route_changes():
    """Fails if any route is added, removed, or changes its HTTP method.

    To update intentionally: edit EXPECTED_ROUTES and document the change
    in CHANGELOG_NEXT.md.
    """
    actual = _actual_routes(app)

    added = actual - EXPECTED_ROUTES
    removed = EXPECTED_ROUTES - actual

    messages = []
    if added:
        messages.append("Routes added (not in EXPECTED_ROUTES):\n" + "\n".join(f"  {p} {m}" for p, m in sorted(added)))
    if removed:
        messages.append("Routes removed (missing from app):\n" + "\n".join(f"  {p} {m}" for p, m in sorted(removed)))

    assert not added and not removed, "\n\n" + "\n\n".join(messages)
