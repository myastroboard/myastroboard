# MyAstroBoard - Roadmap

This document describes features that could potentially be integrated into MyAstroBoard. There are no guarantees; consider this file a list of ideas that may evolve based on my own ideas or future discussions.

## 🗓️ Release Plan

### v1.0 - Stabilization & Overall Quality
**Objective: First stable release**
- Stabilization of critical bugs

### v1.1 and next - Introduce new features

### Medium-term — new standalone features

| Feature | Why | Effort |
|---------|-----|--------|
| Multi-location profiles | Observers travel to dark sites; location drives every calculation | Medium |
| **Observation log** | Record what actually happened after a session (see below) | High |

#### Observation log — realistic scope

Closes the loop: **Plan → Observe → Log → Astrodex**. Users can record what they actually captured, not just what they planned.

What needs to be built from scratch:
- **Session concept** — date, observing site, equipment combo, start/end time, sky conditions (SQM, seeing, transparency)
- **Per-target entries** — actual frame count, integration time, notes, rating (1–5), link to Astrodex
- **New backend module** (`observation_sessions.py`) with per-user JSON storage, same pattern as `astrodex.py`
- **Import from plan** — one-click to seed a session from tonight's Plan My Night targets
- **New frontend** — session list, session detail, entry editor, i18n in 6 languages

The equipment and object models (Equipment, Astrodex) are reusable as references, but the session and entry data model is entirely new. This is a full feature, not an incremental one.
