# Beginner Experience

MyAstroBoard is built to stay useful as an astrophotographer's skill grows, but the app previously
assumed prior knowledge: no onboarding, no skill-aware guidance, no starter target list. The
**Beginner Experience** (v1.1, "First Light") closes that gap with four cooperating pieces:

| Piece | What it does |
|---|---|
| [Guided Setup Wizard](#guided-setup-wizard) | Multi-step first-run modal: location, sky quality, equipment, notifications, "tonight" preview |
| [Difficulty model](#difficulty-model) | A static, per-target 0–100 difficulty score computed alongside AstroScore |
| ["Tonight for you" recommendations](#tonight-for-you-recommendations) | 3–5 targets matched to the user's skill level, shown at the top of SkyTonight → DSO |
| [Beginner Catalog](#beginner-catalog) | A curated, hand-picked list of ~30 forgiving starter targets with explanations |

All of it is opt-out, not opt-in: existing users default to `experience_level: advanced`, which
behaves exactly like before (all targets shown, no filtering).

---

## Guided Setup Wizard

**Module**: `static/js/first_run.js` (logic) + `templates/index.html#wizard-modal` (markup)

Replaces the old single-step "set your location" popup with a skippable multi-step wizard. The
steps shown depend on the user's context, determined once at launch:

```javascript
function _getWizardFlow(config, currentUser) {
    const locationSet = config.location_configured === true;
    const isAdmin = currentUser.role === 'admin';
    if (!locationSet && isAdmin) return 'full';   // Context A
    return 'user';                                // Context B
}
```

| Flow | Who sees it | Steps |
|---|---|---|
| `full` (Context A) | Admin, on a fresh install with no location configured yet | Location → Sky quality (Bortle/SQM) → Equipment → Notifications → Tonight |
| `user` (Context B) | Any other user (location already configured by an admin) | Welcome (read-only site info) → Equipment → Notifications → Tonight |

Location and Bortle steps only appear for the admin doing the initial install, since those
settings are shared/global (see [CONFIGURATION.md](CONFIGURATION.md)) rather than per-user.

- **Equipment step**: preset picker (`static/data/equipment_presets.json`) or manual entry; also
  lists the user's existing telescopes/cameras (including shared equipment). Saves via the
  existing `POST /api/equipment/telescopes` / cameras endpoints (see [EQUIPMENT.md](EQUIPMENT.md)).
- **Notifications step**: same triggers as My Settings → Notifications, toggle-only; on the fresh
  install it also asks for the VAPID contact email (see [NOTIFICATIONS.md](NOTIFICATIONS.md)).
  Skip is always available and never pressured.
- **Tonight step**: renders the same "Tonight for you" panel described below, then a button to
  jump straight to SkyTonight.

### Trigger and completion state

A new `wizard` preference tracks completion:

```json
"wizard": { "completed": false, "skipped": false }
```

The wizard shows when both are `false`. Skipping (single step or "skip all") sets `skipped: true`
and persists via `PUT /api/auth/preferences` — unlike the old popup, the skip is permanent across
sessions/devices, not a `sessionStorage` flag. Users can run it again anytime from
**My Settings → Customize → Redo Setup Wizard**.

---

## Difficulty model

**Module**: `backend/skytonight_calculator.py` → `compute_difficulty_score()`

Every target that SkyTonight computes gets a static difficulty score alongside its AstroScore.
Unlike AstroScore, difficulty does **not** depend on location, date, or Bortle class — the same
object is always the same difficulty everywhere. It is computed once per calculation run and
stored in `dso_results.json` as `difficulty_score` (0–100, lower = easier) and `difficulty`
(`beginner` / `intermediate` / `advanced`).

| Factor | Weight | Easier when... |
|---|---|---|
| Surface brightness (mag/arcsec²) | 0.40 | Brighter (lower value) |
| Angular size (arcmin) | 0.30 | Larger |
| Visual magnitude | 0.20 | Brighter (lower value) |

A fourth factor (minimum integration hours, weight 0.10) is a documented simplification: no
per-target minimum-integration data exists in the general catalogue, so it always contributes 0.
This caps the theoretical maximum raw score around ~90 instead of 100 but does not move any
target across a threshold.

When magnitude or size is missing, the surface-brightness and size components are zeroed and only
the magnitude factor is used ("magnitude-only" scoring). If magnitude is also missing, the target
gets a neutral default of `(50, 'intermediate')`.

**Thresholds**: `score ≤ 35 → beginner`, `35 < score ≤ 65 → intermediate`, `score > 65 → advanced`.

Difficulty is surfaced as a color-coded badge (green/orange/red) wherever a target appears:
the SkyTonight DSO table (with a difficulty filter dropdown), Astrodex entries, and Plan My Night
entries.

---

## "Tonight for you" recommendations

**Endpoint**: `GET /api/skytonight/recommendations` (`@login_required`) — see
[API_ENDPOINTS.md](API_ENDPOINTS.md)

A panel injected above the DSO table on the SkyTonight tab. It reads the user's `experience_level`
preference, filters `dso_results.json` to matching difficulty tiers, sorts by AstroScore
descending, and returns the top N (default 5, max 10 via `?limit=`):

| `experience_level` | Difficulties shown |
|---|---|
| `beginner` | `beginner` only |
| `intermediate` | `beginner` + `intermediate` |
| `advanced` (default) | everything |

Each card shows the target name, type badge, difficulty badge, estimated integration time, and an
"Add to Plan" button. `estimated_integration_hours` comes from the Beginner Catalog when the
target is one of its ~30 curated entries; otherwise it's a rough estimate derived from the
difficulty tier (`beginner → 2h`, `intermediate → 4h`, `advanced → 8h`) and flagged as such via
`estimated_integration_hours_is_estimate`.

The preference is set in **My Settings → Customize** alongside density/theme, and defaults to
`advanced` so existing users see no behavior change until they opt in.

---

## Beginner Catalog

**Module**: `backend/beginner_catalog.py` · **Data**: `backend/catalogues/beginner_catalog.json`
(34 hand-picked entries) · **Endpoint**: `GET /api/beginner-catalog` — see
[API_ENDPOINTS.md](API_ENDPOINTS.md)

A "Beginner" sub-tab on SkyTonight showing a card grid (not a table) of curated, forgiving starter
targets — bright nebulae, open clusters, and a few landmark galaxies. Each card explains *why*
the object is beginner-friendly and suggests a framing, plus:

- **Visible tonight** badge, cross-referenced against the current `dso_results.json`
- **Captured** state, cross-referenced against the user's Astrodex
- **In plan** state, cross-referenced against Plan My Night
- Filters: visible-tonight-only toggle, difficulty (capped at the user's own `experience_level`),
  object type

The catalogue JSON stores only structural data and an `i18n_key` per object — no English text is
hardcoded in the data file. The `why_beginner` and `suggested_framing` strings are resolved at
request time via `I18nManager` from `beginner_catalog.objects.<i18n_key>.why` / `.framing` in the
i18n files, so the whole catalogue is translated in all 6 supported languages.

This tab can be turned off entirely per-user via the `beginner_catalog_enabled` preference
(**My Settings → Customize**) for users who find it redundant with the DSO table.

---

## Preferences reference

New keys added to `preferences` (see [AUTHENTICATION.md](AUTHENTICATION.md#user-preferences)):

| Preference | Allowed values | Default | Description |
|---|---|---|---|
| `experience_level` | `beginner`, `intermediate`, `advanced` | `advanced` | Filters recommendations and the Beginner Catalog's difficulty ceiling |
| `beginner_catalog_enabled` | boolean | `true` | Shows/hides the "Beginner" SkyTonight sub-tab |
| `wizard.completed` | boolean | `false` | Set once the guided wizard is finished |
| `wizard.skipped` | boolean | `false` | Set if the user skips the wizard (any step, or "skip all") |

---

## i18n namespaces

| Namespace | Content |
|---|---|
| `wizard.*` | Wizard step titles, navigation, skip/redo strings |
| `difficulty.*` | Badge labels (`beginner`/`intermediate`/`advanced`) and the difficulty explanation tooltip |
| `recommender.*` | "Tonight for you" panel strings |
| `beginner_catalog.*` | Beginner Catalog tab strings, plus one `objects.<i18n_key>.why` / `.framing` pair per catalogue entry |

---

## Files reference

| File | Role |
|---|---|
| `static/js/first_run.js` | Wizard flow selection, step rendering, skip/completion persistence |
| `static/data/equipment_presets.json` | Gear presets offered in the wizard's equipment step and in the Equipment tab's "New ..." modals — see [EQUIPMENT.md#presets](EQUIPMENT.md#presets) |
| `backend/skytonight_calculator.py` | `compute_difficulty_score()` |
| `backend/skytonight_api.py` | `GET /api/skytonight/recommendations` |
| `backend/beginner_catalog.py` | Catalogue loading, i18n resolution, SkyTonight/Astrodex/Plan enrichment |
| `backend/catalogues/beginner_catalog.json` | The 34-entry curated dataset |
| `backend/app.py` | `GET /api/beginner-catalog` route |
| `static/js/skytonight.js` | Recommendations panel, difficulty badges/filter, Beginner sub-tab |
| `static/js/auth.js` | `experience_level` / `beginner_catalog_enabled` controls in My Settings → Customize |
