# MyAstroBoard - Roadmap

This document describes features that could potentially be integrated into MyAstroBoard. There are no guarantees; consider this file a list of ideas that may evolve based on my own ideas or future discussions.

---

## Release Plan

### v0.9 - Close Web Push + Stabilize

**Objective:** Ship the one half-done feature before declaring stability.

The Web Push infrastructure (VAPID keys, `push_manager.py`, `push_scheduler.py`, API routes, SW handler) is fully built. What remains is end-to-end hardware validation.

- Complete VAPID Web Push E2E test on Android (Chrome) and iOS (Safari)
- Verify notifications fire correctly when the tab is closed - the main nighttime value
- Finalize `VAPID_CONTACT_EMAIL` requirement and document it in `1.INSTALLATION.md`

**Exit criteria:** push notification received on a real Android and iOS device; no open P1 bugs; CHANGELOG_NEXT empty.

---

### v1.0 - First Stable Release

**Objective:** A clean, self-hostable release that a new user can install and use in under 15 minutes.

- Docker `docker compose up` → usable without manual steps
- All 6 i18n languages at 0 missing keys (`python scripts/validate_i18n.py` passes clean)
- API routes stabilized - no breaking route changes after this point
- Documentation reviewed: `1.INSTALLATION.md`, `docs/` up to date

**Exit criteria:** clean install verified; CI passing; i18n 0 missing keys; no known P1/P2 bugs.

---

### v1.1 - First Light (Beginner Experience)

| | |
|---|---|
| **Why** | Astrophotography has a steep learning curve; today MAB assumes prior knowledge. Lowering the floor grows the user base and makes every later feature more valuable. Placed before the Observation Log because beginners need onboarding before they have anything to log. |
| **Effort** | Medium |

#### Guided setup wizard (first-run, skippable)

Step-by-step flow triggered on first login:

1. Set your location on the interactive map
2. Add your first telescope + camera (with presets for popular gear: SW 130PDS, Seestar S50, ZWO ASI294, etc.)
3. Pick your Bortle class from a light pollution map preview
4. Subscribe to push notifications for tonight
5. Land on "Here's what you can image tonight"

#### "What to shoot tonight?" recommender

One-click answer driven by: current conditions, moon phase, equipment FOV, and user skill level (beginner / intermediate / advanced - set in user profile).

Returns 3–5 ranked targets with:
- A sample reference image
- Difficulty tag (`beginner` / `intermediate` / `advanced`)
- Estimated integration time
- One-click "Add to Plan My Night"

Difficulty logic: auto-calculated from magnitude, angular size (larger = easier), surface brightness, and typical integration time required. Surfaced as a badge throughout the UI - SkyTonight cards, Astrodex items, Plan My Night entries.

#### Beginner catalog

Curated seasonal list of 30–50 starter objects:
- Canonical reference image, why it is good for beginners, suggested framing, typical integration time
- Cross-linked to Astrodex ("have you captured this yet?") and Plan My Night
- Seasonally rotated based on current visibility at user location

#### Contextual tips system

Lightweight tooltip layer shown on first visit to each major feature. Dismissible; re-openable from a help icon. One to three sentences max: what this is, why it matters for astrophotography. Not a tutorial wizard - passive and non-intrusive.

**i18n in 6 languages.**


---

### v1.2 - Multi-location Profiles

| | |
|---|---|
| **Why** | Observers travel to dark sites; location drives every calculation (Plan My Night, SkyTonight, aurora, horizon, etc.) |
| **Effort** | Medium |

What needs to be built:

- **Location presets** - app list of saved locations (name, lat/lon, elevation, timezone, horizon profile, bortle, sqm). Creation only by admin. There is always a default location, if no location attributed to users.
- **Attribution of locations** - each locations (one or more) can be attributed to an user
- **Per-user settings** - user can select a default location, and sort locations if he have more that 2
- **Location switcher** - quick selector in the navbar; drives all active calculations
- **Backend extension** - extend existing location config in `auth.py` / `config_defaults.py`; no new storage module needed
- **Horizon profile per location** - associate a custom horizon with each preset
- **i18n** in 6 languages
- **Pre-requis** - must absolutely check for each external API the limit rate to define a limit of authorized location max.
- **Concerned modules** - these modules are specifically based on location: #forecast-astro (all subs), #forecast-weather (all subs), /#skytonight, #spaceflight/iss
- **Astrodex & Plan my night** - use of this location 
- **Advanced call API** - in case of multiple location there is a high risk that same API will be called multiple time quickly. Must be check if some API allow multiple requests in same call, or make an orchestration of calls following the previous did.
- **Notifications** - notifications must take care of location in message. Maybe user should have possibility to disable notification for specific location, in user params.
  
---

### v1.3 - Observation Log

| | |
|---|---|
| **Why** | Closes the loop: **Plan → Observe → Log → Astrodex**. Positioned after v1.2 so that beginners are already onboarded and have sessions worth logging. |
| **Effort** | High |

Users can record what they actually captured after a session, not just what they planned.

What needs to be built from scratch:

- **Session concept** - date, observing site (linked to multi-location preset from v1.1), equipment combo, start/end time, sky conditions (SQM, seeing, transparency)
- **Per-target entries** - actual frame count, integration time, notes, rating (1–5), link to Astrodex
- **New backend module** (`observation_sessions.py`) with per-user JSON storage, same pattern as `astrodex.py`
- **Import from plan** - one-click to seed a session from tonight's Plan My Night targets
- **New frontend** - session list, session detail, entry editor, i18n in 6 languages

The equipment and object models (Equipment, Astrodex) are reusable as references, but the session and entry data model is entirely new. This is a full feature, not an incremental one.

---

### v1.4 - Planning Intelligence

| | |
|---|---|
| **Why** | Advanced imagers need planning depth that matches dedicated tools (Telescopius). These features add no new data model - they derive from existing equipment profiles, SkyTonight data, and Plan My Night. |
| **Effort** | High |

#### Target visibility calendar

Per-object monthly heatmap: best months to image based on altitude arc + available dark hours at user location.

- Accessible from SkyTonight target cards and Astrodex item detail
- Answers "when is NGC 6992 best this year?" in one glance
- Computed server-side from ephemeris data already available in the stack

#### Mosaic planner

Multi-panel planning for targets that exceed the sensor FOV:

- Configure panel grid (2×1, 2×2, 3×2…), overlap percentage, rotation angle
- FOV overlay per equipment combination (reuses existing FOV calculator)
- Output: list of RA/Dec center points per panel → one-click add each as a Plan My Night entry
- Scope: planning-grade (not Telescopius-level interactive sky drag). The value is the Plan My Night integration.

#### Meridian flip estimator

Given a target and start time, compute when the equatorial mount flip will occur:

- Shown inline in Plan My Night timeline as a colored indicator
- Green: no flip during slot; orange: flip mid-session; red: flip within first 10 minutes
- Critical for unattended imaging sessions

#### Advanced SkyTonight filters

New filter sidebar panel:

- Angular size range (arcmin)
- Surface brightness threshold
- Best altitude window (e.g., "above 30° between 22h–02h")
- FOV fit: does the target fit the active equipment combination's sensor?
- Estimated minimum integration time

#### Session time optimizer

Given a Plan My Night target list, re-order entries to maximize average altitude during each assigned slot. One-click "optimize order" button in the Plan My Night toolbar.

**i18n in 6 languages.**

---

### v1.5 - Session Analytics

| | |
|---|---|
| **Why** | Answers "how am I progressing?" for beginners and "how am I optimizing?" for advanced users. Requires v1.3 (Observation Log) as data source. |
| **Effort** | Medium |

#### Personal stats dashboard

New section (or tab within an existing one):

- Total integration hours: lifetime / this year / this month
- Objects captured: count, constellation spread, object-type distribution
- Equipment usage: hours per telescope/camera combination
- Best imaging months at user location (derived from historical weather cache)

#### Wishlist tracker

- Mark any SkyTonight or catalog object as "on my wishlist"
- Progress view: X of Y wishlist objects captured, sorted by next visibility window
- Feeds directly into the Beginner Catalog (v1.2) - beginner objects can be pre-added to the wishlist on first setup

#### Sky coverage map

RA/Dec grid showing captured objects as colored dots:

- Color by object type or by capture date
- Visual sense of "where in the sky have I been?" - motivating for beginners tracking progress

#### Conditions correlation

For logged sessions: overlay seeing score, moon phase, and SQM at the time of capture. Helps identify: "my best sessions happen when seeing > 7 and Bortle < 5." Read-only aggregation - no new data model.

**i18n in 6 languages.**

---

### v2.0 - Interactive Sky Chart

| | |
|---|---|
| **Why** | The one missing visualization that every astronomer expects. Positioned at v2.0 because it has the highest integration surface - it becomes most useful once planning tools (v1.4), observation log (v1.3), and Astrodex are mature. |
| **Effort** | High |

Scope: a planning-grade sky chart integrated with existing data - not a full Stellarium simulation. This distinction keeps the feature achievable.

#### Sky chart view

- Renders stars to ~magnitude 8, constellation lines, DSO markers from the SkyTonight catalog
- Supports horizon-up (Alt/Az) and equatorial (RA/Dec) projection
- Pan and zoom; click an object → opens its existing SkyTonight target card
- Time slider: scrub through the night to preview altitude evolution
- Moon and planets overlaid

#### FOV overlay

- Toggle: render the active equipment combination's FOV rectangle on any selected target
- Instantly visualizes framing without leaving the app
- Pulls directly from the existing FOV calculator

#### Plan My Night integration

- Objects in tonight's plan highlighted with a colored ring on the chart
- Click a plan entry in the sidebar → centers the chart on that target
- Lasso-select a sky region → browse visible SkyTonight targets in that area

#### Astrodex overlay

- Objects already captured (in Astrodex) shown as filled dots vs. outlines
- Provides a visual "coverage" layer on top of the planning layer

**Technology:** [Aladin Lite](https://aladin.cds.unistra.fr/AladinLite/) (MIT-licensed, maintained by CDS Strasbourg) embedded via its JavaScript API - avoids building a sky renderer from scratch and provides professional-grade DSS/HiPS imagery as backdrop.

**i18n in 6 languages.**

---

### v2.1 - Community & Sharing

| | |
|---|---|
| **Why** | Single-user self-hosted installs benefit from sharing; club and family installs benefit even more. Built last in the 2.x cycle because it needs a stable feature set and a user base large enough to make sharing meaningful. v1.2 (beginner onboarding) is the prerequisite for that user base. |
| **Effort** | Medium |

#### Public Astrodex profiles (opt-in)

- User can set their Astrodex to public → accessible at `/u/<username>` without login
- Shareable link; optionally password-protected
- Profile shows: captured objects, equipment used, observation stats (from v1.5)

#### Export to external tools

Export Plan My Night or SkyTonight results as:

- Stellarium bookmarks (`.stel`)
- SkySafari observing list (`.skylist`)
- CSV with RA/Dec (extend existing export)
- NINA-ready target list (XML with coordinates and filter settings)

#### Community object of the month (admin-curated)

- Admin pins a seasonal target list → appears as a special SkyTonight category for all users
- Drives shared focus for club and family multi-user installs
- No external server required - purely local admin action

**i18n in 6 languages.**

---

### v2.2 - Integrations

| | |
|---|---|
| **Why** | Bridges MAB with the capture and guiding software that advanced imagers already run. Most niche audience - placed last. |
| **Effort** | High |

#### Plate solve (upload → coordinates)

- User uploads a FITS or JPEG → MAB calls the Astrometry.net public API → returns RA/Dec center, field scale, rotation angle
- Result: auto-populates Astrodex item coordinates and cross-links to the matching SkyTonight target
- Use case: "I just captured something - what exactly is it?"
- No local solver required; the public API handles it

#### PHD2 guiding log import

- Upload a PHD2 `PHD2_GuideLog` file → MAB parses: total guide time, RMS error, drift trend
- Result attached to an Observation Log session (v1.3)
- Session Analytics dashboard (v1.5) shows guiding quality trend per equipment combination over time

#### NINA sequence export

- From Plan My Night: generate a NINA-compatible sequence XML (target name, RA/Dec, filter, frame count, exposure)
- One-click download; ready to import into NINA without manual re-entry

#### INDI/ASCOM GoTo *(stretch goal)*

- Connect MAB to a running INDI server on the local network → send GoTo commands directly from Plan My Night
- High complexity; included as a stretch goal only - pursue based on user demand after the rest of v2.2 ships

**i18n in 6 languages.**

---

## Summary

| Version | Theme | Audience | Effort |
|---------|-------|----------|--------|
| v0.9 | Web Push E2E validation | All | Low |
| v1.0 | First stable release | All | Low |
| v1.1 | Multi-location profiles | All | Medium |
| v1.2 | First Light - beginner onboarding | Beginners | Medium |
| v1.3 | Observation Log | Intermediate+ | High |
| v1.4 | Planning Intelligence | Advanced | High |
| v1.5 | Session Analytics | All | Medium |
| v2.0 | Interactive Sky Chart | All | High |
| v2.1 | Community & Sharing | All | Medium |
| v2.2 | Integrations (plate solve, PHD2, NINA) | Advanced | High |

### Ordering rationale

- **v1.1 before v1.2** - Multi-location is foundational; the Observation Log (v1.3) uses location presets.
- **v1.2 before v1.3** - Beginners need onboarding before they have sessions worth logging. First Light is also Medium effort vs. the High effort of the Observation Log - better ROI first.
- **v1.5 after v1.3** - Session Analytics are meaningless without Observation Log data.
- **v2.0 after v1.4** - The Sky Chart's value multiplies when planning tools, FOV data, and Astrodex are all mature.
- **v2.1 after v1.2 + v1.5** - Community sharing needs both a user base (built by First Light) and content to share (stats from Analytics, captures from Astrodex).
- **v2.2 last** - Narrowest audience; most complex; no dependency on it from other features.
