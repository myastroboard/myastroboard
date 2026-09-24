# MyAstroBoard - Roadmap

This document describes features that could potentially be integrated into MyAstroBoard. There are no guarantees; consider this file a list of ideas that may evolve based on my own ideas or future discussions.

**Status legend:** ✅ Implemented - shipped · 🗓️ Planned - next in line · 💡 Idea - not started, scope and priority may change.

---

## Architecture direction

MyAstroBoard is an **opinionated core, not a plugin platform.** Extensibility is delivered through narrow, documented extension points where a contributor can add value as one reviewable unit - not through a feature-level plugin system that a stranger cannot safely write anyway:

- **Catalogues** - JSON cross-ref / standalone files (already the mechanism for Pensack 500, LBN, GaryImm, Arp, Sharpless, Barnard, vdB, Abell). Adding one is a JSON file plus a short registration block.
- **Export formatters** - a small registry shipped with v2.1 (Stellarium, SkySafari, NINA, CSV).
- **Connectors** - the `BaseConnector` contract (talk to an external system, return data), hardened in-tree one connector at a time - see [below](#on-the-former-connector-sdk-and-mab-plugins-was-v16).

The recipe per extension type lives in [docs/EXTENDING.md](docs/EXTENDING.md); the connector recipe is already filled in, the export-formatter section is filled in as v2.1 lands.

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

### v2.0 - Interactive Sky Chart

| | |
|---|---|
| **Why** | The one missing visualization that every astronomer expects. Positioned at v2.0 because it has the highest integration surface - it becomes most useful once planning tools (v1.4), observation log (v1.3), and Astrodex are mature. |
| **Effort** | High |
| **Status** | 💡 Idea - subject to change |

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

#### Mosaic planner

Multi-panel planning for targets that exceed the sensor FOV - the multi-panel extension of the FOV overlay above. Originally scoped for v1.4 and moved here: the panel grid only becomes genuinely useful when it can be drawn over real sky imagery, and building it before the chart means building the preview twice.

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

**Technology:** [Aladin Lite](https://aladin.cds.unistra.fr/AladinLite/) (MIT-licensed, maintained by CDS Strasbourg) embedded via its JavaScript API - avoids building a sky renderer from scratch and provides professional-grade DSS/HiPS imagery as backdrop.

**i18n in 6 languages.**

---

### v2.1 - Community & Sharing

| | |
|---|---|
| **Why** | Single-user self-hosted installs benefit from sharing; club and family installs benefit even more. Built last in the 2.x cycle because it needs a stable feature set and a user base large enough to make sharing meaningful. v1.1 (beginner onboarding) is the prerequisite for that user base. |
| **Effort** | Medium |
| **Status** | 💡 Idea - subject to change |

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
| **Status** | 💡 Idea - subject to change |

Everything here that talks to an external system is built as a `BaseConnector` in `backend/connectors/`, same as AllSky, MyAstroShine and the v1.6 MQTT publisher, not as bespoke in-core code. This release is the first real test of whether that contract is expressive enough for connectors that write back into MAB data rather than only reading.

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
| **Status** | 💡 Idea - subject to change |

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
| **Status** | 💡 Idea - subject to change |

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
| **Status** | 💡 Idea - subject to change |

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
| **Status** | 💡 Idea - subject to change |

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
| **Status** | 💡 Idea - subject to change |

Coordinates:

- NINA
- PHD2
- ASCOM Alpaca
- Home Assistant *(extends the v1.6 MQTT Publisher connector with inbound control, rather than a net-new connector)*
- Weather
- Notifications

One-click night:

1. Check weather
2. Connect devices
3. Start sequence
4. Monitor
5. Park mount
6. Generate report

**Prerequisites** - v2.4, v2.5, v2.6; upgrades the v1.6 Home Assistant connector from publish-only to power/roof/dome control.

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

- Best equipment by target (long-term aggregation, feeds back into the v2.3 recommendation engine)
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
| v2.0 | Interactive Sky Chart + mosaic planner | All | High | 💡 Idea |
| v2.1 | Community & Sharing | All | Medium | 💡 Idea |
| v2.2 | Integrations (plate solve, PHD2, NINA) | Advanced | High | 💡 Idea |
| v2.3 | Astro Intelligence (Night Copilot) | All | High | 💡 Idea |
| v2.4 | Observatory Dashboard | Advanced | High | 💡 Idea |
| v2.5 | NINA Companion | Advanced | High | 💡 Idea |
| v2.6 | Smart Automation | Advanced | High | 💡 Idea |
| v2.7 | Observatory Orchestrator | Advanced | High | 💡 Idea |
| v3.0 | Personal Observatory OS | All | Very High | 💡 Idea |
