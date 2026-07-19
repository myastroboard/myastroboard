# Equipment Profiles

The **Equipment** tab lets you catalogue all your astronomy gear. Profiles pre-fill fields across Astrodex, the Exposure Calculator, and the SkyTonight target scorer.

**Module**: `backend/equipment/equipment_profiles.py`

---

## Gear types

| Type | Sub-tab | What to record |
|------|---------|----------------|
| **Telescope** | Telescopes | OTA specs: focal length, aperture, type, reducer/barlow |
| **Camera** | Cameras | Sensor specs: pixel size, resolution, QE, read noise |
| **Mount** | Mounts | Payload capacity, mount type |
| **Filter** | Filters | Type (LRGB, narrowband…), central wavelength, bandwidth |
| **Accessory** | Accessories | Field flattener, focuser, filter wheel, etc. |
| **Combination** | Combinations | Named set of telescope + camera + mount + filters + accessories |

Data is stored per-user in `data/equipments/<user_id>_<type>.json`.

---

## Telescopes

| Field | Description |
|-------|-------------|
| `name` | Display name (e.g. "Celestron C8") |
| `manufacturer` | Brand |
| `telescope_type` | `Refractor`, `Apochromatic Refractor (APO)`, `Reflector`, `Schmidt-Cassegrain (SCT)`, `EdgeHD`, `Rowe Ackerman Schmidt Astrograph (RASA)`, `Ritchey-Chrétien (RC)`, `Newtonian`, `Maksutov-Cassegrain`, `Cassegrain`, `Dobsonian` |
| `aperture_mm` | Clear aperture in mm |
| `focal_length_mm` | Native focal length in mm |
| `reducer_barlow_factor` | Focal reducer (< 1) or Barlow (> 1) factor; default 1.0 |
| `native_focal_ratio` | Auto-calculated: `focal_length / aperture` |
| `effective_focal_length` | Auto-calculated: `focal_length × reducer_barlow_factor` |
| `effective_focal_ratio` | Auto-calculated: `effective_focal_length / aperture` |
| `weight_kg` | OTA weight for payload checks |
| `is_shared` | Share with all users on this instance |

---

## Cameras

| Field | Description |
|-------|-------------|
| `name` | Display name (e.g. "ZWO ASI294MC Pro") |
| `sensor_type` | `CMOS Color`, `CMOS Mono`, `CCD Color`, `CCD Mono` |
| `sensor_width_mm` / `sensor_height_mm` | Physical sensor dimensions |
| `resolution_width_px` / `resolution_height_px` | Full-frame pixel count |
| `pixel_size_um` | Physical pixel pitch in micrometres |
| `sensor_diagonal_mm` | Auto-calculated: `√(width² + height²)` |
| `read_noise_e` | Read noise in electrons (used by the Exposure Calculator) |
| `quantum_efficiency` | QE percentage (used by the Exposure Calculator) |
| `cooling_supported` / `min_temperature_c` | Sensor cooling information |
| `is_shared` | Share with all users |

---

## Mounts

| Field | Description |
|-------|-------------|
| `mount_type` | `Equatorial`, `Alt-Azimuth`, `Dobsonian`, `Fork Mount` |
| `payload_capacity_kg` | Maximum stated payload |
| `recommended_payload_kg` | Auto-calculated: 75 % of max payload (safe imaging load) |
| `tracking_accuracy_arcsec` | Periodic error in arcseconds |
| `guiding_supported` | Whether the mount accepts autoguider input |

---

## Filters

| Field | Description |
|-------|-------------|
| `filter_type` | `LRGB`, `Narrowband`, `Broadband`, `Luminance`, `H-Alpha`, `OIII`, `SII`, `UHC`, `Light Pollution Reduction`, `Solar`, `Other` |
| `central_wavelength_nm` | Centre of the passband in nm |
| `bandwidth_nm` | Full-width at half-maximum in nm |
| `intended_use` | e.g. "emission nebulae", "broadband imaging" |

---

## Accessories

Generic category for any optical or mechanical accessory not covered above: field flatteners, focusers, filter wheels, OAGs, etc.

| Field | Description |
|-------|-------------|
| `accessory_type` | Free text (e.g. "Field Flattener", "Electronic Focuser") |
| `weight_kg` | Weight for payload computation |

---

## Disabling equipment

Every gear type (Telescope, Camera, Mount, Filter, Accessory) and every Combination has an `is_disabled`
flag, set from its own edit form.

- **Deletion is blocked while an item is still referenced by a combination** (your own, or another user's
  if the item is shared) — the delete request returns the combination name(s) so you know what to unlink
  first. Disabling is the alternative when you don't want to fully delete something that's still tied to
  a combination.
- Disabled items are excluded from every combination editor's dropdowns/checkboxes, **unless** they are
  already selected on the combination currently being edited — an existing combination never silently
  loses a component from the editor UI just because that component got disabled later.
- Disabled items are hidden from their list tab by default. A **"Show hidden (N)"** toggle at the top of
  each tab (Telescopes, Cameras, Mounts, Filters, Accessories, Combinations) reveals them, tagged with a
  "Hidden" badge.
- A combination that references a disabled (or no longer resolvable) piece of equipment is automatically
  flagged **invalid** — a computed status, independent of the combination's own `is_disabled` toggle — and
  shown with a warning badge in the Equipment tab. Invalid/disabled combinations are not hidden or blocked
  from further use here; other features (SkyTonight, Plan My Night, Astrodex) are expected to start
  filtering on this status as each becomes combination-aware.

---

## Presets

**File**: `static/data/equipment_presets.json` (static asset, no backend involvement — fetched directly by the frontend)

A curated list of real-world gear (telescopes, cameras, mounts, filters, accessories) that lets users
skip manual data entry for common models. Each entry has an `id`, a `label`, a `manufacturer`, a
`source_url` for provenance, a `suggests_experience` (`beginner` / `intermediate` / `advanced`) used to
sort the closest match to the user's own experience level to the top, and type-specific spec fields
matching the corresponding [gear type](#gear-types) table above one-to-one (e.g. a telescope preset's
`type` maps to `telescope_type`, a filter preset's `filter_type` must be one of the enum values listed
under [Filters](#filters), etc.).

Consumed in two places:

- The **guided setup wizard**'s equipment step (`static/js/first_run.js`) — offered alongside a manual-entry option.
- The **Equipment tab**'s "New Telescope / Camera / Mount / Filter / Accessory" modals (`static/js/equipment.js`) —
  a "Start from a preset" dropdown prefills the form, which remains fully editable afterward. Only shown when
  adding a new item, not when editing an existing one.

To add a preset, append an entry to the relevant array in the JSON file — no code change or restart needed
(it's fetched fresh by the browser). Keep enum-like fields (`type`, `sensor_type`, `mount_type`, `filter_type`)
consistent with the values each form's `<select>` accepts, or the preset will silently fail to prefill that field.

### Bundles (smart telescopes)

A **telescope** preset can declare a `bundle`: an array of sibling equipment items that ship built into the
same physical unit — most commonly an all-in-one "smart telescope" (Seestar, Dwarf, Vespera, …) whose fixed
built-in camera sensor has no other way to be represented, since a plain telescope preset only carries
optical specs (aperture/focal length), not sensor data.

```json
{
  "id": "seestar_s50",
  "...": "... normal telescope fields ...",
  "auto_combination": true,
  "bundle": [
    { "kind": "camera", "label": "Seestar S50 built-in camera (Sony IMX462)", "sensor_width_mm": 5.6, "...": "..." },
    { "kind": "mount", "label": "Seestar S50 built-in AZ mount/tripod", "mount_type": "Alt-Azimuth", "...": "..." },
    { "kind": "filter", "label": "Seestar S50 Solar Filter", "filter_type": "Solar", "...": "..." }
  ]
}
```

- `kind` is one of `camera` / `mount` / `filter` / `accessory`; the rest of each bundle entry's fields match
  that kind's normal preset shape one-to-one (same as a standalone entry in the `cameras`/`mounts`/
  `filters`/`accessories` arrays above).
- Set **`weight_kg: 0`** on every bundle entry — the parent telescope's own `weight_kg` already represents
  the whole fused unit's mass; giving bundle items their own non-zero weight would multiply-count it in a
  combination card's total payload calculation.
- `auto_combination: true` on the parent tells the **guided setup wizard** (`static/js/first_run.js`) to
  create every bundle item alongside the telescope and link them all into one auto-created combination —
  this is what makes "every time the wizard creates equipment, a combination is created" true even for a
  single-preset pick. When a bundling preset is selected, the wizard's separate camera picker is hidden
  (a combination can only have one imaging camera, and the bundle already supplies it).
- Bundle items are never independently selectable elsewhere (no separate preset dropdown entry) — they only
  ever get created as part of their parent telescope's wizard flow.

---

## Equipment combinations

A **combination** is a named configuration that groups a telescope, camera, mount, filters, and accessories. It is the unit used by:

- The **FOV Calculator** (computes field of view for that telescope + camera pair)
- **SkyTonight** ("Best telescope for this target" uses all your combinations)
- **Astrodex** picture metadata (which setup was used for an image session)
- **Plan My Night** telescope selector

At least one of **telescope** or **camera** is required; both are single-value fields (max one telescope,
max one imaging camera per combination). Two additional fields cover setups the base telescope+camera model
doesn't:

| Field | Description |
|-------|-------------|
| `guide_camera_id` | Optional second camera used purely for guiding (OAG or guide scope). Informational only — never factored into FOV or scoring math, since a guide camera never determines framing. |
| `lens_focal_length_mm` / `lens_focal_ratio` | Optional focal length/ratio of a lens mounted directly on the camera, used **only** when no telescope is selected (e.g. a DSLR/mirrorless camera + lens on a star tracker for wide-field imaging). Lets a camera-only combination still be scored like a telescope+camera one. |

A combination is flagged **Shared** only when **every component** in it is individually shared. If one component is later made private, the combination shows a ⚠ warning.

### Photo badges

Each combination card carries two badges sourced from Astrodex:

- **Photo count** — number of Astrodex pictures linking to this combination. Click it to open the same
  slideshow used elsewhere in Astrodex, showing every one of those pictures.
- **Average rating** — mean of the 0-5 star ratings across those pictures (unrated pictures don't count
  toward the average, though they do count toward the photo count).

Both respect the same visibility as the rest of Astrodex: with `config['astrodex']['private']` off
(default), they aggregate every visible user's pictures for that combination; with it on, only your own.

### Deletion

A combination can't be deleted while it's still referenced by any Astrodex picture (any user) - the
delete-guard mirrors the one on individual equipment items above. This is checked in addition to the
component-level guard: deleting the *equipment inside* a combination is blocked separately (see
[Disabling equipment](#disabling-equipment)) while deleting the *combination itself* is blocked by its
pictures.

---

## Field of View calculator

**Sub-tab**: Equipment → FOV

**Endpoint**: `POST /api/equipment/fov-calculator`

### Formulas

#### Image scale (arcsec/pixel)

$$\text{image scale} = \frac{206.265 \times \text{pixel size}\ [\mu m]}{\text{focal length}\ [mm]} \quad [\text{arcsec/px}]$$

The constant 206 265 arcsec ≈ 1 radian.

#### Field of view (degrees)

$$\text{FOV}_\text{h} = \frac{57.3 \times \text{sensor width}\ [mm]}{\text{focal length}\ [mm]}$$

$$\text{FOV}_\text{v} = \frac{57.3 \times \text{sensor height}\ [mm]}{\text{focal length}\ [mm]}$$

$$\text{FOV}_\text{diag} = \frac{57.3 \times \sqrt{\text{width}^2 + \text{height}^2}}{\text{focal length}}$$

The constant 57.3° ≈ 1 radian (small-angle approximation valid for typical FOV values).

#### Sampling classification (Nyquist criterion)

The optimal sampling range is **2–3 pixels per FWHM** of the seeing disk:

$$\text{optimal min} = \frac{\text{seeing}}{3}\quad[\text{arcsec/px}]$$
$$\text{optimal max} = \frac{\text{seeing}}{2}\quad[\text{arcsec/px}]$$

| Result | Condition |
|--------|-----------|
| **Optimal** | `optimal_min ≤ image_scale ≤ optimal_max` |
| **Undersampled** | `image_scale > optimal_max` — fewer than 2 px per FWHM; detail is lost |
| **Oversampled** | `image_scale < optimal_min` — more than 3 px per FWHM; SNR per pixel is low |

Default seeing used for the classification: **2.0 arcsec** (typical suburban sky). You can override this in the calculator UI.

---

## Equipment sharing

Any telescope, camera, mount, filter, or accessory can be marked **"Share with all users"** in its edit form. Shared items are immediately visible to every user on the instance:

- Shared items appear under a *"Shared by Others"* section labelled with the owner's name.
- Non-owners can **read** but not edit or delete.
- Your own shared items show a **Shared** badge.

Shared equipment flows through the whole app:

| Feature | Effect |
|---------|--------|
| FOV Calculator | Shared telescopes & cameras appear in dropdowns |
| SkyTonight — Best Telescope | Recommendations include shared scopes (own listed first) |
| Astrodex — Add Picture | Shared combinations and filters available in selectors |
| Plan My Night | Shared telescopes appear in the telescope selector |
| Exposure Calculator | Shared cameras appear in the camera selector |

---

## SkyTonight integration

SkyTonight uses the **active equipment combination** (telescope + camera) to:

1. Compute the **plate scale** for the Exposure Calculator.
2. Rank targets in the "Best telescope for this target" modal: for each DSO, it evaluates each combination's plate scale against the object's angular size and returns a suitability score.

---

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/equipment/telescopes` | List all telescopes (own + shared) |
| `POST` | `/api/equipment/telescopes` | Create a telescope |
| `GET/PUT/DELETE` | `/api/equipment/telescopes/<id>` | Read / update / delete |
| `GET` | `/api/equipment/cameras` | List cameras |
| `POST` | `/api/equipment/cameras` | Create camera |
| `GET/PUT/DELETE` | `/api/equipment/cameras/<id>` | Read / update / delete |
| `GET` | `/api/equipment/mounts` | List mounts |
| `POST` | `/api/equipment/mounts` | Create mount |
| `GET/PUT/DELETE` | `/api/equipment/mounts/<id>` | Read / update / delete |
| `GET` | `/api/equipment/filters` | List filters |
| `POST` | `/api/equipment/filters` | Create filter |
| `GET/PUT/DELETE` | `/api/equipment/filters/<id>` | Read / update / delete |
| `GET` | `/api/equipment/accessories` | List accessories |
| `POST` | `/api/equipment/accessories` | Create accessory |
| `GET/PUT/DELETE` | `/api/equipment/accessories/<id>` | Read / update / delete |
| `GET` | `/api/equipment/combinations` | List combinations with full analysis |
| `POST` | `/api/equipment/combinations` | Create combination |
| `GET/PUT/DELETE` | `/api/equipment/combinations/<id>` | Read / update / delete |
| `POST` | `/api/equipment/fov-calculator` | Compute FOV for given telescope + camera |
| `GET` | `/api/equipment/summary` | Count of each equipment type owned and shared |
