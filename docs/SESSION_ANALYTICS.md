# Session Analytics and Wishlist

Session Analytics (v1.5) answers two questions from data MyAstroBoard already stores:
**"how am I progressing?"** and **"how am I optimizing?"**. The Wishlist that ships with it
answers a third: **"what do I still want to capture?"**

They live as two sub-tabs of the **Astrodex** main tab, alongside Astrodex, Plan My Night,
the Observation Log, Photo Map and Catalogue Collection - so the whole
`Plan -> Observe -> Log -> Astrodex` loop and everything derived from it stays under one
navigational roof.

## Table of Contents

1. [What is computed, and from what](#what-is-computed-and-from-what)
2. [Why the Observation Log is the primary source](#why-the-observation-log-is-the-primary-source)
3. [The four analytics sections](#the-four-analytics-sections)
4. [Resolving coordinates](#resolving-coordinates)
5. [Scale directions](#scale-directions)
6. [Wishlist](#wishlist)
7. [What "best months" does and does not say](#what-best-months-does-and-does-not-say)
8. [Performance and caching](#performance-and-caching)
9. [API endpoints](#api-endpoints)
10. [Out of scope](#out-of-scope)

---

## What is computed, and from what

| Section | Source |
|---|---|
| Totals, monthly series, object/constellation/equipment breakdowns | Observation Log sessions, nights and entries |
| Sky coverage map | Observation Log entries **+** Astrodex items, placed via the SkyTonight dataset |
| Conditions and results | Observation Log entries (rating) joined to their night (seeing, transparency, SQM, Moon) |
| Best months | Ephemeris at the active location **+** the user's own logged months |
| Wishlist | Its own per-user store, plus derived captured state |

Everything is **strictly self-scoped**: a user only ever sees aggregates of their own log
and their own Astrodex. Observation Log sessions are permanently private, so the analytics
built on them are too. Read-only accounts may read every analytics route; only the
wishlist's write routes require the `user` role.

All the aggregation is pure: `backend/observation/session_analytics.py` takes already-loaded
sessions and returns a payload. Loading files, resolving the request's active location and
reaching across feature packages is the blueprint layer's job
(`backend/blueprints/session_analytics.py`), the same split the Observation Log uses.

---

## Why the Observation Log is the primary source

Attaching a photo to an entry is a manual, optional step, so Astrodex picture metadata
covers an unknown subset of what was actually captured. Every **logged entry**, by
contrast, carries its own `frame_count` / `sub_exposure_seconds` / `integration_minutes`.

So: every "hours" and "objects captured" figure comes from the Observation Log. The
Astrodex collection size is reported as its **own, separately-labelled figure** - never
folded into the logged totals - and Astrodex items are used on the sky coverage map only
to cover objects that were added straight to the gallery without a session entry.

This was decided when v1.3 shipped; see `docs/OBSERVATION_LOG.md`.

### Which figures come from where

- `integration_minutes` is the one guaranteed-summable field. When it is absent but both
  `frame_count` and `sub_exposure_seconds` were recorded, their product is used instead.
- An entry counts as **captured** when it has frames or integration time - the same
  threshold the Observation Log itself uses to auto-register a target in Astrodex. A
  planned-but-clouded-out entry is logged but is not a capture.
- Entries are attributed to **their night's date**, never to `created_at`: a session
  written up three weeks later still lands in the month it happened.
- Distinct objects are counted on the dataset's cross-catalogue `catalogue_group_id` when
  it resolves, so "M 31" and "NGC 224" are one object, not two.
- Equipment hours follow the **effective** combination of each entry: its own override if
  it has one, else the session's. Both are frozen snapshots on the records themselves, so
  renaming or deleting a combination never rewrites history. Entries with no equipment
  recorded get an explicit bucket rather than being dropped, so the hours always add up to
  the headline total.

---

## The four analytics sections

### 1. Headline totals

Integration lifetime / this year / this month, sessions and nights, distinct objects
captured, constellations, average rating, and the Astrodex collection size.

"This month" is the **observer's** month: the date is resolved in the active location's
timezone, not the server's, so a session logged at 01:30 local on the 1st lands where the
user expects it.

### 2. Where your time goes

Integration over time (a dense monthly series - a month with no activity renders as a zero
bar rather than closing up the axis), object types, constellation spread, and equipment
usage.

### 3. Sky coverage

Every captured object placed on an RA/Dec grid: right ascension on the x axis, **reversed**
as on any sky chart, declination on the y axis. Colour by object type or by capture year.

A shaded band marks the declinations that never rise at the active location
(`dec < -(90 - lat)` in the northern hemisphere, mirrored in the southern), so "where have
I been" is read against where the observer can actually go.

Objects whose coordinates cannot be resolved at all are **counted and named**, not silently
dropped - the same honest accounting the Photo Map does with its ungeotagged pictures.

### 4. Conditions and results

Every rated entry joined to its night's seeing, transparency, SQM and Moon illumination,
plotted as four scatters with bucket averages underneath.

This is **descriptive, not predictive**. Each bucket reports its own sample count next to
its average, and a bucket with fewer than five samples is shown as "not enough data yet"
rather than plotted. There is no trend line and no correlation coefficient: over a handful
of nights, one would be noise dressed as insight.

---

## Resolving coordinates

The sky coverage map and the wishlist both need numeric RA/Dec, and neither can take the
stored `ra`/`dec` at face value. Plan My Night and the Observation Log copy those fields
straight from whatever the client sent, and the two SkyTonight frontend paths disagree:
the target cards send `coordinates.ra_hours` (a decimal-hours float) while the result
tables send the formatted `ra_hms` string (`"21h 31m 48.32s"`). Astrodex items are worse -
`ra`/`dec` are stripped on every write.

`backend/observation/target_coordinates.py` is the single resolver, applying one order
everywhere (first hit wins):

1. **The SkyTonight dataset lookup**, which carries canonical numeric `ra_deg`/`dec_deg`
   plus the object's cross-catalogue `group_id`. Display labels such as
   `"M31 - Andromeda Galaxy"` are reduced to their identifier before the lookup.
2. **The record's own stored values**, parsed tolerantly: a number (RA in decimal hours,
   Dec in degrees) or a sexagesimal string in `h m s`, `d m s`, `deg ' "` or colon form.
   A negative-zero degrees field (`-00 30 00`) keeps its sign.
3. **Give up** - and the caller counts the miss.

The wishlist stamps the resolved values onto the item at add time, so the visibility pass
is a pure numeric loop that never re-learns this.

---

## Scale directions

Three of the recorded conditions run in different directions. Every bucket the API emits is
ordered **best first** and carries its own numeric bounds, so no consumer has to re-derive
which way a scale goes:

| Field | Direction | Best band |
|---|---|---|
| `seeing` | 1 = best .. 8 = worst (7Timer ASTRO) | 1-3 |
| `transparency` | 1 = worst .. 8 = best (7Timer ASTRO) | 6-8 |
| `sqm` | higher is darker, therefore better | >= 20.5 |
| `moon_illumination_percent` | lower is better | 0-33 |
| `rating` | 0-5 in 0.5 steps, higher is better | - |

A reversed seeing axis is a correctness bug, not a cosmetic one, and has its own test.

---

## Wishlist

A wishlist item records **intent**: an object you want to capture. It is the only new
persistent state v1.5 introduces - everything else is derived.

Storage is `data/wishlist/<user_id>_wishlist.json`, one file per user, with the same
per-user lock and atomic backup / temp-write / validate / replace / restore sequence the
Observation Log uses. Wishlists are permanently private, and they are included in the admin
backup ZIP.

### Two rules

1. **"Captured" is never stored.** It is recomputed on every read from the Observation Log
   entries and the Astrodex items. A stored boolean would go stale the moment an entry is
   edited or a session deleted, and silently-wrong progress is worse than no progress bar.
2. **Coordinates are resolved and frozen at add time**, through the resolver above.

### Behaviour

- **Deduplication** is cross-catalogue: adding "NGC 224" when "M 31" is already on the list
  is reported as a duplicate, not added twice. Aliases count too.
- **Captured items stay on the list** and are shown as done, so "12 of 20" keeps its
  denominator. `POST /api/wishlist/archive-captured` is the explicit opt-in for removing
  them.
- **Moving targets** (planets, comets) are accepted as wishes but never get a frozen
  position: a fixed RA/Dec would be wrong within weeks, so they simply report no window,
  the same distinction the v1.4 visibility calendar draws.
- **Priorities** are `high` / `normal` / `low`; the list can also be sorted by visibility
  (the default) or name.
- Cap: `MAX_WISHLIST_ITEMS = 500` per user.

### Where objects are added from

| Surface | Notes |
|---|---|
| SkyTonight result tables | Through each row's **More** popup, which covers deep-sky objects, bodies and comets in one place |
| Catalogue Collection cards | Browse a whole catalogue and queue what you want |
| Beginner Catalog cards | The v1.1 tie-in the roadmap asks for |

All three payloads carry an `in_wishlist` flag, computed from a preloaded index so
annotating a thousand SkyTonight rows stays one file read.

The SkyTonight result tables themselves are built as HTML strings - the legacy path the
project style guide says not to extend - which is why the table's entry point is its
per-row **More** popup rather than a new column.

### Next visibility

`GET /api/wishlist` attaches, per item, the observable hours on the **nearest** sampled
night and the best of the next three sampled months. That is the cheap ranking signal the
default sort uses; the precise twelve-month answer stays one click away behind the v1.4
per-object visibility calendar, which every placed item links to.

`?visibility=0` skips the ephemeris pass entirely for a fast render.

---

## What "best months" does and does not say

The chart plots two clearly separate series:

- **Available** - mean dark hours and moonless dark hours *per night* for that calendar
  month at the active location, computed live from the Sun and Moon. This is the site's
  own nightly budget.
- **Logged** - the *month total* the user actually recorded, across all years, plus the
  nights logged and mean rating.

The two are different units - a nightly average against a cumulative total - so they get
**separate y axes**, each labelled. On one shared axis a well-used month climbs above the
available darkness and reads as an impossibility.

It is **not a weather statistic.** MyAstroBoard stores no historical weather: every weather
cache is a short-TTL forecast snapshot that is overwritten in place, and nothing
accumulates a climatology. The chart therefore answers "when is it worth planning to be out
here, and when have I actually been out" - never "when is it clear here".

A weather climatology (multi-year cloud cover from an archive API, behind its own scheduler
cache job) was specified and deliberately deferred; see `feature.md` for the full design if
it is ever picked up.

If the ephemeris cannot be computed for a location, the personal half still renders and the
chart says the sky figures are missing, rather than showing a half-empty chart that looks
complete.

---

## Performance and caching

No scheduler cache job is registered. The analytics are per-user aggregations over that
user's own JSON files - a few milliseconds of dict work even for a heavy log.

The only expensive part is the ephemeris, and it is cached the way v1.4 already caches this
class of work, with bounded in-process LRUs:

| Cache | Key | Why |
|---|---|---|
| Monthly dark hours | `(location_id, year)` | Changes once a year |
| Night contexts | `(location_id, date)` | A night's Sun/Moon grid is identical for every target, so repeated wishlist loads do no fresh ephemeris work |

That is also why the wishlist's visibility pass scales: the grid is built once per sampled
night and every target is folded through it at O(1) trig per time step, so a 500-item
wishlist costs the same few grids as a single object would.

---

## API endpoints

All routes require login and are self-scoped. Write routes additionally require the `user`
role.

| Method | Route | Notes |
|---|---|---|
| `GET` | `/api/session-analytics/summary` | Totals, monthly series, type/constellation/equipment breakdowns, top targets. `?year=` selects the "this year" bucket |
| `GET` | `/api/session-analytics/sky-coverage` | Placed points, unplaced count and names, never-visible declination for the active location |
| `GET` | `/api/session-analytics/conditions` | Per-entry samples plus bucketed averages with sample counts |
| `GET` | `/api/session-analytics/best-months` | Astronomical availability and the user's own logged months. `?year=` |
| `GET` | `/api/wishlist` | Items with derived captured state, progress counters and next visibility. `?sort=visibility\|priority\|name`, `?visibility=0` |
| `POST` | `/api/wishlist` | Body `{"targets": [...]}` - always a list. Returns added items plus skip counts |
| `PATCH` | `/api/wishlist/<item_id>` | `priority`, `notes` |
| `DELETE` | `/api/wishlist/<item_id>` | Remove one item |
| `POST` | `/api/wishlist/archive-captured` | Remove every item currently derived as captured |

The four analytics routes are fetched in parallel when the sub-tab opens, so the
ephemeris-backed one never holds up the three that are instant.

---

## Out of scope

- **Weather climatology** - see above.
- **Per-filter breakdown** of integration time. The Observation Log keeps one aggregate
  `integration_minutes` per entry (already out of scope in v1.3).
- **Cross-user or club leaderboards.** Sessions are private; analytics stay self-scoped.
  Public profiles are a v2.1 concern.
- **A true all-sky projection** for the coverage map. v1.5 ships the rectangular RA/Dec
  grid; the projected, imagery-backed view arrives with the v2.0 sky chart rather than
  being built twice.
- **Guiding-quality trends** per equipment combination - that needs the v2.2 PHD2 import.
- **PDF export** of the dashboard.

---

## Related documentation

- [OBSERVATION_LOG.md](OBSERVATION_LOG.md) - the log every figure here is derived from
- [ASTRODEX.md](ASTRODEX.md) - the gallery, counted separately
- [SKYTONIGHT.md](SKYTONIGHT.md) - the dataset that resolves coordinates and identities
- [LOCATIONS.md](LOCATIONS.md) - the active location that drives visibility and best months
