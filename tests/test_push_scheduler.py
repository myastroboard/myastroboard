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
# N7 — Aurora
# ---------------------------------------------------------------------------

def test_n7_sends_when_kp_meets_threshold(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a: send_calls.append(a))

    cache = {'current': {'kp_index': 6.0, 'visibility_level': 'High'}}
    push_scheduler._check_n7_aurora(_make_user(), cache)

    assert len(send_calls) == 1 and send_calls[0][1] == 'N7'


def test_n7_skips_when_kp_below_default_threshold(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a: send_calls.append(a))

    cache = {'current': {'kp_index': 3.0, 'visibility_level': 'Low'}}
    push_scheduler._check_n7_aurora(_make_user(), cache)

    assert not send_calls


def test_n7_respects_custom_kp_threshold(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a: send_calls.append(a))

    user = _make_user(triggers={'N7': {'enabled': True, 'kp_threshold': 8}})
    cache = {'current': {'kp_index': 7.0, 'visibility_level': 'High'}}
    push_scheduler._check_n7_aurora(user, cache)

    assert not send_calls


def test_n7_skips_when_disabled(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a: send_calls.append(a))

    user = _make_user(triggers={'N7': {'enabled': False}})
    cache = {'current': {'kp_index': 9.0, 'visibility_level': 'Extreme'}}
    push_scheduler._check_n7_aurora(user, cache)

    assert not send_calls


def test_n7_skips_on_cooldown(monkeypatch):
    import push_scheduler
    push_scheduler._mark_notified('u1', 'N7')
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a: send_calls.append(a))

    cache = {'current': {'kp_index': 8.0, 'visibility_level': 'High'}}
    push_scheduler._check_n7_aurora(_make_user(), cache)

    assert not send_calls


def test_n7_skips_when_cache_is_none(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a: send_calls.append(a))

    push_scheduler._check_n7_aurora(_make_user(), None)
    assert not send_calls


# ---------------------------------------------------------------------------
# N1 — Plan start
# ---------------------------------------------------------------------------

def test_n1_sends_when_night_starts_within_lead_window(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a: send_calls.append(a))

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
    monkeypatch.setattr(push_scheduler, '_send', lambda *a: send_calls.append(a))

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
    monkeypatch.setattr(push_scheduler, '_send', lambda *a: send_calls.append(a))

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
    monkeypatch.setattr(push_scheduler, '_send', lambda *a: send_calls.append(a))

    push_scheduler._check_n1_plan_start(_make_user(), None)
    push_scheduler._check_n1_plan_start(_make_user(), {'state': 'none'})

    assert not send_calls


def test_n1_respects_custom_lead_minutes(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a: send_calls.append(a))

    user = _make_user(triggers={'N1': {'enabled': True, 'lead_minutes': 5}})
    payload = {
        'state': 'pending',
        'timeline': {'is_inside_night': False},
        'plan': {'night_start': _now_iso(minutes=10)},  # outside 5-min window
    }
    push_scheduler._check_n1_plan_start(user, payload)

    assert not send_calls


# ---------------------------------------------------------------------------
# N2 — Next target
# ---------------------------------------------------------------------------

def test_n2_sends_for_upcoming_entry(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a: send_calls.append(a))

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
    monkeypatch.setattr(push_scheduler, '_send', lambda *a: send_calls.append(a))

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
    monkeypatch.setattr(push_scheduler, '_send', lambda *a: send_calls.append(a))

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
    monkeypatch.setattr(push_scheduler, '_send', lambda *a: send_calls.append(a))

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
    monkeypatch.setattr(push_scheduler, '_send', lambda *a: send_calls.append(a))

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
    monkeypatch.setattr(push_scheduler, '_send', lambda *a: send_calls.append(a))

    # Entry without 'id' — uses target_name for dedup key
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
# N6 — Astronomical darkness
# ---------------------------------------------------------------------------

def test_n6_sends_when_dusk_within_lead_window(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a: send_calls.append(a))

    cache = {'sun': {'astronomical_dusk': _now_iso(minutes=15)}}
    push_scheduler._check_n6_darkness(_make_user(), cache)

    assert len(send_calls) == 1 and send_calls[0][1] == 'N6'


def test_n6_skips_when_dusk_too_far_away(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a: send_calls.append(a))

    cache = {'sun': {'astronomical_dusk': _now_iso(hours=5)}}
    push_scheduler._check_n6_darkness(_make_user(), cache)

    assert not send_calls


def test_n6_skips_on_cooldown(monkeypatch):
    import push_scheduler
    push_scheduler._mark_notified('u1', 'N6')
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a: send_calls.append(a))

    cache = {'sun': {'astronomical_dusk': _now_iso(minutes=10)}}
    push_scheduler._check_n6_darkness(_make_user(), cache)

    assert not send_calls


# ---------------------------------------------------------------------------
# N3 — ISS transits
# ---------------------------------------------------------------------------

def test_n3_sends_for_upcoming_solar_transit(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a: send_calls.append(a))

    cache = {'solar_transits': [{'start_time': _now_iso(minutes=8)}], 'lunar_transits': []}
    push_scheduler._check_n3_iss(_make_user(), cache)

    assert len(send_calls) == 1
    assert 'solar' in send_calls[0][3].lower()


def test_n3_sends_for_upcoming_lunar_transit(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a: send_calls.append(a))

    cache = {'solar_transits': [], 'lunar_transits': [{'start_time': _now_iso(minutes=5)}]}
    push_scheduler._check_n3_iss(_make_user(), cache)

    assert len(send_calls) == 1
    assert 'lunar' in send_calls[0][3].lower()


def test_n3_picks_the_sooner_transit(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a: send_calls.append(a))

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
    monkeypatch.setattr(push_scheduler, '_send', lambda *a: send_calls.append(a))

    cache = {'solar_transits': [], 'lunar_transits': []}
    push_scheduler._check_n3_iss(_make_user(), cache)

    assert not send_calls


def test_n3_skips_past_transits(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a: send_calls.append(a))

    cache = {
        'solar_transits': [{'start_time': _now_iso(minutes=-5)}],
        'lunar_transits': [],
    }
    push_scheduler._check_n3_iss(_make_user(), cache)

    assert not send_calls


# ---------------------------------------------------------------------------
# N4/N5 — Eclipse notifications
# ---------------------------------------------------------------------------

def test_n4_sends_for_upcoming_lunar_eclipse_peak(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a: send_calls.append(a))

    lunar_data = {'eclipse': {'peak_time': _now_iso(minutes=25)}}
    push_scheduler._check_n4_n5_eclipse(_make_user(), None, lunar_data)

    assert len(send_calls) == 1 and send_calls[0][1] == 'N4'


def test_n5_sends_for_upcoming_solar_eclipse_peak(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a: send_calls.append(a))

    solar_data = {'eclipse': {'peak_time': _now_iso(minutes=20)}}
    push_scheduler._check_n4_n5_eclipse(_make_user(), solar_data, None)

    assert len(send_calls) == 1 and send_calls[0][1] == 'N5'


def test_eclipse_skips_when_peak_too_far_away(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a: send_calls.append(a))

    lunar_data = {'eclipse': {'peak_time': _now_iso(hours=3)}}
    push_scheduler._check_n4_n5_eclipse(_make_user(), None, lunar_data)

    assert not send_calls


def test_eclipse_skips_past_peak(monkeypatch):
    import push_scheduler
    send_calls = []
    monkeypatch.setattr(push_scheduler, '_send', lambda *a: send_calls.append(a))

    lunar_data = {'eclipse': {'peak_time': _now_iso(hours=-1)}}
    push_scheduler._check_n4_n5_eclipse(_make_user(), None, lunar_data)

    assert not send_calls


# ---------------------------------------------------------------------------
# _send — delivery and dead-subscription cleanup
# ---------------------------------------------------------------------------

def test_send_delivers_to_all_subscriptions_and_marks_notified(monkeypatch):
    import push_manager
    import push_scheduler

    delivered = []
    monkeypatch.setattr(push_manager, 'send_push', lambda sub_info, payload: delivered.append(sub_info['endpoint']) or True)

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
        lambda sub_info, payload: sub_info['endpoint'] != 'https://push.example.com/dead'
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

    monkeypatch.setattr(push_manager, 'send_push', lambda *a: True)

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
