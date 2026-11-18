"""SkyTonight normalized dataset models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class SkyTonightCoordinates:
    """Machine-readable equatorial coordinates for a target."""

    ra_hours: float
    dec_degrees: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class SkyTonightTarget:
    """Canonical SkyTonight target record shared across catalogues."""

    target_id: str
    category: str
    object_type: str
    preferred_name: str
    catalogue_names: dict[str, str] = field(default_factory=dict)
    aliases: list[str] = field(default_factory=list)
    constellation: str = ''
    magnitude: float | None = None
    size_arcmin: float | None = None
    coordinates: SkyTonightCoordinates | None = None
    source_catalogues: list[str] = field(default_factory=list)
    translation_key: str = ''
    metadata: dict[str, Any] = field(default_factory=dict)
    difficulty_score: int = 0
    difficulty: str = 'intermediate'
    # Outline of an elongated object: minor axis and position angle of the major axis
    # (degrees from north through east), as OpenNGC gives them. None when unknown.
    size_minor_arcmin: float | None = None
    position_angle_deg: float | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.coordinates is None:
            payload['coordinates'] = None
        # Most targets have no outline: leave the keys out rather than writing nulls into
        # every record of the dataset file.
        for key in ('size_minor_arcmin', 'position_angle_deg'):
            if payload[key] is None:
                del payload[key]
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkyTonightTarget:
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
            difficulty_score=int(data['difficulty_score']) if data.get('difficulty_score') is not None else 0,
            difficulty=str(data.get('difficulty', 'intermediate') or 'intermediate').strip(),
            size_minor_arcmin=(float(data['size_minor_arcmin']) if data.get('size_minor_arcmin') is not None else None),
            position_angle_deg=(
                float(data['position_angle_deg']) if data.get('position_angle_deg') is not None else None
            ),
        )
