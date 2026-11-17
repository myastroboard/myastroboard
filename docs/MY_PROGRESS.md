# My Progress: year in review, badges and challenges

v1.9 tells the observing record back as a story and as milestones. Your Sky already computes
how an observer is doing, as a dashboard to consult; My Progress turns the same data into a dated
review that can be shared, and into goals that give a reason to go back out.

Everything here is **computed on read** from the user's own Observation Log and Astrodex. Nothing
new is stored about observations, and nothing is ever shown to another user.

---

## Year in review ("My astro year")

A short sequence of screens about one calendar year, opened from:

- Astrodex -> Your Sky -> **My astro year** (top right);
- Astrodex -> Progress -> **My astro year**;
- the highlight on the Astrophotography tab, from 1 December to 15 January, when the year has
  data. Its close button hides it until the next year (preference `year_review_dismissed`).

The year selector offers every year with data. Without `?year=`, January still opens the year
that just ended, and a year without data falls back to the most recent year that has some.

| Screen | Shows | Hidden when |
|---|---|---|
| The year | Integration time, nights out, sessions, objects | The year has no capture at all |
| Your targets | Objects captured, how many are new this year, the favourite kind (by hours) | - |
| Target of the year | The object with the most integration, its best-rated picture of the year | No integration recorded |
| Best night | The longest logged night (best rated on a tie): rating, SQM, Moon, targets, equipment | No logged night with a capture |
| Hardest-working equipment | The named combination that collected the most light, its share of the year | No named combination |
| Your progress | Per catalogue, objects captured by the end of the year and how many that year; the previous year's figures when it has data | Nothing to report |
| In pictures | A montage of up to nine of the year's Astrodex pictures, one per object, best rated first | No dated picture that year |

Each screen is a [share card](SHARE_CARDS.md) drawn in the browser: **Share this screen** opens the
usual share modal (formats, theme, facts to keep), and closing it brings the review back on the same
screen. The montage centre-crops each picture to a square tile; a single-picture card is still never
cropped. Screens without a picture scale their text up to fill the card, and the progress screen
draws one bar per catalogue with the year's gain.

To post the whole review at once:

- **Download all (ZIP)** saves every screen as a numbered PNG (`01-...png`, `02-...png`) in one ZIP
  file, built in the browser (stored without compression: the PNGs are already compressed).
- **Share all** appears where the browser can hand several files to the system share sheet (most
  phones), which posts the screens as one carousel.

### Rules

- **The year is the calendar year of the observing night.** An entry belongs to its night's `date`,
  which the Observation Log stores in the observer's local calendar, in either hemisphere.
- **Integration** is the Observation Log's (`integration_minutes`, else frames x sub-exposure), plus
  the integration recorded on Astrodex pictures that no log entry points to: a gallery-only user
  still gets a review, and a picture attached to an entry is never counted twice.
- **Nights out** are logged nights with a capture; for a gallery-only year, the distinct picture
  dates.
- **New this year** means first captured that year, across the log and Astrodex together.
- **No invented figure, no comparison with other users.** The only comparison is with the user's own
  previous year.

---

## Badges

Astrodex -> **Progress**. Badges are earned automatically from what was actually logged:

| Group | Badges |
|---|---|
| Firsts | First galaxy, nebula, star cluster, comet, planet |
| Catalogues | Messier 10 / 25 / 50 / complete, Caldwell 10 / 25 / 50 / complete, Herschel 400 25 / 100 / 200 / complete, Sharpless 10 / 50, Arp 10 / 50, Barnard 10 / 50 |
| Endurance | 10 / 50 / 100 hours of integration, 10 hours on one target, a session spanning two nights |
| Across the sky | Four seasons, 10 / 20 / 40 constellations, both celestial hemispheres |
| Conditions | A night under a Bortle 3 sky or darker (the location preset's Bortle class, or a measured SQM of 21.3 or more), a night with the Moon at most 5 % lit |

- **What counts as captured**: a log entry with frames or integration time (the threshold the
  Observation Log uses to add the target to Astrodex), or an Astrodex item. "M 31" and "NGC 224" are
  the same object.
- **"Complete" means the catalogue as the SkyTonight dataset carries it** (109 Messier objects, for
  instance), read from the dataset rather than written down.
- **The date a badge was earned** is read off the history: the night the tenth Messier object was
  first captured, the night the running total crossed ten hours. A badge earned from an undated
  record has no date.
- **Computed on read, so it can be taken back**: deleting the entries a badge rests on removes it.
  The page says so. This is the same rule as the Wishlist's "captured" state, which is never stored
  either.
- **Announced once, quietly**: a badge earned since the last visit carries a "New" marker, shown
  once (the ids already seen are kept in the `achievements_seen` preference). No animation, no
  notification.
- Each earned badge has a share button; a catalogue badge's card carries a montage of the user's own
  pictures of that catalogue.

### Next within reach

The lowest unearned tier of every badge family already started, closest first (four at most), with
what is left ("11 more Messier objects for this badge"). Families with no progress and the condition
badges, which depend on the sky rather than on effort, are not listed. A catalogue milestone has a
**Visible tonight** button listing the catalogue's objects not captured yet that are observable
tonight within the SkyTonight constraints, each with a Wishlist button.

---

## Challenges

Generated from real visibility at the active location, never from a dated list written by hand.

### Seasonal challenges

"Galaxies / nebulae / star clusters of the season": up to eight of the brightest Messier and Caldwell
objects of each class that are observable for at least 1.5 hours during astronomical darkness, within
the SkyTonight altitude and airmass constraints and the location's custom horizon, on one of the
season's three sampled nights (the 15th of each month). The list is therefore the same all season.
Seasons are meteorological (December-February, ...) and named for the hemisphere of the location.
A class with fewer than three such objects is not offered.

### Messier marathon

The Messier marathon card shows the next marathon (this year's until 15 April, then the next year's),
and moves to the top of the challenges from 1 February.

- **The night**: of the new moons between 1 March and 15 April, the one that lets the most objects be
  caught from this site.
- **Reachable**: an object counts when it stands at least 10 degrees above the horizon (and above the
  custom horizon) while the Sun is below -12 degrees. Marathons are visual and go low, so the imaging
  constraints do not apply. The count is the real maximum for the latitude: from 48 degrees north
  about a hundred, from the tropics nearly all of them.
- **The order**: each object is placed at its best moment inside its window (the start of the window
  for an object setting at dusk, the end for one rising at dawn, the meridian for the rest), which
  gives the classic west-to-east order. The objects out of reach that night are listed.

---

## Settings and privacy

- **My settings -> Customize -> Show badges and challenges** (`achievements_enabled`, on by default)
  hides the Progress tab. The year in review stays available from Your Sky.
- Everything is strictly self-scoped, like the Observation Log. Read-only accounts can see their own
  progress.
- The three new preferences live on the account like every other preference, so account deletion
  and the personal data export cover them. No new table, no new file.
- Share cards are drawn in the browser and never contain a location.

## API

| Method | Route | Notes |
|---|---|---|
| `GET` | `/api/session-analytics/year-review` | Every screen of one year; optional `year` |
| `GET` | `/api/achievements` | Badges with progress, next within reach, catalogue counters and pictures |
| `POST` | `/api/achievements/seen` | Body `{"ids": [...]}`: badges the user has now seen; unknown ids are ignored |
| `GET` | `/api/achievements/challenges` | Seasonal challenges and the next Messier marathon for the active location |
| `GET` | `/api/achievements/missing-tonight` | `catalogue` (one of the badge catalogues), optional `limit` (max 30) |

## Implementation

- `backend/observation/achievement_definitions.py` - the badges, as declarative rows.
- `backend/observation/achievements.py` - collects the facts (captures, integration, nights) once
  and evaluates the badges; pure, the dataset lookup is injected.
- `backend/observation/year_review.py` - the review screens, from the same facts.
- `backend/observation/challenges.py` - seasonal lists, marathon and "missing tonight", on the
  visibility calendar's night grid, with small in-process caches keyed on the location's geometry.
- `backend/blueprints/progress.py` - the routes.
- `static/js/progress.js`, `static/js/year_review.js`, `static/css/bs_progress.css` - the
  frontend; the screens are drawn by `static/js/share_card.js`.

## Related documentation

- [SESSION_ANALYTICS.md](SESSION_ANALYTICS.md) - Your Sky, the aggregations this builds on
- [SHARE_CARDS.md](SHARE_CARDS.md) - the card engine
- [OBSERVATION_LOG.md](OBSERVATION_LOG.md) - the log every figure comes from
