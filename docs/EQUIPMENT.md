# Equipment Profiles

The **Equipment** tab lets you catalogue all your astronomy gear. Profiles pre-fill fields across Astrodex, the Exposure Calculator, and the SkyTonight target scorer.

**Module**: `backend/equipment_profiles.py`

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

## Equipment combinations

A **combination** is a named configuration that groups a telescope, camera, mount, filters, and accessories. It is the unit used by:

- The **FOV Calculator** (computes field of view for that telescope + camera pair)
- **SkyTonight** ("Best telescope for this target" uses all your combinations)
- **Astrodex** picture metadata (which setup was used for an image session)
- **Plan My Night** telescope selector

A combination is flagged **Shared** only when **every component** in it is individually shared. If one component is later made private, the combination shows a ⚠ warning.

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
