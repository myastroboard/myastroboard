"""SkyTonight bodies ingestion for Moon and major planets."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List

from skytonight_models import SkyTonightTarget
from skytonight_targets import normalize_object_name


BODY_DEFINITIONS = [
    {'name': 'Moon',    'object_type': 'Moon',   'aliases': ['Luna', 'Lune']},
    {'name': 'Mercury', 'object_type': 'Planet',  'aliases': ['Mercure']},
    {'name': 'Venus',   'object_type': 'Planet',  'aliases': ['Vénus']},
    {'name': 'Mars',    'object_type': 'Planet',  'aliases': []},
    {'name': 'Jupiter', 'object_type': 'Planet',  'aliases': []},
    {'name': 'Saturn',  'object_type': 'Planet',  'aliases': ['Saturne']},
    {'name': 'Uranus',  'object_type': 'Planet',  'aliases': []},
    {'name': 'Neptune', 'object_type': 'Planet',  'aliases': []},
]


def _target_id(name: str) -> str:
    return f"body-{normalize_object_name(name)}"


def build_body_targets() -> List[SkyTonightTarget]:
    """Build static target records for major solar system bodies."""
    generated_at = datetime.now(timezone.utc).isoformat()
    targets: List[SkyTonightTarget] = []

    for body in BODY_DEFINITIONS:
        name = str(body.get('name') or '').strip()
        if not name:
            continue
        object_type = str(body.get('object_type') or 'Body').strip()
        aliases = [str(value).strip() for value in body.get('aliases', []) if str(value).strip()]

        metadata: Dict[str, str] = {
            'source': 'builtin-solar-system',
            'updated_at': generated_at,
        }

        targets.append(
            SkyTonightTarget(
                target_id=_target_id(name),
                category='bodies',
                object_type=object_type,
                preferred_name=name,
                catalogue_names={'Bodies': name},
                aliases=aliases,
                source_catalogues=['Bodies'],
                translation_key=f"skytonight.type_{normalize_object_name(object_type) or 'body'}",
                metadata=metadata,
            )
        )

    return sorted(targets, key=lambda item: item.preferred_name.lower())
