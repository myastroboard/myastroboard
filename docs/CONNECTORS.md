# Connectors

Connectors integrate external astronomy tools into MyAstroBoard. Once configured and enabled, a connector's data appears in the **Observatory** tab.

---

## Architecture

Connectors are Python classes that extend `BaseConnector` (`backend/connectors/base_connector.py`) and are registered in `backend/connectors/__init__.py`. Each connector exposes one or more **modules** — discrete features that can be independently enabled or disabled.

The registry is discovered at runtime and served via `GET /api/connectors`.

---

## Configuration

**Sub-tab**: Parameters → Connectors

Each connector card shows its current status badge (Enabled / Installed / Not installed) and a Configure button to expand the settings panel.

| Field | Description |
|-------|-------------|
| **Display label** | Custom name shown in the Observatory tab header |
| **Base URL** | Root URL of the external service (e.g. `http://192.168.1.42`) |
| **Enable connector** | Toggle to activate this connector and expose it in Observatory |
| **Modules** | Per-feature toggles — each module can be independently enabled |

Configuration is stored in `config.json → connectors.<name>`.

### Base URL — use a static IP address

> **Always configure the base URL with the device's static IP address** (e.g. `http://192.168.1.42`), not its mDNS hostname (e.g. `http://allsky.local`).

mDNS (`.local`) hostnames are resolved by the operating system's multicast DNS resolver. Inside a Docker container this resolver is not available, causing intermittent `Network is unreachable` errors as the container attempts to connect over IPv6 or fails to resolve the name at all. The URL field shows a warning when a `.local` address is detected.

Your router's DHCP settings or your device's documentation will show its current IP. Assign a static lease to that device so the IP never changes.

### Health check

The **test button** (wifi icon, next to the URL field) immediately probes the URL you have typed — no save required — and shows Reachable / Unreachable. Use it to verify the IP address and port before saving.

The **health-check button** (heart icon, after saving) runs a full per-module probe and reports status badges (✓ / ✗) with a detail message (200 OK, 404 + hint, timeout, etc.) for each enabled module.

---

## AllSky connector

[AllSky](https://github.com/thomasjacquin/allsky) is an open-source all-sky camera system. It serves data entirely through file serving (no REST API).

**Minimum version**: v2023.1

### Modules

| Slug | Label | Default | Description |
|------|-------|---------|-------------|
| `live_image` | Live image | Enabled | Auto-refreshing live sky image (30 s interval) |
| `sensor_data` | Sensor data | Disabled | Temperature, humidity, gain, exposure, brightness — requires the AllSky Export overlay module added to Day & Night pipelines |
| `keogram` | Keogram | Enabled | Daily keogram timeline strip (generated end-of-night) |
| `startrails` | Startrails | Disabled | Stacked startrails image (generated end-of-night) |
| `daily_timelapse` | Daily timelapse | Disabled | Full-night timelapse video (generated end-of-night) |
| `mini_timelapse` | Mini-timelapse | Disabled | Frequent short clip — requires AllSky mini-timelapse enabled (Number Of Images > 0) |

### Advanced settings

| Field | Default | Description |
|-------|---------|-------------|
| `image_path` | `current/tmp` | Path to the live image directory, relative to the base URL |
| `image_filename` | `image.jpg` | Filename of the live image |
| `export_json_path` | `allskydata.json` | Path to the AllSky Export JSON file, relative to `image_path` |

### Sensor data module

The `sensor_data` module reads a JSON file produced by the AllSky **Export** overlay module. This overlay must be added to **both the Day and Night pipelines** in AllSky settings, otherwise the file is never written.

When sensor data is available the Observatory tab shows:

| Field | AllSky variable |
|-------|-----------------|
| Temperature | `AS_TEMPERATURE_C` |
| Humidity | `AS_DEWCONTROLHUMIDITY` or `AS_HUMIDITY` |
| Dew point | `AS_DEWCONTROLDEW` |
| Dew heater | `AS_DEWCONTROLHEATER` |
| Gain | `AS_GAIN` |
| Exposure | `AS_sEXPOSURE` or `AS_EXPOSURE_US` |
| Brightness | `AS_MEAN` |
| AllSky version | `ALLSKY_VERSION` |

The **Day / Night badge** on the live image card is populated from the `DAY_OR_NIGHT` field in the same JSON. It is hidden when sensor data is disabled or when the field is absent from the exported data.

### Observatory display

When modules are enabled the Observatory tab renders the following layout:

| Row | Left | Right |
|-----|------|-------|
| 1 | Live image (auto-refreshes every 30 s) | Sensor data (polls every 60 s) — if enabled |
| 2 | Startrails | Keogram |
| 3 | Mini-timelapse | Daily timelapse |

Rows 2 and 3 only appear for their respective enabled modules. End-of-night images (keogram, startrails, daily timelapse) show a *Not yet generated* placeholder until AllSky produces them at the end of the night.

**Click any image** to open it fullscreen in a zoom modal. The live image modal continues to auto-refresh at the same 30-second interval while open.

A **last-updated timestamp** is shown below the live image and updates on each refresh cycle. It requires no extra modules.

### Proxy

All resource URLs are served through the MyAstroBoard backend at `/api/connectors/allsky/proxy?module=<slug>`. The browser never contacts the AllSky instance directly — this avoids mixed-content issues when MyAstroBoard is accessed remotely over HTTPS while AllSky runs on a local HTTP server.

### Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Images never load, proxy errors in logs | `.local` hostname used | Replace with static IP address |
| Images load locally but not remotely | Browser trying to reach AllSky directly | Ensure proxy is not disabled; check MyAstroBoard logs |
| Day/Night badge not shown | `sensor_data` module disabled, or Export overlay not in pipeline | Enable `sensor_data` and add Export module to AllSky pipelines |
| Keogram / startrails show *Not yet generated* | End-of-night processing not run yet | Normal during the night; images appear after AllSky finishes its end-of-night run |
| Daily timelapse shows empty video player | No timelapse generated yet | Normal; the placeholder appears automatically once AllSky produces the file |
| Sensor data unavailable | Export JSON not found or AllSky offline | Check AllSky Export module path matches `export_json_path` in advanced settings |

---

## Adding a new connector

1. Create a class in `backend/connectors/` that extends `BaseConnector`
2. Implement the three abstract methods: `health_check()`, `get_module_urls()`, `fetch_sensor_data()`
3. Register it in `backend/connectors/__init__.py`

The connector appears automatically in the Parameters → Connectors UI.

Want to suggest a connector? [Open a discussion](https://github.com/myastroboard/myastroboard/discussions/new?category=ideas&labels=enhancement,connector).
