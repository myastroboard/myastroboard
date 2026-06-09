"""Tests for push_scheduler.py: trigger logic, cooldown helpers, and delivery."""

import sys
import time
import types
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

backend_path = __import__('os').path.join(__import__('os').path.dirname(__import__('os').path.dirname(__file__)), 'backend')
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

if 'psutil' not in sys.modules:
    sys.modules['psutil'] = types.ModuleType('psutil')


@pytest.fixture(autouse=True)
def reset_scheduler_state():
    import push_scheduler
    push_scheduler._last_sent.clear()
    push_scheduler._n2_notified.clear()
    push_scheduler._any_active_night = False
    yield
    push_scheduler._last_sent.clear()
    push_scheduler._n2_notified.clear()
    push_scheduler._any_active_night = False


def _make_user(user_id='u1', username='alice', subscriptions=None, triggers=None):
    user = MagicMock()
    user.user_id = user_id
    user.username = username
    user.push_subscriptions = subscriptions if subscriptions is not None else [
        {'endpoint': 'https://push.example.com/abc', 'keys': {'p256dh': 'X', 'auth': 'Y'}}
    ]
    notif_cfg = {'enabled': True, 'triggers': triggers or {}}
    user.preferences = {'notifications': notif_cfg}
    return user


def _now_iso(**delta):
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat()


# ---------------------------------------------------------------------------
# Cooldown helpers
# ---------------------------------------------------------------------------

def test_was_recently_notified_returns_false_when_never_sent():
    import push_scheduler
    assert not push_scheduler._was_recently_notified('u1', 'N7', 3600)


def test_was_recently_notified_returns_true_within_cooldown():
    import push_scheduler
    push_scheduler._mark_notified('u1', 'N7')
    assert push_scheduler._was_recently_notified('u1', 'N7', 3600)


def test_was_recently_notified_returns_false_after_cooldown_expires():
    import push_scheduler
    push_scheduler._last_sent['u1'] = {'N7': time.monotonic() - 7200}
    assert not push_scheduler._was_recently_notified('u1', 'N7', 3600)


def test_mark_notified_is_per_user_and_trigger():
    import push_scheduler
    push_scheduler._mark_notified('u1', 'N7')
    assert push_scheduler._was_recently_notified('u1', 'N7', 3600)
    assert not push_scheduler._was_recently_notified('u2', 'N7', 3600)
    assert not push_scheduler._was_recently_notified('u1', 'N1', 3600)


# ---------------------------------------------------------------------------
# N7 - Aurora
# ---------------------------------------------------------------------------

def test_n7_sends_when_kp_meets_threshold(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))

    cache = {'current': {'kp_index': 6.0, 'visibility_level': 'High'}}
    push_scheduler._check_n7_aurora(_make_user(), cache)

    assert len(send_calls) == 1 and send_calls[0][1] == 'N7'


def test_n7_skips_when_kp_below_default_threshold(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))

    cache = {'current': {'kp_index': 3.0, 'visibility_level': 'Low'}}
    push_scheduler._check_n7_aurora(_make_user(), cache)

    assert not send_calls


def test_n7_respects_custom_kp_threshold(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))

    user = _make_user(triggers={'N7': {'enabled': True, 'kp_threshold': 8}})
    cache = {'current': {'kp_index': 7.0, 'visibility_level': 'High'}}
    push_scheduler._check_n7_aurora(user, cache)

    assert not send_calls


def test_n7_skips_when_disabled(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))

    user = _make_user(triggers={'N7': {'enabled': False}})
    cache = {'current': {'kp_index': 9.0, 'visibility_level': 'Extreme'}}
    push_scheduler._check_n7_aurora(user, cache)

    assert not send_calls


def test_n7_skips_on_cooldown(monkeypatch):
    import push_scheduler
    push_scheduler._mark_notified('u1', 'N7')
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))

    cache = {'current': {'kp_index': 8.0, 'visibility_level': 'High'}}
    push_scheduler._check_n7_aurora(_make_user(), cache)

    assert not send_calls


def test_n7_skips_when_cache_is_none(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))

    push_scheduler._check_n7_aurora(_make_user(), None)
    assert not send_calls


# ---------------------------------------------------------------------------
# N1 - Plan start
# ---------------------------------------------------------------------------

def test_n1_sends_when_night_starts_within_lead_window(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))

    payload = {
        'state': 'pending',
        'timeline': {'is_inside_night': False},
        'plan': {'night_start': _now_iso(minutes=10)},
    }
    push_scheduler._check_n1_plan_start(_make_user(), payload)

    assert len(send_calls) == 1 and send_calls[0][1] == 'N1'


def test_n1_skips_when_already_inside_night(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))

    payload = {
        'state': 'active',
        'timeline': {'is_inside_night': True},
        'plan': {'night_start': _now_iso(minutes=-60)},
    }
    push_scheduler._check_n1_plan_start(_make_user(), payload)

    assert not send_calls


def test_n1_skips_when_night_starts_too_far_away(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))

    payload = {
        'state': 'pending',
        'timeline': {'is_inside_night': False},
        'plan': {'night_start': _now_iso(hours=3)},
    }
    push_scheduler._check_n1_plan_start(_make_user(), payload)

    assert not send_calls


def test_n1_skips_when_state_is_none_or_payload_none(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))

    push_scheduler._check_n1_plan_start(_make_user(), None)
    push_scheduler._check_n1_plan_start(_make_user(), {'state': 'none'})

    assert not send_calls


def test_n1_respects_custom_lead_minutes(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))

    user = _make_user(triggers={'N1': {'enabled': True, 'lead_minutes': 5}})
    payload = {
        'state': 'pending',
        'timeline': {'is_inside_night': False},
        'plan': {'night_start': _now_iso(minutes=10)},  # outside 5-min window
    }
    push_scheduler._check_n1_plan_start(user, payload)

    assert not send_calls


# ---------------------------------------------------------------------------
# N2 - Next target
# ---------------------------------------------------------------------------

def test_n2_sends_for_upcoming_entry(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))

    payload = {
        'state': 'active',
        'timeline': {'is_inside_night': True},
        'plan': {'entries': [
            {'id': 'e1', 'name': 'M42', 'timeline_start': _now_iso(minutes=3), 'done': False},
        ]},
    }
    push_scheduler._check_n2_next_target(_make_user(), payload)

    assert len(send_calls) == 1 and send_calls[0][1] == 'N2'


def test_n2_deduplicates_same_entry_across_calls(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))

    payload = {
        'state': 'active',
        'timeline': {'is_inside_night': True},
        'plan': {'entries': [
            {'id': 'e1', 'name': 'M42', 'timeline_start': _now_iso(minutes=3), 'done': False},
        ]},
    }
    user = _make_user()
    push_scheduler._check_n2_next_target(user, payload)
    push_scheduler._check_n2_next_target(user, payload)

    assert len(send_calls) == 1


def test_n2_skips_done_entries(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))

    payload = {
        'state': 'active',
        'timeline': {'is_inside_night': True},
        'plan': {'entries': [
            {'id': 'e1', 'name': 'M42', 'timeline_start': _now_iso(minutes=3), 'done': True},
        ]},
    }
    push_scheduler._check_n2_next_target(_make_user(), payload)

    assert not send_calls


def test_n2_skips_when_outside_night(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))

    payload = {
        'state': 'pending',
        'timeline': {'is_inside_night': False},
        'plan': {'entries': [
            {'id': 'e1', 'name': 'M42', 'timeline_start': _now_iso(minutes=3), 'done': False},
        ]},
    }
    push_scheduler._check_n2_next_target(_make_user(), payload)

    assert not send_calls


def test_n2_skips_entry_outside_lead_window(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))

    payload = {
        'state': 'active',
        'timeline': {'is_inside_night': True},
        'plan': {'entries': [
            {'id': 'e1', 'name': 'M42', 'timeline_start': _now_iso(minutes=30), 'done': False},
        ]},
    }
    push_scheduler._check_n2_next_target(_make_user(), payload)

    assert not send_calls


def test_n2_uses_target_name_fallback_for_dedup(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))

    # Entry without 'id' - uses target_name for dedup key
    payload = {
        'state': 'active',
        'timeline': {'is_inside_night': True},
        'plan': {'entries': [
            {'target_name': 'NGC 224', 'name': 'Andromeda', 'timeline_start': _now_iso(minutes=2), 'done': False},
        ]},
    }
    user = _make_user()
    push_scheduler._check_n2_next_target(user, payload)
    push_scheduler._check_n2_next_target(user, payload)

    assert len(send_calls) == 1


# ---------------------------------------------------------------------------
# N6 - Astronomical darkness
# ---------------------------------------------------------------------------

def test_n6_sends_when_dusk_within_lead_window(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))

    cache = {'next_astronomical_dusk_utc': _now_iso(minutes=15), 'location': {'timezone': 'UTC'}}
    push_scheduler._check_n6_darkness(_make_user(), cache)

    assert len(send_calls) == 1 and send_calls[0][1] == 'N6'


def test_n6_skips_when_dusk_too_far_away(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))

    cache = {'next_astronomical_dusk_utc': _now_iso(hours=5), 'location': {'timezone': 'UTC'}}
    push_scheduler._check_n6_darkness(_make_user(), cache)

    assert not send_calls


def test_n6_skips_on_cooldown(monkeypatch):
    import push_scheduler
    push_scheduler._mark_notified('u1', 'N6')
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))

    cache = {'next_astronomical_dusk_utc': _now_iso(minutes=10), 'location': {'timezone': 'UTC'}}
    push_scheduler._check_n6_darkness(_make_user(), cache)

    assert not send_calls


# ---------------------------------------------------------------------------
# N3 - ISS transits
# ---------------------------------------------------------------------------

def test_n3_sends_for_upcoming_solar_transit(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))

    cache = {'solar_transits': [{'start_time': _now_iso(minutes=8)}], 'lunar_transits': []}
    push_scheduler._check_n3_iss(_make_user(), cache)

    assert len(send_calls) == 1
    assert 'solar' in send_calls[0][3].lower()


def test_n3_sends_for_upcoming_lunar_transit(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))

    cache = {'solar_transits': [], 'lunar_transits': [{'start_time': _now_iso(minutes=5)}]}
    push_scheduler._check_n3_iss(_make_user(), cache)

    assert len(send_calls) == 1
    assert 'lunar' in send_calls[0][3].lower()


def test_n3_picks_the_sooner_transit(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))

    cache = {
        'solar_transits': [{'start_time': _now_iso(minutes=9)}],
        'lunar_transits': [{'start_time': _now_iso(minutes=4)}],
    }
    push_scheduler._check_n3_iss(_make_user(), cache)

    assert len(send_calls) == 1
    assert 'lunar' in send_calls[0][3].lower()


def test_n3_skips_when_no_transits(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))

    cache = {'solar_transits': [], 'lunar_transits': []}
    push_scheduler._check_n3_iss(_make_user(), cache)

    assert not send_calls


def test_n3_skips_past_transits(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))

    cache = {
        'solar_transits': [{'start_time': _now_iso(minutes=-5)}],
        'lunar_transits': [],
    }
    push_scheduler._check_n3_iss(_make_user(), cache)

    assert not send_calls


# ---------------------------------------------------------------------------
# N4/N5 - Eclipse notifications
# ---------------------------------------------------------------------------

def test_n4_sends_for_upcoming_lunar_eclipse_peak(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))

    lunar_data = {'eclipse': {'peak_time': _now_iso(minutes=25)}}
    push_scheduler._check_n4_n5_eclipse(_make_user(), None, lunar_data)

    assert len(send_calls) == 1 and send_calls[0][1] == 'N4'


def test_n5_sends_for_upcoming_solar_eclipse_peak(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))

    solar_data = {'eclipse': {'peak_time': _now_iso(minutes=20)}}
    push_scheduler._check_n4_n5_eclipse(_make_user(), solar_data, None)

    assert len(send_calls) == 1 and send_calls[0][1] == 'N5'


def test_eclipse_skips_when_peak_too_far_away(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))

    lunar_data = {'eclipse': {'peak_time': _now_iso(hours=3)}}
    push_scheduler._check_n4_n5_eclipse(_make_user(), None, lunar_data)

    assert not send_calls


def test_eclipse_skips_past_peak(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))

    lunar_data = {'eclipse': {'peak_time': _now_iso(hours=-1)}}
    push_scheduler._check_n4_n5_eclipse(_make_user(), None, lunar_data)

    assert not send_calls


# ---------------------------------------------------------------------------
# _send - delivery and dead-subscription cleanup
# ---------------------------------------------------------------------------

def test_send_delivers_to_all_subscriptions_and_marks_notified(monkeypatch):
    import push_manager
    import push_scheduler

    delivered = []
    monkeypatch.setattr(push_manager, 'send_push', lambda sub_info, payload, **kw: delivered.append(sub_info['endpoint']) or True)

    user = _make_user(subscriptions=[
        {'endpoint': 'https://push.example.com/1', 'keys': {}},
        {'endpoint': 'https://push.example.com/2', 'keys': {}},
    ])
    push_scheduler._send(user, 'N7', 'Aurora Alert', 'Kp 6.5', '/aurora')

    assert sorted(delivered) == ['https://push.example.com/1', 'https://push.example.com/2']
    assert push_scheduler._was_recently_notified('u1', 'N7', 60)


def test_send_skips_user_with_no_subscriptions(monkeypatch):
    import push_manager
    import push_scheduler

    delivered = []
    monkeypatch.setattr(push_manager, 'send_push', lambda *a: delivered.append(1) or True)

    push_scheduler._send(_make_user(subscriptions=[]), 'N7', 'Title', 'Body', '/url')

    assert not delivered


def test_send_removes_dead_subscriptions(monkeypatch):
    import push_manager
    import push_scheduler

    monkeypatch.setattr(
        push_manager, 'send_push',
        lambda sub_info, payload, **kw: sub_info['endpoint'] != 'https://push.example.com/dead'
    )

    cleanup_calls = []
    monkeypatch.setattr(push_scheduler, '_cleanup_dead_subscriptions', lambda u, eps: cleanup_calls.append(eps))

    user = _make_user(subscriptions=[
        {'endpoint': 'https://push.example.com/alive', 'keys': {}},
        {'endpoint': 'https://push.example.com/dead', 'keys': {}},
    ])
    push_scheduler._send(user, 'N1', 'Title', 'Body', '/url')

    assert cleanup_calls == [['https://push.example.com/dead']]


def test_send_does_not_call_cleanup_when_all_succeed(monkeypatch):
    import push_manager
    import push_scheduler

    monkeypatch.setattr(push_manager, 'send_push', lambda *a, **kw: True)

    cleanup_calls = []
    monkeypatch.setattr(push_scheduler, '_cleanup_dead_subscriptions', lambda u, eps: cleanup_calls.append(eps))

    push_scheduler._send(_make_user(), 'N7', 'Title', 'Body', '/url')

    assert not cleanup_calls


# ---------------------------------------------------------------------------
# _cleanup_dead_subscriptions
# ---------------------------------------------------------------------------

def test_cleanup_removes_dead_endpoints_and_saves(monkeypatch):
    import auth
    import push_scheduler

    saved = []
    monkeypatch.setattr(auth.user_manager, 'save_users', lambda: saved.append(1))

    user = _make_user(subscriptions=[
        {'endpoint': 'https://push.example.com/alive', 'keys': {}},
        {'endpoint': 'https://push.example.com/dead', 'keys': {}},
    ])
    push_scheduler._cleanup_dead_subscriptions(user, ['https://push.example.com/dead'])

    remaining = [s['endpoint'] for s in user.push_subscriptions]
    assert remaining == ['https://push.example.com/alive']
    assert saved


def test_cleanup_handles_all_dead(monkeypatch):
    import auth
    import push_scheduler

    monkeypatch.setattr(auth.user_manager, 'save_users', lambda: None)

    user = _make_user(subscriptions=[
        {'endpoint': 'https://push.example.com/dead1', 'keys': {}},
        {'endpoint': 'https://push.example.com/dead2', 'keys': {}},
    ])
    push_scheduler._cleanup_dead_subscriptions(
        user, ['https://push.example.com/dead1', 'https://push.example.com/dead2']
    )

    assert user.push_subscriptions == []


# ---------------------------------------------------------------------------
# Lifecycle / lock / poll loop
# ---------------------------------------------------------------------------


def test_send_does_not_mark_notified_when_all_deliveries_fail(monkeypatch):
    import push_manager
    import push_scheduler

    monkeypatch.setattr(push_manager, 'send_push', lambda *a, **kw: False)
    push_scheduler._send(_make_user(), 'N7', 'Title', 'Body', '/url')

    assert not push_scheduler._was_recently_notified('u1', 'N7', 60)


def test_load_cache_returns_none_on_exception(monkeypatch):
    import push_scheduler

    class _FailingCacheModule:
        @staticmethod
        def load_shared_cache_entry(_k):
            raise RuntimeError('boom')

    monkeypatch.setitem(sys.modules, 'cache_store', _FailingCacheModule)
    assert push_scheduler._load_cache('any') is None


def test_pick_active_plan_prefers_inside_night(monkeypatch):
    import push_scheduler

    monkeypatch.setitem(
        sys.modules,
        'plan_my_night',
        types.SimpleNamespace(
            get_all_plan_files=lambda _uid: [
                '/x/u1_plan_telescope1.json',
                '/x/u1_plan_my_night.json',
            ],
            get_plan_with_timeline=lambda _uid, _u, telescope_id=None: (
                {'state': 'current', 'timeline': {'is_inside_night': False}, 'plan': {}}
                if telescope_id == 'telescope1'
                else {'state': 'current', 'timeline': {'is_inside_night': True}, 'plan': {}}
            ),
        ),
    )

    payload = push_scheduler._pick_active_plan('u1', 'alice')
    assert payload is not None
    assert payload.get('timeline', {}).get('is_inside_night') is True


def test_pick_active_plan_returns_none_when_import_fails(monkeypatch):
    import builtins
    import push_scheduler

    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == 'plan_my_night':
            raise ImportError('missing')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', _fake_import)
    assert push_scheduler._pick_active_plan('u1', 'alice') is None


def test_poll_sets_any_active_night_and_calls_checks(monkeypatch):
    import push_scheduler

    calls = []
    monkeypatch.setattr(push_scheduler, '_check_n7_aurora', lambda *a, **k: calls.append('n7'))
    monkeypatch.setattr(push_scheduler, '_check_n1_plan_start', lambda *a, **k: calls.append('n1'))
    monkeypatch.setattr(push_scheduler, '_check_n2_next_target', lambda *a, **k: calls.append('n2'))
    monkeypatch.setattr(push_scheduler, '_check_n6_darkness', lambda *a, **k: calls.append('n6'))
    monkeypatch.setattr(push_scheduler, '_check_n3_iss', lambda *a, **k: calls.append('n3'))
    monkeypatch.setattr(push_scheduler, '_check_n4_n5_eclipse', lambda *a, **k: calls.append('n45'))
    monkeypatch.setattr(push_scheduler, '_load_cache', lambda _k: {})
    monkeypatch.setattr(
        push_scheduler,
        '_pick_active_plan',
        lambda _uid, _name: {'state': 'current', 'timeline': {'is_inside_night': True}, 'plan': {}},
    )

    user = _make_user(user_id='u1', username='alice')
    fake_um = types.SimpleNamespace(users={'u1': user}, _reload_users_if_changed=lambda: None)
    monkeypatch.setitem(sys.modules, 'auth', types.SimpleNamespace(user_manager=fake_um))

    push_scheduler._poll()

    assert push_scheduler._any_active_night is True
    assert calls.count('n7') == 1
    assert calls.count('n45') == 1


def test_poll_skips_users_with_notifications_disabled_or_no_subscriptions(monkeypatch):
    import push_scheduler

    called = []
    monkeypatch.setattr(push_scheduler, '_check_n7_aurora', lambda *a, **k: called.append(1))
    monkeypatch.setattr(push_scheduler, '_load_cache', lambda _k: {})
    monkeypatch.setattr(push_scheduler, '_pick_active_plan', lambda *_a, **_k: None)

    u_disabled = _make_user(user_id='u1', username='disabled')
    u_disabled.preferences = {'notifications': {'enabled': False, 'triggers': {}}}
    u_no_sub = _make_user(user_id='u2', username='nosub', subscriptions=[])

    fake_um = types.SimpleNamespace(users={'u1': u_disabled, 'u2': u_no_sub}, _reload_users_if_changed=lambda: None)
    monkeypatch.setitem(sys.modules, 'auth', types.SimpleNamespace(user_manager=fake_um))

    push_scheduler._poll()
    assert not called


def test_start_does_not_spawn_when_lock_unavailable(monkeypatch):
    import push_scheduler

    push_scheduler._scheduler_thread = None
    monkeypatch.setattr(push_scheduler, '_acquire_lock', lambda: False)

    push_scheduler.start()
    assert push_scheduler._scheduler_thread is None


def test_start_spawns_thread_and_stop_sets_event(monkeypatch):
    import push_scheduler

    release_calls = []

    class _FakeThread:
        def __init__(self, target=None, name=None, daemon=None):
            self._alive = False
            self.target = target

        def start(self):
            self._alive = True

        def is_alive(self):
            return self._alive

    push_scheduler._scheduler_thread = None
    push_scheduler._stop_event.clear()
    monkeypatch.setattr(push_scheduler, '_acquire_lock', lambda: True)
    monkeypatch.setattr(push_scheduler.threading, 'Thread', _FakeThread)
    monkeypatch.setattr(push_scheduler, '_release_lock', lambda: release_calls.append(1))

    push_scheduler.start()
    assert push_scheduler._scheduler_thread is not None
    assert push_scheduler._scheduler_thread.is_alive() is True

    push_scheduler.stop()
    assert push_scheduler._stop_event.is_set() is True
    assert release_calls == [1]


def test_release_lock_handles_unlock_errors(monkeypatch, tmp_path):
    import push_scheduler

    lock_path = tmp_path / 'lock.tmp'
    fp = open(lock_path, 'w', encoding='utf-8')
    push_scheduler._lock_file = fp

    monkeypatch.setattr(push_scheduler.sys, 'platform', 'win32')
    monkeypatch.setattr(push_scheduler.msvcrt, 'locking', lambda *a, **k: (_ for _ in ()).throw(PermissionError('x')))

    push_scheduler._release_lock()
    assert push_scheduler._lock_file is None


def test_acquire_lock_success_and_failure(monkeypatch, tmp_path):
    import push_scheduler

    fake_constants = types.SimpleNamespace(DATA_DIR_CACHE=str(tmp_path))
    monkeypatch.setitem(sys.modules, 'constants', fake_constants)
    monkeypatch.setattr(push_scheduler.sys, 'platform', 'win32')
    monkeypatch.setattr(push_scheduler.msvcrt, 'locking', lambda *a, **k: None)

    assert push_scheduler._acquire_lock() is True
    assert push_scheduler._lock_file is not None
    push_scheduler._release_lock()

    monkeypatch.setattr(push_scheduler.msvcrt, 'locking', lambda *a, **k: (_ for _ in ()).throw(OSError('busy')))
    assert push_scheduler._acquire_lock() is False


# ---------------------------------------------------------------------------
# Additional branch coverage
# ---------------------------------------------------------------------------

def test_n7_non_numeric_kp_skips(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))
    cache = {'current': {'kp_index': 'not-a-number', 'visibility_level': 'Low'}}
    push_scheduler._check_n7_aurora(_make_user(), cache)
    assert not send_calls


def test_n1_disabled_skips(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))
    user = _make_user(triggers={'N1': {'enabled': False}})
    payload = {'state': 'pending', 'timeline': {'is_inside_night': False},
               'plan': {'night_start': _now_iso(minutes=10)}}
    push_scheduler._check_n1_plan_start(user, payload)
    assert not send_calls


def test_n1_no_night_start_skips(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))
    payload = {'state': 'pending', 'timeline': {'is_inside_night': False}, 'plan': {}}
    push_scheduler._check_n1_plan_start(_make_user(), payload)
    assert not send_calls


def test_n1_naive_datetime_handled(monkeypatch):
    """Naive datetime in night_start is treated as UTC."""
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))
    from datetime import datetime, timedelta
    # Naive ISO string (no +00:00)
    naive_start = (datetime.utcnow() + timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M:%S')
    payload = {'state': 'pending', 'timeline': {'is_inside_night': False},
               'plan': {'night_start': naive_start}}
    push_scheduler._check_n1_plan_start(_make_user(), payload)
    # May or may not send depending on lead window, but should not crash


def test_n1_exception_in_date_parsing_swallowed(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))
    payload = {'state': 'pending', 'timeline': {'is_inside_night': False},
               'plan': {'night_start': 'not-a-date'}}
    push_scheduler._check_n1_plan_start(_make_user(), payload)
    assert not send_calls  # Exception handled gracefully


def test_n2_disabled_skips(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))
    user = _make_user(triggers={'N2': {'enabled': False}})
    payload = {'state': 'active', 'timeline': {'is_inside_night': True},
               'plan': {'entries': [{'id': 'e1', 'name': 'M42',
                                     'timeline_start': _now_iso(minutes=3), 'done': False}]}}
    push_scheduler._check_n2_next_target(user, payload)
    assert not send_calls


def test_n2_past_entry_skipped(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))
    payload = {'state': 'active', 'timeline': {'is_inside_night': True},
               'plan': {'entries': [{'id': 'e1', 'name': 'M42',
                                     'timeline_start': _now_iso(minutes=-10), 'done': False}]}}
    push_scheduler._check_n2_next_target(_make_user(), payload)
    assert not send_calls


def test_n2_no_start_str_entry_skipped(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))
    payload = {'state': 'active', 'timeline': {'is_inside_night': True},
               'plan': {'entries': [{'id': 'e1', 'name': 'M42', 'done': False}]}}
    push_scheduler._check_n2_next_target(_make_user(), payload)
    assert not send_calls


def test_n2_bad_date_exception_swallowed(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))
    payload = {'state': 'active', 'timeline': {'is_inside_night': True},
               'plan': {'entries': [{'id': 'e1', 'name': 'M42',
                                     'timeline_start': 'not-a-date', 'done': False}]}}
    push_scheduler._check_n2_next_target(_make_user(), payload)
    assert not send_calls


def test_n6_no_cache_skips(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))
    push_scheduler._check_n6_darkness(_make_user(), None)
    assert not send_calls


def test_n6_disabled_skips(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))
    user = _make_user(triggers={'N6': {'enabled': False}})
    push_scheduler._check_n6_darkness(user, {'next_astronomical_dusk_utc': _now_iso(minutes=10)})
    assert not send_calls


def test_n6_no_dusk_str_skips(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))
    push_scheduler._check_n6_darkness(_make_user(), {'location': {}})
    assert not send_calls


def test_n6_exception_in_parsing_swallowed(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))
    push_scheduler._check_n6_darkness(_make_user(), {'next_astronomical_dusk_utc': 'bad-date'})
    assert not send_calls


def test_n6_naive_dusk_handled(monkeypatch):
    import push_scheduler
    from datetime import datetime, timedelta
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))
    naive = (datetime.utcnow() + timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M:%S')
    push_scheduler._check_n6_darkness(_make_user(), {'next_astronomical_dusk_utc': naive})
    # Should not crash - may or may not send


def test_n3_no_cache_skips(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))
    push_scheduler._check_n3_iss(_make_user(), None)
    assert not send_calls


def test_n3_disabled_skips(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))
    user = _make_user(triggers={'N3': {'enabled': False}})
    push_scheduler._check_n3_iss(user, {'solar_transits': [{'start_time': _now_iso(minutes=5)}],
                                         'lunar_transits': []})
    assert not send_calls


def test_n3_transit_outside_lead_no_notification(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))
    cache = {'solar_transits': [{'start_time': _now_iso(minutes=30)}], 'lunar_transits': []}
    push_scheduler._check_n3_iss(_make_user(), cache)
    assert not send_calls


def test_n3_cooldown_active_skips(monkeypatch):
    import push_scheduler
    push_scheduler._mark_notified('u1', 'N3')
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))
    cache = {'solar_transits': [{'start_time': _now_iso(minutes=5)}], 'lunar_transits': []}
    push_scheduler._check_n3_iss(_make_user(), cache)
    assert not send_calls


def test_n3_no_start_str_in_transit_skipped(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))
    cache = {'solar_transits': [{}], 'lunar_transits': [{}]}
    push_scheduler._check_n3_iss(_make_user(), cache)
    assert not send_calls


def test_n3_bad_timestamp_in_transit_swallowed(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))
    cache = {'solar_transits': [{'start_time': 'bad-date'}], 'lunar_transits': []}
    push_scheduler._check_n3_iss(_make_user(), cache)
    assert not send_calls


def test_n4n5_disabled_skips(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))
    user = _make_user(triggers={'N4': {'enabled': False}, 'N5': {'enabled': False}})
    push_scheduler._check_n4_n5_eclipse(user, {'eclipse': {'peak_time': _now_iso(minutes=20)}},
                                         {'eclipse': {'peak_time': _now_iso(minutes=20)}})
    assert not send_calls


def test_n4_no_peak_time_skips(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))
    push_scheduler._check_n4_n5_eclipse(_make_user(), None, {'eclipse': {}})
    assert not send_calls


def test_n4_bad_peak_time_exception_swallowed(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))
    push_scheduler._check_n4_n5_eclipse(_make_user(), None, {'eclipse': {'peak_time': 'bad-date'}})
    assert not send_calls


def test_cleanup_exception_handler(monkeypatch):
    """_cleanup_dead_subscriptions swallows exceptions."""
    import push_scheduler
    import auth
    monkeypatch.setattr(auth.user_manager, 'save_users', lambda: (_ for _ in ()).throw(Exception('db fail')))
    user = _make_user(subscriptions=[{'endpoint': 'https://push.example.com/dead', 'keys': {}}])
    # Should not raise
    push_scheduler._cleanup_dead_subscriptions(user, ['https://push.example.com/dead'])


def test_load_cache_returns_none_when_entry_is_none(monkeypatch):
    import push_scheduler

    class _NullCacheModule:
        @staticmethod
        def load_shared_cache_entry(_k):
            return None

    monkeypatch.setitem(sys.modules, 'cache_store', _NullCacheModule)
    result = push_scheduler._load_cache('any')
    assert result is None


def test_pick_active_plan_no_plan_files(monkeypatch):
    import push_scheduler
    monkeypatch.setitem(
        sys.modules,
        'plan_my_night',
        types.SimpleNamespace(
            get_all_plan_files=lambda _uid: [],
            get_plan_with_timeline=lambda *a, **k: {},
        ),
    )
    result = push_scheduler._pick_active_plan('u1', 'alice')
    assert result is None


def test_pick_active_plan_file_wrong_prefix_skipped(monkeypatch):
    """Files not matching user prefix are skipped."""
    import push_scheduler
    monkeypatch.setitem(
        sys.modules,
        'plan_my_night',
        types.SimpleNamespace(
            get_all_plan_files=lambda _uid: ['/x/u2_plan_my_night.json'],
            get_plan_with_timeline=lambda *a, **k: {'state': 'current',
                                                     'timeline': {'is_inside_night': False}},
        ),
    )
    result = push_scheduler._pick_active_plan('u1', 'alice')
    assert result is None  # Wrong user prefix


def test_pick_active_plan_state_none_excluded(monkeypatch):
    """Plans with state='none' are excluded from candidates."""
    import push_scheduler
    monkeypatch.setitem(
        sys.modules,
        'plan_my_night',
        types.SimpleNamespace(
            get_all_plan_files=lambda _uid: ['/x/u1_plan_my_night.json'],
            get_plan_with_timeline=lambda *a, **k: {'state': 'none',
                                                     'timeline': {'is_inside_night': False}},
        ),
    )
    result = push_scheduler._pick_active_plan('u1', 'alice')
    assert result is None


def test_pick_active_plan_exception_loading_plan(monkeypatch):
    """Exception when loading a plan is swallowed."""
    import push_scheduler
    monkeypatch.setitem(
        sys.modules,
        'plan_my_night',
        types.SimpleNamespace(
            get_all_plan_files=lambda _uid: ['/x/u1_plan_my_night.json'],
            get_plan_with_timeline=lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')),
        ),
    )
    result = push_scheduler._pick_active_plan('u1', 'alice')
    assert result is None


def test_start_skips_when_thread_already_alive(monkeypatch):
    """start() is a no-op if scheduler thread is alive."""
    import push_scheduler
    alive_thread = MagicMock()
    alive_thread.is_alive.return_value = True
    push_scheduler._scheduler_thread = alive_thread
    acquire_calls = []
    monkeypatch.setattr(push_scheduler, '_acquire_lock', lambda: acquire_calls.append(True) or True)
    push_scheduler.start()
    assert not acquire_calls  # Lock not acquired because thread already alive


def test_poll_no_night_start_skips_active_check(monkeypatch):
    """Line 549->562: is_inside_night=False and no night_start → False branch."""
    import push_scheduler

    calls = []
    monkeypatch.setattr(push_scheduler, '_check_n7_aurora', lambda *a, **k: calls.append('n7'))
    monkeypatch.setattr(push_scheduler, '_check_n1_plan_start', lambda *a, **k: None)
    monkeypatch.setattr(push_scheduler, '_check_n2_next_target', lambda *a, **k: None)
    monkeypatch.setattr(push_scheduler, '_check_n6_darkness', lambda *a, **k: None)
    monkeypatch.setattr(push_scheduler, '_check_n3_iss', lambda *a, **k: None)
    monkeypatch.setattr(push_scheduler, '_check_n4_n5_eclipse', lambda *a, **k: None)
    monkeypatch.setattr(push_scheduler, '_load_cache', lambda _k: {})
    monkeypatch.setattr(
        push_scheduler, '_pick_active_plan',
        lambda _uid, _name: {
            'state': 'current',
            'timeline': {'is_inside_night': False},
            'plan': {},  # no night_start key
        },
    )
    user = _make_user(user_id='u1', username='alice')
    fake_um = types.SimpleNamespace(users={'u1': user}, _reload_users_if_changed=lambda: None)
    monkeypatch.setitem(sys.modules, 'auth', types.SimpleNamespace(user_manager=fake_um))

    push_scheduler._poll()

    assert calls.count('n7') == 1
    assert push_scheduler._any_active_night is False


def test_run_calls_poll_once_then_exits(monkeypatch):
    """Lines 576-581: _run() executes loop body once then exits when stop event set."""
    import push_scheduler

    push_scheduler._stop_event.clear()
    poll_calls = []

    def _poll_and_stop():
        poll_calls.append(1)
        push_scheduler._stop_event.set()

    monkeypatch.setattr(push_scheduler, '_poll', _poll_and_stop)
    push_scheduler._run()
    push_scheduler._stop_event.clear()

    assert poll_calls == [1]


def test_acquire_lock_open_fails_returns_false(monkeypatch, tmp_path):
    """Line 610->613: open() raises → _lock_file stays None → if block skipped → return False."""
    import push_scheduler
    import builtins

    push_scheduler._lock_file = None

    real_open = builtins.open

    def _failing_open(path, *args, **kwargs):
        if 'push_scheduler.lock' in str(path):
            raise OSError('permission denied')
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, 'open', _failing_open)
    fake_constants = types.SimpleNamespace(DATA_DIR_CACHE=str(tmp_path))
    monkeypatch.setitem(sys.modules, 'constants', fake_constants)

    result = push_scheduler._acquire_lock()

    assert result is False
    assert push_scheduler._lock_file is None


def test_poll_fast_mode_via_pending_night(monkeypatch):
    """Poll detects a plan with night starting within 30 min and sets any_active."""
    import push_scheduler
    from datetime import datetime, timedelta, timezone as tz

    soon_start = (datetime.now(tz.utc) + timedelta(minutes=10)).isoformat()

    for fn in ('_check_n7_aurora', '_check_n1_plan_start', '_check_n2_next_target',
               '_check_n6_darkness', '_check_n3_iss', '_check_n4_n5_eclipse'):
        monkeypatch.setattr(push_scheduler, fn, lambda *a, **k: None)
    monkeypatch.setattr(push_scheduler, '_load_cache', lambda _k: {})
    monkeypatch.setattr(
        push_scheduler,
        '_pick_active_plan',
        lambda _uid, _name: {'state': 'current',
                              'timeline': {'is_inside_night': False},
                              'plan': {'night_start': soon_start}},
    )

    user = _make_user(user_id='u1', username='alice')
    fake_um = types.SimpleNamespace(users={'u1': user}, _reload_users_if_changed=lambda: None)
    monkeypatch.setitem(sys.modules, 'auth', types.SimpleNamespace(user_manager=fake_um))

    push_scheduler._poll()
    assert push_scheduler._any_active_night is True


# ---------------------------------------------------------------------------
# Additional branch coverage tests
# ---------------------------------------------------------------------------

def test_n2_skips_when_payload_none(monkeypatch):
    """Lines 232-233: _check_n2_next_target returns early when payload is None."""
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))
    push_scheduler._check_n2_next_target(_make_user(), None)
    assert not send_calls


def test_n2_skips_when_state_none(monkeypatch):
    """Lines 232-233: _check_n2_next_target returns early when state='none'."""
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))
    push_scheduler._check_n2_next_target(_make_user(), {'state': 'none'})
    assert not send_calls


def test_n2_naive_datetime_in_entry_gets_utc(monkeypatch):
    """Line 259: naive timeline_start is treated as UTC (tzinfo=None branch)."""
    import push_scheduler
    from datetime import datetime, timedelta, timezone as tz
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))
    soon = (datetime.utcnow() + timedelta(minutes=3)).strftime('%Y-%m-%dT%H:%M:%S')  # naive
    plan_payload = {
        'state': 'current',
        'timeline': {'is_inside_night': True},
        'plan': {
            'entries': [{'done': False, 'timeline_start': soon, 'name': 'M31', 'id': 'x_naive'}]
        },
    }
    # Clear N2 notified state so cooldown doesn't interfere
    push_scheduler._n2_notified.clear()
    push_scheduler._check_n2_next_target(_make_user(), plan_payload)
    # send may or may not fire, but must not raise


def test_n6_bad_timezone_name_falls_back_to_empty(monkeypatch):
    """Lines 324-325: ZoneInfo(bad_tz_name) raises, dusk_local_time falls back to ''."""
    import push_scheduler
    from datetime import datetime, timedelta, timezone as tz
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))
    # Clear cooldown
    push_scheduler._last_sent.pop(_make_user().user_id, None)
    soon = (datetime.now(tz.utc) + timedelta(minutes=5)).isoformat()
    cache = {
        'next_astronomical_dusk_utc': soon,
        'location': {'timezone': 'NOT/A_REAL_TIMEZONE'},
    }
    push_scheduler._check_n6_darkness(_make_user(), cache)
    # Should not raise; _send may be called with dusk_local_time=''


def test_n3_solar_naive_datetime_gets_utc(monkeypatch):
    """Line 358: naive solar transit start_time is replaced with UTC."""
    import push_scheduler
    from datetime import datetime, timedelta
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))
    push_scheduler._last_sent.clear()
    soon = (datetime.utcnow() + timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M:%S')  # naive
    cache = {'solar_transits': [{'start_time': soon}], 'lunar_transits': []}
    push_scheduler._check_n3_iss(_make_user(), cache)
    # Must not raise


def test_n3_lunar_naive_datetime_gets_utc(monkeypatch):
    """Line 369: naive lunar transit start_time is replaced with UTC."""
    import push_scheduler
    from datetime import datetime, timedelta
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))
    push_scheduler._last_sent.clear()
    soon = (datetime.utcnow() + timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M:%S')  # naive
    cache = {'solar_transits': [], 'lunar_transits': [{'start_time': soon}]}
    push_scheduler._check_n3_iss(_make_user(), cache)
    # Must not raise


def test_n3_bad_lunar_timestamp_exception_swallowed(monkeypatch):
    """Lines 372-373: bad lunar transit timestamp is swallowed."""
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))
    cache = {'solar_transits': [], 'lunar_transits': [{'start_time': 'not-a-date'}]}
    push_scheduler._check_n3_iss(_make_user(), cache)
    assert not send_calls


def test_n4_naive_peak_datetime_gets_utc(monkeypatch):
    """Line 424: naive peak_time in lunar eclipse data is replaced with UTC."""
    import push_scheduler
    from datetime import datetime, timedelta
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))
    push_scheduler._last_sent.clear()
    soon = (datetime.utcnow() + timedelta(minutes=20)).strftime('%Y-%m-%dT%H:%M:%S')  # naive
    lunar_data = {'eclipse': {'peak_time': soon}}
    push_scheduler._check_n4_n5_eclipse(_make_user(), None, lunar_data)
    # Must not raise


def test_pick_active_plan_fallback_returns_current_state(monkeypatch):
    """Lines 504-506: when no candidate is_inside_night, return first with state='current'."""
    import push_scheduler
    monkeypatch.setitem(
        sys.modules,
        'plan_my_night',
        types.SimpleNamespace(
            get_all_plan_files=lambda _uid: [
                '/x/u1_plan_my_night.json',
                '/x/u1_plan_scope2.json',
            ],
            get_plan_with_timeline=lambda uid, uname, telescope_id=None: {
                'state': 'current',
                'timeline': {'is_inside_night': False},
            },
        ),
    )
    result = push_scheduler._pick_active_plan('u1', 'alice')
    assert result is not None
    assert result['state'] == 'current'


def test_pick_active_plan_fallback_returns_first_candidate(monkeypatch):
    """Line 507: when no candidate is state='current', return candidates[0]."""
    import push_scheduler
    monkeypatch.setitem(
        sys.modules,
        'plan_my_night',
        types.SimpleNamespace(
            get_all_plan_files=lambda _uid: ['/x/u1_plan_my_night.json'],
            get_plan_with_timeline=lambda uid, uname, telescope_id=None: {
                'state': 'future',
                'timeline': {'is_inside_night': False},
            },
        ),
    )
    result = push_scheduler._pick_active_plan('u1', 'alice')
    assert result is not None
    assert result['state'] == 'future'


def test_poll_outer_exception_swallowed(monkeypatch):
    """Lines 569-570: outer exception in _poll() is caught and logged."""
    import push_scheduler
    # Make user_manager import raise inside the poll try block
    bad_auth = types.SimpleNamespace(
        user_manager=types.SimpleNamespace(
            users={},
            _reload_users_if_changed=lambda: (_ for _ in ()).throw(RuntimeError('reload boom')),
        )
    )
    monkeypatch.setitem(sys.modules, 'auth', bad_auth)
    push_scheduler._poll()  # Must not raise


def test_poll_bad_night_start_exception_swallowed(monkeypatch):
    """Lines 559-560: unparseable night_start causes inner exception that is swallowed."""
    import push_scheduler
    for fn in ('_check_n7_aurora', '_check_n1_plan_start', '_check_n2_next_target',
               '_check_n6_darkness', '_check_n3_iss', '_check_n4_n5_eclipse'):
        monkeypatch.setattr(push_scheduler, fn, lambda *a, **k: None)
    monkeypatch.setattr(push_scheduler, '_load_cache', lambda _k: {})
    monkeypatch.setattr(
        push_scheduler,
        '_pick_active_plan',
        lambda _uid, _name: {
            'state': 'current',
            'timeline': {'is_inside_night': False},
            'plan': {'night_start': 'NOT_A_DATE'},  # triggers except at line 559
        },
    )
    user = _make_user(user_id='u1', username='alice')
    fake_um = types.SimpleNamespace(users={'u1': user}, _reload_users_if_changed=lambda: None)
    monkeypatch.setitem(sys.modules, 'auth', types.SimpleNamespace(user_manager=fake_um))
    push_scheduler._poll()  # Must not raise


def test_release_lock_when_no_lock_file(monkeypatch):
    """Line 619: _release_lock() is a no-op when _lock_file is None."""
    import push_scheduler
    push_scheduler._lock_file = None
    push_scheduler._release_lock()  # Must not raise


def test_n3_past_lunar_transit_not_added_to_candidates(monkeypatch):
    """Branch 370→363: lunar transit in the PAST is not added to candidates (dt <= now)."""
    import push_scheduler
    from datetime import datetime, timedelta
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a, **kw: send_calls.append(a))
    push_scheduler._last_sent.clear()
    # Past transit → dt < now → loop continues without appending
    past = (datetime.utcnow() - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
    cache = {'solar_transits': [], 'lunar_transits': [{'start_time': past}]}
    push_scheduler._check_n3_iss(_make_user(), cache)
    assert not send_calls  # No candidate → no notification


def test_poll_no_plan_skips_fast_mode_detection(monkeypatch):
    """Branch 542→562: when plan_payload is None, fast-mode block is skipped."""
    import push_scheduler
    for fn in ('_check_n7_aurora', '_check_n1_plan_start', '_check_n2_next_target',
               '_check_n6_darkness', '_check_n3_iss', '_check_n4_n5_eclipse'):
        monkeypatch.setattr(push_scheduler, fn, lambda *a, **k: None)
    monkeypatch.setattr(push_scheduler, '_load_cache', lambda _k: {})
    monkeypatch.setattr(push_scheduler, '_pick_active_plan', lambda _uid, _name: None)
    user = _make_user(user_id='u1', username='alice')
    fake_um = types.SimpleNamespace(users={'u1': user}, _reload_users_if_changed=lambda: None)
    monkeypatch.setitem(sys.modules, 'auth', types.SimpleNamespace(user_manager=fake_um))
    push_scheduler._poll()
    assert push_scheduler._any_active_night is False


def test_poll_night_start_naive_gets_utc(monkeypatch):
    """Line 555: naive night_start string is given UTC tz (tzinfo=None branch)."""
    import push_scheduler
    from datetime import datetime, timedelta
    for fn in ('_check_n7_aurora', '_check_n1_plan_start', '_check_n2_next_target',
               '_check_n6_darkness', '_check_n3_iss', '_check_n4_n5_eclipse'):
        monkeypatch.setattr(push_scheduler, fn, lambda *a, **k: None)
    monkeypatch.setattr(push_scheduler, '_load_cache', lambda _k: {})
    # Naive datetime string for night_start, 10 min from now → active
    soon_naive = (datetime.utcnow() + timedelta(minutes=10)).strftime('%Y-%m-%dT%H:%M:%S')
    monkeypatch.setattr(
        push_scheduler, '_pick_active_plan',
        lambda _uid, _name: {
            'state': 'current',
            'timeline': {'is_inside_night': False},
            'plan': {'night_start': soon_naive},  # naive → branch 555
        },
    )
    user = _make_user(user_id='u1', username='alice')
    fake_um = types.SimpleNamespace(users={'u1': user}, _reload_users_if_changed=lambda: None)
    monkeypatch.setitem(sys.modules, 'auth', types.SimpleNamespace(user_manager=fake_um))
    push_scheduler._poll()  # Must not raise


def test_poll_night_start_far_future_not_fast_mode(monkeypatch):
    """Branch 557→562: secs_until > 30*60 → any_active stays False."""
    import push_scheduler
    from datetime import datetime, timedelta, timezone as tz
    for fn in ('_check_n7_aurora', '_check_n1_plan_start', '_check_n2_next_target',
               '_check_n6_darkness', '_check_n3_iss', '_check_n4_n5_eclipse'):
        monkeypatch.setattr(push_scheduler, fn, lambda *a, **k: None)
    monkeypatch.setattr(push_scheduler, '_load_cache', lambda _k: {})
    far_future = (datetime.now(tz.utc) + timedelta(hours=2)).isoformat()
    monkeypatch.setattr(
        push_scheduler, '_pick_active_plan',
        lambda _uid, _name: {
            'state': 'current',
            'timeline': {'is_inside_night': False},
            'plan': {'night_start': far_future},  # 2h away → not inside 30-min window
        },
    )
    user = _make_user(user_id='u1', username='alice')
    fake_um = types.SimpleNamespace(users={'u1': user}, _reload_users_if_changed=lambda: None)
    monkeypatch.setitem(sys.modules, 'auth', types.SimpleNamespace(user_manager=fake_um))
    push_scheduler._poll()
    assert push_scheduler._any_active_night is False


def test_release_lock_logger_failure_swallowed(monkeypatch):
    """Lines 629-630: nested logger error in _release_lock is silently swallowed."""
    import push_scheduler
    from unittest.mock import MagicMock
    mock_file = MagicMock()
    mock_file.fileno.side_effect = OSError('fd closed')
    push_scheduler._lock_file = mock_file
    # Also patch the logger to raise when error() is called
    import logging
    monkeypatch.setattr(push_scheduler.logger, 'error', lambda *a, **k: (_ for _ in ()).throw(ValueError('log closed')))
    push_scheduler._release_lock()  # Must not raise
    assert push_scheduler._lock_file is None
