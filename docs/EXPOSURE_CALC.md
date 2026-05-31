# Exposure Calculator

The Exposure Calculator is a tool inside the **Equipment** tab that helps astrophotographers determine the optimal sub-exposure length and total number of frames for a given night.

## Where to find it

**Equipment → Exposure Calc**

## Inputs

| Field | Description | Default |
|-------|-------------|---------|
| Telescope | Select from your saved telescopes | - |
| Camera | Select from your saved cameras | - |
| Read noise (e⁻) | Auto-filled from camera profile if available | 4 e⁻ |
| Quantum efficiency (%) | Sensor QE; 60–75% covers most modern CMOS cameras | 65% |
| Total integration (h) | Planned session length | 3 h |
| Sky quality | Bortle class 1 (pristine) to 9 (inner city) | Bortle 5 |

## Outputs

| Output | Meaning |
|--------|---------|
| Plate scale | Angular size of one pixel on the sky (arcsec/px) |
| Sky background | Estimated sky photon rate hitting each pixel (e⁻/px/s) |
| Recommended sub-exposure | Minimum exposure for sky-limited imaging |
| Number of subs | Subs needed to fill the requested total integration time |

## Method

### Plate scale

$$\text{plate\_scale} = \frac{206.265 \times \text{pixel\_size}\ [\mu m]}{\text{focal\_length}\ [mm]} \quad [\text{arcsec/px}]$$

### Sky background rate

The sky photon rate per pixel per second is computed from the observed sky surface brightness (SQM value derived from the Bortle class), the telescope aperture, and the plate scale:

$$B_\text{sky} = F_0 \times 10^{-\text{SQM}/2.5} \times \text{QE} \times \frac{\pi}{4} \times D_m^2 \times \text{plate\_scale}^2$$

Where:
- $F_0 = 9 \times 10^9$ photons/m²/s/arcsec² - Vega zero-point flux, V-band
- $D_m$ - aperture in metres
- $\text{plate\_scale}$ - in arcsec/px (so $\text{plate\_scale}^2$ is arcsec²/px)

### Bortle → SQM mapping

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

$$n_\text{subs} = \text{round}\!\left(\frac{\text{total\_integration}}{t_\text{sub}}\right)$$

## Calibration

The formula was validated against published empirical measurements:
- ASI294MC Pro, f/7, 150 mm aperture, pixel = 4.63 µm, QE ≈ 75%, Bortle 5 (SQM 20.3)
- Expected sky background from real data: ~0.83 e⁻/px/s
- Formula result: ~1.0 e⁻/px/s - within the measurement uncertainty

## Limitations

- **QE is assumed flat** across the spectral range. In practice, QE varies with wavelength. The formula uses V-band sky flux (matching the SQM meter passband), which gives the best absolute accuracy for broadband RGB imaging.
- **Narrowband filters** require different treatment: the sky background is much lower (fewer e⁻/px/s) through Ha/OIII/SII filters, so sub-exposures can and should be much longer. The calculator is primarily intended for broadband (L/RGB/OSC) imaging.
- **Dark current** is not included. For cooled cameras (−10 °C or colder), dark current is negligible. For uncooled or mildly cooled cameras add dark current to `B_sky` if known.
- **Atmospheric extinction**, light pollution gradients, and vignetting are not modelled.
