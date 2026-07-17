# MyAstroBoard - Roadmap

This document describes features that could potentially be integrated into MyAstroBoard. There are no guarantees; consider this file a list of ideas that may evolve based on my own ideas or future discussions.

---

## Release Plan

### v1.2 - Multi-location Profiles

| | |
|---|---|
| **Why** | Observers travel to dark sites; location drives every calculation (Plan My Night, SkyTonight, aurora, horizon, etc.) |
| **Effort** | Medium |

What needs to be built:

- **Location presets** - app list of saved locations (name, lat/lon, elevation, timezone, horizon profile, bortle, sqm). Creation only by admin. There is always a default location, if no location attributed to users.
- **Attribution of locations** - each location (one or more) can be attributed to a user
- **Per-user settings** - user can select a default location, and sort locations if they have more than 2
- **Location switcher** - quick selector in the navbar; drives all active calculations
- **Backend extension** - extend existing location config in `auth.py` / `config_defaults.py`; no new storage module needed
- **Horizon profile per location** - associate a custom horizon with each preset
- **i18n** in 6 languages
- **Prerequisites** - must absolutely check for each external API the limit rate to define a limit of authorized location max. Detail of this calculation must be documented to easily recalculate it when API change their quota. Finally, if the result is 5 or more, we should limit to 5 locations.
- **Concerned modules** - these modules are specifically based on location: #forecast-astro (all subs), #forecast-weather (all subs), /#skytonight, #spaceflight/iss
- **Astrodex & Plan my night** - use of this location
- **Advanced call API** - in case of multiple locations there is a high risk that the same API will be called multiple times quickly. Must check whether some APIs allow multiple requests in the same call, or orchestrate calls following the same pattern as previous ones.
- **Notifications** - notifications must take care of location in message. Maybe user should have possibility to disable notification for specific location, in user params.

---

### v1.3 - Observation Log

| | |
|---|---|
| **Why** | Closes the loop: **Plan -> Observe -> Log -> Astrodex**. Positioned after v1.2 so that beginners are already onboarded and have sessions worth logging. |
| **Effort** | High |

Users can record what they actually captured after a session, not just what they planned.

What needs to be built from scratch:

- **Session concept** - date, observing site (linked to multi-location preset from v1.2), equipment combo, start/end time, sky conditions (SQM, seeing, transparency)
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
- Output: list of RA/Dec center points per panel -> one-click add each as a Plan My Night entry
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
- Feeds directly into the Beginner Catalog (v1.1) - beginner objects can be pre-added to the wishlist on first setup

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
- Pan and zoom; click an object -> opens its existing SkyTonight target card
- Time slider: scrub through the night to preview altitude evolution
- Moon and planets overlaid

#### FOV overlay

- Toggle: render the active equipment combination's FOV rectangle on any selected target
- Instantly visualizes framing without leaving the app
- Pulls directly from the existing FOV calculator

#### Plan My Night integration

- Objects in tonight's plan highlighted with a colored ring on the chart
- Click a plan entry in the sidebar -> centers the chart on that target
- Lasso-select a sky region -> browse visible SkyTonight targets in that area

#### Astrodex overlay

- Objects already captured (in Astrodex) shown as filled dots vs. outlines
- Provides a visual "coverage" layer on top of the planning layer

**Technology:** [Aladin Lite](https://aladin.cds.unistra.fr/AladinLite/) (MIT-licensed, maintained by CDS Strasbourg) embedded via its JavaScript API - avoids building a sky renderer from scratch and provides professional-grade DSS/HiPS imagery as backdrop.

**i18n in 6 languages.**

---

### v2.1 - Community & Sharing

| | |
|---|---|
| **Why** | Single-user self-hosted installs benefit from sharing; club and family installs benefit even more. Built last in the 2.x cycle because it needs a stable feature set and a user base large enough to make sharing meaningful. v1.1 (beginner onboarding) is the prerequisite for that user base. |
| **Effort** | Medium |

#### Public Astrodex profiles (opt-in)

- User can set their Astrodex to public -> accessible at `/u/<username>` without login
- Shareable link; optionally password-protected
- Profile shows: captured objects, equipment used, observation stats (from v1.5)

#### Export to external tools

Export Plan My Night or SkyTonight results as:

- Stellarium bookmarks (`.stel`)
- SkySafari observing list (`.skylist`)
- CSV with RA/Dec (extend existing export)
- NINA-ready target list (XML with coordinates and filter settings)

#### Community object of the month (admin-curated)

- Admin pins a seasonal target list -> appears as a special SkyTonight category for all users
- Drives shared focus for club and family multi-user installs
- No external server required - purely local admin action

**i18n in 6 languages.**

---

### v2.2 - Integrations

| | |
|---|---|
| **Why** | Bridges MAB with the capture and guiding software that advanced imagers already run. Most niche audience - placed last. |
| **Effort** | High |

#### Plate solve (upload -> coordinates)

- User uploads a FITS or JPEG -> MAB calls the Astrometry.net public API -> returns RA/Dec center, field scale, rotation angle
- Result: auto-populates Astrodex item coordinates and cross-links to the matching SkyTonight target
- Use case: "I just captured something - what exactly is it?"
- No local solver required; the public API handles it

#### PHD2 guiding log import

- Upload a PHD2 `PHD2_GuideLog` file -> MAB parses: total guide time, RMS error, drift trend
- Result attached to an Observation Log session (v1.3)
- Session Analytics dashboard (v1.5) shows guiding quality trend per equipment combination over time

#### NINA sequence export

- From Plan My Night: generate a NINA-compatible sequence XML (target name, RA/Dec, filter, frame count, exposure)
- One-click download; ready to import into NINA without manual re-entry

#### INDI/ASCOM GoTo *(stretch goal)*

- Connect MAB to a running INDI server on the local network -> send GoTo commands directly from Plan My Night
- High complexity; included as a stretch goal only - pursue based on user demand after the rest of v2.2 ships

**i18n in 6 languages.**

---

### v2.3 - Astro Intelligence (Night Copilot)

| | |
|---|---|
| **Why** | Every planning tool up to this point (Plan My Night, SkyTonight filters, Wishlist, Session Analytics) still requires the user to decide what to shoot. This version closes the loop by suggesting it. It's a pure software/data feature with no hardware connector required, so it can ship ahead of the live-integration cluster (v2.4+). |
| **Effort** | High |

#### Night Copilot

Suggests the best target for tonight using signals already collected elsewhere in the app:

- Weather forecast (existing #forecast-weather)
- Moon phase and position
- Seeing & transparency (existing #forecast-astro)
- User observation history (v1.3 Observation Log)
- Wishlist (v1.5)
- Available time window (Plan My Night)

Additional features:

- **Progress tracker** - visual "how close am I to done" per wishlist/catalog
- **Duplicate detection** - warn before re-planning a target already well-captured (reuses Astrodex + Observation Log)
- **Equipment recommendations** - suggest the best telescope/camera combo from the user's equipment list for a given target
- **Exposure recommendations** - suggest sub-exposure length and total integration time based on target surface brightness, moon phase, and historical results for similar targets

**Prerequisites** - meaningful recommendations need v1.3 (Observation Log) and v1.5 (Session Analytics/Wishlist) as data sources, and benefit from v2.0 (Sky Chart) for target context.

**i18n in 6 languages.**

---

### v2.4 - Observatory Dashboard

| | |
|---|---|
| **Why** | Turns MyAstroBoard into the real-time dashboard of the observatory, not just a planning tool. First of the "live" versions - it requires a persistent device-connector layer (ASCOM Alpaca / INDI) that today only exists as the v2.2 GoTo stretch goal. |
| **Effort** | High |

What needs to be built:

- **Live equipment status** - real-time state (connected / parked / slewing / imaging) pulled via ASCOM Alpaca or INDI
- **Multi-rig support** - dashboard scales to more than one telescope/camera setup running concurrently
- **Live image preview** - last captured frame, pulled from the imaging software's output folder or API
- **Night timeline** - chronological visual log of tonight's sequence events (slew, filter change, meridian flip, errors)
- **Power & weather monitoring** - local sensors or Home Assistant entities (mains power, dew point, cloud cover) surfaced on the dashboard

**Prerequisites** - promotes v2.2's INDI/ASCOM GoTo stretch goal from a one-off command into a persistent connector; requires the app to reach devices on the local network, which is a deployment consideration for cloud/remote installs.

**i18n in 6 languages.**

---

### v2.5 - NINA Companion

| | |
|---|---|
| **Why** | Not a replacement for NINA - a live companion view for users who already run NINA as their capture software. Upgrades v2.2's file-based NINA sequence export / PHD2 log import into a live, bidirectional connection. |
| **Effort** | High |

Features:

- **Live NINA connector** - via NINA's Advanced API plugin, replacing manual XML export with direct sequence push and live read-back
- **Sequence monitoring** - real-time progress of the running NINA sequence inside MAB
- **End-of-session report** - auto-generated summary (frames captured, time per filter, errors) at sequence completion
- **Guiding statistics** - live RMS/drift trend, superseding v2.2's static PHD2 log import
- **Storage monitoring** - free disk space on the capture PC, warns before a session fills the drive

**Prerequisites** - builds directly on the live-connector layer from v2.4; requires the NINA Advanced API plugin on the user's rig.

**i18n in 6 languages.**

---

### v2.6 - Smart Automation

| | |
|---|---|
| **Why** | With live equipment status (v2.4) and NINA telemetry (v2.5) available, MAB can start acting on conditions instead of only displaying them. |
| **Effort** | High |

Features:

- **Weather-aware planning** - Plan My Night re-evaluates automatically as forecast conditions change through the night
- **Dynamic target switching** - suggest (or, opt-in, auto-apply) a swap to a better-positioned/clearer target when conditions shift
- **Smart notifications** - push alerts tied to live equipment/weather state (e.g. "clouds rolling in", "guiding RMS degrading"), extending the existing notification system with the location-awareness added in v1.2
- **Automatic pause/resume** - pause the running sequence on cloud cover / high wind / meridian-flip risk, resume when clear

**Prerequisites** - v2.4 (live status), v2.5 (NINA telemetry), and the existing push notification infrastructure.

**i18n in 6 languages.**

---

### v2.7 - Observatory Orchestrator

| | |
|---|---|
| **Why** | Coordinates every connector built through v2.4-v2.6 into a single one-click flow - the payoff of the live-integration cluster. |
| **Effort** | High |

Coordinates:

- NINA
- PHD2
- ASCOM Alpaca
- Home Assistant *(net-new connector, not covered by earlier versions)*
- Weather
- Notifications

One-click night:

1. Check weather
2. Connect devices
3. Start sequence
4. Monitor
5. Park mount
6. Generate report

**Prerequisites** - v2.4, v2.5, v2.6; adds a new Home Assistant connector for power/roof/dome control.

**i18n in 6 languages.**

---

### v3.0 - Personal Observatory OS

| | |
|---|---|
| **Why** | Long-term vision, not a committed release. MyAstroBoard orchestrates existing astro software (NINA, PHD2, ASCOM Alpaca, INDI, Seestar, Stellarium, Home Assistant, weather, AllSky…) rather than replacing it, and becomes the one place that remembers everything across years of sessions - the equivalent of Home Assistant for astronomy. |
| **Effort** | Very high / open-ended |

#### Plugin ecosystem

- Public connector API so the community can build and share their own integrations (NINA, PHD2, ASCOM Alpaca, INDI, Seestar, Stellarium, Home Assistant, weather providers, AllSky, etc.)
- Lets MAB grow its integration surface without one person maintaining every connector

#### Intelligent journal (observatory memory)

Natural-language queries over the history accumulated in Observation Log (v1.3) and Session Analytics (v1.5), e.g.:

- "What's my best image of M31?"
- "Which setup works best for galaxies?"
- "How many hours have I logged on IC 1396?"
- "Which nights with seeing > 4 produced my best images?"
- "What Caldwell objects are left to photograph?"

Also:

- Best equipment by target (long-term aggregation, feeds back into the v2.3 recommendation engine)
- Best conditions by target/season
- Integration history across all connectors
- Personal, evolving recommendations

---

## Summary

| Version | Theme | Audience | Effort | Implemented |
|---------|-------|----------|--------|--------|
| v0.9 | Web Push E2E validation | All | Low | X |
| v1.0 | First stable release | All | Low | X |
| v1.1 | First Light - beginner onboarding | Beginners | Medium | X |
| v1.2 | Multi-location profiles | All | Medium | |
| v1.3 | Observation Log | Intermediate+ | High | |
| v1.4 | Planning Intelligence | Advanced | High | |
| v1.5 | Session Analytics | All | Medium | |
| v2.0 | Interactive Sky Chart | All | High | |
| v2.1 | Community & Sharing | All | Medium | |
| v2.2 | Integrations (plate solve, PHD2, NINA) | Advanced | High | |
| v2.3 | Astro Intelligence (Night Copilot) | All | High | |
| v2.4 | Observatory Dashboard | Advanced | High | |
| v2.5 | NINA Companion | Advanced | High | |
| v2.6 | Smart Automation | Advanced | High | |
| v2.7 | Observatory Orchestrator | Advanced | High | |
| v3.0 | Personal Observatory OS | All | Very High | |
