# MyAstroBoard - Roadmap

This document describes features that could potentially be integrated into MyAstroBoard. There are no guarantees; consider this file a list of ideas that may evolve based on my own ideas or future discussions.

## 🗓️ Release Plan

### v1.0 - Stabilization & Overall Quality
**Objective: First stable release + smooth user experience**
- Stabilization of critical bugs
- Improved mobile interface (responsive)

### Immediate — before calling v1.0 done
1. **Tests for push backend** — `push_manager.py`, `push_scheduler.py` trigger logic, new API routes, User model round-trip.
2. **End-to-end test on a real mobile device** - verify push subscriptions work on Android (Chrome) and iOS (Safari with limitations). The code is correct in theory but untested on hardware.

### Short-term — the most natural next feature

**Observation log** is the biggest missing piece for an astrophotography app. Users plan their night (Plan My Night), they observe, but there's nowhere to record what actually happened:

- What targets they captured
- Actual exposure time / number of frames
- Equipment used (already modelled)
- Sky conditions that night (could pull from weather cache)
- Notes / rating
This closes the loop: Plan → Observe → Log → Astrodex (where captured objects are catalogued). The data model is already 80% there — Plan My Night has the target list, Equipment has the gear, Astrodex has the objects.

### Medium-term
| Feature	| Why | Effort |
|----|-------|---------------|
| Multi-location profiles	| Observers travel to dark sites | Medium |
| Seeing forecast tied to Plan My Night | "Best night this week to observe X"	| Medium |
| Exposure calculator	| Integration time for targets by sensor+scope | Medium |
| Moon phase calendar with Plan My Night | Visual planning across a month	| Low |
