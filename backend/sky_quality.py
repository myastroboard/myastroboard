"""
Light pollution estimation from user-configured Bortle class or SQM value.

All functions are pure (no I/O, no external dependencies). The user enters
their Bortle class once in Location Settings; SQM is derived from the Bortle
midpoint table unless the user also provides a direct SQM reading.
"""

from __future__ import annotations

from typing import Optional

# ---------------------------------------------------------------------------
# Bortle ↔ SQM midpoint table
# ---------------------------------------------------------------------------

# Representative SQM (mag/arcsec²) for each Bortle class.
# Values are the midpoints of the SQM ranges defined in the World Atlas 2015
# classification used by lightpollutionmap.info.
BORTLE_SQM_MIDPOINTS: dict[int, float] = {
    1: 22.00,   # >21.9 - pristine dark sky
    2: 21.70,   # 21.5–21.9
    3: 21.40,   # 21.3–21.5
    4: 21.05,   # 20.8–21.3
    5: 20.55,   # 20.3–20.8
    6: 19.90,   # 19.5–20.3
    7: 19.00,   # 18.5–19.5
    8: 17.75,   # 17.0–18.5
    9: 16.00,   # <17.0 - inner city
}

# Human-readable Bortle descriptions (English).
BORTLE_DESCRIPTIONS: dict[int, str] = {
    1: "Excellent dark sky",
    2: "Dark sky",
    3: "Rural",
    4: "Rural / suburban",
    5: "Suburban",
    6: "Bright suburban",
    7: "Suburban / urban",
    8: "City",
    9: "Inner city",
}

# Per-object-type LP sensitivity multiplier.
# 1.0 = full light-pollution impact; 0.0 = completely immune.
# Only broadband sensitivity is modelled here (narrowband would require
# per-session imaging-mode data, which is not yet available).
OBJECT_LP_SENSITIVITY: dict[str, float] = {
    "galaxy":   1.00,
    "nebula":   0.85,
    "cluster":  0.50,
    "planet":   0.05,
    "moon":     0.00,
    "comet":    0.70,
    "asteroid": 0.60,
}

_DEFAULT_SENSITIVITY = 0.80  # used for unknown object types


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def bortle_to_sqm(bortle: int) -> float:
    """Return the representative SQM midpoint for a given Bortle class (1–9)."""
    if bortle not in BORTLE_SQM_MIDPOINTS:
        raise ValueError(f"Bortle class must be an integer between 1 and 9, got {bortle!r}")
    return BORTLE_SQM_MIDPOINTS[bortle]


def sqm_to_bortle(sqm: float) -> int:
    """Return the estimated Bortle class for a given SQM value (mag/arcsec²)."""
    if sqm > 21.9:
        return 1
    if sqm > 21.5:
        return 2
    if sqm > 21.3:
        return 3
    if sqm > 20.8:
        return 4
    if sqm > 20.3:
        return 5
    if sqm > 19.5:
        return 6
    if sqm > 18.5:
        return 7
    if sqm > 17.0:
        return 8
    return 9


def light_pollution_factor(sqm: float) -> float:
    """
    Non-linear sky-darkness weighting factor derived from SQM.

    Uses a power curve to reflect signal-to-noise degradation in broadband
    astrophotography. The impact is more severe below SQM ~20 (suburban sky);
    dark skies above ~21.5 are nearly equivalent.

    Returns a value in [0.0, 1.0]:
        1.0 - pristine dark sky (SQM ≥ 22)
        0.0 - inner city (SQM ≤ 17)
    """
    normalized = max(0.0, min(1.0, (sqm - 17.0) / 5.0))
    return round(normalized ** 1.5, 4)


def object_lp_factor(sqm: float, object_type: Optional[str]) -> float:
    """
    Effective light-pollution factor for a specific object type.

    Objects with low LP sensitivity (e.g. planets) are barely affected even
    under heavy light pollution; highly sensitive objects (e.g. galaxies) take
    the full penalty.

    Returns a value in [0.0, 1.0] - multiply sky_score by this value.
    """
    base = light_pollution_factor(sqm)
    key = (object_type or "").lower().strip()
    sensitivity = OBJECT_LP_SENSITIVITY.get(key, _DEFAULT_SENSITIVITY)
    return round(1.0 - (sensitivity * (1.0 - base)), 4)
