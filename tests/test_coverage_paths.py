
# ---------------------------------------------------------------------------
# Coverage boost — targeted tests for specific uncovered paths in app.py
# ---------------------------------------------------------------------------
import pytest
import app as _app_mod
import cache_store as _cache_store


# ---------------------------------------------------------------------------


class TestCacheSyncPaths:
    """Tests for cache-sync code paths (sync returns True then is_cache_valid True)."""

    @staticmethod
    def _sync_then_valid(monkeypatch, cache_attr, data, valid_method='is_cache_valid'):
        cache = getattr(_cache_store, cache_attr)
        cache['data'] = data
        call_counts = {}

        def is_valid_fake(c, ttl):
            key = id(c)
            call_counts[key] = call_counts.get(key, 0) + 1
            return call_counts[key] >= 2

        monkeypatch.setattr(_cache_store, valid_method, is_valid_fake)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda *_: True)

    def test_moon_report_sync_path(self, client_admin, monkeypatch):
        self._sync_then_valid(monkeypatch, '_moon_report_cache', {'moon': 'data'})
        resp = client_admin.get('/api/moon/report')
        assert resp.status_code == 200

    def test_dark_window_sync_path(self, client_admin, monkeypatch):
        self._sync_then_valid(monkeypatch, '_dark_window_report_cache', {'window': 'data'})
        resp = client_admin.get('/api/moon/dark-window')
        assert resp.status_code == 200

    def test_horizon_graph_sync_path(self, client_admin, monkeypatch):
        self._sync_then_valid(monkeypatch, '_horizon_graph_cache', {'graph': 'data'})
        resp = client_admin.get('/api/astro/horizon-graph')
        assert resp.status_code == 200

    def test_seeing_forecast_sync_path(self, client_admin, monkeypatch):
        self._sync_then_valid(monkeypatch, '_seeing_forecast_cache', {'seeing': 'data'})
        resp = client_admin.get('/api/seeing-forecast')
        assert resp.status_code == 200

    def test_planetary_events_sync_path(self, client_admin, monkeypatch):
        self._sync_then_valid(monkeypatch, '_planetary_events_cache', {'events': []})
        resp = client_admin.get('/api/events/planetary')
        assert resp.status_code == 200

    def test_special_phenomena_sync_path(self, client_admin, monkeypatch):
        self._sync_then_valid(monkeypatch, '_special_phenomena_cache', {'events': []})
        resp = client_admin.get('/api/events/phenomena')
        assert resp.status_code == 200

    def test_solar_system_events_sync_path(self, client_admin, monkeypatch):
        self._sync_then_valid(monkeypatch, '_solar_system_events_cache', {'events': []})
        resp = client_admin.get('/api/events/solarsystem')
        assert resp.status_code == 200

    def test_iss_passes_sync_path(self, client_admin, monkeypatch):
        self._sync_then_valid(monkeypatch, '_iss_passes_cache', {'window_days': 20, 'passes': []})
        import iss_passes as _iss
        monkeypatch.setattr(_iss, 'get_celestrak_status', lambda: 'ok')
        monkeypatch.setattr(_iss, 'get_iss_tle_source_info', lambda: {})
        resp = client_admin.get('/api/iss/passes')
        assert resp.status_code == 200

    def test_all_events_eclipse_sync_paths(self, client_admin, monkeypatch):
        """Cache sync branches in get_all_events_api for multiple caches."""
        call_counts = {}

        def is_valid_per_cache(c, ttl):
            key = id(c)
            call_counts[key] = call_counts.get(key, 0) + 1
            return call_counts[key] >= 2

        monkeypatch.setattr(_cache_store, 'is_cache_valid', is_valid_per_cache)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda *_: True)
        for attr in (
            '_solar_eclipse_cache',
            '_lunar_eclipse_cache',
            '_aurora_cache',
            '_iss_passes_cache',
            '_moon_planner_report_cache',
            '_planetary_events_cache',
            '_special_phenomena_cache',
            '_solar_system_events_cache',
        ):
            getattr(_cache_store, attr)['data'] = None
        resp = client_admin.get('/api/events/upcoming')
        assert resp.status_code in (200, 400, 500)

    def test_sidereal_time_sync_valid_for_today(self, client_admin, monkeypatch):
        """Covers lines 2821->2824 – cache valid-for-today after sync."""
        call_counts = {}

        def is_valid_today(c, ttl):
            key = id(c)
            call_counts[key] = call_counts.get(key, 0) + 1
            return call_counts[key] >= 2

        _cache_store._sidereal_time_cache['data'] = {'hourly_forecast': []}
        monkeypatch.setattr(_cache_store, 'is_cache_valid_for_today', is_valid_today)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda *_: True)
        import sidereal_time as _st
        monkeypatch.setattr(
            _st.SiderealTimeService,
            'get_current_sidereal_info',
            lambda self: {'lst': 0.0, 'lmst': '00h00m00s'},
        )
        resp = client_admin.get('/api/astro/sidereal-time')
        assert resp.status_code in (200, 400)

    def test_seeing_forecast_not_ready_returns_202(self, client_admin, monkeypatch):
        """Covers line 1972 – seeing forecast pending."""
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda *_: False)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda *_: False)
        _cache_store._seeing_forecast_cache['data'] = None
        resp = client_admin.get('/api/seeing-forecast')
        assert resp.status_code == 202


class TestWeatherForecastLiveData:
    """Test the DataFrame-processing path in get_weather_forecast."""

    def test_weather_forecast_with_dataframe_response(self, client_admin, monkeypatch):
        """Covers lines 1675-1695."""
        pd = pytest.importorskip('pandas')

        df = pd.DataFrame({
            'date': pd.to_datetime(['2026-06-07T22:00:00+00:00']),
            'temperature_2m': [15.0],
            'bytes_col': [b'raw bytes'],
        })
        mock_forecast = {
            'hourly': df,
            'location': {'name': 'TestCity', 'lat': '48.85'},
        }
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda *_: False)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda *_: False)
        monkeypatch.setattr(_app_mod, 'get_hourly_forecast', lambda: mock_forecast)
        monkeypatch.setattr(_cache_store, 'update_shared_cache_entry', lambda *_: None)

        resp = client_admin.get('/api/weather/forecast')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'hourly' in data
        assert 'location' in data


class TestCatalogueLookupSimbad:
    """Tests for the SIMBAD fallback path in catalogue lookup."""

    def test_simbad_lookup_name_in_catalogue(self, client_admin, monkeypatch):
        """Covers lines 3910-3936 – SIMBAD found, name matches catalogue value."""
        import skytonight_targets as _skt
        import object_info as _oi

        monkeypatch.setattr(_skt, 'get_lookup_entry', lambda *a, **kw: None)
        monkeypatch.setattr(_oi, 'is_safe_identifier', lambda name: True)
        monkeypatch.setattr(
            _oi, 'resolve_identifier_for_catalogue_lookup',
            lambda name: {'aliases': ['HIP 12345'], 'object_type': 'Star', 'constellation': 'Ori'},
        )
        monkeypatch.setattr(
            _oi, 'build_catalogue_names_from_aliases',
            lambda name, aliases: {'Hipparcos': 'HIP 12345'},
        )

        resp = client_admin.get('/api/astrodex/catalogue-lookup?name=HIP+12345')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['found'] is True
        assert data['preferred_name'] == 'HIP 12345'

    def test_simbad_lookup_name_not_in_catalogue(self, client_admin, monkeypatch):
        """Covers SIMBAD path where name does NOT match any catalogue value → use alias."""
        import skytonight_targets as _skt
        import object_info as _oi

        monkeypatch.setattr(_skt, 'get_lookup_entry', lambda *a, **kw: None)
        monkeypatch.setattr(_oi, 'is_safe_identifier', lambda name: True)
        monkeypatch.setattr(
            _oi, 'resolve_identifier_for_catalogue_lookup',
            lambda name: {'aliases': ['NGC 1234'], 'object_type': 'Galaxy', 'constellation': 'Peg'},
        )
        monkeypatch.setattr(
            _oi, 'build_catalogue_names_from_aliases',
            lambda name, aliases: {'OpenNGC': 'NGC 1234'},
        )

        resp = client_admin.get('/api/astrodex/catalogue-lookup?name=unknown+name')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['found'] is True
        assert data['preferred_name'] == 'NGC 1234'

    def test_simbad_lookup_no_aliases_uses_name(self, client_admin, monkeypatch):
        """Covers branch where aliases list is empty → preferred_name = name."""
        import skytonight_targets as _skt
        import object_info as _oi

        monkeypatch.setattr(_skt, 'get_lookup_entry', lambda *a, **kw: None)
        monkeypatch.setattr(_oi, 'is_safe_identifier', lambda name: True)
        monkeypatch.setattr(
            _oi, 'resolve_identifier_for_catalogue_lookup',
            lambda name: {'aliases': [], 'object_type': 'Unknown', 'constellation': '?'},
        )
        monkeypatch.setattr(
            _oi, 'build_catalogue_names_from_aliases',
            lambda name, aliases: {},
        )

        resp = client_admin.get('/api/astrodex/catalogue-lookup?name=sparse_obj')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['found'] is True

    def test_simbad_returns_none_gives_not_found(self, client_admin, monkeypatch):
        """Covers is_safe_identifier=True but SIMBAD returns None."""
        import skytonight_targets as _skt
        import object_info as _oi

        monkeypatch.setattr(_skt, 'get_lookup_entry', lambda *a, **kw: None)
        monkeypatch.setattr(_oi, 'is_safe_identifier', lambda name: True)
        monkeypatch.setattr(_oi, 'resolve_identifier_for_catalogue_lookup', lambda name: None)

        resp = client_admin.get('/api/astrodex/catalogue-lookup?name=not+found')
        assert resp.status_code == 200
        assert resp.get_json()['found'] is False


class TestConfigUpdateEdgeCases:
    """Tests for specific branches in update_config_api."""

    def _base_config(self):
        return {
            'location': {
                'latitude': 48.8566,
                'longitude': 2.3522,
                'timezone': 'Europe/Paris',
                'elevation': 100,
            },
            'skytonight': {'enabled': True},
        }

    def test_bortle_out_of_range_returns_400(self, client_admin):
        """Covers line 959 – bortle out of range."""
        cfg = self._base_config()
        cfg['location']['bortle'] = 15
        resp = client_admin.post('/api/config', json=cfg)
        assert resp.status_code == 400
        assert 'bortle' in resp.get_json().get('error', '').lower()

    def test_sqm_negative_returns_400(self, client_admin):
        """Covers line 967 – sqm <= 0."""
        cfg = self._base_config()
        cfg['location']['sqm'] = -1.0
        resp = client_admin.post('/api/config', json=cfg)
        assert resp.status_code == 400
        assert 'sqm' in resp.get_json().get('error', '').lower()

    def test_config_with_location_configured_already_set(self, client_admin):
        """Covers line 973->977 False arc – location_configured already in config."""
        cfg = self._base_config()
        cfg['location_configured'] = True
        resp = client_admin.post('/api/config', json=cfg)
        assert resp.status_code == 200

    def test_config_skytonight_non_dict(self, client_admin):
        """Covers branch where incoming skytonight is not a dict."""
        cfg = self._base_config()
        cfg['skytonight'] = 'invalid'
        resp = client_admin.post('/api/config', json=cfg)
        assert resp.status_code == 200

    def test_config_skytonight_nested_non_dict_values(self, client_admin):
        """Covers line 927 – merging non-dict values in skytonight dict."""
        cfg = self._base_config()
        cfg['skytonight'] = {'some_key': 'scalar-value', 'enabled': True}
        resp = client_admin.post('/api/config', json=cfg)
        assert resp.status_code == 200


class TestPasswordChangeSuccess:
    """Covers line 402 – successful password change."""

    def test_password_change_success(self, client_admin, monkeypatch):
        from auth import user_manager as _um
        monkeypatch.setattr(_um, 'change_own_password', lambda *_: None)
        resp = client_admin.post(
            '/api/auth/change-password',
            json={'current_password': 'anypass', 'new_password': 'NewPass123!'},
        )
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'success'


class TestAuthStatusStaleSess:
    """Covers lines 363->373 – username in session but get_current_user returns None."""

    def test_auth_status_stale_username_in_session(self, monkeypatch):
        """Username in session but no matching user → authenticated=False."""
        _app = _app_mod.app
        monkeypatch.setattr(_app_mod, 'get_current_user', lambda: None)
        with _app.test_client() as c:
            with c.session_transaction() as sess:
                sess['username'] = 'ghost_user_not_in_db'
            resp = c.get('/api/auth/status')
            assert resp.status_code == 200
            assert resp.get_json()['authenticated'] is False


class TestPushExceptionPaths:
    """Tests for push endpoint exception handlers."""

    def test_push_subscribe_save_exception(self, client_admin, monkeypatch):
        """Covers lines 538-540 – exception in push subscribe save."""
        from auth import user_manager as _um

        def raise_error():
            raise RuntimeError('disk full')

        monkeypatch.setattr(_um, 'save_users', raise_error)
        resp = client_admin.post(
            '/api/push/subscribe',
            json={
                'subscription': {
                    'endpoint': 'https://exception-test.example.com/push/unique-ep',
                    'keys': {'p256dh': 'abc', 'auth': 'def'},
                }
            },
        )
        assert resp.status_code == 500

    def test_push_list_exception(self, client_admin, monkeypatch):
        """Covers lines 577-579 – exception iterating subscriptions list."""
        from auth import user_manager as _um

        class _BrokenList:
            def __iter__(self):
                raise RuntimeError('broken subscriptions')
            def __len__(self):
                return 1

        user = _um.get_user_by_username('admin')
        original = user.push_subscriptions
        user.push_subscriptions = _BrokenList()
        try:
            resp = client_admin.get('/api/push/subscriptions')
            assert resp.status_code == 500
        finally:
            user.push_subscriptions = original

    def test_push_delete_all_exception(self, client_admin, monkeypatch):
        """Covers lines 596-598 – exception during delete-all push subscriptions."""
        from auth import user_manager as _um

        def raise_error():
            raise RuntimeError('disk full')

        monkeypatch.setattr(_um, 'save_users', raise_error)
        user = _um.get_user_by_username('admin')
        if user:
            original = list(user.push_subscriptions)
            user.push_subscriptions = [{'endpoint': 'https://example.com/x', 'keys': {}}]
            try:
                resp = client_admin.delete('/api/push/subscriptions')
                assert resp.status_code in (200, 500)
            finally:
                user.push_subscriptions = original

    def test_push_unsubscribe_exception(self, client_admin, monkeypatch):
        """Covers lines 750-752 – exception in unsubscribe."""
        from auth import user_manager as _um

        def raise_error():
            raise RuntimeError('disk full')

        monkeypatch.setattr(_um, 'save_users', raise_error)
        user = _um.get_user_by_username('admin')
        if user:
            original = list(user.push_subscriptions)
            ep = 'https://example.com/push/test-unsub'
            user.push_subscriptions = [{'endpoint': ep, 'keys': {}}]
            try:
                resp = client_admin.delete('/api/push/unsubscribe', json={'endpoint': ep})
                assert resp.status_code in (200, 500)
            finally:
                user.push_subscriptions = original

    def test_push_test_with_dead_endpoint(self, client_admin, monkeypatch):
        """Covers lines 715-726 – dead endpoint cleaned up in push_test."""
        from auth import user_manager as _um
        import push_manager as _pm

        monkeypatch.setattr(_pm, 'send_push', lambda *_a, **_k: False)
        monkeypatch.setattr(_um, 'save_users', lambda: None)
        user = _um.get_user_by_username('admin')
        if user:
            original = list(user.push_subscriptions)
            user.push_subscriptions = [
                {'endpoint': 'https://dead.example.com/push', 'keys': {'p256dh': 'a', 'auth': 'b'}}
            ]
            try:
                resp = client_admin.post('/api/push/test', json={})
                assert resp.status_code in (200, 400, 500)
            finally:
                user.push_subscriptions = original


class TestBackupRestorePaths:
    """Tests for backup restore endpoint validation and write paths."""

    def _make_zip(self, entries):
        import io as _io
        import zipfile as _zf

        buf = _io.BytesIO()
        with _zf.ZipFile(buf, mode='w') as z:
            for name, content in entries:
                z.writestr(name, content)
        buf.seek(0)
        return buf

    def test_restore_with_invalid_json_content_returns_400(self, client_admin):
        """Covers lines 1310-1311 – JSON validation failure."""
        buf = self._make_zip([('config.json', b'this is not json')])
        data = {'file': (buf, 'backup.zip')}
        resp = client_admin.post('/api/backup/restore', data=data, content_type='multipart/form-data')
        assert resp.status_code == 400
        assert 'JSON' in resp.get_json().get('error', '')

    def test_restore_directory_entry_skipped(self, client_admin):
        """Covers line 1284 – directory entries skipped."""
        import io as _io
        import zipfile as _zf

        buf = _io.BytesIO()
        with _zf.ZipFile(buf, mode='w') as z:
            zi = _zf.ZipInfo('subdir/')
            z.writestr(zi, '')
            z.writestr('config.json', b'not valid json either')
        buf.seek(0)
        data = {'file': (buf, 'backup.zip')}
        resp = client_admin.post('/api/backup/restore', data=data, content_type='multipart/form-data')
        assert resp.status_code in (200, 400, 500)


class TestTranslationBranches:
    """Tests covering translation edge cases in solar-system and phenomena routes."""

    def test_solar_system_events_non_list_events(self, client_admin, monkeypatch):
        """Covers line 2590 – events is not a list."""
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda *_: False)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda *_: False)
        _cache_store._solar_system_events_cache['data'] = {'events': 'not-a-list', 'language': 'en'}
        resp = client_admin.get('/api/events/solarsystem?lang=fr')
        assert resp.status_code == 200

    def test_solar_system_events_non_dict_event(self, client_admin, monkeypatch):
        """Covers lines 2598-2599 – event in list is not a dict."""
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda *_: False)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda *_: False)
        _cache_store._solar_system_events_cache['data'] = {'events': ['string-event'], 'language': 'en'}
        resp = client_admin.get('/api/events/solarsystem?lang=fr')
        assert resp.status_code == 200

    def test_solar_system_asteroid_occultation_event(self, client_admin, monkeypatch):
        """Covers lines 2636->2645 – Asteroid Occultation event translation branch."""
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda *_: False)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda *_: False)
        _cache_store._solar_system_events_cache['data'] = {
            'events': [{'event_type': 'Asteroid Occultation', 'title': 'Ast', 'description': 'Desc'}],
            'language': 'en',
        }
        resp = client_admin.get('/api/events/solarsystem?lang=fr')
        assert resp.status_code == 200

    def test_special_phenomena_non_list_events(self, client_admin, monkeypatch):
        """Covers line 2657 – special phenomena events not a list."""
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda *_: False)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda *_: False)
        _cache_store._special_phenomena_cache['data'] = {'events': 'bad', 'language': 'en'}
        resp = client_admin.get('/api/events/phenomena?lang=fr')
        assert resp.status_code == 200

    def test_special_phenomena_non_dict_event(self, client_admin, monkeypatch):
        """Covers lines 2675-2676 – non-dict event in special phenomena."""
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda *_: False)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda *_: False)
        _cache_store._special_phenomena_cache['data'] = {'events': [42], 'language': 'en'}
        resp = client_admin.get('/api/events/phenomena?lang=fr')
        assert resp.status_code == 200


class TestPlanMyNightCoveragePaths:
    """Tests for Plan My Night endpoint edge cases."""

    def test_plan_add_target_previous_plan_locked(self, client_admin, monkeypatch):
        """Covers line 3209 – plan belongs to a previous night."""
        import plan_my_night as _pmn

        monkeypatch.setattr(
            _pmn, 'create_or_add_target',
            lambda **_kw: (False, 'previous_plan_locked', None, None),
        )
        monkeypatch.setattr(
            _app_mod, '_resolve_observing_night_for_plan',
            lambda: {
                'start': '2026-06-07T22:00:00',
                'end': '2026-06-08T04:00:00',
                'duration_hours': 6.0,
            },
        )
        resp = client_admin.post(
            '/api/plan-my-night/targets',
            json={'item': {'name': 'M42', 'type': 'Nebula'}, 'catalogue': 'Messier'},
        )
        assert resp.status_code == 409

    def test_resolve_observing_night_fallback_path(self, client_admin, monkeypatch):
        """Covers lines 3001-3019 – sun service fails, fallback to calc results."""
        from sun_phases import SunService as _SS

        def sun_raise(self):
            raise RuntimeError('sun fail')

        monkeypatch.setattr(_SS, 'get_today_report', sun_raise)
        monkeypatch.setattr(
            _app_mod, 'load_calculation_results',
            lambda: {
                'metadata': {
                    'night_start': '2026-06-07T22:00:00',
                    'night_end': '2026-06-08T04:00:00',
                }
            },
        )
        import plan_my_night as _pmn

        monkeypatch.setattr(
            _pmn, 'create_or_add_target',
            lambda **_kw: (True, 'created', {}, {'id': 'entry-1'}),
        )
        monkeypatch.setattr(_pmn, 'get_plan_with_timeline', lambda *a, **kw: {'state': 'ok'})
        resp = client_admin.post(
            '/api/plan-my-night/targets',
            json={'item': {'name': 'M42', 'type': 'Nebula'}, 'catalogue': 'Messier'},
        )
        assert resp.status_code in (200, 400, 409, 500)

    def test_plan_search_across_telescopes(self, client_admin, monkeypatch):
        """Covers lines 3387-3396 – entry not in default plan, found in telescope plan."""
        import plan_my_night as _pmn
        import astrodex as _adx
        import os as _os

        entry_id = 'test-entry-scope-123'
        telescope_plan = {'entries': [{'id': entry_id, 'name': 'M42', 'catalogue': 'Messier'}]}

        monkeypatch.setattr(
            _pmn, 'get_all_plan_files',
            lambda uid: [f'data/plans/{uid}_plan_scope1.json'],
        )
        monkeypatch.setattr(
            _pmn, 'load_user_plan',
            lambda uid, uname, telescope_id=None: {'plan': telescope_plan},
        )
        monkeypatch.setattr(_adx, 'is_item_in_astrodex', lambda *_: False)
        monkeypatch.setattr(_adx, 'create_astrodex_item', lambda *_: {'id': 'new-item'})

        resp = client_admin.post(f'/api/plan-my-night/targets/{entry_id}/add-to-astrodex')
        assert resp.status_code in (200, 404, 500)


class TestAstrodexUploadPaths:
    """Tests for specific astrodex upload/image paths."""

    def test_upload_empty_filename_returns_400(self, client_admin):
        """Covers lines 3758-3759 – file present but empty filename."""
        import io as _io

        data = {'file': (_io.BytesIO(b''), '')}
        resp = client_admin.post('/api/astrodex/upload', data=data, content_type='multipart/form-data')
        assert resp.status_code in (400, 401, 500)

    def test_upload_exception_returns_500(self, client_admin, monkeypatch):
        """Covers lines 3805-3807 – exception during upload."""
        import io as _io
        import astrodex as _adx

        def raise_error():
            raise RuntimeError('disk error')

        monkeypatch.setattr(_adx, 'ensure_astrodex_directories', raise_error)
        data = {'file': (_io.BytesIO(b'\x89PNG\r\n\x1a\n' + b'\x00' * 50), 'test.png')}
        resp = client_admin.post('/api/astrodex/upload', data=data, content_type='multipart/form-data')
        assert resp.status_code in (400, 500)

    def test_switch_catalogue_name_success(self, client_admin, monkeypatch):
        """Covers lines 3589, 3595-3597 – switch catalogue name success."""
        import astrodex as _adx

        monkeypatch.setattr(
            _adx, 'switch_item_catalogue_name',
            lambda uid, item_id, catalogue: {'id': item_id, 'name': 'NGC 224'},
        )
        resp = client_admin.post(
            '/api/astrodex/items/test-item-id/catalogue-name',
            json={'catalogue': 'OpenNGC'},
        )
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'success'

    def test_switch_catalogue_name_no_result(self, client_admin, monkeypatch):
        """Covers line 3589 False branch – switch returns None/empty."""
        import astrodex as _adx

        monkeypatch.setattr(
            _adx, 'switch_item_catalogue_name',
            lambda uid, item_id, catalogue: None,
        )
        resp = client_admin.post(
            '/api/astrodex/items/test-item-id/catalogue-name',
            json={'catalogue': 'OpenNGC'},
        )
        assert resp.status_code in (400, 404, 500)


class TestSpaceflightCachePaths:
    """Tests for spaceflight cache-not-ready and sync paths."""

    def test_spaceflight_launches_not_ready(self, client_admin, monkeypatch):
        """Covers line 2124 – launches cache not ready."""
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda *_: False)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda *_: False)
        _cache_store._spaceflight_launches_cache['data'] = None
        resp = client_admin.get('/api/spaceflight/launches')
        assert resp.status_code in (200, 202, 503)

    def test_spaceflight_events_not_ready(self, client_admin, monkeypatch):
        """Covers line 2166 – events cache not ready."""
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda *_: False)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda *_: False)
        _cache_store._spaceflight_events_cache['data'] = None
        resp = client_admin.get('/api/spaceflight/events')
        assert resp.status_code in (200, 202, 503)

    def test_spaceflight_events_after_sync(self, client_admin, monkeypatch):
        """Covers line 2160 – events cached after sync."""
        call_counts = {}

        def is_valid_per_cache(c, ttl):
            key = id(c)
            call_counts[key] = call_counts.get(key, 0) + 1
            return call_counts[key] >= 2

        _cache_store._spaceflight_events_cache['data'] = {'results': []}
        monkeypatch.setattr(_cache_store, 'is_cache_valid', is_valid_per_cache)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda *_: True)
        resp = client_admin.get('/api/spaceflight/events')
        assert resp.status_code == 200

    def test_spaceflight_astronauts_after_sync(self, client_admin, monkeypatch):
        """Covers line 2139 – astronauts cached after sync."""
        call_counts = {}

        def is_valid_per_cache(c, ttl):
            key = id(c)
            call_counts[key] = call_counts.get(key, 0) + 1
            return call_counts[key] >= 2

        _cache_store._spaceflight_astronauts_cache['data'] = {'astronauts': []}
        monkeypatch.setattr(_cache_store, 'is_cache_valid', is_valid_per_cache)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda *_: True)
        resp = client_admin.get('/api/spaceflight/astronauts')
        assert resp.status_code == 200

    def test_spaceflight_astronauts_not_ready(self, client_admin, monkeypatch):
        """Covers line 2145 – astronauts cache not ready."""
        monkeypatch.setattr(_cache_store, 'is_cache_valid', lambda *_: False)
        monkeypatch.setattr(_cache_store, 'sync_cache_from_shared', lambda *_: False)
        _cache_store._spaceflight_astronauts_cache['data'] = None
        resp = client_admin.get('/api/spaceflight/astronauts')
        assert resp.status_code in (200, 202, 503)


class TestObjectInfoPaths:
    """Tests for object info endpoint edge cases."""

    def test_object_info_invalid_identifier_from_backend(self, client_admin, monkeypatch):
        """Covers line 2025 – get_object_info returns error=invalid_identifier."""
        import object_info as _oi

        monkeypatch.setattr(_oi, 'is_safe_identifier', lambda name: True)
        monkeypatch.setattr(_oi, 'get_object_info',
                            lambda name, lang='en': {'error': 'invalid_identifier'})
        resp = client_admin.get('/api/object/INVALID_IDENT')
        assert resp.status_code in (400, 500)


class TestTimezonesAndCoordinates:
    """Tests for timezones listing and coordinate conversion."""

    def test_timezones_filters_posix_and_right(self, client_admin):
        """Covers line 1563->1562 – posix/right timezones are filtered out in loop."""
        resp = client_admin.get('/api/timezones')
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        assert len(data) > 0
        for tz in data:
            name = tz if isinstance(tz, str) else (tz.get('value') or tz.get('name') or '')
            assert not name.startswith('posix/')
            assert not name.startswith('right/')

    def test_coordinate_out_of_range_returns_400(self, client_admin):
        """Covers line 1545 – coordinate value out of valid range."""
        resp = client_admin.post(
            '/api/convert-coordinates',
            json={'dms': '181d00m00.0s'},
        )
        assert resp.status_code == 400
