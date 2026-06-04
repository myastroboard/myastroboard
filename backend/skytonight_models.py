"""SkyTonight normalized dataset models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class SkyTonightCoordinates:
    """Machine-readable equatorial coordinates for a target."""

    ra_hours: float
    dec_degrees: float

    def to_dict(self) -> Dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class SkyTonightTarget:
    """Canonical SkyTonight target record shared across catalogues."""

    target_id: str
    category: str
    object_type: str
    preferred_name: str
    catalogue_names: Dict[str, str] = field(default_factory=dict)
    aliases: List[str] = field(default_factory=list)
    constellation: str = ''
    magnitude: Optional[float] = None
    size_arcmin: Optional[float] = None
    coordinates: Optional[SkyTonightCoordinates] = None
    source_catalogues: List[str] = field(default_factory=list)
    translation_key: str = ''
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        if self.coordinates is None:
            payload['coordinates'] = None
        return payload

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SkyTonightTarget':
        coordinates_data = data.get('coordinates')
        coordinates = None
        if isinstance(coordinates_data, dict):
            coordinates = SkyTonightCoordinates(
                ra_hours=float(coordinates_data.get('ra_hours', 0.0)),
                dec_degrees=float(coordinates_data.get('dec_degrees', 0.0)),
            )

        catalogue_names = data.get('catalogue_names', {})
        aliases = data.get('aliases', [])
        source_catalogues = data.get('source_catalogues', [])
        metadata = data.get('metadata', {})

        return cls(
            target_id=str(data.get('target_id', '') or '').strip(),
            category=str(data.get('category', '') or '').strip(),
            object_type=str(data.get('object_type', '') or '').strip(),
            preferred_name=str(data.get('preferred_name', '') or '').strip(),
            catalogue_names=(
                {str(key): str(value) for key, value in catalogue_names.items()}
                if isinstance(catalogue_names, dict)
                else {}
            ),
            aliases=[str(value) for value in aliases if str(value).strip()] if isinstance(aliases, list) else [],
            constellation=str(data.get('constellation', '') or '').strip(),
            magnitude=float(data['magnitude']) if data.get('magnitude') is not None else None,
            size_arcmin=float(data['size_arcmin']) if data.get('size_arcmin') is not None else None,
            coordinates=coordinates,
            source_catalogues=(
                [str(value) for value in source_catalogues if str(value).strip()]
                if isinstance(source_catalogues, list)
                else []
            ),
            translation_key=str(data.get('translation_key', '') or '').strip(),
            metadata=metadata if isinstance(metadata, dict) else {},
        )
