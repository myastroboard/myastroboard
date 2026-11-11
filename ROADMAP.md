# MyAstroBoard - Roadmap

This document describes features that could potentially be integrated into MyAstroBoard. There are no guarantees; consider this file a list of ideas that may evolve based on my own ideas or future discussions.

**Status legend:** ✅ Implemented - shipped · 🗓️ Planned - next in line · 💡 Idea - not started, scope and priority may change.

---

## Architecture direction

MyAstroBoard is an **opinionated core, not a plugin platform.** Extensibility is delivered through narrow, documented extension points where a contributor can add value as one reviewable unit - not through a feature-level plugin system that a stranger cannot safely write anyway:

- **Catalogues** - JSON cross-ref / standalone files (already the mechanism for Pensack 500, LBN, GaryImm, Arp, Sharpless, Barnard, vdB, Abell). Adding one is a JSON file plus a short registration block.
- **Export formatters** - a small registry shipped with v1.10 (Stellarium, SkySafari, NINA, AstroBin, CSV).
- **Connectors** - the `BaseConnector` contract (talk to an external system, return data), hardened in-tree one connector at a time - see [below](#on-the-former-connector-sdk-and-mab-plugins-was-v16).

The recipe per extension type lives in [docs/EXTENDING.md](docs/EXTENDING.md); the connector recipe is already filled in, the export-formatter section is filled in as v1.10 lands.

### On the former "Connector SDK and mab-plugins" (was v1.6)

A public, versioned `BaseConnector` SDK plus a separate `myastroboard/mab-plugins` repository for
community connectors - i.e. a connector catalogue - was previously slotted at v1.6. It is
dropped:

- A connector already gets its narrow, reviewable contract from `BaseConnector` itself - no
  version-range negotiation or install-from-catalogue machinery has turned out to be needed to
  get that. The 2026-09-15 connector refactor (MyAstroShine promoted to a first-class
  `BaseConnector`, one module per connector on both sides, each connector owning its own
  constants and declaring its `target_modules`) delivered the actual benefit the SDK was chasing -
  a uniform, reviewable shape - without a public API surface or an external repository to
  maintain compatibility against.
- A separate curated repository is a distribution and moderation commitment (compatibility
  matrix, reviewed PRs from strangers, an in-app installer) with no requester behind it yet. New
  connectors keep landing directly in `backend/connectors/` by PR, same as AllSky and
  MyAstroShine.
- Reconsidered only if an external contributor actually shows up wanting to maintain a connector
  MAB would rather not carry in-tree - the same bar the old v1.6 entry already set, just without
  building the catalogue machinery in advance of that demand.

The freed v1.6 slot goes to the MQTT Publisher connector below - a concrete, scoped connector,
not the general-purpose SDK.

### On the former "Feature Registry" (was v1.5)

A formal feature manifest and registry - every feature declaring its routes, i18n namespace, cache jobs, capabilities and migration hooks - was previously a dedicated release. It has been dissolved:

- **Breaking the internal feature-dependency cycles** (astrodex <-> equipment, equipment <-> observation log, equipment <-> plan my night, events <-> skytonight, skytonight <-> weather) is real and worth doing - but as **ongoing hygiene**: one cycle broken per release as that area is touched, plus a "no new cycles" code-review rule. Not a refactoring-only release with no user-visible surface.
- **Per-feature i18n namespaces** are adopted incrementally when a feature's files are touched, and `validate_i18n.py` gains namespace-by-namespace parity checks at that point.
- A **formal registry** (registry-driven navbar, per-feature enable flags, declared capabilities) is reconsidered only in the 2.x line, and only if two or more features concretely need it. Building it now to serve a *possible* v3.0 is retrofit speculation, not retrofit debt.

---

## Release Plan

### v0.9 - Web Push E2E Validation

| | |
|---|---|
| **Why** | Ship the one half-done feature before declaring stability - the Web Push infrastructure (VAPID keys, `push_manager.py`, `push_scheduler.py`, SW handler) was fully built but needed real-device validation. |
| **Effort** | Low |
| **Status** | ✅ Implemented |

End-to-end Web Push notifications validated on Android (Chrome) and iOS (Safari), including delivery while the tab is closed.

---

### v1.0 - First Stable Release

| | |
|---|---|
| **Why** | A clean, self-hostable release that a new user can install and use in under 15 minutes. |
| **Effort** | Low |
| **Status** | ✅ Implemented |

`docker compose up` install with no manual steps, all 6 i18n languages complete, stabilized API routes, and up-to-date documentation.

---

### v1.1 - First Light (Beginner Experience)

| | |
|---|---|
| **Why** | Astrophotography has a steep learning curve; today MAB assumes prior knowledge. Lowering the floor grows the user base and makes every later feature more valuable. |
| **Effort** | Medium |
| **Status** | ✅ Implemented |

Guided first-run setup wizard, a "what to shoot tonight?" recommender, a curated beginner catalog, and a contextual tips system across the app.

---

### v1.2 - Multi-location Profiles

| | |
|---|---|
| **Why** | Observers travel to dark sites; location drives every calculation (Plan My Night, SkyTonight, aurora, horizon, etc.) |
| **Effort** | Medium |
| **Status** | ✅ Implemented |

Admin-managed location presets (with horizon profile, bortle, SQM) that users can be attributed to, pick a default from, and switch between via a navbar selector - driving every location-aware module (Plan My Night, SkyTonight, forecasts, ISS, Astrodex, notifications).

Also shipped in this release, outside the multi-location theme: the **Plan My Night schedule optimizer**. It proposes a target order plus a single pre-first-target delay derived from each target's real altitude-based visibility window, previews the result with per-entry warnings (never observable, window too short, truncated, pushed past night end), and refuses to apply if the plan changed since the preview.

---

### v1.3 - Observation Log

| | |
|---|---|
| **Why** | Closes the loop: **Plan -> Observe -> Log -> Astrodex**. Positioned after v1.2 so that beginners are already onboarded and have sessions worth logging. |
| **Effort** | High |
| **Status** | ✅ Implemented |

Users can record what they actually captured after a session, not just what they planned.

What needs to be built from scratch:

- **Session concept** - date, observing site (linked to multi-location preset from v1.2), equipment combo, start/end time, sky conditions (SQM, seeing, transparency)
- **Per-target entries** - actual frame count, integration time, notes, rating (1-5), link to Astrodex
- **New backend module** (`observation_sessions.py`) with per-user JSON storage, same pattern as `astrodex.py`
- **Import from plan** - one-click to seed a session from tonight's Plan My Night targets
- **New frontend** - session list, session detail, entry editor, i18n in 6 languages

The equipment and object models (Equipment, Astrodex) are reusable as references, but the session and entry data model is entirely new. This is a full feature, not an incremental one.

---

### v1.4 - Planning Intelligence

| | |
|---|---|
| **Why** | Advanced imagers need planning depth that matches dedicated tools (Telescopius). These features build on the existing equipment profiles, SkyTonight ephemeris, and Plan My Night timeline - but they are not free of new state: the meridian flip estimator adds mount flip fields, and the visibility calendar adds a year-scale ephemeris path with its own cache. |
| **Effort** | High |
| **Status** | ✅ Implemented |

#### Target visibility calendar

Per-object monthly heatmap: best months to image based on altitude arc + available dark hours at user location.

- Accessible from SkyTonight target cards and Astrodex item detail
- Answers "when is NGC 6992 best this year?" in one glance
- Computed server-side on demand: the existing SkyTonight pipeline only ever covers *tonight* (per-target altitude outputs are wiped on every run), so this adds a year-scale ephemeris path with its own cache
- Deep sky objects only - a fixed-coordinate calendar is meaningless for planets and comets

#### Meridian flip estimator

Given a target and start time, compute when the equatorial mount flip will occur:

- Shown inline in Plan My Night timeline as a colored indicator
- Green: no flip during slot; orange: flip mid-session; red: flip within first 10 minutes
- Requires new mount fields on the Equipment profile (flip required, past-meridian tracking allowance, flip duration) - the current mount model carries none of them
- Critical for unattended imaging sessions

#### Advanced SkyTonight filters

New filter sidebar panel:

- Angular size range (arcmin)
- Surface brightness threshold
- Best altitude window (e.g., "above 30° between 22h-02h")
- FOV fit: does the target fit the active equipment combination's sensor?
- Estimated minimum integration time (needs a formula that does not exist yet - the Exposure Calculator sizes subs *from* a total integration, it never estimates the total)

Applied server-side, before the result-set truncation: the DSO payload is capped at the top targets by AstroScore, so a filter applied client-side over that list would look like a catalogue-wide search without being one.

**i18n in 6 languages.**

---

### v1.5 - Session Analytics

| | |
|---|---|
| **Why** | Answers "how am I progressing?" for beginners and "how am I optimizing?" for advanced users. Requires v1.3 (Observation Log) as data source. Kept as the release right after v1.4 - a user-visible feature that also tests whether any shared feature structure is actually needed, rather than a refactoring-only release that speculates about it. |
| **Effort** | Medium |
| **Status** | ✅ Implemented |

#### Personal stats dashboard

New section (or tab within an existing one):

- Total integration hours: lifetime / this year / this month
- Objects captured: count, constellation spread, object-type distribution
- Equipment usage: hours per telescope/camera combination
- Best imaging months at user location: dark and moonless-dark hours per month computed live from the ephemeris, next to the hours actually logged. **Not** derived from a historical weather cache - no such cache exists (every weather cache is a short-TTL forecast snapshot), so the chart never claims to say when the sky is clear. A weather climatology behind its own scheduler cache job was specified and deliberately deferred.

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

It adds a whole new surface (tab, sub-tabs, i18n namespace, aggregations). If building it makes a shared registry feel *necessary* rather than merely tidy, that is the signal to scope one; if the existing per-domain conventions absorb it fine, that is the signal not to.

**Verdict after shipping: no registry needed.** The release added one blueprint, two i18n
namespaces, two sub-tab entries in `switchSubTab()`, one CSS file and two script tags - every one
a single-line insertion into an existing list. What it *did* surface was duplication (four copies
of the constellation abbreviation table) and a real data-shape inconsistency (the stored `ra`/`dec`
on a frozen target is a float on one code path and a formatted string on another). Both were fixed
with a shared helper in `utils/` and a single resolver module, which is the mechanism
[Architecture direction](#architecture-direction) already prescribes. Per-domain conventions
absorbed the feature, so no registry is scoped.

---

### v1.6 - MQTT Publisher & Home Assistant Integration

| | |
|---|---|
| **Why** | The connector pattern hardened through AllSky and MyAstroShine (one module per connector, `target_modules`, declared config/secret fields) is solid enough to point outward instead of only pulling data in. A lot of self-hosted astro setups already run Home Assistant for the rest of the observatory (power, roof, weather sensors); publishing MAB's own state as MQTT lets it show up on an existing HA dashboard instead of requiring a second one. Scoped as a publish-only connector - no inbound control, no device layer - so it does not need to wait for the v2.4+ live-equipment cluster. Replaces the dropped "Connector SDK and mab-plugins" idea in this slot - see [Architecture direction](#on-the-former-connector-sdk-and-mab-plugins-was-v16). |
| **Effort** | Medium |
| **Status** | ✅ Implemented (connector) |

#### MQTT Publisher connector

- `MqttConnector` in `backend/connectors/` - same shape as AllSky/MyAstroShine, plus a
  background publisher thread (`mqtt_publisher.py`, started like the push scheduler) that
  pushes to the broker on an interval and on Home Assistant's birth message
- Home Assistant MQTT Discovery (device-based, HA 2024.11+): one device for the board, one per
  location preset, one per opted-in user - no YAML on the HA side
- Six modules: sky conditions (period, night score, sun/moon, dark and best windows, top
  target), weather now, upcoming events, user activity (Astrodex counters, plan, equipment,
  log totals), latest Astrodex picture (HA `image` entity), board diagnostics
- Parameters: broker URL (`mqtt://` / `mqtts://`), user + password, discovery toggle, base
  topic, interval, client id, self-signed TLS. The password lives in the new connector
  credentials sidecar, outside `config.json` and outside backups (applies to MyAstroShine's
  credentials too, migrated automatically)

#### Companion Home Assistant cards repository

- Separate repository [lovelace-myastroboard-card](https://github.com/myastroboard/lovelace-myastroboard-card):
  ready-made Lovelace cards and dashboard YAML that consume the topics above - HA-side
  definitions only, no code inside MAB, so none of the trust-boundary concerns of the dropped
  mab-plugins idea
- HACS *Dashboard* category (one `.js` named after the repository, `hacs.json`, GitHub releases)
- Status: repository created, content in progress

#### Topics published

Answered during implementation - the full entity and topic reference is in
[docs/HOME_ASSISTANT.md](docs/HOME_ASSISTANT.md):

- Multi-location: one HA device per preset, keyed by its uuid. Multi-user: one device per user
  who opted in themselves (Parameters -> Customize), gated by admin module toggles
- Astrodex as a camera entity: same connector, `astrodex_image` module, HA `image` platform fed
  with the newest picture (resized, no coordinates)
- Weather and night score: both published (`observation_score` 0-10 is the sky widget's score)

**i18n in 6 languages.**

#### Astrodex Stream connector

A second, unrelated connector landed in the same v1.6 slot: a personal, auto-refreshing photo
slideshow of a user's Astrodex pictures, servable to Home Assistant's **Generic Camera**
integration (or any still-image viewer) without a real video stream.

- `AstrodexStreamConnector` in `backend/connectors/` - same shape as the others, no `MODULES`
  (the slideshow is the whole connector), no `SECRET_FIELDS` (the per-user signing key is
  auto-generated, never admin-entered)
- RTSP and a continuously pushed MJPEG stream were both considered and rejected: the first needs
  a new Docker port (incompatible with this project's zero-manual-config promise), the second
  would starve the app's synchronous `gunicorn` workers with long-lived connections. The server
  instead renders whichever photo is "current" as a pure function of wall-clock time, and a
  client just polls a plain JPEG URL - full reasoning in
  [docs/ASTRODEX_STREAM.md](docs/ASTRODEX_STREAM.md#why-not-a-real-video-stream)
- One signed URL per user (HMAC-SHA256, nothing stored per user) so a club install can't let one
  member read another's stream; a shared URL (every user's photos merged) is available only when
  Astrodex is not set to private; an admin **Rotate keys** action invalidates every URL at once
- Photos shuffle rather than repeating in a fixed alphabetical order, never the same one
  back-to-back; no crossfade transition between photos - a client polling mid-transition would
  latch onto a half-blended frame until its own next poll, so every served frame is always one
  full, clean photo

**i18n in 6 languages.**

---

### v1.7 - Database Storage

| | |
|---|---|
| **Why** | Everything persistent lived in JSON files under `data/`, one per user and per feature. Two gunicorn workers writing them needed file locks, temp files and backup copies in every module, an account deletion could leave files behind, and every search across users (delete guards, shared equipment, picture visibility) re-read every user's files. A relational database with versioned migrations gives transactions, referential integrity and a schema that can evolve safely - groundwork the 2.x releases (sky chart overlays, sharing, integrations) build on. |
| **Effort** | High |
| **Status** | ✅ Implemented |

#### SQLite storage, fully relational

- One SQLite database, `data/myastroboard.db` - no extra container, still zero configuration
- One row per object: Astrodex items and pictures, observation sessions, nights, entries and
  attachments, wishlist items, equipment, combinations and their filters/accessories, plans and
  plan entries; accounts and settings (configuration, app/security settings, secrets, VAPID keys)
- Parent -> child foreign keys with cascades, unique ids per user, indexed search columns; each
  row also keeps the object as JSON, so a field the schema does not know yet is never lost
- Every write is one transaction, which also serializes the gunicorn workers (no file locks)
- Cross-user searches are SQL queries instead of loops over every user's data
- Pictures, attachments, caches and SkyTonight results stay files

#### Schema migrations (Alembic)

- Versioned, reversible migrations, applied automatically at start under a cross-process lock
  (one worker migrates, the other waits)
- CI checks that migrations apply both ways and match the table definitions

#### One-shot import of the 1.6 data

- On first start: archive every 1.6 file into `data/backups/pre-1.7-<date>.zip` (re-read and
  checked), import everything in one transaction, read each record back and compare it with its
  file, and only then delete the JSON files; a report is written next to the archive
- Files of deleted accounts and unreadable per-user files are moved aside, never lost
- Any failure: nothing imported, nothing deleted, the instance shows a maintenance page and can
  go back to 1.6 untouched

#### Backup, privacy and recovery

- Admin backup ZIP keeps the 1.6 JSON layout (1.6 backups restore on 1.7), secrets still excluded
- Account deletion removes all of the user's rows in one transaction; "Download my data" is
  built from the database
- `backend/db/manage.py` command line replaces hand-editing `users.json` (reset a password,
  disable 2FA, status)

Full reference: [docs/DATABASE.md](docs/DATABASE.md).

---

## Direction after v1.7

Up to v1.7 the roadmap built the full loop **Plan -> Observe -> Log -> Astrodex -> Review**. What
the application still lacks is not depth but **visibility**: nothing it produces is an image
someone wants to share, it cannot be tried without installing it, and the most expected planning
visual (what the sensor sees on a target) is missing. The remaining 1.x releases therefore make the
application **visible**, then **effortless**; none of them needs any hardware connection.

Each release is planned around one thing worth showing, so that a release is also something to
publish.

What changed from the previous 2.x plan:

- **Pulled forward into 1.x**: the field-of-view overlay (as a framing simulator on a still
  image), exports to external tools, and public profiles.
- **Pulled forward inside 2.x**: plate solving, now paired with image annotation, and the Night
  Copilot.
- **Merged and deferred**: the former v2.4-v2.7 (Observatory Dashboard, NINA Companion, Smart
  Automation, Observatory Orchestrator) become one demand-driven line, v2.4+. They are the most
  expensive items, serve the narrowest audience, overlap with mature capture software, and carry a
  hardware-safety risk no other feature has.
- **New**: share cards, year in review, achievements, automatic log import from FITS headers,
  multi-night imaging projects, moon-aware filter advice, 7-night outlook, transient alerts,
  planetary and lunar section, club mode.

---

### v1.8 - See and Show

| | |
|---|---|
| **Why** | The application has no shareable output and no visual answer to the first question every imager asks: "what will this target look like in my instrument?" Dedicated tools (Telescopius, the NINA framing assistant) answer it, so users leave MyAstroBoard at the exact moment they prepare a night. |
| **Effort** | Medium |
| **Status** | ✅ Implemented (framing simulator, share cards) - the website tour and the follow-ups below are still open |

#### Framing simulator

Shipped:

- A **Framing** action on the SkyTonight deep-sky table, Plan My Night entries, the Wishlist and
  Astrodex items
- Real sky imagery (DSS2 colour) centred on the target, with the sensor rectangle of the selected
  equipment combination drawn to scale
- Sensor rotation, centre offset by dragging, overlay of up to three combinations for comparison;
  the best fit is selected on opening, or the plan's own combination from Plan My Night
- A plain-language verdict (good fit, tight, small, larger than the field with an estimated mosaic
  grid) and PNG export
- Built on the existing FOV formulas and a server-side cache of CDS imagery: the browser never
  calls a third party

Follow-ups:

- Eyepiece field circle for visual observers - the equipment model has no eyepiece yet
- Save the framing (centre and rotation) on a Plan My Night entry - needs a plan model change

#### Share cards

A **Share** action that renders a ready-to-post image, in the formats the main image networks show
uncropped (4:5 by default, 1:1, 16:9, 9:16), from data the application already holds:

- **Astrodex photo** - the picture with its acquisition details (equipment, frames, sub-exposure,
  total integration, date)
- **Session recap** - targets, total integration and conditions of a logged night
- **Framing** - the framing simulator view (its own PNG export; moving it onto the share card
  engine and its formats is a follow-up)
- **My sky tonight** - night score, dark window, Moon phase, top targets
- **Event** - an upcoming event (eclipse, meteor shower, ISS transit, comet) with its time for the
  user's own location; the altitude is not part of the event data yet

Rendered in the browser, nothing is sent anywhere. No coordinates and no location name; each field
can be removed before export. A small "MyAstroBoard - myastroboard.org" footer is on by default
and can be turned off.

#### Try before installing

- A guided tour on the project website: one short looping clip per key moment, then the one-line
  install
- A **static demo** is under evaluation: the real interface served as plain files from recorded API
  responses, at no hosting cost. Server-side filters, searches and calculations would only work for
  the recorded cases, and the sky shown is the one recorded, not tonight's
- A hosted, live read-only demo instance is **not planned**: it needs paid infrastructure

**i18n in 6 languages.**

---

### v1.9 - My Progress

| | |
|---|---|
| **Why** | Your Sky already computes how an observer is doing, as a dashboard to consult. The same figures told as a dated story, and as milestones to reach, give a reason to go back out and something to show. Mostly a new presentation of existing aggregations. |
| **Effort** | Medium |
| **Status** | 🗓️ Planned - next in line |

#### Year in review

- A short sequence of screens for a given year: total integration and nights, objects captured and
  new this year, target of the year, best night, hardest-working equipment, catalogue progress, a
  mosaic of the year's best pictures
- Each screen exports as a share card
- Available all year for any past year; highlighted on the dashboard around the end of the year
- Strictly private, like the Observation Log; a screen with no data is hidden, never shown empty
- Date-sensitive: it is only worth publishing in December, so it may ship ahead of v1.8

#### Achievements and challenges

- Badges computed from what was actually logged: first galaxy / nebula / comet, Messier and other
  catalogue milestones, integration hours, seasons and constellations covered
- Seasonal challenges generated from real visibility at the user's location, never from a dated
  hardcoded list; a **Messier marathon** planner at the right time of year, with the achievable
  count for the latitude
- A "next within reach" view linking to the missing targets visible tonight
- Sober by design and can be turned off; no ranking between users

**i18n in 6 languages.**

---

### v1.10 - Effortless Log

| | |
|---|---|
| **Why** | Manual entry is what makes experienced imagers drop a logbook after three nights: their capture software has already written everything into each file. This release makes the log fill itself, tracks multi-night work per filter, and lets a plan leave for the tools that run the hardware. |
| **Effort** | High |
| **Status** | 💡 Idea - subject to change |

#### Automatic import from FITS headers

- Drop the folder of a night into the browser: only the **header** of each file is read, in the
  browser; the images are never uploaded
- Frames are grouped by night, target and filter; calibration frames are set aside
- A review screen (target matched to the catalogue, proposed equipment combination, duplicates)
  before anything is saved
- Covers the common capture sources (NINA, ASIAIR, SharpCap, smart telescopes)

#### Multi-night imaging projects

- A project is a target, an equipment combination and an integration goal, optionally per filter
  ("8 h H-alpha, 6 h OIII, 6 h SII")
- Progress bars fed by the Observation Log; remaining time, next visibility window and end of
  season for the target
- Projects in progress and visible tonight are proposed first in Plan My Night
- Requires a per-filter breakdown on log entries, which v1.3 left out of scope

#### Exports to external tools

- Target lists from Plan My Night, the Wishlist and SkyTonight: NINA, Stellarium, SkySafari,
  extended CSV
- Acquisition details from the log: AstroBin acquisition CSV, and a one-line technical caption
- Ships the small **export formatter registry** announced under
  [Architecture direction](#architecture-direction)

#### Moon-aware filter advice

- Each target is tagged broadband or narrowband-friendly from its object type and catalogue
- A plain advice line for tonight's Moon, and a "suits tonight's Moon" quick filter
- Takes the filters of the active equipment combination into account
- Advice only in this release; AstroScore is not changed

**i18n in 6 languages.**

---

### v1.11 - Open to the Outside

| | |
|---|---|
| **Why** | The application answers "tonight?" well but not "which night this week?", knows nothing about new objects appearing in the sky, has little for lunar and planetary observers, and gives a user nowhere to point people to. |
| **Effort** | High |
| **Status** | 💡 Idea - subject to change |

#### 7-night outlook

- Seven tiles on the dashboard, one per night: overall score, clouds, wind, dew risk, moonless dark
  hours, seeing when available, and a one-line verdict
- A night opens its hourly detail and its best targets
- Nights beyond three days are marked as uncertain
- Optional notification for the best night of the week; published through the MQTT connector

#### Public observatory page (opt-in)

- A public address without login, per user, off by default; the administrator can disable the
  feature for the whole instance
- The user chooses block by block what is shown: pictures individually marked public, headline
  figures, equipment, badges, tonight's conditions without position
- No coordinates, no location name, no map; the Observation Log stays private
- Link preview tags, and a small embeddable "sky tonight" widget for a club website

#### Transient alerts

- A **Transients** list next to comets: bright supernovae and novae, with tonight's visibility from
  the user's location
- Magnitude limit adjustable to the equipment; same actions as any target (altitude chart, framing,
  Plan My Night, Astrodex)
- A notification trigger for a new bright transient observable from the location
- Live source only: no dated hardcoded list; depends on a data source whose access terms allow it

#### Planetary and lunar

- Planets tonight: best time, altitude, apparent diameter, and a planetary score driven by seeing
  and altitude rather than Moon and sky darkness
- Jupiter's Galilean moons and their events, Saturn's ring tilt, phases of the inner planets
- Moon tonight: features near the terminator, known lighting effects (Lunar X and V) with their
  time, libration
- Planet size in pixels for the selected equipment combination

**i18n in 6 languages.**

---

### v2.0 - Interactive Sky Chart

| | |
|---|---|
| **Why** | The one missing visualization that every astronomer expects. Positioned at v2.0 because it has the highest integration surface - it becomes most useful once planning tools (v1.4), observation log (v1.3), Astrodex and the framing simulator (v1.8) are mature. |
| **Effort** | High |
| **Status** | 💡 Idea - subject to change |

Scope: a planning-grade sky chart integrated with existing data - not a full Stellarium simulation. This distinction keeps the feature achievable.

#### Sky chart view

- Renders stars to ~magnitude 8, constellation lines, DSO markers from the SkyTonight catalog
- Supports horizon-up (Alt/Az) and equatorial (RA/Dec) projection
- Pan and zoom; click an object -> opens its existing SkyTonight target card
- Time slider: scrub through the night to preview altitude evolution
- Moon and planets overlaid

#### Interactive framing

- The v1.8 framing simulator becomes a layer of the chart: the sensor rectangle is moved and
  rotated over zoomable imagery, with other surveys (H-alpha) as backdrop

#### Mosaic planner

Multi-panel planning for targets that exceed the sensor FOV - the multi-panel extension of the framing simulator.

- Configure panel grid (2x1, 2x2, 3x2...), overlap percentage, rotation angle
- Live grid preview on the chart, over the DSS/HiPS backdrop, per equipment combination
- Output: list of RA/Dec center points per panel -> one-click add each as a Plan My Night entry
- Panel centers are arbitrary coordinates, not catalogue targets: plan entries gain a mosaic grouping, and each panel must inherit its parent target's altitude curve so the timeline, optimizer, and exports still report real visibility
- Panel coordinates must come from a proper spherical offset, not a flat RA/cos(dec) approximation - large mosaics are built precisely at the high declinations where the flat form breaks down

#### Plan My Night integration

- Objects in tonight's plan highlighted with a colored ring on the chart
- Click a plan entry in the sidebar -> centers the chart on that target
- Lasso-select a sky region -> browse visible SkyTonight targets in that area

#### Astrodex overlay

- Objects already captured (in Astrodex) shown as filled dots vs. outlines
- Provides a visual "coverage" layer on top of the planning layer

**Technology:** [Aladin Lite](https://aladin.cds.unistra.fr/AladinLite/) (maintained by CDS Strasbourg) embedded via its JavaScript API - avoids building a sky renderer from scratch and provides professional-grade DSS/HiPS imagery as backdrop. Its license must be confirmed as AGPL-3.0 compatible before adoption; the library is vendored and its imagery goes through a server-side cached proxy, like the map tiles.

**i18n in 6 languages.**

---

### v2.1 - Astro Intelligence

| | |
|---|---|
| **Why** | Two features that make the application say something the user did not know: what is really in a picture, and what to shoot tonight. Both are pure software, so they come before any hardware integration. |
| **Effort** | High |
| **Status** | 💡 Idea - subject to change |

#### Plate solve and annotated image

- Analyse an Astrodex picture: centre, field scale and rotation are computed and stored on it
- **Annotation**: every catalogue object inside the field is labelled on the picture; the annotated
  image exports as a share card
- "Also in this image": each object found can be added to Astrodex in one click
- Measured field compared with the theoretical field of the equipment combination
- Built as an opt-in connector (the Astrometry.net public API first; a local solver as an option),
  because the picture leaves the instance

#### Night Copilot

Every planning tool up to this point still requires the user to decide what to shoot. The Copilot proposes it, with reasons. A rule engine over signals already collected, not a generative model:

- **Proposed night** - one click builds a complete, editable plan opened in Plan My Night
- **Reasons in plain language** for each choice (high from 22:00 to 02:00, on the wishlist, 3 h
  missing on a project, Moon set at 23:00)
- **Integration time estimate** per target - a range, from surface brightness, sky quality,
  aperture and sampling; always labelled as an estimate, and omitted when the data is missing
- **Duplicate warning** before re-planning a target already well captured
- **Equipment recommendation** from the user's own combinations

**Prerequisites** - benefits from v1.10 (projects, moon-aware advice) and v1.11 (7-night outlook).

**i18n in 6 languages.**

---

### v2.2 - Club

| | |
|---|---|
| **Why** | A club or family install reaches many people at once, but today a shared instance only shares equipment and merges Astrodex views. Nothing makes the group live. To be built with one or two pilot clubs rather than from this list alone. |
| **Effort** | Medium |
| **Status** | 💡 Idea - subject to change |

- **Object of the month** (admin-curated) - a pinned target or short list shown to all users, with
  the pictures members already uploaded; expires by itself
- **Outings** - a small calendar of observing nights at a registered location, with the forecast
  for that place and night, and sign-ups
- **Club board** (individual opt-in) - catalogue progress and club-wide totals, without a podium
- **Club page** - the aggregated version of the v1.11 public page
- No external server required - purely local

**i18n in 6 languages.**

---

### v2.3 - Capture Bridges (file-based)

| | |
|---|---|
| **Why** | Bridges MAB with the capture and guiding software that advanced imagers already run, by exchanging files only: no device connection, no hardware risk, no network constraint. Narrow audience - to be built if the v1.10 exports are actually used. |
| **Effort** | Medium |
| **Status** | 💡 Idea - subject to change |

#### NINA sequence export

- From Plan My Night: generate a NINA-compatible sequence (target name, RA/Dec, rotation, filter, frame count, exposure)
- One-click download; ready to import into NINA without manual re-entry

#### PHD2 guiding log import

- Upload a PHD2 `PHD2_GuideLog` file -> MAB parses: total guide time, RMS error, drift trend
- Result attached to an Observation Log session (v1.3)
- Session Analytics dashboard (v1.5) shows guiding quality trend per equipment combination over time

#### Capture folder recognition

- The v1.10 FITS import recognises ASIAIR and smart-telescope folder layouts for a no-setup import
- End-of-night report: planned versus captured

**i18n in 6 languages.**

---

### v2.4+ - Live Observatory (demand-driven)

| | |
|---|---|
| **Why** | Turns MyAstroBoard into the real-time dashboard of the observatory, then lets it act on the equipment. Groups the former v2.4 (Observatory Dashboard), v2.5 (NINA Companion), v2.6 (Smart Automation) and v2.7 (Observatory Orchestrator). Not scheduled: it starts only when users actually ask for it. |
| **Effort** | Very high |
| **Status** | 💡 Idea - not scheduled |

Why it is last: it needs equipment driven by a computer on the same network as MyAstroBoard (the narrowest audience of this roadmap), NINA / ASIAIR / Voyager already do it on the machine wired to the hardware, and a command error has physical consequences (a roof left open, a cable wrap) that a display error never has.

If it starts, it proceeds in this order, each step usable on its own:

1. **Read-only status** - live equipment state (connected / parked / slewing / imaging), last captured frame, running sequence progress, guiding statistics, disk space; one `BaseConnector` per software (NINA Advanced API, ASCOM Alpaca, INDI)
2. **Alerts** on that state (guiding degrading, sequence stopped, clouds rolling in) through the existing notifications - still no command sent
3. **Actions**, one at a time, each off by default and confirmed: push a sequence, GoTo, pause and resume on weather; never a roof or enclosure without an independent hardware safety
4. **One-click night** - check weather, connect, start, monitor, park, report - only if the three previous steps are in use

Already covered without any live connection: observatory state through the v1.6 MQTT connector and Home Assistant, the AllSky camera in the Observatory tab, and the after-the-fact picture of a night through the v1.10 FITS import and v2.3 file bridges.

**i18n in 6 languages.**

---

### v3.0 - Personal Observatory OS

| | |
|---|---|
| **Why** | Long-term vision, not a committed release. MyAstroBoard orchestrates existing astro software (NINA, PHD2, ASCOM Alpaca, INDI, Seestar, Stellarium, Home Assistant, weather, AllSky…) rather than replacing it, and becomes the one place that remembers everything across years of sessions. |
| **Effort** | Very high / open-ended |
| **Status** | 💡 Idea - subject to change |

#### Feature-level modularity (probably never)

A public connector API and curated community repository was once the plan for this slot (see [Architecture direction](#on-the-former-connector-sdk-and-mab-plugins-was-v16)); that idea is dropped, connectors stay in-tree. What this section once committed to - promoting **core features** (SkyTonight, Astrodex, Plan My Night, Equipment...) from internal modules to separately installable units - is now an explicit "probably never":

- Nobody self-hosting a planning app wants "SkyTonight without Astrodex". The install base that benefits from feature-level modularity is tiny, and the features are deeply interdependent (Plan My Night without SkyTonight is meaningless, Astrodex without Equipment loses picture metadata)
- It needs a dependency solver plus graceful degradation for every meaningful subset. The state space grows as 2^N and the features are not independent, so this is a deliberate and permanent maintenance cost, not a free consequence of modularity
- Reconsidered only if MyAstroBoard reaches genuine multi-maintainer scale **and** the incremental boundary work (no cycles, per-feature i18n, core vs feature routes) has actually landed by then - neither is assumed
- The community integration surface (NINA, PHD2, ASCOM Alpaca, INDI, Seestar, Stellarium, Home Assistant, weather providers, AllSky) already grows through the same in-tree `BaseConnector` contract, PR by PR, without one person maintaining every connector - that is the modularity that matters, and it does not require a public SDK or an external repository

#### Intelligent journal (observatory memory)

Natural-language queries over the history accumulated in Observation Log (v1.3) and Session Analytics (v1.5), e.g.:

- "What's my best image of M31?"
- "Which setup works best for galaxies?"
- "How many hours have I logged on IC 1396?"
- "Which nights with seeing > 4 produced my best images?"
- "What Caldwell objects are left to photograph?"

Also:

- Best equipment by target (long-term aggregation, feeds back into the v2.1 recommendation engine)
- Best conditions by target/season
- Integration history across all connectors
- Personal, evolving recommendations

---

## Summary

| Version | Theme | Audience | Effort | Status |
|---------|-------|----------|--------|--------|
| v0.9 | Web Push E2E validation | All | Low | ✅ Implemented |
| v1.0 | First stable release | All | Low | ✅ Implemented |
| v1.1 | First Light - beginner onboarding | Beginners | Medium | ✅ Implemented |
| v1.2 | Multi-location profiles | All | Medium | ✅ Implemented |
| v1.3 | Observation Log | Intermediate+ | High | ✅ Implemented |
| v1.4 | Planning Intelligence (visibility calendar, meridian flip, advanced filters) | Advanced | High | ✅ Implemented |
| v1.5 | Session Analytics | All | Medium | ✅ Implemented |
| v1.6 | MQTT Publisher & Home Assistant Integration + Astrodex Stream | All | Medium | ✅ Implemented |
| v1.7 | Database storage (SQLite, relational, Alembic migrations, verified 1.6 import) | All | High | ✅ Implemented |
| v1.8 | See and Show (framing simulator, share cards, guided tour) | All | Medium | ✅ Implemented |
| v1.9 | My Progress (year in review, achievements and challenges) | All | Medium | 🗓️ Planned |
| v1.10 | Effortless Log (FITS import, imaging projects, exports, moon-aware advice) | Advanced | High | 💡 Idea |
| v1.11 | Open to the Outside (7-night outlook, public page, transients, planetary and lunar) | All | High | 💡 Idea |
| v2.0 | Interactive Sky Chart + mosaic planner | All | High | 💡 Idea |
| v2.1 | Astro Intelligence (plate solve and annotation, Night Copilot) | All | High | 💡 Idea |
| v2.2 | Club (object of the month, outings, club board) | Clubs | Medium | 💡 Idea |
| v2.3 | Capture Bridges, file-based (NINA sequence, PHD2 log) | Advanced | Medium | 💡 Idea |
| v2.4+ | Live Observatory (former v2.4-v2.7), demand-driven | Advanced | Very High | 💡 Idea - not scheduled |
| v3.0 | Personal Observatory OS | All | Very High | 💡 Idea |
