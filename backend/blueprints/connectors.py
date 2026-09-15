"""Connectors registry Blueprint. Route: /api/connectors

Lists the BaseConnector registry (backend/connectors/). Each connector's own
routes live in a sibling module named after it - blueprints/connectors_allsky.py,
blueprints/connectors_myastroshine.py.
"""

from flask import Blueprint, jsonify, request

from utils.auth import admin_required, login_required
from utils.logging_config import get_logger
from utils.repo_config import load_config, save_config

logger = get_logger(__name__)

connectors_bp = Blueprint('connectors', __name__)


def _public_config(cls, cfg: dict) -> dict:
    """The connector's config block as the browser may see it.

    Every key the card needs to render, with each of the connector's SECRET_FIELDS
    replaced by a masked stand-in: the card only has to show that a credential is set,
    never its value, and this endpoint is reachable by any signed-in user.
    """
    public = dict(cfg)
    for field in cls.SECRET_FIELDS:
        raw = str(cfg.get(field) or "")
        public[field] = _mask_secret(raw)
        public[f"has_{field}"] = bool(raw)
    return public


def _mask_secret(value: str) -> str:
    """Render a secret as '****' + its last 4 chars, or '' when unset.

    A secret of 4 characters or fewer reveals no tail at all.
    """
    if not value:
        return ""
    if len(value) <= 4:
        return "****"
    return f"****{value[-4:]}"


@connectors_bp.route('/api/connectors', methods=['GET'])
@login_required
def list_connectors_api():
    """List all available connectors with their installed/enabled state."""
    from connectors import REGISTRY

    config = load_config()
    connectors_cfg = config.get("connectors", {})
    result = []
    for name, cls in REGISTRY.items():
        cfg = connectors_cfg.get(name, {})
        connector = cls(cfg)
        result.append(
            {
                "name": name,
                "label": cls.label,
                "description": cls.description,
                "min_version": cls.min_version,
                "homepage": cls.homepage,
                "modules": cls.MODULES,
                "target_modules": list(cls.target_modules),
                "secret_fields": list(cls.SECRET_FIELDS),
                "installed": connector.is_configured(),
                "enabled": connector.is_enabled(),
                "config": _public_config(cls, cfg),
            }
        )
    return jsonify(result)


@connectors_bp.route('/api/connectors/<name>/config', methods=['POST'])
@admin_required
def save_connector_config_api(name):
    """Persist one connector's config block.

    The merge happens here rather than in the browser: the client sends only the fields it
    edited, so a secret it was never given (GET /api/connectors masks them) cannot be echoed
    back as a masked string and overwrite the real one. A blank or still-masked secret means
    "keep what is stored".
    """
    from connectors import REGISTRY

    cls = REGISTRY.get(name)
    if cls is None:
        return jsonify({"error": "unknown connector"}), 404

    payload = request.get_json(silent=True) or {}
    config = load_config()
    connectors_cfg = config.setdefault("connectors", {})
    current = dict(connectors_cfg.get(name, {}) or {})

    if "label" in payload:
        current["label"] = str(payload.get("label") or "").strip()
    if "url" in payload:
        current["url"] = str(payload.get("url") or "").strip().rstrip("/")
    if "enabled" in payload:
        current["enabled"] = bool(payload.get("enabled"))

    if "modules" in payload and isinstance(payload["modules"], dict):
        known = {m["slug"] for m in cls.MODULES}
        modules = dict(current.get("modules", {}) or {})
        for slug, value in payload["modules"].items():
            if slug in known and isinstance(value, dict):
                modules[slug] = {"enabled": bool(value.get("enabled"))}
        current["modules"] = modules

    for field, default in cls.CONFIG_FIELDS.items():
        if field not in payload:
            continue
        raw = payload.get(field)
        if field in cls.SECRET_FIELDS:
            incoming = str(raw or "").strip()
            # Blank, or the masked placeholder handed out by GET /api/connectors, means
            # "unchanged" - never let either land in the stored config.
            if incoming and not incoming.startswith("****"):
                current[field] = incoming
        elif isinstance(default, bool):
            current[field] = bool(raw)
        elif field in cls.URL_FIELDS:
            current[field] = str(raw or "").strip().rstrip("/") or default
        else:
            current[field] = str(raw or "").strip() or default

    connectors_cfg[name] = current
    if not save_config(config):
        return jsonify({"error": "Failed to save configuration"}), 500

    connector = cls(current)
    return jsonify({"status": "success", "enabled": connector.is_enabled(), "installed": connector.is_configured()})
