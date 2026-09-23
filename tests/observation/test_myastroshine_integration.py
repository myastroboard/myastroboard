"""Tests for the MyAstroShine integration module (observation/myastroshine_integration.py).

Covers the handoff token (mint / verify / tamper / expiry / kid rotation /
malformed ids), the webhook return signature, the source-picture payload, and the
enhanced-duplicate creation (metadata copy, enhanced_* stamps, is_main,
copy_rating, replay 409, missing item 404).
"""

import hashlib
import hmac
import json
import os
import tempfile
import time
import uuid

import pytest

from observation import astrodex
from observation import myastroshine_integration as integration

_TOKEN = "mas_abcdef123456extrachars"
_SECRET = "s" * 64

# Handoff identifiers are validated to a strict uuid shape - use real ones.
_UID = str(uuid.uuid4())
_IID = str(uuid.uuid4())
_PID = str(uuid.uuid4())


def _cfg(**overrides):
    cfg = {
        "enabled": True,
        "url": "http://192.168.1.42:8002",
        "token": _TOKEN,
        "signing_secret": _SECRET,
        "callback_url_override": "",
        "copy_rating": False,
    }
    cfg.update(overrides)
    return cfg


@pytest.fixture
def temp_data_dir(monkeypatch):
    """Isolated DATA_DIR + a clean in-memory consumed-jti store per test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setenv("DATA_DIR", tmpdir)
        astrodex.ASTRODEX_DIR = os.path.join(tmpdir, "astrodex")
        astrodex.ASTRODEX_IMAGES_DIR = os.path.join(astrodex.ASTRODEX_DIR, "images")
        integration._consumed.clear()
        monkeypatch.setattr(integration, "get_integration_config", lambda config=None: _cfg())
        yield tmpdir
        integration._consumed.clear()


def _seed_item_with_picture(user_id=_UID):
    astrodex.ensure_astrodex_directories()
    item = astrodex.create_astrodex_item(
        user_id,
        {"name": "M31 - Andromeda Galaxy", "type": "Galaxy", "catalogue": "Messier", "constellation": "Andromeda"},
    )
    picture = astrodex.add_picture_to_item(
        user_id,
        item["id"],
        {
            "filename": "src.jpg",
            "date": "2026-08-14",
            "exposition_time": 120,
            "frames": 180,
            "integration_minutes": 360,
            "iso": "800",
            "device": "RC8",
            "filters": "L",
            "notes": "first light",
            "location_id": "loc-1",
            "location_name": "Col de l'Ecre",
            "latitude": 43.75,
            "longitude": 6.9,
            "elevation": 1200,
            "rating": 3.5,
        },
    )
    # Write an actual image file so resolve_source_image_path works.
    with open(os.path.join(astrodex.ASTRODEX_IMAGES_DIR, "src.jpg"), "wb") as handle:
        handle.write(b"\xff\xd8\xff\xe0 fake jpeg")
    return item, picture


def _mint(cfg=None, user_id=_UID, item_id=_IID, picture_id=_PID, callback_base="https://astro.example.com"):
    return integration.mint_handoff(
        cfg or _cfg(), user_id=user_id, item_id=item_id, picture_id=picture_id, callback_base=callback_base
    )["handoff"]


# ---------------------------------------------------------------------------
# integration_enabled
# ---------------------------------------------------------------------------


def test_integration_enabled_requires_all_fields():
    assert integration.integration_enabled(_cfg()) is True
    assert integration.integration_enabled(_cfg(enabled=False)) is False
    assert integration.integration_enabled(_cfg(url="")) is False
    assert integration.integration_enabled(_cfg(token="")) is False
    assert integration.integration_enabled(_cfg(signing_secret="")) is False


def test_integration_enabled_reads_config_when_cfg_omitted(monkeypatch):
    monkeypatch.setattr(integration, "get_integration_config", lambda config=None: _cfg())
    assert integration.integration_enabled() is True


# ---------------------------------------------------------------------------
# Handoff token
# ---------------------------------------------------------------------------


def test_mint_and_verify_handoff_roundtrip():
    cfg = _cfg()
    result = integration.mint_handoff(
        cfg, user_id=_UID, item_id=_IID, picture_id=_PID, callback_base="https://astro.example.com/"
    )
    assert result["myastroshine_url"] == "http://192.168.1.42:8002"
    assert result["open_url"] == f"http://192.168.1.42:8002/#/?handoff={result['handoff']}"

    claims = integration.verify_handoff(cfg, result["handoff"])
    assert claims is not None
    assert claims["item_id"] == _IID
    assert claims["picture_id"] == _PID
    assert claims["user_id"] == _UID
    assert claims["callback_base"] == "https://astro.example.com"
    assert claims["kid"] == _TOKEN[:12]
    assert claims["exp"] - claims["iat"] == integration.MyAstroShineConnector.HANDOFF_TTL_SECONDS


def test_verify_handoff_rejects_tampered_signature():
    token = _mint()
    body, _, sig = token.partition(".")
    assert integration.verify_handoff(_cfg(), f"{body}.{sig[:-2]}xx") is None


def test_verify_handoff_rejects_tampered_payload():
    token = _mint()
    _, _, sig = token.partition(".")
    forged_payload = integration._b64url_encode(json.dumps({"user_id": "attacker"}).encode())
    assert integration.verify_handoff(_cfg(), f"{forged_payload}.{sig}") is None


def test_verify_handoff_rejects_malformed_identifiers():
    # Valid signature, but an id that would escape the per-user Astrodex path.
    token = _mint(user_id="../../etc/passwd")
    assert integration.verify_handoff(_cfg(), token) is None


def test_verify_handoff_rejects_expired(monkeypatch):
    token = _mint()
    real_time = time.time
    far_future = real_time() + integration.MyAstroShineConnector.HANDOFF_TTL_SECONDS + 10
    monkeypatch.setattr(integration.time, "time", lambda: far_future)
    assert integration.verify_handoff(_cfg(), token) is None


def test_verify_handoff_rejects_kid_mismatch_after_token_rotation():
    minted = _mint()
    assert integration.verify_handoff(_cfg(token="mas_zzzzzzzzzzzznew"), minted) is None


def test_verify_handoff_rejects_when_not_configured():
    assert integration.verify_handoff(_cfg(signing_secret=""), "a.b") is None
    assert integration.verify_handoff(_cfg(), "not-a-token") is None


# ---------------------------------------------------------------------------
# canonical_json + webhook signature
# ---------------------------------------------------------------------------


def test_canonical_json_is_sorted_and_compact():
    assert integration.canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_verify_return_signature_ok_and_tampered():
    cfg = _cfg()
    payload = {"parameters": {"denoise": 0.4}, "myastroshine_version": "0.3.0"}
    image = b"processed-jpeg-bytes"
    signing_input = f"{integration.canonical_json(payload)}\n{hashlib.sha256(image).hexdigest()}".encode()
    good = "sha256=" + hmac.new(_SECRET.encode(), signing_input, hashlib.sha256).hexdigest()

    assert integration.verify_return_signature(cfg, payload, image, good) is True
    assert integration.verify_return_signature(cfg, payload, b"other-bytes", good) is False
    assert integration.verify_return_signature(cfg, {"parameters": {}}, image, good) is False
    assert integration.verify_return_signature(cfg, payload, image, "sha256=deadbeef") is False
    assert integration.verify_return_signature(_cfg(signing_secret=""), payload, image, good) is False


# ---------------------------------------------------------------------------
# build_source_payload
# ---------------------------------------------------------------------------


def test_build_source_payload_shape(temp_data_dir):
    item, picture = _seed_item_with_picture()
    claims = {"user_id": _UID, "item_id": item["id"], "picture_id": picture["id"]}
    payload = integration.build_source_payload(claims, token="TOK")

    assert payload["object"] == {
        "item_id": item["id"],
        "name": "M31 - Andromeda Galaxy",
        "type": "Galaxy",
        "catalogue": "Messier",
        "constellation": "Andromeda",
    }
    assert payload["picture"]["source_picture_id"] == picture["id"]
    assert payload["picture"]["exposition_time"] == 120
    assert payload["picture"]["location_name"] == "Col de l'Ecre"
    assert payload["image"]["url"] == "/api/astrodex/integration/source/image?handoff=TOK"
    assert payload["image"]["filename"] == "src.jpg"
    assert payload["image"]["content_type"] == "image/jpeg"


def test_build_source_payload_missing_returns_none(temp_data_dir):
    _seed_item_with_picture()
    claims = {"user_id": _UID, "item_id": str(uuid.uuid4()), "picture_id": str(uuid.uuid4())}
    assert integration.build_source_payload(claims) is None


def test_build_source_payload_rejects_bad_user_id(temp_data_dir):
    _seed_item_with_picture()
    claims = {"user_id": "../../etc", "item_id": str(uuid.uuid4()), "picture_id": str(uuid.uuid4())}
    assert integration.build_source_payload(claims) is None


def test_resolve_source_image_path(temp_data_dir):
    item, picture = _seed_item_with_picture()
    claims = {"user_id": _UID, "item_id": item["id"], "picture_id": picture["id"]}
    path = integration.resolve_source_image_path(claims)
    assert path and os.path.isfile(path)


# ---------------------------------------------------------------------------
# create_enhanced_duplicate
# ---------------------------------------------------------------------------


def _claims_for(item, picture, user_id=_UID, jti=None):
    return {
        "user_id": user_id,
        "item_id": item["id"],
        "picture_id": picture["id"],
        "jti": jti or str(uuid.uuid4()),
        "exp": time.time() + 600,
    }


def test_create_enhanced_duplicate_copies_metadata_and_stamps(temp_data_dir):
    item, source = _seed_item_with_picture()
    payload = {"parameters": {"sharpen": 0.2}, "myastroshine_version": "0.3.0"}

    result = integration.create_enhanced_duplicate(_claims_for(item, source), b"enhanced-jpeg", payload)
    assert result["status"] == "created"

    stored = astrodex.get_astrodex_item(_UID, item["id"])
    assert len(stored["pictures"]) == 2
    dup = stored["pictures"][1]
    assert dup["is_main"] is False
    assert dup["exposition_time"] == 120
    assert dup["device"] == "RC8"
    assert dup["location_name"] == "Col de l'Ecre"
    assert dup["rating"] is None  # copy_rating defaults to False
    assert dup["enhanced_by"] == "myastroshine"
    assert dup["enhanced_from_picture_id"] == source["id"]
    assert dup["enhanced_parameters"] == {"sharpen": 0.2}
    assert dup["enhanced_source_version"] == "0.3.0"
    assert dup["filename"] != source["filename"]
    assert os.path.isfile(os.path.join(astrodex.ASTRODEX_IMAGES_DIR, dup["filename"]))


def test_create_enhanced_duplicate_copy_rating(temp_data_dir, monkeypatch):
    monkeypatch.setattr(integration, "get_integration_config", lambda config=None: _cfg(copy_rating=True))
    item, source = _seed_item_with_picture()
    integration.create_enhanced_duplicate(_claims_for(item, source), b"jpeg", {"parameters": {}})
    dup = astrodex.get_astrodex_item(_UID, item["id"])["pictures"][1]
    assert dup["rating"] == 3.5


def test_create_enhanced_duplicate_replay_is_409(temp_data_dir):
    item, source = _seed_item_with_picture()
    claims = _claims_for(item, source)
    integration.create_enhanced_duplicate(claims, b"jpeg", {"parameters": {}})
    with pytest.raises(integration.EnhancedDuplicateError) as excinfo:
        integration.create_enhanced_duplicate(claims, b"jpeg", {"parameters": {}})
    assert excinfo.value.status == 409


def test_create_enhanced_duplicate_unknown_item_is_404(temp_data_dir):
    _seed_item_with_picture()
    bad = {
        "user_id": _UID,
        "item_id": str(uuid.uuid4()),
        "picture_id": str(uuid.uuid4()),
        "jti": str(uuid.uuid4()),
        "exp": time.time() + 60,
    }
    with pytest.raises(integration.EnhancedDuplicateError) as excinfo:
        integration.create_enhanced_duplicate(bad, b"jpeg", {"parameters": {}})
    assert excinfo.value.status == 404


def test_create_enhanced_duplicate_rejects_bad_ids(temp_data_dir):
    item, source = _seed_item_with_picture()
    bad = _claims_for(item, source, user_id="../../etc/passwd")
    with pytest.raises(integration.EnhancedDuplicateError) as excinfo:
        integration.create_enhanced_duplicate(bad, b"jpeg", {"parameters": {}})
    assert excinfo.value.status == 401


def test_consumed_jti_persists_to_disk(temp_data_dir):
    integration.mark_handoff_consumed("jti-persist", time.time() + 300)
    on_disk = json.load(open(integration._consumed_file_path(), encoding="utf-8"))
    assert "jti-persist" in on_disk

    integration._consumed.clear()
    integration._load_consumed_from_disk()
    assert integration.is_handoff_consumed("jti-persist") is True


# ---------------------------------------------------------------------------
# get_integration_config (the real one - other tests monkeypatch it away)
# ---------------------------------------------------------------------------


def test_get_integration_config_from_explicit_config():
    cfg = integration.get_integration_config({"connectors": {"myastroshine": {"url": "http://x:1"}}})
    assert cfg == {"url": "http://x:1"}


def test_get_integration_config_handles_missing_and_none_block():
    assert integration.get_integration_config({"connectors": {"myastroshine": None}}) == {}
    assert integration.get_integration_config({}) == {}


def test_get_integration_config_loads_config_when_omitted(monkeypatch):
    monkeypatch.setattr(integration, "load_config", lambda: {"connectors": {"myastroshine": {"enabled": True}}})
    assert integration.get_integration_config() == {"enabled": True}


# ---------------------------------------------------------------------------
# verify_handoff - forged-but-signed payloads exercise the decode / shape guards
# ---------------------------------------------------------------------------


def _sign_body(cfg, body: str) -> str:
    sig = integration._b64url_encode(
        hmac.new(cfg["signing_secret"].encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    )
    return f"{body}.{sig}"


def test_verify_handoff_rejects_undecodable_json_payload():
    cfg = _cfg()
    token = _sign_body(cfg, integration._b64url_encode(b"this is not json{"))
    assert integration.verify_handoff(cfg, token) is None


def test_verify_handoff_rejects_non_dict_claims():
    cfg = _cfg()
    token = _sign_body(cfg, integration._b64url_encode(b"123"))
    assert integration.verify_handoff(cfg, token) is None


def test_verify_handoff_rejects_non_numeric_exp():
    cfg = _cfg()
    body = integration._b64url_encode(
        integration.canonical_json({"kid": _TOKEN[:12], "exp": "not-a-number"}).encode("utf-8")
    )
    assert integration.verify_handoff(cfg, _sign_body(cfg, body)) is None


# ---------------------------------------------------------------------------
# consumed-jti store: disk load resilience + expiry pruning
# ---------------------------------------------------------------------------


def test_load_consumed_from_disk_ignores_non_dict_file(temp_data_dir):
    astrodex.ensure_astrodex_directories()
    with open(integration._consumed_file_path(), "w", encoding="utf-8") as handle:
        json.dump(["not", "a", "dict"], handle)
    integration._consumed.clear()
    integration._load_consumed_from_disk()
    assert integration._consumed == {}


def test_load_consumed_from_disk_skips_bad_and_expired_entries(temp_data_dir):
    astrodex.ensure_astrodex_directories()
    with open(integration._consumed_file_path(), "w", encoding="utf-8") as handle:
        json.dump({"good": time.time() + 300, "unparseable": "xxx", "expired": 1.0}, handle)
    integration._consumed.clear()
    integration._load_consumed_from_disk()
    assert list(integration._consumed) == ["good"]


def test_is_handoff_consumed_drops_expired_entry(temp_data_dir):
    integration._consumed["stale"] = time.time() - 5
    assert integration.is_handoff_consumed("stale") is False
    assert "stale" not in integration._consumed


def test_mark_handoff_consumed_default_expiry_and_prunes_expired(temp_data_dir):
    integration._consumed["already-expired"] = time.time() - 10
    integration.mark_handoff_consumed("fresh")  # no explicit expiry -> TTL default
    assert integration._consumed["fresh"] > time.time()
    assert "already-expired" not in integration._consumed


# ---------------------------------------------------------------------------
# consumed-jti store shared between gunicorn workers (separate processes, one file)
# ---------------------------------------------------------------------------


def _spend_in_other_worker(jti):
    """Write a jti to the on-disk store without touching this process's in-memory dict."""
    astrodex.ensure_astrodex_directories()
    path = integration._consumed_file_path()
    data = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    data[jti] = time.time() + 300
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)


def test_jti_spent_by_another_worker_is_seen_as_consumed(temp_data_dir):
    _spend_in_other_worker("jti-other-worker")
    assert integration.is_handoff_consumed("jti-other-worker") is True
    assert integration.claim_handoff("jti-other-worker") is False


def test_mark_keeps_jtis_persisted_by_another_worker(temp_data_dir):
    _spend_in_other_worker("jti-from-a")
    integration.mark_handoff_consumed("jti-from-b", time.time() + 300)
    on_disk = json.load(open(integration._consumed_file_path(), encoding="utf-8"))
    assert {"jti-from-a", "jti-from-b"} <= set(on_disk)


def test_claim_handoff_is_single_use(temp_data_dir):
    assert integration.claim_handoff("jti-once", time.time() + 300) is True
    assert integration.claim_handoff("jti-once", time.time() + 300) is False


def test_claim_handoff_reclaims_expired_jti_with_default_expiry(temp_data_dir):
    integration._consumed["jti-expired"] = time.time() - 5
    assert integration.claim_handoff("jti-expired") is True
    assert integration._consumed["jti-expired"] > time.time()


def test_release_handoff_removes_jti_from_memory_and_disk(temp_data_dir):
    integration.claim_handoff("jti-release", time.time() + 300)
    integration.release_handoff("jti-release")
    on_disk = json.load(open(integration._consumed_file_path(), encoding="utf-8"))
    assert "jti-release" not in on_disk
    assert integration.is_handoff_consumed("jti-release") is False


def test_create_enhanced_duplicate_replay_rejected_across_workers(temp_data_dir):
    item, source = _seed_item_with_picture()
    claims = _claims_for(item, source)
    integration.create_enhanced_duplicate(claims, b"jpeg", {"parameters": {}})
    integration._consumed.clear()  # a different worker never saw the first request in memory
    with pytest.raises(integration.EnhancedDuplicateError) as excinfo:
        integration.create_enhanced_duplicate(claims, b"jpeg", {"parameters": {}})
    assert excinfo.value.status == 409


def test_failed_enhanced_duplicate_releases_jti_for_retry(temp_data_dir):
    item, source = _seed_item_with_picture()
    claims = dict(_claims_for(item, source), item_id=str(uuid.uuid4()))  # item does not exist
    with pytest.raises(integration.EnhancedDuplicateError) as excinfo:
        integration.create_enhanced_duplicate(claims, b"jpeg", {"parameters": {}})
    assert excinfo.value.status == 404
    assert integration.is_handoff_consumed(claims["jti"]) is False


# ---------------------------------------------------------------------------
# _find_item_and_picture / build_source_payload / resolve_source_image_path
# ---------------------------------------------------------------------------


def test_find_item_and_picture_scans_past_non_matching_pictures(temp_data_dir):
    item, _ = _seed_item_with_picture()
    second = astrodex.add_picture_to_item(_UID, item["id"], {"filename": "b.jpg"})
    found_item, found_picture = integration._find_item_and_picture(_UID, item["id"], second["id"])
    assert found_item["id"] == item["id"]
    assert found_picture["id"] == second["id"]


def test_find_item_and_picture_known_item_unknown_picture(temp_data_dir):
    item, _ = _seed_item_with_picture()
    found_item, found_picture = integration._find_item_and_picture(_UID, item["id"], str(uuid.uuid4()))
    assert found_item["id"] == item["id"]
    assert found_picture is None


def test_resolve_source_image_path_missing_picture(temp_data_dir):
    _seed_item_with_picture()
    claims = {"user_id": _UID, "item_id": str(uuid.uuid4()), "picture_id": str(uuid.uuid4())}
    assert integration.resolve_source_image_path(claims) is None


def test_resolve_source_image_path_picture_without_filename(temp_data_dir):
    item = astrodex.create_astrodex_item(_UID, {"name": "M42", "type": "Nebula"})
    picture = astrodex.add_picture_to_item(_UID, item["id"], {"filename": ""})
    claims = {"user_id": _UID, "item_id": item["id"], "picture_id": picture["id"]}
    assert integration.resolve_source_image_path(claims) is None


def test_resolve_source_image_path_file_absent_on_disk(temp_data_dir):
    item = astrodex.create_astrodex_item(_UID, {"name": "M42", "type": "Nebula"})
    picture = astrodex.add_picture_to_item(_UID, item["id"], {"filename": "ghost.jpg"})
    claims = {"user_id": _UID, "item_id": item["id"], "picture_id": picture["id"]}
    assert integration.resolve_source_image_path(claims) is None


# ---------------------------------------------------------------------------
# _save_enhanced_image guard + create_enhanced_duplicate secondary failures
# ---------------------------------------------------------------------------


def test_save_enhanced_image_rejects_bad_user_id(temp_data_dir):
    assert integration._save_enhanced_image("../../etc/passwd", b"jpeg") is None


def test_create_enhanced_duplicate_appends_note(temp_data_dir):
    item, source = _seed_item_with_picture()  # source already has notes="first light"
    integration.create_enhanced_duplicate(
        _claims_for(item, source), b"jpeg", {"parameters": {}, "note": "  denoised x3  "}
    )
    dup = astrodex.get_astrodex_item(_UID, item["id"])["pictures"][1]
    assert dup["notes"] == "first light\ndenoised x3"


def test_create_enhanced_duplicate_note_without_base_notes(temp_data_dir):
    item = astrodex.create_astrodex_item(_UID, {"name": "M13", "type": "Cluster"})
    source = astrodex.add_picture_to_item(_UID, item["id"], {"filename": "s.jpg"})
    with open(os.path.join(astrodex.ASTRODEX_IMAGES_DIR, "s.jpg"), "wb") as handle:
        handle.write(b"\xff\xd8\xff")
    integration.create_enhanced_duplicate(
        _claims_for(item, source), b"jpeg", {"parameters": {}, "note": "stand-alone note"}
    )
    dup = astrodex.get_astrodex_item(_UID, item["id"])["pictures"][1]
    assert dup["notes"] == "stand-alone note"


def test_create_enhanced_duplicate_image_store_failure_is_500(temp_data_dir, monkeypatch):
    item, source = _seed_item_with_picture()
    monkeypatch.setattr(integration, "_save_enhanced_image", lambda *a, **k: None)
    with pytest.raises(integration.EnhancedDuplicateError) as excinfo:
        integration.create_enhanced_duplicate(_claims_for(item, source), b"jpeg", {"parameters": {}})
    assert excinfo.value.status == 500


def test_create_enhanced_duplicate_item_vanishes_on_save_is_404(temp_data_dir, monkeypatch):
    item, source = _seed_item_with_picture()
    monkeypatch.setattr(integration.astrodex, "add_picture_to_item", lambda *a, **k: None)
    with pytest.raises(integration.EnhancedDuplicateError) as excinfo:
        integration.create_enhanced_duplicate(_claims_for(item, source), b"jpeg", {"parameters": {}})
    assert excinfo.value.status == 404
