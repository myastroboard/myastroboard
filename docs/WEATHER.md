# Weather & Conditions

The Weather tab provides atmospheric conditions specifically analysed for astronomical observation and astrophotography. It combines two independent data sources: **Open-Meteo** for standard meteorological data and **7Timer** for seeing and transparency forecasts.

---

## Tab layout

| Sub-tab | Content |
|---------|---------|
| **Weather** | Hourly weather forecast (temperature, humidity, wind, clouds, precipitation) |
| **Seeing** | 7Timer astronomical seeing and transparency forecast |
| **Trend** | Multi-hour time-series charts of astrophotography-specific conditions |
| **Alerts** | Active weather alerts and dew-point warnings |

---

## Open-Meteo weather forecast

**Source**: [Open-Meteo](https://open-meteo.com/) — free, no API key required.

**Cache TTL**: 1 hour (`WEATHER_CACHE_TTL` in `utils/constants.py`).

**Module**: `backend/weather/weather_openmeteo.py`

### Variables fetched

| Variable | Use |
|----------|-----|
| `temperature_2m` | Temperature at 2 m (°C / °F) |
| `relative_humidity_2m` | Relative humidity (%) |
| `dew_point_2m` | Dew point — distance from ambient drives fog/dew warning |
| `precipitation_probability` | Rain/snow probability (%) |
| `cloud_cover` | Total cloud cover (%) |
| `cloud_cover_low` | Low-altitude clouds (0–3 km) |
| `cloud_cover_mid` | Mid-altitude clouds (3–8 km) |
| `cloud_cover_high` | High-altitude clouds (cirrus, 8+ km) |
| `wind_speed_10m` | Surface wind speed |
| `wind_direction_10m` | Surface wind direction |
| `surface_pressure` | Atmospheric pressure (hPa) |
| `visibility` | Horizontal visibility (km) |
| `wind_speed_80m`, `120m` | Upper-atmosphere wind for jet-stream analysis |

### Cloud layer discrimination

The three cloud-cover layers help astrophotographers distinguish:
- **Low clouds** (fog, stratus) — completely block imaging.
- **Mid clouds** (altocumulus) — usually opaque, block imaging.
- **High clouds** (cirrus) — thin and sometimes transparent; imaging may still be possible.

Total cloud cover is shown as the primary go/no-go indicator.

### Rate-limiting behaviour

Open-Meteo free tier allows a limited number of concurrent requests. `weather/weather_openmeteo.py` implements two protections:

| Guard | Behaviour |
|-------|-----------|
| Single-flight lock | Only one concurrent call is made for the hourly forecast |
| Global concurrency cooldown | If a "Too many concurrent requests" error is received, **all** Open-Meteo callers back off for 90 seconds (`_GLOBAL_CONCURRENCY_COOLDOWN`) |

When rate-limited, the API returns the **last successful response** (stale-while-error) to avoid empty screens.

---

## Astro weather analysis

**Module**: `backend/weather/weather_astro.py`

**Class**: `AstroWeatherAnalyzer`

This module transforms raw Open-Meteo variables into astrophotography-specific metrics. It calculates conditions for up to 48 hours and caches results for 30 minutes.

### Seeing estimate (Pickering scale)

The seeing estimate is derived from wind speed at multiple altitudes and atmospheric stability proxies available from Open-Meteo:

| Pickering | Quality | Conditions |
|-----------|---------|------------|
| 1–3 | Poor | Strong winds, turbulent atmosphere |
| 4–5 | Fair | Moderate conditions |
| 6–7 | Good | Suitable for deep-sky imaging |
| 8–9 | Very good | Suitable for planetary imaging |
| 10 | Perfect | Exceptional stability |

> **Note**: This is a *model-derived* estimate. For high-resolution planetary imaging, cross-check with the 7Timer seeing forecast below.

### Transparency (limiting magnitude)

Transparency is estimated from cloud cover, humidity, and visibility:

$$m_\text{lim} = m_{\text{lim,zenith}} - \Delta(\text{cloud},\, \text{humidity},\, \text{visibility})$$

| mag/arcsec² | Sky quality |
|-------------|-------------|
| ≥ 7.5 | Excellent dark sky |
| 6.5 – 7.4 | Good |
| 5.5 – 6.4 | Average suburban |
| ≤ 5.0 | Light-polluted / cloudy |

### Dew point warning

When the difference between ambient temperature and dew point is ≤ 2 °C (`DEW_POINT_WARNING_THRESHOLD`), a dew alert is raised. Dew on optics ends a session; plan dew heaters accordingly.

### Jet stream impact

Wind speed at 80 m and 120 m altitude is used as a proxy for jet-stream influence. High upper-atmosphere winds correlate with poor seeing even when the surface is calm.

### Best astro period

`AstroWeatherAnalyzer` identifies the **best consecutive window** within the forecast where:
- Cloud cover is low
- Humidity is acceptable
- Wind is calm
- Dew margin is safe

This "best period" badge is displayed in the Trend sub-tab.

---

## 7Timer seeing forecast

**Source**: [7Timer ASTRO product](https://www.7timer.info/)

**Cache TTL**: 6 hours (`CACHE_TTL_SEEING_FORECAST`). On a fetch failure, the cache is left
untouched (previous good forecast keeps being served) instead of being overwritten with a
failure marker - a transient 7Timer outage no longer blanks the tab for the full TTL window,
since the next 5-minute scheduler tick retries once the existing entry's TTL naturally elapses.

**Module**: `backend/astroweather/seeing_forecast_7timer.py`

**Class**: `SeeingForecastService`

7Timer's ASTRO product returns eight fields per 3-hourly timepoint: `seeing`, `transparency`,
`cloudcover`, `lifted_index`, `rh2m` (humidity), `wind10m` (direction + speed class), `temp2m`
and `prec_type`. All of them are decoded and surfaced - not just seeing - and combined into a
single composite `quality_score` (0-10) per timeslot.

### Seeing scale (7Timer)

| Value | Label | FWHM | Notes |
|-------|-------|------|-------|
| 1 | Excellent | < 0.5 arcsec | Perfect for planetary imaging |
| 2 | Very Good | 0.5 – 0.75 arcsec | Excellent planetary detail |
| 3 | Good | 0.75 – 1 arcsec | Very good for planetary imaging |
| 4 | Moderate | 1 – 1.25 arcsec | Fair for planetary imaging |
| 5 | Fair | 1.25 – 1.5 arcsec | Usable with reduced fine detail |
| 6 | Poor | 1.5 – 2 arcsec | Poor conditions |
| 7 | Very Poor | 2 – 2.5 arcsec | Unsuitable for high-res imaging |
| 8 | Bad | > 2.5 arcsec | Unsuitable for planetary imaging |

### Transparency scale (7Timer)

7Timer's transparency field uses the same 1–8 shape as seeing (1 = worst, 8 = best), expressed
as limiting magnitude per air mass:

| Value | Label | Mag per air mass |
|-------|-------|-------------------|
| 1 | Very Poor | < 0.3 |
| 2 | Poor | 0.3 – 0.4 |
| 3 | Below Average | 0.4 – 0.5 |
| 4 | Average | 0.5 – 0.6 |
| 5 | Above Average | 0.6 – 0.7 |
| 6 | Good | 0.7 – 0.85 |
| 7 | Very Good | 0.85 – 1 |
| 8 | Excellent | > 1 |

### Cloud cover scale (7Timer)

1–9 scale, 1 = clearest (0–6% cover), 9 = fully overcast (94–100% cover).

### Wind speed scale (7Timer, 10m)

1–8 scale from calm (< 0.3 m/s) to hurricane (> 32.6 m/s), paired with a compass direction.

### Composite quality score

Each forecast point's `quality_score` (0-10, higher is better) combines four of the raw 7Timer
fields:

| Component | Weight | Why |
|-----------|--------|-----|
| Seeing | 35% | 7Timer's own astronomy-specific model output (not a proxy) |
| Transparency | 30% | Same - 7Timer's own model output |
| Cloud cover | 25% | Strongest remaining go/no-go signal |
| Wind speed | 10% | Tracking-stability proxy |

Active precipitation (`prec_type` != `none`) is a hard multiplicative veto (score × 0.1) rather
than an averaged component, the same convention used by `weather_astro.py`'s
`precipitation_factor`: rain or snow shouldn't be masked by otherwise-clear metrics.
`lifted_index` is decoded and exposed but not scored, since 7Timer's `seeing` value already
folds atmospheric stability into its own model.

The Seeing sub-tab renders this as an hourly timeline in the same visual style as the Trend
sub-tab's "Tonight's Score" (`night-score-timeline`): one card per timeslot with the combined
score, a quality badge, and an icon row for every underlying metric (seeing, transparency,
cloud cover, wind, humidity, precipitation).

### Best windows

Two "best window" cards are computed from the forecast:

- **Best Seeing Window** - longest consecutive run with `seeing` ≤ 3 (Good or better),
  unchanged from the original seeing-only definition - still the relevant metric for planetary
  imagers.
- **Best Overall Window** - longest consecutive run with `quality_score` ≥ 6 (Good or better),
  reflecting the full picture (seeing + transparency + clouds + wind).

---

## Weather alerts

**Module**: `backend/weather/weather_astro.py` (alert generation)

Alerts are generated from the Open-Meteo data and include:

| Alert | Trigger condition |
|-------|-----------------|
| High cloud cover | Cloud cover > 50 % during the observing window |
| Dew risk | Dew point within 2 °C of ambient temperature |
| Strong wind | Wind speed > 30 km/h |
| High humidity | Relative humidity > 85 % |
| Rain risk | Precipitation probability > 30 % |

Alerts are translated using the i18n system and displayed in the **Alerts** sub-tab.

---

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/weather/forecast` | Full hourly weather forecast from Open-Meteo |
| `GET` | `/api/weather/astro-analysis` | Astrophotography metrics (seeing, transparency, best period) |
| `GET` | `/api/weather/astro-current` | Current-hour astrophotography conditions snapshot |
| `GET` | `/api/weather/alerts` | Active weather alerts list |
| `GET` | `/api/seeing-forecast` | 7Timer seeing and transparency time-series |

---

## Data sources

- **Open-Meteo**: [open-meteo.com](https://open-meteo.com/) — free, open-source weather API; no account required.
- **7Timer**: [7timer.info](https://www.7timer.info/) — free astronomical weather service based on GFS model data; no account required.
