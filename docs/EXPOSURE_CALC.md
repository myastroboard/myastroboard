# Exposure Calculator

The Exposure Calculator is a tool inside the **Equipment** tab that helps astrophotographers determine the optimal sub-exposure length and total number of frames for a given night.

## Where to find it

**Equipment -> Exposure Calc**

## Inputs

| Field | Description | Default |
|-------|-------------|---------|
| Telescope | Select from your saved telescopes | - |
| Camera | Select from your saved cameras | - |
| Read noise (e⁻) | Auto-filled from camera profile if available | 4 e⁻ |
| Quantum efficiency (%) | Sensor QE; 60-75% covers most modern CMOS cameras | 65% |
| Total integration (h) | Planned session length | 3 h |
| Sky quality | Bortle class 1 (pristine) to 9 (inner city) | Bortle 5 |

## Outputs

| Output | Meaning |
|--------|---------|
| Plate scale | Angular size of one pixel on the sky (arcsec/px) |
| Sky background | Estimated sky photon rate hitting each pixel (e⁻/px/s) |
| Recommended sub-exposure | Minimum exposure for sky-limited imaging |
| Number of subs | Subs needed to fill the requested total integration time |

## Limitations

- **QE is assumed flat** across the spectral range. In practice, QE varies with wavelength. The formula uses V-band sky flux (matching the SQM meter passband), which gives the best absolute accuracy for broadband RGB imaging.
- **Narrowband filters** require different treatment: the sky background is much lower (fewer e⁻/px/s) through Ha/OIII/SII filters, so sub-exposures can and should be much longer. The calculator is primarily intended for broadband (L/RGB/OSC) imaging.
- **Dark current** is not included. For cooled cameras (−10 °C or colder), dark current is negligible. For uncooled or mildly cooled cameras add dark current to `B_sky` if known.
- **Atmospheric extinction**, light pollution gradients, and vignetting are not modelled.

## Estimated minimum integration time

The Exposure Calculator sizes subs *from* a total integration the user supplies. The SkyTonight
**advanced DSO filter** "max estimated integration time" needs the opposite: a rough estimate of the
*total* integration a target needs. This is implemented in `backend/equipment/exposure_math.py`
(`estimate_min_integration_hours`) and is a deliberately rough planning heuristic, not a promise.

### How the estimate is computed

Working in the **sky-limited regime** (which the sub-exposure length from [Method](#method) guarantees), the
per-pixel signal-to-noise ratio after a total integration time $T$ is

$$\text{SNR} = \frac{S \cdot T}{\sqrt{(S + B)\,T}} = \sqrt{T}\;\frac{S}{\sqrt{S + B}}$$

where $S$ and $B$ are the per-pixel photo-electron rates (e⁻/px/s) from the **target's mean surface
brightness** and from the **sky**, both computed with the same
$F_0 \times 10^{-\text{SB}/2.5} \times \text{QE} \times \frac{\pi}{4} D_m^2 \times \text{plate scale}^2$
form used for $B_\text{sky}$ in [Method](#method). Solving for $T$ to reach a chosen per-pixel SNR target:

$$T = \text{SNR}_\text{target}^2 \;\frac{S + B}{S^2}$$

- $\text{SNR}_\text{target} = 15$ (per pixel, on the target's mean surface brightness). This is a
  "detectable and processable" threshold, **not** "publication quality" - deep, clean images of
  faint targets need far more.
- The target's mean surface brightness comes from the catalogue integrated magnitude spread over the
  catalogue angular size (`skytonight_calculator._surface_brightness`, then converted from
  mag/arcmin² to mag/arcsec²). This **over-estimates the required time** for objects with a bright
  core and faint outer halo (e.g. M31, M42) - the mean over the full catalogue extent is much
  fainter than the part you would actually expose for.
- Sky brightness comes from the active location's measured SQM if set, otherwise the Bortle -> SQM
  table in [Method](#method).
- Because $S$ and $B$ share the $D_m^2 \times \text{plate scale}^2$ factor, aperture largely cancels:
  the estimate is driven by **f-ratio, pixel size, sky brightness and target surface brightness** -
  the well-known result that per-pixel SNR on extended sources depends on f-ratio, not aperture.

### Limitations

- Broadband (L / RGB / OSC) only, exactly like the sub-exposure calculator - narrowband sky rates
  are far lower and the estimate does not model them.
- No QE-curve, atmospheric extinction, filter transmission, gradient or vignetting modelling.
- The mean-surface-brightness input skews the estimate long for centrally-concentrated targets.
- Treat the number as an order-of-magnitude planning aid ("minutes", "a couple of hours", "many
  nights"), not a target to hit.

## Method

### Plate scale

$$\text{plate scale} = \frac{206.265 \times \text{pixel size}\ [\mu m]}{\text{focal length}\ [mm]} \quad [\text{arcsec/px}]$$

### Sky background rate

The sky photon rate per pixel per second is computed from the observed sky surface brightness (SQM value derived from the Bortle class), the telescope aperture, and the plate scale:

$$B_\text{sky} = F_0 \times 10^{-\text{SQM}/2.5} \times \text{QE} \times \frac{\pi}{4} \times D_m^2 \times \text{plate scale}^2$$

Where:
- $F_0 = 9 \times 10^9$ photons/m²/s/arcsec² - Vega zero-point flux, V-band
- $D_m$ - aperture in metres
- $\text{plate scale}$ - in arcsec/px (so $\text{plate scale}^2$ is arcsec²/px)

### Bortle -> SQM mapping

| Bortle | SQM (mag/arcsec²) |
|--------|-------------------|
| 1 | 22.0 |
| 2 | 21.5 |
| 3 | 21.2 |
| 4 | 20.8 |
| 5 | 20.3 |
| 6 | 19.5 |
| 7 | 18.8 |
| 8 | 18.3 |
| 9 | 17.5 |

### Optimal sub-exposure (5× criterion)

The recommended sub-exposure is chosen so that the sky background contributes **5 times more noise variance** than the read noise:

$$B_\text{sky} \times t_\text{sub} = 5 \times \text{RN}^2 \implies t_\text{sub} = \frac{5 \times \text{RN}^2}{B_\text{sky}}$$

This is the standard "sky-limited" criterion used in amateur astrophotography. Exposures shorter than this threshold are read-noise dominated; longer exposures don't improve SNR per unit time.

### Number of subs

$$n_\text{subs} = \text{round}\!\left(\frac{\text{total integration}}{t_\text{sub}}\right)$$

## Calibration

The formula was validated against published empirical measurements:
- ASI294MC Pro, f/7, 150 mm aperture, pixel = 4.63 µm, QE ≈ 75%, Bortle 5 (SQM 20.3)
- Expected sky background from real data: ~0.83 e⁻/px/s
- Formula result: ~1.0 e⁻/px/s - within the measurement uncertainty
