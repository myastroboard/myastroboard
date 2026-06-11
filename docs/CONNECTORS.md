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
| **Base URL** | Root URL of the external service (e.g. `http://allsky.local`) |
| **Enable connector** | Toggle to activate this connector and expose it in Observatory |
| **Modules** | Per-feature toggles — each module can be independently enabled |

Configuration is stored in `config.json → connectors.<name>`.

### Health check

The health-check button (heart icon) runs a live reachability probe against each enabled module URL and reports per-module status badges (✓ / ✗) with a detail message (200 OK, 404 + hint, timeout, etc.).

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

### Proxy

All resource URLs are served through the MyAstroBoard backend at `/api/connectors/allsky/proxy?module=<slug>`. The browser never contacts the AllSky instance directly — this avoids mixed-content issues and works correctly behind a reverse proxy with HTTPS.

---

## Adding a new connector

1. Create a class in `backend/connectors/` that extends `BaseConnector`
2. Implement the three abstract methods: `health_check()`, `get_module_urls()`, `fetch_sensor_data()`
3. Register it in `backend/connectors/__init__.py`

The connector appears automatically in the Parameters → Connectors UI.

Want to suggest a connector? [Open a discussion](https://github.com/myastroboard/myastroboard/discussions/new?category=ideas&labels=enhancement,connector).
