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
| **Filter** | Filters | Type (LRGB, narrowband...), central wavelength, bandwidth |
| **Accessory** | Accessories | Field flattener, focuser, filter wheel, etc. |
| **Combination** | Combinations | Named set of telescope + camera + mount + filters + accessories |

Data is stored in the database: `equipment_items` (one row per telescope, camera, mount, filter or accessory), `equipment_combinations` and `combination_equipment` (the filters and accessories of each combination); `equipments/<user_id>_<type>.json` inside a backup ZIP.

---

## Equipment combinations

A **combination** is a named configuration that groups a telescope, camera, mount, filters, and accessories. It is the unit used by:

- The **FOV Calculator** (computes field of view for that telescope + camera pair)
- **SkyTonight** ("Best Equipment For This Target" rates all your enabled and valid combinations)
- **Astrodex** picture metadata (which setup was used for an image session)
- **Plan My Night** combination selector (see [PLAN_MY_NIGHT.md](PLAN_MY_NIGHT.md))

At least one of **telescope** or **camera** is required; both are single-value fields (max one telescope,
max one imaging camera per combination). Two additional fields cover setups the base telescope+camera model
doesn't:

| Field | Description |
|-------|-------------|
| `guide_camera_id` | Optional second camera used purely for guiding (OAG or guide scope). Informational only - never factored into FOV or scoring math, since a guide camera never determines framing. |
| `lens_focal_length_mm` / `lens_focal_ratio` | Optional focal length/ratio of a lens mounted directly on the camera, used **only** when no telescope is selected (e.g. a DSLR/mirrorless camera + lens on a star tracker for wide-field imaging). Lets a camera-only combination still be scored like a telescope+camera one. |

A combination is flagged **Shared** only when **every component** in it is individually shared. If one component is later made private, the combination shows a ⚠ warning.

### Photo badges

Each combination card carries two badges sourced from Astrodex:

- **Photo count** - number of Astrodex pictures linking to this combination. Click it to open the same
  slideshow used elsewhere in Astrodex, showing every one of those pictures.
- **Average rating** - mean of the 0-5 star ratings across those pictures (unrated pictures don't count
  toward the average, though they do count toward the photo count).

Both respect the same visibility as the rest of Astrodex: with `config['astrodex']['private']` off
(default), they aggregate every visible user's pictures for that combination; with it on, only your own.

### Deletion

A combination can't be deleted while it's still referenced by any Astrodex picture (any user), pinned to
any Plan My Night plan (any user), or referenced by any Observation Log session (any user) - the
delete-guard mirrors the one on individual equipment items. This is checked in addition to the
component-level guard: deleting the *equipment inside* a combination is blocked separately (see
[Disabling equipment](#disabling-equipment)) while deleting the *combination itself* is blocked by its
pictures, plans or sessions (see [OBSERVATION_LOG.md](OBSERVATION_LOG.md#deletion-and-reference-counting)).

---

## Field of View calculator

**Sub-tab**: Equipment -> FOV

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

The optimal sampling range is **2-3 pixels per FWHM** of the seeing disk:

$$\text{optimal min} = \frac{\text{seeing}}{3}\quad[\text{arcsec/px}]$$
$$\text{optimal max} = \frac{\text{seeing}}{2}\quad[\text{arcsec/px}]$$

| Result | Condition |
|--------|-----------|
| **Optimal** | `optimal_min ≤ image_scale ≤ optimal_max` |
| **Undersampled** | `image_scale > optimal_max` - fewer than 2 px per FWHM; detail is lost |
| **Oversampled** | `image_scale < optimal_min` - more than 3 px per FWHM; SNR per pixel is low |

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
| SkyTonight - Combination recommendations | Recommendations include shared combinations (own listed first) |
| Astrodex - Add Picture | Shared combinations and filters available in selectors |
| Plan My Night | Shared combinations appear in the combination selector |
| Exposure Calculator | Shared cameras appear in the camera selector |

---

## Disabling equipment

Every gear type (Telescope, Camera, Mount, Filter, Accessory) and every Combination has an `is_disabled`
flag, set from its own edit form.

- **Deletion is blocked while an item is still referenced by a combination** (your own, or another user's
  if the item is shared) - the delete request returns the combination name(s) so you know what to unlink
  first. Disabling is the alternative when you don't want to fully delete something that's still tied to
  a combination.
- Disabled items are excluded from every combination editor's dropdowns/checkboxes, **unless** they are
  already selected on the combination currently being edited - an existing combination never silently
  loses a component from the editor UI just because that component got disabled later.
- Disabled items are hidden from their list tab by default. A **"Show hidden (N)"** toggle at the top of
  each tab (Telescopes, Cameras, Mounts, Filters, Accessories, Combinations) reveals them, tagged with a
  "Hidden" badge.
- A combination that references a disabled (or no longer resolvable) piece of equipment is automatically
  flagged **invalid** - a computed status, independent of the combination's own `is_disabled` toggle - and
  shown with a warning badge in the Equipment tab. Invalid/disabled combinations are not hidden or blocked
  from further use here; other features (SkyTonight, Plan My Night, Astrodex) are expected to start
  filtering on this status as each becomes combination-aware.

---

## SkyTonight integration

For each DSO, `POST /api/skytonight/combination-recommendations` rates every enabled and valid equipment combination (own + shared) on a 1-5 scale:

1. Resolves each combination's effective optics - a telescope's aperture/focal length/f-ratio, or for a camera-only combination (no telescope), its `lens_focal_length_mm`/`lens_focal_ratio`.
2. Scores focal length against an ideal range derived from the target's apparent size/type, and aperture against the target's magnitude.
3. When the combination's camera has sensor dimensions, blends in a real field-of-view match (via the FOV Calculator's formulas) against the target's apparent size, instead of relying on the focal-length heuristic alone.

Disabled or invalid combinations (see [Disabling equipment](#disabling-equipment)) never appear in recommendations. See [SKYTONIGHT.md](SKYTONIGHT.md#equipment-combination-recommendations) for the full scoring model.

---

## Presets

**Sources**: `presets/equipment/<type>/<manufacturer>.json`, one small file per gear type and manufacturer.
**Generated file**: `static/data/equipment_presets.json` (static asset, no backend involvement - fetched
directly by the frontend), built from the sources by `scripts/build_equipment_presets.py`. Never edit it by hand.

A curated list of real-world gear (telescopes, cameras, mounts, filters, accessories) that lets users
skip manual data entry for common models. Each entry has an `id`, a `label`, a `manufacturer`, a
`source_url` for provenance, a `suggests_experience` (`beginner` / `intermediate` / `advanced`) used to
sort the closest match to the user's own experience level to the top, and type-specific spec fields.
**Several preset keys are not named like the stored fields** of the [Telescopes](#telescopes) and
[Cameras](#cameras) tables below (`label`, `type`, `resolution_w`, `resolution_h`): use the
[preset field reference](#preset-field-reference), not those tables, when writing a preset.

Consumed in two places:

- The **guided setup wizard**'s equipment step (`static/js/first_run.js`) - offered alongside a manual-entry option.
- The **Equipment tab**'s "New Telescope / Camera / Mount / Filter / Accessory" modals (`static/js/equipment.js`) -
  a "Start from a preset" dropdown prefills the form, which remains fully editable afterward. Only shown when
  adding a new item, not when editing an existing one.

### Adding or editing a preset

No code change or restart is needed: the browser fetches the generated file fresh.

1. Open the file of the gear type and manufacturer, for example `presets/equipment/telescopes/zwo.json`,
   or create it. The file name is the manufacturer in lowercase, every run of other characters replaced
   by a hyphen (`Sky-Watcher` -> `sky-watcher.json`, `William Optics` -> `william-optics.json`), and the
   file holds that manufacturer only:

   ```json
   {
     "$schema": "../telescopes.schema.json",
     "presets": [
       { "id": "zwo_seestar_s50", "label": "Seestar S50", "manufacturer": "ZWO", "...": "..." }
     ]
   }
   ```

   The `$schema` line gives completion and inline errors in VS Code and most editors. The schemas
   (`presets/equipment/<type>.schema.json`) are generated from the same rules the script checks.
2. Fill the entry with the keys of the [preset field reference](#preset-field-reference) below.
3. Run `python scripts/build_equipment_presets.py`. It formats the sources (2-space indent, presets
   sorted by `id`), rebuilds the generated file and the schemas, then lists every problem it finds, with
   the file and the preset id. Commit the sources and the generated files together.

A wrong key or enum value raises no error in the browser: the field is left empty or replaced by a default.
That is why the script checks every rule below; the *Validate equipment presets* CI job runs
`python scripts/build_equipment_presets.py --check` (no write) when a preset file or a source it reads
changes, and fails a pull request whose sources and generated files disagree.

### Bundles (smart telescopes)

A **telescope** preset can declare a `bundle`: the ids of the equipment that ships in the box with it -
most commonly an all-in-one "smart telescope" (Seestar, Dwarf, Vespera, ...) whose fixed built-in camera
sensor has no other way to be represented, since a plain telescope preset only carries optical specs
(aperture/focal length), not sensor data. Each item is a normal preset in the file of its own type:

```json
// presets/equipment/telescopes/zwo.json
{ "id": "seestar_s50", "...": "... normal telescope fields ...", "auto_combination": true,
  "bundle": ["seestar_s50_camera", "seestar_s50_mount", "seestar_s50_solar_filter"] }

// presets/equipment/cameras/zwo.json
{ "id": "seestar_s50_camera", "label": "Seestar S50 built-in camera (Sony IMX462)", "built_in": true,
  "weight_kg": 0, "sensor_width_mm": 3.15, "...": "..." }
```

- A bundle references one **camera**, at most one **mount**, and any number of filters and accessories,
  each listed once. It describes what ships in the box: an accessory sold separately (the Seestar TC20
  tripod, the TH10 tripod head) is a standalone accessory preset, not part of a bundle.
- **`"built_in": true`** marks an item that is part of the unit and not sold on its own (a smart telescope's
  camera, mount, bundled solar filter). It is left out of the standalone preset lists and reaches the app only
  through the bundles that reference it; it must be referenced by at least one bundle, needs no
  `source_url` / `suggests_experience`, and has **`weight_kg: 0`** - the telescope's own `weight_kg` is the
  whole unit's mass, so a non-zero weight would count it twice in a combination card's payload. A bundled
  item without `built_in` (a camera also sold separately) keeps its own list entry and its real weight.
- The generated file replaces every reference by the item itself, with a `kind` field
  (`camera` / `mount` / `filter` / `accessory`): the frontend reads the bundle as a list of objects.
- The bundle mount must carry what the combination card adds up - the telescope, the bundled camera and
  the bundled accessories - within its recommended load (75 % of `payload_capacity_kg`).
- `auto_combination: true` on the parent makes picking that preset create every bundle item alongside
  the telescope and link them all into one combination (`static/js/equipment_bundles.js`):
  - in the **guided setup wizard** (`static/js/first_run.js`), always - the wizard's separate camera
    picker is hidden (a combination can only have one imaging camera, and the bundle already supplies it);
  - in the **Equipment tab**'s "New Telescope" form, through an option shown under the preset picker,
    ticked by default. Without the built-in camera, the framing simulator and the field of view of the
    combination cannot be computed.
- The bundle **cameras** are also offered in the Equipment tab's "New Camera" preset picker (once each), so
  a smart telescope saved without its camera (before bundles existed, or with the option unticked) can be
  completed: add the camera, then select it in the combination. Built-in mounts and filters are not
  offered separately.
- **Orientation**: give a bundle camera's `sensor_width_mm` / `sensor_height_mm` and `resolution_w` /
  `resolution_h` in the orientation the device delivers its images, since the framing simulator draws the
  width across. Seestar units record in portrait (S50: 1080 x 1920), so their short side is the width;
  Dwarf, Vespera and Atlas record in landscape.
- **Built-in mount capacity**: makers publish no payload for a built-in mount. The bundle mount's
  `payload_capacity_kg` is sized so the unit's own weight sits at the recommended load (75% of the
  capacity), so the combination does not report a payload warning for the device itself.
- A sensor size the maker does not publish is derived as resolution x pixel size (Seestar S50 Pro:
  2160 x 3840 px at 2.9 um = 6.26 x 11.14 mm; Seestar S30 Plus: 1440 x 2560 px at 2.9 um = 4.18 x 7.42 mm).
  A published size must agree with resolution x pixel size within 2 %, on each axis.
- A pixel size the maker does not publish (camera bodies, as a rule) is derived as sensor width /
  resolution width (Nikon Z 6II: 35.9 mm / 6048 px = 5.94 um), with the resolution of the largest RAW image.
  A body's `weight_kg` is the weight with battery and card when the maker gives both, since that is what the
  mount carries; it is left out when the maker publishes none (Canon EOS 6D Mark II, EOS 2000D).
- Sony's UK and Australian spec pages omit the Alpha 7 IV image size; its 7008 x 4672 px comes from the spec
  page of the official Sony Thailand store
  (<https://store.sony.co.th/th/blogs/en_7149167116331_40893409230891/en_7149167116331_40893409230891_specifications/?locale=en>),
  and `source_url` stays the Sony UK page that gives every other value.
- When the maker publishes neither the sensor size nor its resolution, but does publish the field of view,
  the focal length and the pixel size (Unistellar Odyssey: 45 x 33.6 arcmin, 320 mm, 1.45 um), the sensor
  size is derived as focal length x field of view in radians (4.19 x 3.13 mm), and the resolution as sensor
  size / pixel size (2890 x 2159 px). Without at least these three figures, the preset is not added.
- A device that bins its sensor for astro images (DWARFLAB Draco: 8192 x 6144 at 1.197 um, delivered 2x2
  binned) gets the delivered resolution and binned pixel size (4096 x 3072 at 2.394 um); the sensor size is
  the same either way.
- Maker spec tables are often rendered by JavaScript or folded in an accordion (DWARFLAB, Unistellar shop,
  Celestron): read the rendered page, not the raw HTML, before concluding a value is not published.
- **Atlas Twin** carries two identical 80 mm modules pointed at the same target. A combination holds one
  imaging camera, so the preset has one module's optics and camera (same field of view, same image scale)
  and the weight of the mount plus both modules (3.5 + 2 x 3 kg). The doubled light ("F/3.2 equivalent")
  is not modelled.

### Preset field reference

The exact keys the frontend reads from a preset (`static/js/equipment.js`, `equipment_bundles.js`,
`first_run.js`). Any other key is ignored; a key under its stored name (`name`, `telescope_type`,
`sensor_type`, `resolution_width_px`) is ignored too, which leaves the field empty.

**Every entry**: `id` (unique snake_case across every preset file), `label` (becomes the item's `name`),
`manufacturer`, `source_url` (the maker's official spec page) and `suggests_experience` (`beginner` /
`intermediate` / `advanced`). A camera, mount, filter or accessory may carry `"built_in": true` (see
[Bundles](#bundles-smart-telescopes)), and may then leave out `source_url` and `suggests_experience`.

| Preset | Key in the preset | Stored as | Notes |
|--------|-------------------|-----------|-------|
| Telescope | `type` | `telescope_type` | A **code**, not the form label: `refractor`, `apo`, `reflector`, `sct`, `edgehd`, `rasa`, `rc`, `newtonian`, `maksutov`, `cassegrain`, `dobsonian`. An unknown value becomes `Refractor`. |
| Telescope | `aperture_mm`, `focal_length_mm`, `weight_kg` | same | Aperture 10-5000 mm, focal length 100-50000 mm. For a smart telescope, `weight_kg` is the whole unit. |
| Telescope | `focal_ratio` | not stored | Informational; the f-ratio is recalculated from focal length / aperture. |
| Telescope | `auto_combination`, `bundle` | - | See [Bundles](#bundles-smart-telescopes). |
| Camera | `type` | `sensor_type` | A **code**: `cmos_color`, `cmos_mono`, `ccd_color`, `ccd_mono`, `dslr_color`, `mirrorless_color` (the last two are stored as `CMOS Color`). An unknown value becomes `CMOS Color`, so a mono camera with a wrong code silently turns into a colour one. |
| Camera | `resolution_w`, `resolution_h` | `resolution_width_px`, `resolution_height_px` | Width 640-16000 px, height 480-12000 px. **Not** `resolution_width_px`: the API then rejects the camera, and a bundle is created without it. |
| Camera | `sensor_width_mm`, `sensor_height_mm`, `pixel_size_um` | same | Sensor 1-100 mm, pixel 1-10 um. Width and height in the same orientation as `resolution_w` / `resolution_h`, and equal to resolution x pixel size within 2 %. |
| Camera | `weight_kg`, `cooling_supported`, `min_temperature_c` | same | `min_temperature_c` between -50 and 0, only for cooled cameras. |
| Mount | `mount_type` | same | The exact form value: `Equatorial`, `Alt-Azimuth`, `Dobsonian`, `Fork Mount`. |
| Mount | `payload_capacity_kg`, `tracking_accuracy_arcsec`, `guiding_supported`, `meridian_flip_required`, `meridian_flip_delay_min`, `meridian_flip_duration_min` | same | In a **bundle**, only `mount_type`, `payload_capacity_kg` and `guiding_supported` are kept. |
| Filter | `filter_type` | same | The exact form value, see [Filters](#filters). |
| Filter | `central_wavelength_nm`, `bandwidth_nm`, `intended_use` | same | Wavelength 300-2000 nm, bandwidth 1-1000 nm. |
| Accessory | `accessory_type`, `weight_kg` | same | `accessory_type` is free text. |

Not carried by presets: a camera's `read_noise_e` and `quantum_efficiency` (the user enters them; the
Exposure Calculator needs them), a telescope's `reducer_barlow_factor` (always 1.0).

**Checklist for a new preset**, for a person or an AI agent:

1. Take every value from the maker's official spec page, and put that page in `source_url`. Never estimate
   a value; a sensor size the maker does not publish is derived as described above.
2. Use the preset keys and codes of the table above, not the stored field names.
3. For a smart telescope: put its camera, mount and boxed filters in the files of their own types with
   `"built_in": true` and `weight_kg: 0`, and list their ids in the telescope's `bundle` (exactly one camera,
   at most one mount). Give the camera in the orientation the device delivers its images, and the mount a
   `payload_capacity_kg` of at least the unit's `weight_kg` / 0.75.
4. Run `python scripts/build_equipment_presets.py` and fix every problem it lists.

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
| `meridian_flip_required` | Whether the mount flips at the meridian. Left as "Auto", it is derived from `mount_type` (`Equatorial` -> yes; alt-az / Dobsonian / fork -> no); set it explicitly for the exceptions (a fork mount on a wedge does flip). |
| `meridian_flip_delay_min` | Minutes the mount keeps tracking past the meridian before a flip is needed (0-120). |
| `meridian_flip_duration_min` | Dead time for the flip plus re-centre and re-guide (0-60, default 5). |

The last three feed the Plan My Night **meridian flip** indicator - see
[PLAN_MY_NIGHT.md](PLAN_MY_NIGHT.md#meridian-flip). Absent on older mount files, they are backfilled
to these defaults on every read (`equipment_profiles.normalize_mount_flip_fields`, applied by
`get_mount`, the mounts list endpoint and `plan_my_night._resolve_plan_mount`); the stored file is
not rewritten.

---

## Filters

| Field | Description |
|-------|-------------|
| `filter_type` | `LRGB`, `Narrowband`, `Broadband`, `Luminance`, `RGB`, `H-Alpha`, `OIII`, `SII`, `UHC`, `Light Pollution Reduction`, `Solar`, `Other` |
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
