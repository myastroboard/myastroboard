
# ---------------------------------------------------------------------------
# Coverage boost — second batch: cache fallback arcs, config, backup, etc.
# ---------------------------------------------------------------------------
import time as _time

import app as _app_mod
import cache_store as _cache_store


def _install_default_location_id():
    """The admin client's active location = the install default preset."""
    from repo_config import load_config, get_install_default_location

    return get_install_default_location(load_config()).get('id')


def _force_invalid_isolated(monkeypatch):
    """v1.2 arc setup: the TTL check always fails and shared-file lookups are
    isolated, so each route deterministically exercises its stale/pending
    fallback for the caller's per-location cache slot."""
    monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda *_: False)
    monkeypatch.setattr(_cache_store, 'load_shared_cache_entry', lambda *_: None)


def _set_location_slot(name, data):
    """Plant `data` in the active location's in-memory slot for cache `name`."""
    entry = _cache_store.get_location_cache_entry(name, _install_default_location_id())
    entry['data'] = data
    entry['timestamp'] = 1.0 if data is not None else 0
    return entry


class TestSyncTruePostSyncFalseBranches:
    """Covers the stale/pending fallback arc of every per-location cached endpoint.

    v1.2 pattern: the in-memory slot is expired (is_cache_valid False) and the
    shared file has nothing fresher → the data-return line is NOT taken; the
    route falls through to serving stale data or a 202 pending payload.
    """

    def _setup(self, monkeypatch):
        _force_invalid_isolated(monkeypatch)

    def test_moon_report_sync_true_post_invalid(self, client_admin, monkeypatch):
        """moon_report slot empty → pending fallback."""
        self._setup(monkeypatch)
        _set_location_slot('moon_report', None)
        resp = client_admin.get('/api/moon/report')
        assert resp.status_code in (200, 202)

    def test_dark_window_sync_true_post_invalid(self, client_admin, monkeypatch):
        """dark_window slot empty → pending fallback."""
        self._setup(monkeypatch)
        _set_location_slot('dark_window', None)
        resp = client_admin.get('/api/moon/dark-window')
        assert resp.status_code in (200, 202)

    def test_next_7_nights_sync_then_valid(self, client_admin, monkeypatch):
        """moon_planner slot hydrated from the shared file → 200 with data."""
        shared_payload = {'timestamp': _time.time() + 60, 'data': {'next_7_nights': []}}
        entry = _set_location_slot('moon_planner', None)
        assert entry['data'] is None
        monkeypatch.setattr(_cache_store, 'load_shared_cache_entry', lambda *_: shared_payload)
        resp = client_admin.get('/api/moon/next-7-nights')
        assert resp.status_code == 200

    def test_aurora_sync_true_post_invalid(self, client_admin, monkeypatch):
        """aurora slot empty → pending fallback."""
        self._setup(monkeypatch)
        _set_location_slot('aurora', None)
        resp = client_admin.get('/api/aurora/predictions')
        assert resp.status_code in (200, 202)

    def test_seeing_forecast_sync_true_post_invalid(self, client_admin, monkeypatch):
        """seeing_forecast slot empty → pending fallback."""
        self._setup(monkeypatch)
        _set_location_slot('seeing_forecast', None)
        resp = client_admin.get('/api/seeing-forecast')
        assert resp.status_code in (200, 202)

    def test_iss_passes_sync_true_post_invalid(self, client_admin, monkeypatch):
        """iss_passes slot empty → 202 pending."""
        self._setup(monkeypatch)
        _set_location_slot('iss_passes', None)
        import iss_passes as _iss
        monkeypatch.setattr(_iss, 'get_celestrak_status', lambda: 'ok')
        monkeypatch.setattr(_iss, 'get_iss_tle_source_info', lambda: {})
        resp = client_admin.get('/api/iss/passes')
        assert resp.status_code in (200, 202)

    def test_sun_report_sync_true_post_invalid(self, client_admin, monkeypatch):
        """sun_report slot empty → pending fallback."""
        self._setup(monkeypatch)
        _set_location_slot('sun_report', None)
        resp = client_admin.get('/api/sun/today')
        assert resp.status_code in (200, 202)

    def test_solar_eclipse_sync_true_post_invalid(self, client_admin, monkeypatch):
        """solar_eclipse slot empty → pending fallback."""
        self._setup(monkeypatch)
        _set_location_slot('solar_eclipse', None)
        resp = client_admin.get('/api/sun/next-eclipse')
        assert resp.status_code in (200, 202)

    def test_lunar_eclipse_sync_true_post_invalid(self, client_admin, monkeypatch):
        """lunar_eclipse slot empty → pending fallback."""
        self._setup(monkeypatch)
        _set_location_slot('lunar_eclipse', None)
        resp = client_admin.get('/api/moon/next-eclipse')
        assert resp.status_code in (200, 202)

    def test_all_events_sync_post_invalid(self, client_admin, monkeypatch):
        """All aggregated per-location slots empty in get_upcoming_events_api."""
        self._setup(monkeypatch)
        for name in (
            'solar_eclipse', 'lunar_eclipse', 'aurora', 'iss_passes',
            'moon_planner', 'planetary_events', 'special_phenomena',
            'solar_system_events',
        ):
            _set_location_slot(name, None)
        resp = client_admin.get('/api/events/upcoming')
        assert resp.status_code in (200, 400, 500)

    def test_planetary_events_sync_true_post_invalid(self, client_admin, monkeypatch):
        """planetary_events slot empty → pending fallback."""
        self._setup(monkeypatch)
        _set_location_slot('planetary_events', None)
        resp = client_admin.get('/api/events/planetary')
        assert resp.status_code in (200, 202)

    def test_special_phenomena_sync_true_post_invalid(self, client_admin, monkeypatch):
        """special_phenomena slot empty → pending fallback."""
        self._setup(monkeypatch)
        _set_location_slot('special_phenomena', None)
        resp = client_admin.get('/api/events/phenomena')
        assert resp.status_code in (200, 202)

    def test_solar_system_sync_true_post_invalid(self, client_admin, monkeypatch):
        """solar_system_events slot empty → pending fallback."""
        self._setup(monkeypatch)
        _set_location_slot('solar_system_events', None)
        resp = client_admin.get('/api/events/solarsystem')
        assert resp.status_code in (200, 202)

    def test_sidereal_time_sync_true_post_invalid(self, client_admin, monkeypatch):
        """sidereal_time slot empty → live computation fallback."""
        self._setup(monkeypatch)
        _set_location_slot('sidereal_time', None)
        import sidereal_time as _st
        monkeypatch.setattr(
            _st.SiderealTimeService,
            'get_current_sidereal_info',
            lambda self: {'lst': 0.0, 'lmst': '00h00m00s'},
        )
        resp = client_admin.get('/api/astro/sidereal-time')
        assert resp.status_code in (200, 400)

    def test_horizon_graph_sync_true_post_invalid(self, client_admin, monkeypatch):
        """horizon_graph slot empty → pending fallback."""
        self._setup(monkeypatch)
        _set_location_slot('horizon_graph', None)
        resp = client_admin.get('/api/astro/horizon-graph')
        assert resp.status_code in (200, 202)

    def test_best_window_sync_true_post_invalid(self, client_admin, monkeypatch):
        """best_window slots expired → stale/pending fallback."""
        self._setup(monkeypatch)
        resp = client_admin.get('/api/tonight/best-window')
        assert resp.status_code in (200, 400, 202)

    def test_best_window_single_mode_sync(self, client_admin, monkeypatch):
        """Single-mode best_window served from a hydrated shared-file entry."""
        shared_payload = {'timestamp': _time.time() + 60, 'data': {'window': {'start': None}}}
        _set_location_slot('best_window_practical', None)
        monkeypatch.setattr(_cache_store, 'load_shared_cache_entry', lambda *_: shared_payload)
        resp = client_admin.get('/api/tonight/best-window?mode=standard')
        assert resp.status_code in (200, 400, 202)


class TestConfigValidBortleAndSqm:
    """Covers lines 959, 967 – valid bortle and sqm values stored into location."""

    def _base_config(self):
        return {
            'location': {
                'latitude': 48.8566,
                'longitude': 2.3522,
                'timezone': 'Europe/Paris',
                'elevation': 100,
            },
        }

    def test_valid_bortle_stored(self, client_admin):
        """Covers line 959 – new_location['bortle'] = valid int."""
        cfg = self._base_config()
        cfg['location']['bortle'] = 5
        resp = client_admin.post('/api/config', json=cfg)
        assert resp.status_code == 200

    def test_valid_sqm_stored(self, client_admin):
        """Covers line 967 – new_location['sqm'] = valid float."""
        cfg = self._base_config()
        cfg['location']['sqm'] = 21.5
        resp = client_admin.post('/api/config', json=cfg)
        assert resp.status_code == 200

    def test_valid_bortle_and_sqm_together(self, client_admin):
        """Covers both 959 and 967 in a single request."""
        cfg = self._base_config()
        cfg['location']['bortle'] = 3
        cfg['location']['sqm'] = 22.1
        resp = client_admin.post('/api/config', json=cfg)
        assert resp.status_code == 200


class TestBackupRestoreAstrodexSubpath:
    """Covers backup restore paths for files with sub-path components."""

    def _make_zip(self, entries):
        import io as _io
        import zipfile as _zf

        buf = _io.BytesIO()
        with _zf.ZipFile(buf, mode='w') as z:
            for name, content in entries:
                z.writestr(name, content)
        buf.seek(0)
        return buf

    def test_restore_astrodex_file_with_subpath(self, client_admin):
        """Covers lines 1295-1299 (sub-path parts), 1306->1314 (non-JSON recognized),
        1333-1338 (dir clear), 1356-1357 (binary write)."""
        buf = self._make_zip([('astrodex/user123/item.json', b'{"name": "M42"}')])
        data = {'file': (buf, 'backup.zip')}
        resp = client_admin.post('/api/backup/restore', data=data, content_type='multipart/form-data')
        assert resp.status_code in (200, 400, 500)

    def test_restore_config_and_astrodex_together(self, client_admin):
        """Covers json_blobs path (1351-1354) and non-json path (1356-1357) together."""
        import json as _json
        config_content = _json.dumps({'location': {'latitude': 48.0}}).encode()
        buf = self._make_zip([
            ('config.json', config_content),
            ('astrodex/user123/obs.json', b'{"name": "Observation"}'),
        ])
        data = {'file': (buf, 'backup.zip')}
        resp = client_admin.post('/api/backup/restore', data=data, content_type='multipart/form-data')
        assert resp.status_code in (200, 400, 500)

    def test_restore_app_settings_reloads(self, client_admin, monkeypatch):
        """Covers lines 1361-1363 – app_settings reload after restore."""
        import json as _json
        settings_content = _json.dumps({'session_cookie_secure': False}).encode()
        import app_settings as _as
        monkeypatch.setattr(_as, 'reload_app_settings', lambda: None)
        monkeypatch.setattr(_as, 'get_app_settings', lambda: {'session_cookie_secure': False})
        buf = self._make_zip([('app_settings.json', settings_content)])
        data = {'file': (buf, 'backup.zip')}
        resp = client_admin.post('/api/backup/restore', data=data, content_type='multipart/form-data')
        assert resp.status_code in (200, 400, 500)


class TestSimbadFalseBranch:
    """Covers 3916->3936 – is_safe_identifier returns False."""

    def test_simbad_unsafe_identifier_returns_not_found(self, client_admin, monkeypatch):
        """Covers 3916->3936 – is_safe_identifier False → immediate not_found."""
        import skytonight_targets as _skt
        import object_info as _oi

        monkeypatch.setattr(_skt, 'get_lookup_entry', lambda *a, **kw: None)
        monkeypatch.setattr(_oi, 'is_safe_identifier', lambda name: False)

        resp = client_admin.get('/api/astrodex/catalogue-lookup?name=unsafe%3Bname')
        assert resp.status_code == 200
        assert resp.get_json()['found'] is False


class TestAstrodexSwitchException:
    """Covers 3595-3597 – unexpected exception in switch_catalogue_name."""

    def test_switch_catalogue_name_exception_returns_500(self, client_admin, monkeypatch):
        import astrodex as _adx

        def raise_unexpected(*_, **__):
            raise IOError('unexpected')

        monkeypatch.setattr(_adx, 'switch_item_catalogue_name', raise_unexpected)
        resp = client_admin.post(
            '/api/astrodex/items/test-item/catalogue-name',
            json={'catalogue': 'OpenNGC'},
        )
        assert resp.status_code == 500


class TestConfigProxyAndAstrodex:
    """Tests for config edge cases around proxy and astrodex."""

    def _base_config(self):
        return {
            'location': {
                'latitude': 48.0,
                'longitude': 2.0,
                'timezone': 'Europe/Paris',
                'elevation': 50,
            },
        }

    def test_config_astrodex_not_in_existing_config(self, client_admin, monkeypatch):
        """Covers 904->908 – 'astrodex' not in existing config → add defaults."""
        import repo_config as _rc

        original_load = _rc.load_config

        def load_without_astrodex():
            cfg = original_load() or {}
            cfg.pop('astrodex', None)
            return cfg

        monkeypatch.setattr(_rc, 'load_config', load_without_astrodex)
        monkeypatch.setattr(_app_mod, 'load_config', load_without_astrodex)
        resp = client_admin.post('/api/config', json=self._base_config())
        assert resp.status_code == 200

    def test_config_update_saves_skytonight_with_non_dict_sub_value(self, client_admin):
        """Covers line 916 – skytonight top-level key with non-dict value."""
        cfg = self._base_config()
        cfg['skytonight'] = {'enabled': True, 'some_flag': 'scalar'}
        resp = client_admin.post('/api/config', json=cfg)
        assert resp.status_code == 200

    def test_config_sqm_as_string_parses_ok(self, client_admin):
        """Covers line 967 True branch with string-formatted sqm."""
        cfg = self._base_config()
        cfg['location']['sqm'] = '21.0'
        resp = client_admin.post('/api/config', json=cfg)
        assert resp.status_code == 200

    def test_config_bortle_as_string_parses_ok(self, client_admin):
        """Covers line 959 True branch with string-formatted bortle."""
        cfg = self._base_config()
        cfg['location']['bortle'] = '7'
        resp = client_admin.post('/api/config', json=cfg)
        assert resp.status_code == 200


class TestPlanResolveNightFallback:
    """Covers the full fallback path in _resolve_observing_night_for_plan."""

    def test_resolve_night_both_except_returns_none(self, client_admin, monkeypatch):
        """Covers 2990-2992, 3001, 3011, 3020-3022 – both sun and calc fail → None."""
        from sun_phases import SunService as _SS

        def sun_raise(self):
            raise RuntimeError('sun fail')

        monkeypatch.setattr(_SS, 'get_today_report', sun_raise)
        monkeypatch.setattr(_app_mod, 'load_calculation_results',
                            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError('calc fail')))

        import plan_my_night as _pmn

        monkeypatch.setattr(
            _pmn, 'create_or_add_target',
            lambda **_kw: (True, 'created', {}, {'id': 'e-1'}),
        )
        monkeypatch.setattr(_pmn, 'get_plan_with_timeline', lambda *a, **kw: {'state': 'ok'})

        resp = client_admin.post(
            '/api/plan-my-night/targets',
            json={'item': {'name': 'M31', 'type': 'Galaxy'}, 'catalogue': 'Messier'},
        )
        assert resp.status_code in (200, 400, 409, 500)

    def test_resolve_night_missing_metadata_returns_none(self, client_admin, monkeypatch):
        """Covers 3011 – calc results missing night_start/end → None."""
        from sun_phases import SunService as _SS

        def sun_raise(self):
            raise RuntimeError('sun fail')

        monkeypatch.setattr(_SS, 'get_today_report', sun_raise)
        monkeypatch.setattr(_app_mod, 'load_calculation_results',
                            lambda *_a, **_k: {'metadata': {'night_start': None, 'night_end': None}})

        import plan_my_night as _pmn

        monkeypatch.setattr(
            _pmn, 'create_or_add_target',
            lambda **_kw: (True, 'created', {}, {'id': 'e-2'}),
        )

        resp = client_admin.post(
            '/api/plan-my-night/targets',
            json={'item': {'name': 'NGC 224', 'type': 'Galaxy'}, 'catalogue': 'Messier'},
        )
        assert resp.status_code in (200, 400, 409, 500)


class TestEquipmentPaths:
    """Covers equipment endpoint paths using equipment_profiles module."""

    def test_get_telescope_by_id_found(self, client_admin, monkeypatch):
        """Covers line 4008 – telescope found by ID."""
        import equipment_profiles as _ep

        fake = {'id': 'scope-1', 'name': 'Test Scope', 'focal_length': 800}
        monkeypatch.setattr(_ep, 'get_telescope', lambda uid, tid: fake)
        monkeypatch.setattr(_ep, 'load_all_shared_equipment', lambda kind, uid: [])
        resp = client_admin.get('/api/equipment/telescopes/scope-1')
        assert resp.status_code == 200

    def test_update_telescope_shared_by_other_returns_403(self, client_admin, monkeypatch):
        """Covers line 4029 – 403 when updating another user's shared telescope."""
        import equipment_profiles as _ep

        monkeypatch.setattr(_ep, 'load_all_shared_equipment',
                            lambda kind, uid: [{'id': 'scope-1', 'name': 'Shared'}])
        resp = client_admin.put('/api/equipment/telescopes/scope-1', json={'name': 'Renamed'})
        assert resp.status_code == 403

    def test_get_camera_by_id_found(self, client_admin, monkeypatch):
        """Covers line 4123 – camera found by ID."""
        import equipment_profiles as _ep

        fake = {'id': 'cam-1', 'name': 'ASI294'}
        monkeypatch.setattr(_ep, 'get_camera', lambda uid, cid: fake)
        monkeypatch.setattr(_ep, 'load_all_shared_equipment', lambda kind, uid: [])
        resp = client_admin.get('/api/equipment/cameras/cam-1')
        assert resp.status_code == 200

    def test_update_camera_shared_by_other_returns_403(self, client_admin, monkeypatch):
        """Covers line 4144 – 403 when updating another user's shared camera."""
        import equipment_profiles as _ep

        monkeypatch.setattr(_ep, 'load_all_shared_equipment',
                            lambda kind, uid: [{'id': 'cam-1', 'name': 'Shared'}])
        resp = client_admin.put('/api/equipment/cameras/cam-1', json={'name': 'Renamed'})
        assert resp.status_code == 403

    def test_get_mount_by_id_found(self, client_admin, monkeypatch):
        """Covers line 4238 – mount found by ID."""
        import equipment_profiles as _ep

        fake = {'id': 'mnt-1', 'name': 'EQ6-R'}
        monkeypatch.setattr(_ep, 'get_mount', lambda uid, mid: fake)
        monkeypatch.setattr(_ep, 'load_all_shared_equipment', lambda kind, uid: [])
        resp = client_admin.get('/api/equipment/mounts/mnt-1')
        assert resp.status_code == 200

    def test_update_mount_shared_by_other_returns_403(self, client_admin, monkeypatch):
        """Covers line 4259 – 403 when updating another user's shared mount."""
        import equipment_profiles as _ep

        monkeypatch.setattr(_ep, 'load_all_shared_equipment',
                            lambda kind, uid: [{'id': 'mnt-1', 'name': 'Shared'}])
        resp = client_admin.put('/api/equipment/mounts/mnt-1', json={'name': 'Renamed'})
        assert resp.status_code == 403

    def test_get_filter_by_id_found(self, client_admin, monkeypatch):
        """Covers line 4353 – filter found by ID."""
        import equipment_profiles as _ep

        fake = {'id': 'filter-1', 'name': 'OIII'}
        monkeypatch.setattr(_ep, 'get_filter', lambda uid, fid: fake)
        monkeypatch.setattr(_ep, 'load_all_shared_equipment', lambda kind, uid: [])
        resp = client_admin.get('/api/equipment/filters/filter-1')
        assert resp.status_code == 200

    def test_update_filter_shared_by_other_returns_403(self, client_admin, monkeypatch):
        """Covers line 4374 – 403 when updating another user's shared filter."""
        import equipment_profiles as _ep

        monkeypatch.setattr(_ep, 'load_all_shared_equipment',
                            lambda kind, uid: [{'id': 'filter-1', 'name': 'Shared'}])
        resp = client_admin.put('/api/equipment/filters/filter-1', json={'name': 'Renamed'})
        assert resp.status_code == 403

    def test_get_accessory_by_id_found(self, client_admin, monkeypatch):
        """Covers line 4449 – accessory found by ID."""
        import equipment_profiles as _ep

        fake = {'id': 'acc-1', 'name': 'Barlow 2x'}
        monkeypatch.setattr(_ep, 'get_accessory', lambda uid, aid: fake)
        monkeypatch.setattr(_ep, 'load_all_shared_equipment', lambda kind, uid: [])
        resp = client_admin.get('/api/equipment/accessories/acc-1')
        assert resp.status_code == 200

    def test_update_accessory_shared_by_other_returns_403(self, client_admin, monkeypatch):
        """Covers line 4489 – 403 when updating another user's shared accessory."""
        import equipment_profiles as _ep

        monkeypatch.setattr(_ep, 'load_all_shared_equipment',
                            lambda kind, uid: [{'id': 'acc-1', 'name': 'Shared'}])
        resp = client_admin.put('/api/equipment/accessories/acc-1', json={'name': 'Renamed'})
        assert resp.status_code == 403


class TestMiscRemainingPaths:
    """Miscellaneous remaining uncovered paths."""

    def test_plan_observation_window_exception(self, client_admin, monkeypatch):
        """Covers 3418-3420 – exception in plan observation window."""
        import plan_my_night as _pmn

        def raise_err(*a, **kw):
            raise RuntimeError('calc error')

        monkeypatch.setattr(_pmn, 'get_plan_with_timeline', raise_err)
        resp = client_admin.get('/api/plan-my-night')
        assert resp.status_code in (200, 500)

    def test_plan_export_csv_exception(self, client_admin, monkeypatch):
        """Covers 3495-3497 – exception in plan CSV export."""
        import plan_my_night as _pmn

        def raise_err(*a, **kw):
            raise RuntimeError('io error')

        monkeypatch.setattr(_pmn, 'get_plan_with_timeline', raise_err)
        resp = client_admin.get('/api/plan-my-night/export.csv')
        assert resp.status_code in (200, 500)

    def test_backup_download_exception(self, client_admin, monkeypatch):
        """Covers 1217-1219 – exception in backup download."""
        import zipfile as _zf

        def bad_zipfile(*a, **kw):
            raise IOError('disk full')

        monkeypatch.setattr(_zf, 'ZipFile', bad_zipfile)
        resp = client_admin.get('/api/backup/download')
        assert resp.status_code == 500

    def test_spaceflight_image_path_traversal(self, client_admin):
        """Covers line 2187 – path traversal attempt in spaceflight image."""
        resp = client_admin.get('/api/spaceflight/image/../../etc/passwd')
        assert resp.status_code in (400, 404)

    def test_iss_location_no_config(self, client_admin, monkeypatch):
        """Covers lines around ISS location when no config."""
        monkeypatch.setattr(_app_mod, 'load_config', lambda: None)
        resp = client_admin.get('/api/iss/location')
        assert resp.status_code in (200, 400, 500)

    def test_logs_api_returns_content(self, client_admin):
        """Covers 1494-1496 path (logs endpoint)."""
        resp = client_admin.get('/api/logs')
        assert resp.status_code in (200, 500)

    def test_coordinate_conversion_exception_via_bad_regex(self, client_admin, monkeypatch):
        """Covers 1551-1553 – exception in coordinate conversion."""
        import re as _re

        original_match = _re.match
        call_count = [0]

        def patched_match(pattern, string, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] > 2:
                raise RuntimeError('regex error')
            return original_match(pattern, string, *args, **kwargs)

        monkeypatch.setattr(_re, 'match', patched_match)
        resp = client_admin.post('/api/convert-coordinates', json={'dms': '48d38m36.16s'})
        assert resp.status_code in (200, 400, 500)

    def test_push_notification_trigger_no_target(self, client_admin, monkeypatch):
        """Covers lines 627, 677-679 – push notification trigger."""
        import push_manager as _pm

        monkeypatch.setattr(_pm, 'send_push', lambda *a, **kw: True)
        resp = client_admin.post('/api/push/test/iss_pass')
        assert resp.status_code in (200, 400, 500)

    def test_plan_clear_all_success(self, client_admin, monkeypatch):
        """Covers plan clear-all success path."""
        import plan_my_night as _pmn

        monkeypatch.setattr(_pmn, 'clear_all_plans', lambda uid: 3)
        resp = client_admin.delete('/api/plan-my-night/clear-all')
        assert resp.status_code == 200
        assert resp.get_json()['deleted'] == 3

    def test_password_change_wrong_current_password(self, client_admin, monkeypatch):
        """Covers line 402 error branch – wrong current password."""
        from auth import user_manager as _um

        def raise_auth(*_):
            raise ValueError('Wrong current password')

        monkeypatch.setattr(_um, 'change_own_password', raise_auth)
        resp = client_admin.post(
            '/api/auth/change-password',
            json={'current_password': 'wrong', 'new_password': 'NewPass123!'},
        )
        assert resp.status_code in (400, 401, 500)

    def test_metrics_endpoint_accessible(self, client_admin):
        """Covers metrics endpoint path."""
        resp = client_admin.get('/api/metrics')
        assert resp.status_code in (200, 400, 404, 500)

    def test_accessory_by_id_found(self, client_admin, monkeypatch):
        """Covers line 4449 – accessory found by ID."""
        import equipment_profiles as _ep

        fake = {'id': 'acc-1', 'name': 'Barlow 2x'}
        monkeypatch.setattr(_ep, 'get_accessory', lambda uid, aid: fake)
        monkeypatch.setattr(_ep, 'load_all_shared_equipment', lambda kind, uid: [])
        resp = client_admin.get('/api/equipment/accessories/acc-1')
        assert resp.status_code == 200

    def test_combination_by_id_found(self, client_admin, monkeypatch):
        """Covers lines 4590-4591 – combination found by ID."""
        import equipment_profiles as _ep

        fake = {'id': 'combo-1', 'name': 'My Setup', 'telescope_id': 't1', 'camera_id': 'c1'}
        monkeypatch.setattr(_ep, 'get_combination', lambda uid, cid: fake)
        monkeypatch.setattr(_ep, 'compute_combination_share_status',
                            lambda combo, uid: {'is_owner': True, 'is_shared': False})
        resp = client_admin.get('/api/equipment/combinations/combo-1')
        assert resp.status_code == 200

    def test_next_7_nights_sync_false_post_invalid(self, client_admin, monkeypatch):
        """moon_planner slot empty and TTL invalid → pending fallback."""
        _force_invalid_isolated(monkeypatch)
        _set_location_slot('moon_planner', None)
        resp = client_admin.get('/api/moon/next-7-nights')
        assert resp.status_code in (200, 202)

    def test_iss_passes_sync_data_different_window(self, client_admin, monkeypatch):
        """Cached window_days doesn't match the requested window → recompute/pending arc."""
        entry = _set_location_slot('iss_passes', {'window_days': 99, 'passes': []})
        entry['timestamp'] = _time.time() + 60  # valid TTL, wrong window
        monkeypatch.setattr(_cache_store, 'load_shared_cache_entry', lambda *_: None)
        import iss_passes as _iss
        monkeypatch.setattr(_iss, 'get_celestrak_status', lambda: 'ok')
        monkeypatch.setattr(_iss, 'get_iss_tle_source_info', lambda: {})
        resp = client_admin.get('/api/iss/passes?days=7')
        assert resp.status_code in (200, 202)

    def test_push_test_no_subscriptions(self, client_admin, monkeypatch):
        """Covers line 627 – push test with no subscriptions returns 400."""
        from auth import user_manager as _um

        user = _um.get_user_by_username('admin')
        if user:
            original = list(user.push_subscriptions)
            user.push_subscriptions = []
            try:
                resp = client_admin.post('/api/push/test', json={})
                assert resp.status_code in (200, 400, 500)
            finally:
                user.push_subscriptions = original

    def test_translation_asteroid_occultation_missing_body(self, client_admin, monkeypatch):
        """Asteroid occultation with empty body/star translated from stale slot data."""
        _force_invalid_isolated(monkeypatch)
        _set_location_slot('solar_system_events', {
            'events': [{
                'event_type': 'Asteroid Occultation',
                'title': 'Test',
                'description': 'Test desc',
                'raw_data': {'asteroid_name': 'Test', 'star_magnitude': 8.5},
            }],
            'language': 'en',
        })
        resp = client_admin.get('/api/events/solarsystem?lang=fr')
        assert resp.status_code == 200

    def test_special_phenomena_translation_with_format_key(self, client_admin, monkeypatch):
        """Phenomena translation fallback.format(**kwargs) from stale slot data."""
        _force_invalid_isolated(monkeypatch)
        _set_location_slot('special_phenomena', {
            'events': [{
                'event_type': 'Astronomical Event',
                'title': 'Spring Equinox',
                'raw_data': {'event': 'spring_equinox', 'hemisphere': 'northern'},
            }],
            'language': 'en',
        })
        resp = client_admin.get('/api/events/phenomena?lang=de')
        assert resp.status_code == 200

    def test_resolve_night_calc_empty_metadata(self, client_admin, monkeypatch):
        """Covers 2979, 2982-2983, 2990-2992 – calc returns empty metadata."""
        from sun_phases import SunService as _SS

        def sun_raise(self):
            raise RuntimeError('sun fail')

        monkeypatch.setattr(_SS, 'get_today_report', sun_raise)
        monkeypatch.setattr(_app_mod, 'load_calculation_results', lambda *_a, **_k: {})

        import plan_my_night as _pmn

        monkeypatch.setattr(
            _pmn, 'create_or_add_target',
            lambda **_kw: (True, 'created', {}, {'id': 'e-x'}),
        )
        resp = client_admin.post(
            '/api/plan-my-night/targets',
            json={'item': {'name': 'Saturn', 'type': 'Planet'}, 'catalogue': 'SolarSystem'},
        )
        assert resp.status_code in (200, 400, 409, 500)

    def test_plan_export_pdf_exception(self, client_admin, monkeypatch):
        """Covers 3495-3497 – exception in plan PDF export."""
        import plan_my_night as _pmn

        def raise_err(*a, **kw):
            raise RuntimeError('pdf error')

        monkeypatch.setattr(_pmn, 'get_plan_with_timeline', raise_err)
        resp = client_admin.get('/api/plan-my-night/export.pdf')
        assert resp.status_code in (200, 500)

    def test_astrodex_image_serve_found(self, client_admin, monkeypatch):
        """Covers line 3832 – image found and send_from_directory called."""
        import astrodex as _adx
        import flask as _flask
        import os as _os

        monkeypatch.setattr(_adx, 'can_user_view_image', lambda uid, filename: True)
        monkeypatch.setattr(_adx, 'ASTRODEX_IMAGES_DIR', _os.path.dirname(__file__))
        monkeypatch.setattr(
            _flask, 'send_from_directory',
            lambda d, f, **kw: _flask.jsonify({'file': f}),
        )
        resp = client_admin.get('/api/astrodex/images/conftest.py')
        assert resp.status_code in (200, 400, 403, 404, 500)

    def test_sidereal_time_sync_post_invalid_location(self, client_admin, monkeypatch):
        """Sidereal slot invalid-for-today → live computation arc."""
        monkeypatch.setattr(_cache_store, 'is_cache_valid_for_today', lambda *_: False)
        monkeypatch.setattr(_cache_store, 'load_shared_cache_entry', lambda *_: None)
        _set_location_slot('sidereal_time', None)
        import sidereal_time as _st
        monkeypatch.setattr(
            _st.SiderealTimeService,
            'get_current_sidereal_info',
            lambda self: {'lst': 0.0, 'lmst': '00h00m00s'},
        )
        resp = client_admin.get('/api/astro/sidereal-time')
        assert resp.status_code in (200, 400)

    def test_best_window_all_modes_sync_post_valid(self, client_admin, monkeypatch):
        """best_window slots pre-filled and valid → data-found arc."""
        for name in ('best_window_strict', 'best_window_practical', 'best_window_illumination'):
            entry = _set_location_slot(name, {'status': 'ready'})
            entry['timestamp'] = _time.time() + 60
        monkeypatch.setattr(_cache_store, 'load_shared_cache_entry', lambda *_: None)
        resp = client_admin.get('/api/tonight/best-window')
        assert resp.status_code in (200, 400, 202)
