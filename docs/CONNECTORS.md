# Connectors

Connectors integrate external astronomy tools into MyAstroBoard. Once configured and enabled, a connector's data appears in the app tabs it declares — AllSky feeds the **Observatory** tab, MyAstroShine feeds the **Astrodex**, and a connector may feed no tab at all: the MQTT / Home Assistant connector publishes MyAstroBoard's own state *outward* and is standalone.

---

## Architecture

Connectors are Python classes that extend `BaseConnector` (`backend/connectors/base_connector.py`) and are registered in `backend/connectors/__init__.py`. Each connector exposes one or more **modules** — discrete features that can be independently enabled or disabled.

The registry is discovered at runtime and served via `GET /api/connectors`.

### File layout

One module per connector on each side, named after it:

| | Shared | AllSky | MyAstroShine | MQTT / Home Assistant |
|---|---|---|---|---|
| Connector | `connectors/base_connector.py` | `connectors/allsky_connector.py` | `connectors/myastroshine_connector.py` | `connectors/mqtt_connector.py` (+ `mqtt_publisher.py`, `mqtt_payloads.py`) |
| Blueprint | `blueprints/connectors.py` | `blueprints/connectors_allsky.py` | `blueprints/connectors_myastroshine.py` | `blueprints/connectors_mqtt.py` |
| Tests | `tests/blueprints/test_connectors.py` | `tests/blueprints/test_connectors_allsky.py` | `tests/blueprints/test_connectors_myastroshine.py` | `tests/blueprints/test_connectors_mqtt.py`, `tests/connectors/test_mqtt_*.py` |

Credentials of every connector (`SECRET_FIELDS`) live in `utils/connector_secrets.py`'s sidecar,
not in `config.json` - see [Secrets](#secrets).

`blueprints/connectors.py` serves the two routes every connector shares — the listing and the
config save; a connector's own routes go in its own blueprint module, registered in
`backend/app.py`.

### Declaring a connector

Beyond `name` / `label` / `description` / `min_version` / `homepage`, a connector says what it
needs through class attributes, so the shared listing, save route and card can handle it without
special-casing:

| Attribute | Purpose |
|---|---|
| `MODULES` | Independently-toggleable features. Empty is valid — the card then shows no Modules section |
| `target_modules` | App tabs the data lands in (see above). Empty = standalone |
| `CONFIG_FIELDS` | Settable config keys beyond `label` / `url` / `enabled` / `modules`, as `{key: default}`. `POST /api/connectors/<name>/config` accepts these and nothing else, coercing each value to the type of its default (`str`, `bool` or `int`) |
| `SECRET_FIELDS` | Keys holding credentials. Stored in the secrets sidecar, masked by `GET /api/connectors`; a blank or still-masked submission means "keep the stored value" |
| `URL_FIELDS` | Keys among `CONFIG_FIELDS` holding a URL, so the save strips their trailing slash |

A connector's own tuning knobs (cache TTLs, size caps, rate limits) are class attributes too,
not entries in `utils/constants.py` — adding a connector should not mean editing a shared file.

`is_configured()` says what "installed" means (a base URL by default; MyAstroShine also requires
its credentials). Only `health_check()` must be implemented — `get_module_urls()` and
`fetch_sensor_data()` default to empty, for a connector that serves no browser-fetched resource
and no live readings.

### Secrets

Credentials never reach the browser. `GET /api/connectors` is readable by any signed-in user, so
it replaces every `SECRET_FIELDS` value with `****` + the last 4 characters and adds a
`has_<field>` boolean; the card shows the masked form as an input placeholder and submits the
field blank unless the admin types a new value. The merge happens server-side in
`POST /api/connectors/<name>/config` (admin only), so a value the browser was never given cannot
be echoed back and overwrite the real one.

Credentials never sit in `config.json` either (v1.6). They live in
`data/connectors_secrets.json`, written by `utils/connector_secrets.py` (atomic, owner-only
permissions) and deliberately absent from the backup ZIP and the config export - the same rule
`secret_key.txt` and `vapid.json` already follow. Consequences:

- a backup restored on a fresh host needs each connector's credentials re-entered once;
- a connector is always constructed from `merge_secrets(name, config_block, cls.SECRET_FIELDS)`,
  the config block overlaid with the sidecar (`blueprints/connectors.py`,
  `observation/myastroshine_integration.get_integration_config`, `connectors/mqtt_publisher.py`);
- an install upgraded from an earlier version is migrated at startup and on the first save:
  values still found in `config.json` move to the sidecar and are stripped from the config.

### Target modules

A connector also declares `target_modules` — the list of app tabs where its data shows up:

```python
class AllSkyConnector(BaseConnector):
    target_modules = ["observatory"]
```

Slugs match the navbar tab keys (`observatory`, `astrodex`, `weather`, `skytonight`, …) so the UI can reuse the existing translations; `static/js/connectors/connectors.js` maps them in `_TARGET_MODULE_I18N_KEYS`. The connector card renders one translated badge per slug under the description.

The list is purely declarative — nothing is routed or wired from it. An **empty list is a valid, meaningful value**: it means the connector is self-contained and adds nothing to an existing tab (the MQTT / Home Assistant publisher), and the card then shows a single *Standalone* badge.

---

## Configuration

**Sub-tab**: Parameters → Connectors

Each connector card shows its current status badge (Enabled / Installed / Not installed) and a Configure button to expand the settings panel.

| Field | Description |
|-------|-------------|
| **Display label** | Custom name shown in the Observatory tab header |
| **Base URL** | Root URL of the external service (e.g. `http://192.168.1.42`) |
| **Enable connector** | Toggle to activate this connector and expose it in its target tabs |
| **Modules** | Per-feature toggles — each module can be independently enabled |

Under the description each card shows an **Appears in** row: one badge per app tab the connector feeds, or a *Standalone* badge when it feeds none.

Configuration is stored in `config.json → connectors.<name>`, written by
`POST /api/connectors/<name>/config`.

### Base URL — use a static IP address

> **Always configure the base URL with the device's static IP address** (e.g. `http://192.168.1.42`), not its mDNS hostname (e.g. `http://allsky.local`).

mDNS (`.local`) hostnames are resolved by the operating system's multicast DNS resolver. Inside a Docker container this resolver is not available, causing intermittent `Network is unreachable` errors as the container attempts to connect over IPv6 or fails to resolve the name at all. The URL field shows a warning when a `.local` address is detected.

Your router's DHCP settings or your device's documentation will show its current IP. Assign a static lease to that device so the IP never changes.

### Health check

The **test button** (wifi icon, next to the URL field) immediately probes the URL you have typed — no save required — and shows Reachable / Unreachable. Use it to verify the IP address and port before saving.

The **health-check button** (heart icon, after saving) runs a full per-module probe and reports status badges (✓ / ✗) with a detail message (200 OK, 404 + hint, timeout, etc.) for each enabled module.

The test button also sends the connector's other fields as typed, so a connector that needs
credentials to answer (MQTT) can probe with them before anything is saved. A connector that
runs something in the background can declare a `statusEndpoint` and `actions` in
`_CONNECTOR_UI` (`static/js/connectors/connectors.js`): the card then shows a live status line
and action buttons under the save row.

---

## AllSky connector

[AllSky](https://github.com/AllskyTeam/allsky) is an open-source all-sky camera system. It serves data entirely through file serving (no REST API).

**Minimum version**: v2024.12

**Appears in**: Observatory

### Modules

| Slug | Label | Default | Description |
|------|-------|---------|-------------|
| `live_image` | Live image | Enabled | Auto-refreshing live sky image (30 s interval) |
| `sensor_data` | Sensor data | Disabled | Temperature, humidity, gain, exposure, brightness — requires the AllSky Export overlay module added to Day & Night pipelines |
| `keogram` | Keogram | Enabled | Daily keogram timeline strip (generated end-of-night) |
| `startrails` | Startrails | Disabled | Stacked startrails image (generated end-of-night) |
| `daily_timelapse` | Daily timelapse | Disabled | Full-night timelapse video (generated end-of-night) |

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
| 2 | Startrails | Daily timelapse |
| 3 | Keogram (full width) | |

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

## MyAstroShine integration

MyAstroShine is a `BaseConnector` like AllSky — in the `REGISTRY`, listed by
`GET /api/connectors`, saved through `POST /api/connectors/myastroshine/config`, and rendered by
the same card. What is specific to it is declared, not special-cased:

```python
class MyAstroShineConnector(BaseConnector):
    min_version = "v0.4.0"
    target_modules = ["astrodex"]
    MODULES = []                                     # the round-trip is the whole connector
    SECRET_FIELDS = ("token", "signing_secret")
    URL_FIELDS = ("callback_url_override",)
    CONFIG_FIELDS = {"token": "", "signing_secret": "", "callback_url_override": "", "copy_rating": False}
```

**Appears in**: Astrodex — not the Observatory, so it has no Observatory panel.

`is_configured()` requires the two credentials on top of the URL: a URL alone signs no handoff,
so the card reports *Not installed* until all three are set. `health_check()` probes
`<url>/api/health`; MyAstroShine is LAN-only, so an unreachable result is expected and normal
when the board runs on another network, and the card says so rather than showing a plain error.

Its own routes — the handoff and the two cookieless endpoints the MyAstroShine container calls
back on — stay in `blueprints/connectors_myastroshine.py` under `/api/astrodex/integration/*`.
Full documentation: [MYASTROSHINE.md](MYASTROSHINE.md).

## MQTT / Home Assistant connector

Publishes MyAstroBoard's state to an MQTT broker with Home Assistant MQTT Discovery: one
Home Assistant device for the board, one per location preset (sky conditions, weather, events)
and one per **opted-in** user (Astrodex counters, tonight's plan and equipment, observation log
totals, latest picture). Publish-only. Full documentation, entity tables and topic reference:
[HOME_ASSISTANT.md](HOME_ASSISTANT.md).

**Minimum version**: Home Assistant 2024.11 (device-based discovery)

**Appears in**: nowhere in MyAstroBoard - *Standalone* (its output is Home Assistant)

```python
class MqttConnector(BaseConnector):
    target_modules = []
    SECRET_FIELDS = ("password",)
    CONFIG_FIELDS = {"username": "", "password": "", "base_topic": "myastroboard", "discovery_enabled": True,
                     "discovery_prefix": "homeassistant", "publish_interval_seconds": 60, "client_id": "",
                     "tls_insecure": False}
```

The shared `url` field carries the broker as `mqtt://host:1883` or `mqtts://host:8883`;
`is_configured()` only needs that URL (anonymous brokers exist). `health_check()` is one real
MQTT connect.

### Modules

| Slug | Label | Default | Description |
|------|-------|---------|-------------|
| `sky_conditions` | Sky conditions | Enabled | Sky period, night score, sun and moon times, dark window, best window, top target |
| `weather_now` | Weather now | Enabled | Current weather for astrophotography: clouds, wind, dew risk, seeing, transparency |
| `upcoming_events` | Upcoming events | Disabled | Next event, next ISS / CSS pass, aurora activity, next eclipses |
| `user_activity` | User activity | Disabled | Astrodex counters, tonight's plan and its equipment, observation log totals - per opted-in user |
| `astrodex_image` | Latest Astrodex picture | Disabled | The newest Astrodex picture as an image entity - per opted-in user |
| `board_diagnostics` | Board diagnostics | Enabled | Version, update available, cache and SkyTonight scheduler state, last publish |

### Advanced settings

| Field | Default | Description |
|-------|---------|-------------|
| `base_topic` | `myastroboard` | Root of every published topic |
| `discovery_prefix` | `homeassistant` | Home Assistant's discovery prefix |
| `publish_interval_seconds` | `60` | Publish cycle (minimum 15 s); states go out only when changed |
| `client_id` | generated | MQTT client id, generated once when blank |
| `tls_insecure` | `false` | Accept a self-signed broker certificate (`mqtts://` only) |

### How it runs

`connectors/mqtt_publisher.py` is a background thread started from `app.py` like the push
scheduler (lock file under `data/cache/`, one worker owns it). It idles until the connector is
enabled, then keeps a paho-mqtt client connected (last will = `offline` on `<base>/status`) and
runs a publish cycle every interval: `connectors/mqtt_payloads.py` builds the devices, discovery
and state messages are published only when they changed, and topics that are no longer wanted
(module off, user opted out, location deleted) receive an empty retained payload so Home
Assistant drops them. A trigger file carries the card's *Publish now* / *Remove from Home
Assistant* actions to the owning worker; a status file carries the publisher's state back to
`GET /api/connectors/mqtt/status`.

The three MQTT modules reach feature packages only through lazy imports: `connectors/` is
imported at module level by `cache/` and `observation/`, so a module-level import back would be
a circular import (a test guards this).

### Troubleshooting

See [HOME_ASSISTANT.md - Troubleshooting](HOME_ASSISTANT.md#troubleshooting).

## Astrodex Stream connector

A personal, auto-refreshing photo slideshow of a user's Astrodex pictures, rendered as a single
"current frame" JPEG that any still-image camera viewer (Home Assistant's **Generic Camera**
integration, a plain `<img>` tag, ...) can poll. Deliberately **not** a real video stream (no
RTSP, no pushed MJPEG) - see [ASTRODEX_STREAM.md](ASTRODEX_STREAM.md#why-not-a-real-video-stream)
for the feasibility reasoning. The frame is a pure function of wall-clock time, so there is no
background thread and nothing to start or stop when the connector is enabled or disabled. No
crossfade between photos: a client polling mid-transition would receive - and keep statically
displaying, until its own next poll - one half-blended frame, which would look broken rather
than smooth. Which photo is "current" instead shuffles pseudo-randomly (seeded by the feed and
the time slot, so every viewer polling at the same moment agrees without any shared state) and
never repeats the same photo twice in a row.

**Appears in**: Astrodex - not the Observatory, so it has no Observatory panel.

```python
class AstrodexStreamConnector(BaseConnector):
    target_modules = ["astrodex"]
    MODULES = []                                      # the slideshow is the whole connector
    SECRET_FIELDS = ()                                 # nothing admin-entered - see below
    CONFIG_FIELDS = {"display_seconds": 20, "aspect_ratio": "16:9"}
    ENUM_FIELDS = {"aspect_ratio": ("16:9", "9:16", "4:3", "3:4", "1:1")}
```

`ENUM_FIELDS` is a `BaseConnector` attribute (added for this connector, reusable by any future
one): the shared `POST /api/connectors/<name>/config` handler keeps a submitted value only when
it is one of the declared choices, falling back to the field's `CONFIG_FIELDS` default otherwise;
`GET /api/connectors` exposes the allowed values as `enum_fields` so the card can build a
`<select>` from them instead of hardcoding the choices a second time. `is_configured()` always
returns `True` - there is no external URL or credential, nothing to "install".

**Per-user signing key**: rather than storing a secret per user, a stream URL embeds an
HMAC-SHA256 token of the user id, keyed by a signing secret generated once on first use
(`connectors_secrets.json`, never entered by an admin - same idea as the auto-generated VAPID
keys). Verifying a request just recomputes the token. Rotating the secret (the card's **Rotate
keys** action, `POST /api/connectors/astrodex_stream/rotate`) invalidates every URL at once - the
only revocation mechanism.

Its own routes live in `blueprints/astrodex_stream.py` under `/api/astrodex/stream/*`. Full
documentation: [ASTRODEX_STREAM.md](ASTRODEX_STREAM.md).

## Adding a new connector

1. Create a class in `backend/connectors/<name>_connector.py` that extends `BaseConnector`
2. Implement `health_check()`; override `get_module_urls()` / `fetch_sensor_data()` only if the
   connector actually serves browser-fetched resources or live readings
3. Declare `target_modules`, and `MODULES` / `CONFIG_FIELDS` / `SECRET_FIELDS` / `URL_FIELDS` as
   needed (see [Declaring a connector](#declaring-a-connector))
4. Register it in `backend/connectors/__init__.py`
5. Add its routes, if any, in `backend/blueprints/connectors_<name>.py` and register the
   blueprint in `backend/app.py`
6. Add `connectors.<name>_label` / `connectors.<name>_desc` to all six `static/i18n/*.json`, and
   an entry in `_CONNECTOR_UI` (`static/js/connectors/connectors.js`) for its icon and any
   config inputs beyond the common ones (text, password, url or number inputs, checkboxes,
   an optional status line and action buttons)

The connector appears automatically in the Parameters → Connectors UI.

Want to suggest a connector? [Open a discussion](https://github.com/myastroboard/myastroboard/discussions/new?category=ideas&labels=enhancement,connector).
