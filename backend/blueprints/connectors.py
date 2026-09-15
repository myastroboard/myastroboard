"""Connectors registry Blueprint. Route: /api/connectors

Lists the BaseConnector registry (backend/connectors/). Each connector's own
routes live in a sibling module named after it - blueprints/connectors_allsky.py,
blueprints/connectors_myastroshine.py.
"""

from flask import Blueprint, jsonify

from utils.auth import login_required
from utils.logging_config import get_logger
from utils.repo_config import load_config

logger = get_logger(__name__)

connectors_bp = Blueprint('connectors', __name__)


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
        result.append(
            {
                "name": name,
                "label": cls.label,
                "description": cls.description,
                "min_version": cls.min_version,
                "homepage": cls.homepage,
                "modules": cls.MODULES,
                "target_modules": list(cls.target_modules),
                "installed": bool(cfg.get("url")),
                "enabled": bool(cfg.get("enabled")) and bool(cfg.get("url")),
                "config": cfg,
            }
        )
    return jsonify(result)
