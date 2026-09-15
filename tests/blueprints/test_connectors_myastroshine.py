"""Route tests for the MyAstroShine integration blueprint.

GET  /api/astrodex/integration/status
GET  /api/connectors/myastroshine/health
POST /api/connectors/myastroshine/health
POST /api/astrodex/integration/handoff
GET  /api/astrodex/integration/source
GET  /api/astrodex/integration/source/image
POST /api/astrodex/integration/enhanced

plus this connector's slice of the shared card routes:
GET  /api/connectors
POST /api/connectors/myastroshine/config
"""

import hashlib
import hmac
import io
import json
import os
import sys
import tempfile
import types

import pytest

if "psutil" not in sys.modules:
    sys.modules["psutil"] = types.ModuleType("psutil")

from observation import astrodex
from connectors.myastroshine_connector import MyAstroShineConnector
from observation import myastroshine_integration as integration
from utils.auth import user_manager

_TOKEN = "mas_abcdef123456extrachars"
_SECRET = "s" * 64


def _cfg(**overrides):
    cfg = {
        "enabled": True,
        "url": "http://192.168.1.42:8002",
        "token": _TOKEN,
        "signing_secret": _SECRET,
        "callback_url_override": "",
        "copy_rating": False,
        "label": "",
    }
    cfg.update(overrides)
    return cfg


@pytest.fixture
def admin_id():
    user = user_manager.get_user_by_username("admin")
    assert user is not None
    return user.user_id


@pytest.fixture
def client_admin():
    from app import app as flask_app

    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        user = user_manager.get_user_by_username("admin")
        with c.session_transaction() as sess:
            sess["user_id"] = user.user_id
            sess["username"] = user.username
            sess["role"] = user.role
        yield c


@pytest.fixture
def client():
    from app import app as flask_app

    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


@pytest.fixture
def env(monkeypatch):
    """Temp DATA_DIR, clean consumed store, integration config forced to _cfg()."""
    from blueprints import connectors_myastroshine as _bp

    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setenv("DATA_DIR", tmpdir)
        astrodex.ASTRODEX_DIR = os.path.join(tmpdir, "astrodex")
        astrodex.ASTRODEX_IMAGES_DIR = os.path.join(astrodex.ASTRODEX_DIR, "images")
        astrodex.ensure_astrodex_directories()
        integration._consumed.clear()
        _bp._rate_hits.clear()  # the cookieless-endpoint rate limiter is process-global
        monkeypatch.setattr(integration, "get_integration_config", lambda config=None: _cfg())
        yield tmpdir
        integration._consumed.clear()
        _bp._rate_hits.clear()


def _seed(user_id):
    item = astrodex.create_astrodex_item(
        user_id, {"name": "M31", "type": "Galaxy", "catalogue": "Messier", "constellation": "Andromeda"}
    )
    picture = astrodex.add_picture_to_item(
        user_id,
        item["id"],
        {
            "filename": "src.jpg",
            "date": "2026-08-14",
            "exposition_time": 120,
            "rating": 4.0,
            "device": "RC8",
            "location_name": "Dark Site",
        },
    )
    with open(os.path.join(astrodex.ASTRODEX_IMAGES_DIR, "src.jpg"), "wb") as handle:
        handle.write(b"\xff\xd8\xff\xe0 jpeg")
    return item, picture


def _handoff_for(item, picture, user_id, **cfg_overrides):
    return integration.mint_handoff(
        _cfg(**cfg_overrides),
        user_id=user_id,
        item_id=item["id"],
        picture_id=picture["id"],
        callback_base="https://astro.example.com",
    )["handoff"]


def _sign_enhanced(payload, image_bytes):
    canon = integration.canonical_json(payload)
    signing_input = f"{canon}\n{hashlib.sha256(image_bytes).hexdigest()}".encode()
    return "sha256=" + hmac.new(_SECRET.encode(), signing_input, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# /status
# ---------------------------------------------------------------------------


def test_status_requires_login(client, env):
    assert client.get("/api/astrodex/integration/status").status_code == 401


def test_status_reports_enabled(client_admin, env):
    resp = client_admin.get("/api/astrodex/integration/status")
    assert resp.status_code == 200
    assert resp.get_json() == {"enabled": True}


def test_status_reports_disabled(client_admin, env, monkeypatch):
    monkeypatch.setattr(integration, "get_integration_config", lambda config=None: _cfg(enabled=False))
    assert client_admin.get("/api/astrodex/integration/status").get_json() == {"enabled": False}


# ---------------------------------------------------------------------------
# Card config: served by the shared GET /api/connectors and
# POST /api/connectors/<name>/config, like every other connector.
# ---------------------------------------------------------------------------


def _listed(client, monkeypatch, cfg=None):
    """The myastroshine entry of GET /api/connectors, for the given stored config."""
    monkeypatch.setattr(
        "blueprints.connectors.load_config",
        lambda: {"connectors": {"myastroshine": cfg if cfg is not None else _cfg()}},
    )
    listing = client.get("/api/connectors").get_json()
    return next(c for c in listing if c["name"] == "myastroshine")


def test_listing_masks_secrets(client_admin, env, monkeypatch):
    """The listing is reachable by any signed-in user - it must never carry the real values."""
    entry = _listed(client_admin, monkeypatch)
    assert entry["config"]["token"] == "****" + _TOKEN[-4:]
    assert entry["config"]["signing_secret"] == "****ssss"
    assert entry["config"]["has_token"] is True
    assert entry["config"]["url"] == "http://192.168.1.42:8002"
    assert _SECRET not in json.dumps(entry)
    assert _TOKEN not in json.dumps(entry)


def test_listing_masks_short_and_empty_secrets(client_admin, env, monkeypatch):
    entry = _listed(client_admin, monkeypatch, _cfg(token="abcd", signing_secret=""))
    assert entry["config"]["token"] == "****"
    assert entry["config"]["signing_secret"] == ""
    assert entry["config"]["has_signing_secret"] is False


def test_listing_reports_astrodex_target_module(client_admin, env, monkeypatch):
    """The card badge must say AstroDex - MyAstroShine does not feed the Observatory."""
    assert _listed(client_admin, monkeypatch)["target_modules"] == ["astrodex"]


def test_listing_identity_comes_from_the_connector_class(client_admin, env, monkeypatch):
    """The card's identity has one source: MyAstroShineConnector, not the route."""
    entry = _listed(client_admin, monkeypatch)
    assert entry["label"] == MyAstroShineConnector.label
    assert entry["description"] == MyAstroShineConnector.description
    assert entry["min_version"] == MyAstroShineConnector.min_version
    assert entry["homepage"] == MyAstroShineConnector.homepage
    assert entry["target_modules"] == MyAstroShineConnector.target_modules
    assert entry["modules"] == []  # the round-trip is the whole connector


def test_listing_not_installed_without_credentials(client_admin, env, monkeypatch):
    """A URL alone does not make MyAstroShine usable - no handoff could be signed."""
    entry = _listed(client_admin, monkeypatch, _cfg(token="", signing_secret=""))
    assert entry["installed"] is False
    assert entry["enabled"] is False


def test_listing_installed_and_enabled_with_credentials(client_admin, env, monkeypatch):
    entry = _listed(client_admin, monkeypatch)
    assert entry["installed"] is True
    assert entry["enabled"] is True


def test_config_post_requires_admin(client, env):
    assert client.post("/api/connectors/myastroshine/config", json={"url": "x"}).status_code == 401


def test_config_post_unknown_connector_is_404(client_admin, env):
    assert client_admin.post("/api/connectors/nope/config", json={"url": "x"}).status_code == 404


def test_config_post_blank_secret_keeps_current(client_admin, env, monkeypatch):
    saved = {}
    monkeypatch.setattr("blueprints.connectors.load_config", lambda: {"connectors": {"myastroshine": _cfg()}})
    monkeypatch.setattr("blueprints.connectors.save_config", lambda cfg: saved.update(cfg) or True)

    resp = client_admin.post(
        "/api/connectors/myastroshine/config",
        json={
            "url": "http://10.0.0.5:8002/",
            "token": "",
            "signing_secret": "****ssss",
            "copy_rating": True,
        },
    )
    assert resp.status_code == 200
    stored = saved["connectors"]["myastroshine"]
    assert stored["url"] == "http://10.0.0.5:8002"
    assert stored["token"] == _TOKEN  # blank means unchanged
    assert stored["signing_secret"] == _SECRET  # masked echo ignored
    assert stored["copy_rating"] is True


def test_config_post_updates_secret_when_provided(client_admin, env, monkeypatch):
    saved = {}
    monkeypatch.setattr("blueprints.connectors.load_config", lambda: {"connectors": {"myastroshine": _cfg()}})
    monkeypatch.setattr("blueprints.connectors.save_config", lambda cfg: saved.update(cfg) or True)

    client_admin.post("/api/connectors/myastroshine/config", json={"token": "mas_newtoken000000"})
    assert saved["connectors"]["myastroshine"]["token"] == "mas_newtoken000000"


def test_config_post_updates_label_callback_and_enabled(client_admin, env, monkeypatch):
    saved = {}
    monkeypatch.setattr("blueprints.connectors.load_config", lambda: {"connectors": {}})
    monkeypatch.setattr("blueprints.connectors.save_config", lambda cfg: saved.update(cfg) or True)
    resp = client_admin.post(
        "/api/connectors/myastroshine/config",
        json={
            "label": "  My Shine  ",
            "url": "http://10.0.0.9:8002/",
            "callback_url_override": "http://10.0.0.9:5000/",
            "enabled": True,
        },
    )
    assert resp.status_code == 200
    stored = saved["connectors"]["myastroshine"]
    assert stored["label"] == "My Shine"
    assert stored["callback_url_override"] == "http://10.0.0.9:5000"
    assert stored["enabled"] is True


def test_config_post_ignores_undeclared_fields(client_admin, env, monkeypatch):
    """Only the connector's own CONFIG_FIELDS are settable - not arbitrary config keys."""
    saved = {}
    monkeypatch.setattr("blueprints.connectors.load_config", lambda: {"connectors": {}})
    monkeypatch.setattr("blueprints.connectors.save_config", lambda cfg: saved.update(cfg) or True)
    client_admin.post(
        "/api/connectors/myastroshine/config",
        json={"url": "http://x:1", "image_path": "../../etc", "role": "admin"},
    )
    stored = saved["connectors"]["myastroshine"]
    assert "image_path" not in stored  # that one belongs to AllSky
    assert "role" not in stored


def test_config_post_save_failure_is_500(client_admin, env, monkeypatch):
    monkeypatch.setattr("blueprints.connectors.load_config", lambda: {"connectors": {}})
    monkeypatch.setattr("blueprints.connectors.save_config", lambda cfg: False)
    resp = client_admin.post("/api/connectors/myastroshine/config", json={"url": "http://x:1"})
    assert resp.status_code == 500


# ---------------------------------------------------------------------------
# /api/connectors/myastroshine/health - the reachability probe
# ---------------------------------------------------------------------------


_PROBE = "/api/connectors/myastroshine/health"
_RESOLVE = "connectors.myastroshine_connector.socket.getaddrinfo"
_REQUESTS_GET = "connectors.myastroshine_connector.requests.get"


def test_probe_blocks_loopback(client_admin, env):
    resp = client_admin.post(_PROBE, json={"url": "http://127.0.0.1:8002"})
    assert resp.status_code == 400
    assert resp.get_json()["reachable"] is False


def test_probe_reports_reachable(client_admin, env, monkeypatch):
    class _Resp:
        status_code = 200

    monkeypatch.setattr(_RESOLVE, lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))])
    monkeypatch.setattr(_REQUESTS_GET, lambda *a, **k: _Resp())
    resp = client_admin.post(_PROBE, json={"url": "https://myshine.example.com"})
    assert resp.get_json() == {"reachable": True, "modules": {}}


def test_probe_requires_a_url(client_admin, env, monkeypatch):
    monkeypatch.setattr(integration, "get_integration_config", lambda config=None: _cfg(url=""))
    resp = client_admin.post(_PROBE, json={})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "url required"


def test_probe_get_uses_the_configured_url(client_admin, env, monkeypatch):
    """GET probes what is saved; POST probes what the admin typed."""
    monkeypatch.setattr(_RESOLVE, lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 8002))])
    resp = client_admin.get(_PROBE)
    assert resp.status_code == 400  # the saved URL resolves to loopback -> blocked


def test_probe_rejects_non_http_scheme(client_admin, env):
    resp = client_admin.post(_PROBE, json={"url": "ftp://myshine.example.com"})
    assert resp.status_code == 400
    assert "valid http" in resp.get_json()["error"]


def test_probe_unresolvable_host(client_admin, env, monkeypatch):
    import socket as _socket

    def _gaierror(*a, **k):
        raise _socket.gaierror("no such host")

    monkeypatch.setattr(_RESOLVE, _gaierror)
    resp = client_admin.post(_PROBE, json={"url": "http://nope.invalid"})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "unable to resolve host"


def test_probe_explicit_port_and_connection_error(client_admin, env, monkeypatch):
    import requests

    monkeypatch.setattr(_RESOLVE, lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 8002))])

    def _conn_err(*a, **k):
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(_REQUESTS_GET, _conn_err)
    resp = client_admin.post(_PROBE, json={"url": "http://myshine.example.com:8002"})
    assert resp.get_json() == {"reachable": False, "modules": {}}


def test_probe_internal_error(client_admin, env, monkeypatch):
    monkeypatch.setattr("connectors.myastroshine_connector.urlparse", _raise)
    assert client_admin.post(_PROBE, json={"url": "http://x:1"}).status_code == 500


# ---------------------------------------------------------------------------
# /handoff
# ---------------------------------------------------------------------------


def test_handoff_forbidden_when_disabled(client_admin, env, admin_id, monkeypatch):
    monkeypatch.setattr(integration, "get_integration_config", lambda config=None: _cfg(enabled=False))
    item, picture = _seed(admin_id)
    resp = client_admin.post(
        "/api/astrodex/integration/handoff", json={"item_id": item["id"], "picture_id": picture["id"]}
    )
    assert resp.status_code == 403


def test_handoff_404_for_unknown_picture(client_admin, env, admin_id):
    item, _ = _seed(admin_id)
    resp = client_admin.post(
        "/api/astrodex/integration/handoff",
        json={"item_id": item["id"], "picture_id": "00000000-0000-4000-8000-000000000000"},
    )
    assert resp.status_code == 404


def test_handoff_400_for_malformed_ids(client_admin, env, admin_id):
    _seed(admin_id)
    resp = client_admin.post("/api/astrodex/integration/handoff", json={"item_id": "../../x", "picture_id": "ghost"})
    assert resp.status_code == 400


def test_handoff_returns_open_url(client_admin, env, admin_id):
    item, picture = _seed(admin_id)
    resp = client_admin.post(
        "/api/astrodex/integration/handoff", json={"item_id": item["id"], "picture_id": picture["id"]}
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["myastroshine_url"] == "http://192.168.1.42:8002"
    assert body["open_url"].startswith("http://192.168.1.42:8002/#/?handoff=")
    claims = integration.verify_handoff(_cfg(), body["handoff"])
    assert claims["user_id"] == admin_id
    assert claims["item_id"] == item["id"]


def test_handoff_uses_callback_override(client_admin, env, admin_id, monkeypatch):
    monkeypatch.setattr(
        integration, "get_integration_config", lambda config=None: _cfg(callback_url_override="http://192.168.1.9:5000")
    )
    item, picture = _seed(admin_id)
    resp = client_admin.post(
        "/api/astrodex/integration/handoff", json={"item_id": item["id"], "picture_id": picture["id"]}
    )
    handoff = resp.get_json()["handoff"]
    claims = integration.verify_handoff(_cfg(), handoff)
    assert claims["callback_base"] == "http://192.168.1.9:5000"


# ---------------------------------------------------------------------------
# /source + /source/image
# ---------------------------------------------------------------------------


def test_source_rejects_bad_handoff(client, env):
    assert client.get("/api/astrodex/integration/source?handoff=bogus").status_code == 401


def test_source_returns_metadata(client, env, admin_id):
    item, picture = _seed(admin_id)
    handoff = _handoff_for(item, picture, admin_id)
    resp = client.get(f"/api/astrodex/integration/source?handoff={handoff}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["object"]["name"] == "M31"
    assert body["picture"]["source_picture_id"] == picture["id"]
    assert body["image"]["url"] == f"/api/astrodex/integration/source/image?handoff={handoff}"


def test_source_image_streams_bytes(client, env, admin_id):
    item, picture = _seed(admin_id)
    handoff = _handoff_for(item, picture, admin_id)
    resp = client.get(f"/api/astrodex/integration/source/image?handoff={handoff}")
    assert resp.status_code == 200
    assert resp.data.startswith(b"\xff\xd8\xff")


# ---------------------------------------------------------------------------
# /enhanced
# ---------------------------------------------------------------------------


def _enhanced_form(handoff, payload, image_bytes):
    return {
        "handoff": handoff,
        "payload": json.dumps(payload),
        "image": (io.BytesIO(image_bytes), "enhanced.jpg"),
    }


def test_enhanced_rejects_bad_signature(client, env, admin_id):
    item, picture = _seed(admin_id)
    handoff = _handoff_for(item, picture, admin_id)
    resp = client.post(
        "/api/astrodex/integration/enhanced",
        data=_enhanced_form(handoff, {"parameters": {}}, b"jpegbytes"),
        headers={"X-Webhook-Signature": "sha256=wrong"},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 401


def test_enhanced_nominal_creates_duplicate(client, env, admin_id):
    item, picture = _seed(admin_id)
    handoff = _handoff_for(item, picture, admin_id)
    payload = {"parameters": {"denoise": 0.3}, "myastroshine_version": "0.3.0"}
    image = b"\xff\xd8\xff enhanced result"
    resp = client.post(
        "/api/astrodex/integration/enhanced",
        data=_enhanced_form(handoff, payload, image),
        headers={"X-Webhook-Signature": _sign_enhanced(payload, image)},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201, resp.get_json()
    body = resp.get_json()
    assert body["status"] == "created"

    stored = astrodex.get_astrodex_item(admin_id, item["id"])
    assert len(stored["pictures"]) == 2
    assert stored["pictures"][1]["enhanced_by"] == "myastroshine"
    assert stored["pictures"][1]["is_main"] is False


def test_enhanced_replay_is_409(client, env, admin_id):
    item, picture = _seed(admin_id)
    handoff = _handoff_for(item, picture, admin_id)
    payload = {"parameters": {}}
    image = b"\xff\xd8\xff bytes"
    form = lambda: client.post(  # noqa: E731
        "/api/astrodex/integration/enhanced",
        data=_enhanced_form(handoff, payload, image),
        headers={"X-Webhook-Signature": _sign_enhanced(payload, image)},
        content_type="multipart/form-data",
    )
    assert form().status_code == 201
    assert form().status_code == 409


# ---------------------------------------------------------------------------
# helpers / rate limiter unit coverage
# ---------------------------------------------------------------------------


def _raise(*args, **kwargs):
    raise RuntimeError("boom")


def test_mask_secret_variants():
    from blueprints.connectors import _mask_secret

    assert _mask_secret("") == ""
    assert _mask_secret("abcd") == "****"  # <= 4 chars -> no tail revealed
    assert _mask_secret("abcdefgh") == "****efgh"


def test_rate_limited_trips_after_budget_then_window_evicts(monkeypatch):
    import blueprints.connectors_myastroshine as bp
    from connectors.myastroshine_connector import MyAstroShineConnector

    bp._rate_hits.clear()
    now = [1000.0]
    monkeypatch.setattr(bp.time, "time", lambda: now[0])
    key = "10.0.0.1"

    for _ in range(MyAstroShineConnector.ENHANCED_RATE_LIMIT):
        assert bp._rate_limited(key) is False
    assert bp._rate_limited(key) is True  # budget exhausted

    now[0] += MyAstroShineConnector.ENHANCED_RATE_WINDOW_SECONDS + 1  # stale hits fall out of window
    assert bp._rate_limited(key) is False
    bp._rate_hits.clear()


def test_rate_limited_prunes_idle_buckets():
    import blueprints.connectors_myastroshine as bp

    bp._rate_hits.clear()
    for i in range(520):
        bp._rate_hits[f"idle-{i}"] = bp.deque()
    assert bp._rate_limited("live") is False
    assert "idle-0" not in bp._rate_hits and "live" in bp._rate_hits
    bp._rate_hits.clear()


# ---------------------------------------------------------------------------
# /status error path
# ---------------------------------------------------------------------------


def test_status_internal_error(client_admin, env, monkeypatch):
    monkeypatch.setattr(integration, "integration_enabled", _raise)
    assert client_admin.get("/api/astrodex/integration/status").status_code == 500


# ---------------------------------------------------------------------------
# /handoff branches
# ---------------------------------------------------------------------------


def test_handoff_404_for_unknown_item(client_admin, env, admin_id):
    _seed(admin_id)
    resp = client_admin.post(
        "/api/astrodex/integration/handoff",
        json={
            "item_id": "00000000-0000-4000-8000-000000000000",
            "picture_id": "11111111-1111-4111-8111-111111111111",
        },
    )
    assert resp.status_code == 404


def test_handoff_internal_error(client_admin, env, admin_id, monkeypatch):
    item, picture = _seed(admin_id)
    monkeypatch.setattr(integration, "mint_handoff", _raise)
    resp = client_admin.post(
        "/api/astrodex/integration/handoff", json={"item_id": item["id"], "picture_id": picture["id"]}
    )
    assert resp.status_code == 500


# ---------------------------------------------------------------------------
# /source + /source/image branches
# ---------------------------------------------------------------------------


def test_source_rate_limited(client, env, monkeypatch):
    monkeypatch.setattr("blueprints.connectors_myastroshine._rate_limited", lambda key: True)
    assert client.get("/api/astrodex/integration/source?handoff=x").status_code == 429


def test_source_401_when_integration_disabled(client, env, monkeypatch):
    monkeypatch.setattr(integration, "get_integration_config", lambda config=None: _cfg(enabled=False))
    assert client.get("/api/astrodex/integration/source?handoff=whatever").status_code == 401


def test_source_404_when_payload_missing(client, env, admin_id, monkeypatch):
    item, picture = _seed(admin_id)
    handoff = _handoff_for(item, picture, admin_id)
    monkeypatch.setattr(integration, "build_source_payload", lambda *a, **k: None)
    resp = client.get(f"/api/astrodex/integration/source?handoff={handoff}")
    assert resp.status_code == 404


def test_source_internal_error(client, env, admin_id, monkeypatch):
    item, picture = _seed(admin_id)
    handoff = _handoff_for(item, picture, admin_id)
    monkeypatch.setattr(integration, "build_source_payload", _raise)
    resp = client.get(f"/api/astrodex/integration/source?handoff={handoff}")
    assert resp.status_code == 500


def test_source_image_rate_limited(client, env, monkeypatch):
    monkeypatch.setattr("blueprints.connectors_myastroshine._rate_limited", lambda key: True)
    assert client.get("/api/astrodex/integration/source/image?handoff=x").status_code == 429


def test_source_image_rejects_bad_handoff(client, env):
    assert client.get("/api/astrodex/integration/source/image?handoff=bogus").status_code == 401


def test_source_image_404_when_path_unresolved(client, env, admin_id, monkeypatch):
    item, picture = _seed(admin_id)
    handoff = _handoff_for(item, picture, admin_id)
    monkeypatch.setattr(integration, "resolve_source_image_path", lambda *a, **k: None)
    resp = client.get(f"/api/astrodex/integration/source/image?handoff={handoff}")
    assert resp.status_code == 404


def test_source_image_internal_error(client, env, admin_id, monkeypatch):
    item, picture = _seed(admin_id)
    handoff = _handoff_for(item, picture, admin_id)
    monkeypatch.setattr(integration, "resolve_source_image_path", _raise)
    resp = client.get(f"/api/astrodex/integration/source/image?handoff={handoff}")
    assert resp.status_code == 500


# ---------------------------------------------------------------------------
# /enhanced branches
# ---------------------------------------------------------------------------


def test_enhanced_rate_limited(client, env, monkeypatch):
    monkeypatch.setattr("blueprints.connectors_myastroshine._rate_limited", lambda key: True)
    assert client.post("/api/astrodex/integration/enhanced").status_code == 429


def test_enhanced_rejects_bad_handoff(client, env):
    resp = client.post(
        "/api/astrodex/integration/enhanced", data={"handoff": "bogus"}, content_type="multipart/form-data"
    )
    assert resp.status_code == 401


def test_enhanced_rejects_oversized_content_length(client, env, admin_id, monkeypatch):
    item, picture = _seed(admin_id)
    handoff = _handoff_for(item, picture, admin_id)
    monkeypatch.setattr(MyAstroShineConnector, "MAX_IMAGE_BYTES", 64)
    payload = {"parameters": {}}
    oversized = b"\xff\xd8\xff" + b"0" * (2 * 1024 * 1024)  # > 64 + 1 MiB slack
    resp = client.post(
        "/api/astrodex/integration/enhanced",
        data=_enhanced_form(handoff, payload, oversized),
        headers={"X-Webhook-Signature": _sign_enhanced(payload, oversized)},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 413


def test_enhanced_requires_image_part(client, env, admin_id):
    item, picture = _seed(admin_id)
    handoff = _handoff_for(item, picture, admin_id)
    resp = client.post(
        "/api/astrodex/integration/enhanced",
        data={"handoff": handoff, "payload": "{}"},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "image part is required"


def test_enhanced_rejects_empty_image(client, env, admin_id):
    item, picture = _seed(admin_id)
    handoff = _handoff_for(item, picture, admin_id)
    resp = client.post(
        "/api/astrodex/integration/enhanced",
        data={"handoff": handoff, "payload": "{}", "image": (io.BytesIO(b""), "e.jpg")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "image part is empty"


def test_enhanced_rejects_image_over_max_bytes(client, env, admin_id, monkeypatch):
    item, picture = _seed(admin_id)
    handoff = _handoff_for(item, picture, admin_id)
    monkeypatch.setattr(MyAstroShineConnector, "MAX_IMAGE_BYTES", 4)
    resp = client.post(
        "/api/astrodex/integration/enhanced",
        data={"handoff": handoff, "payload": "{}", "image": (io.BytesIO(b"\xff\xd8\xff\xff\xff\xff"), "e.jpg")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 413
    assert resp.get_json()["error"] == "Image too large"


def test_enhanced_rejects_non_object_payload(client, env, admin_id):
    item, picture = _seed(admin_id)
    handoff = _handoff_for(item, picture, admin_id)
    resp = client.post(
        "/api/astrodex/integration/enhanced",
        data={"handoff": handoff, "payload": "[1, 2, 3]", "image": (io.BytesIO(b"\xff\xd8\xff x"), "e.jpg")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "payload must be valid JSON"


def test_enhanced_internal_error(client, env, admin_id, monkeypatch):
    item, picture = _seed(admin_id)
    handoff = _handoff_for(item, picture, admin_id)
    payload = {"parameters": {}}
    image = b"\xff\xd8\xff x"
    monkeypatch.setattr(integration, "create_enhanced_duplicate", _raise)
    resp = client.post(
        "/api/astrodex/integration/enhanced",
        data=_enhanced_form(handoff, payload, image),
        headers={"X-Webhook-Signature": _sign_enhanced(payload, image)},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 500
