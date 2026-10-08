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

Credentials of every connector (`SECRET_FIELDS`) live in `utils/connector_secrets.py`'s store,
not in the configuration - see [Secrets](#secrets). A connector that talks MQTT does not declare a
broker of its own: it picks a shared connection - see [MQTT connections](#mqtt-connections).

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
| `CONNECTION_FIELD` | Config key holding the id of the shared MQTT connection the connector uses (`""` = none). See [MQTT connections](#mqtt-connections) |

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

Credentials never sit in the configuration either (v1.6). They live in a separate database
setting (`connectors_secrets`), written by `utils/connector_secrets.py` in one transaction, and
deliberately absent from the backup ZIP and the config export - the same rule the session secret
key and the VAPID keys already follow. Consequences:

- a backup restored on a fresh host needs each connector's credentials re-entered once;
- a connector is always constructed from `merge_secrets(name, config_block, cls.SECRET_FIELDS)`,
  the config block overlaid with the stored secrets (`blueprints/connectors.py`,
  `observation/myastroshine_integration.get_integration_config`, `connectors/mqtt_publisher.py`);
- an install upgraded from an earlier version is migrated at startup and on the first save:
  values still found in the configuration move to the secrets store and are stripped from it.

### MQTT connections

A broker is declared once, as a connection (`utils/mqtt_connections.py`, managed in
Parameters -> Configuration through `blueprints/mqtt_connections.py`), and shared by every
connector that talks MQTT - the Home Assistant publisher and the AllSky sensor reader today, a
Home Assistant sensor reader tomorrow - on the same broker or on separate ones.

- A connection is `{id, name, url, username, tls_insecure}` in `config["mqtt_connections"]`; its
  password is in the secrets store under `mqtt_connection:<id>`; API answers only carry a fixed
  `********` mask (no tail, unlike `SECRET_FIELDS` tokens).
- A connector declares `CONNECTION_FIELD` (`mqtt_connection_id` for both). Callers build it as
  `cls(block, connection=connection_for(cls, block, config))`: the connection
  (`{id, name, url, username, tls_insecure}`) is kept apart from the block, so a connector keeps its
  own `url` next to the broker (AllSky: its web interface). The password is fetched with
  `connection_password(id)` and passed explicitly, never held by the connector.
- A connector that **reads** topics lists them in `mqtt_subscriptions()`;
  `connectors/mqtt_subscriber.py` (one background thread, like the publisher) keeps one client per
  connector and stores its last message, read back with `mqtt_subscriber.read_last_message(name)`.
- The card shows a connection picker (`connectionField` in `_CONNECTOR_UI`): in place of the URL
  field (`connectionReplacesUrl`, Home Assistant), or inside one module (`connectionModule`, AllSky's
  `sensor_data`). `GET /api/connectors` lists the connections' names as `connection_options`.
- `BaseConnector.validate_config(block)` lets a connector refuse a save the typed coercion cannot
  catch (AllSky: a topic with a wildcard).
- The shared save refuses an unknown connection id, and refuses a `client_id` already used by
  another connector on the same connection: each connector opens its own client, and a broker
  disconnects a client when another one connects with the same id. A blank client id is generated
  per connector, so it never conflicts.
- A connection picked by a connector cannot be deleted (409 with `used_by`).
- Up to 1.7.1 the MQTT connector held its own `url` / `username` / `tls_insecure` / password.
  `repo_config` turns such a block into the fixed-id connection `home-assistant` on every read
  (old backups included), and `app.py` moves its password once at startup.

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

Configuration is stored in the configuration under `connectors.<name>`, written by
`POST /api/connectors/<name>/config`.

### Base URL — use a static IP address

> **Always configure the base URL with the device's static IP address** (e.g. `http://192.168.1.42`), not its mDNS hostname (e.g. `http://allsky.local`).

mDNS (`.local`) hostnames are resolved by the operating system's multicast DNS resolver. Inside a Docker container this resolver is not available, causing intermittent `Network is unreachable` errors as the container attempts to connect over IPv6 or fails to resolve the name at all. The URL field shows a warning when a `.local` address is detected.

Your router's DHCP settings or your device's documentation will show its current IP. Assign a static lease to that device so the IP never changes.

### Health check

The **test button** (wifi icon, next to the URL field) immediately probes the URL you have typed — no save required — and shows Reachable / Unreachable. Use it to verify the IP address and port before saving.

The **health-check button** (heart icon, after saving) runs a full per-module probe and reports status badges (✓ / ✗) with a detail message (200 OK, 404 + hint, timeout, etc.) for each enabled module.

A module that needs setup on the remote side can declare `moduleSetup` in `_CONNECTOR_UI`: the card
then shows a collapsible list of steps under that module, each optionally with a value to copy.

The test button also sends the connector's other fields as typed, so a connector that needs
credentials to answer can probe with them before anything is saved; on a connector with a
connection picker it probes the picked connection. A connector that
runs something in the background can declare a `statusEndpoint` and `actions` in
`_CONNECTOR_UI` (`static/js/connectors/connectors.js`): the card then shows a live status line
and action buttons under the save row.

---

## AllSky connector

[AllSky](https://github.com/AllskyTeam/allsky) is an open-source all-sky camera system. Its images
are files served by its web server; its sensor data is published over MQTT by its *Publish Data*
module.

**Minimum version**: v2024.12 (v2026.10 supported too)

**Appears in**: Observatory

### AllSky versions

Both versions work without reconfiguring:

| | v2024.12 | v2026.10 onwards |
|---|---|---|
| Live image URL | `/current/tmp/image.jpg` | `/current/image.jpg` (`/current/` now serves `tmp/current_images`) |
| Publish Data module | *AllSKY Redis/MQTT/REST Data Publish* | *Publish Data to Redis/MQTT/REST/influxDB* |
| Publish Data TLS | none (`mqtt://` only) | *Use SSL* switch, on by default |
| Environment sensor | one sensor per module (Dew Heater, Fans) | one shared sensor (`AS_TEMP`, `AS_HUMIDITY`, `AS_DEW`) |

- **Layout detection**: when `image_path` is `current` or `current/tmp`, the other one is tried too.
  The first that answers is remembered for 5 minutes (per worker), and the health check always probes again.
  A custom `image_path` is used as-is.
- **Variable names**: Publish Data sends the variables under their `AS_` names in both versions.
  A prefix-less key (`TEMPERATURE_C`) is still also exposed under its `AS_` name, and
  `AS_DAY_OR_NIGHT` as `DAY_OR_NIGHT`.

### Modules

| Slug | Label | Default | Description |
|------|-------|---------|-------------|
| `live_image` | Live image | Enabled | Auto-refreshing live sky image (30 s interval) |
| `sensor_data` | Sensor data | Disabled | Temperature, humidity, gain, exposure, brightness - received over MQTT from AllSky's Publish Data module |
| `keogram` | Keogram | Enabled | Daily keogram timeline strip (generated end-of-night) |
| `startrails` | Startrails | Disabled | Stacked startrails image (generated end-of-night) |
| `daily_timelapse` | Daily timelapse | Disabled | Full-night timelapse video (generated end-of-night) |

### Settings

| Field | Default | Description |
|-------|---------|-------------|
| `url` | - | AllSky's web interface (images) |
| `mqtt_connection_id` | - | The shared [MQTT connection](#mqtt-connections) the sensor data arrives on - the same broker as Home Assistant or another one |
| `mqtt_topic` | `allsky` | *MQTT Topic* of the Publish Data module; an exact topic (no `+` / `#`) |
| `image_path` (advanced) | `current` | Path to the live image directory, relative to the base URL (`current/tmp` before AllSky v2026.10 - both are detected automatically) |
| `image_filename` (advanced) | `image.jpg` | Filename of the live image |
| `client_id` (advanced) | generated | `myastroboard-allsky-<hex>` when blank; must differ from the other connectors on the same connection |

### Sensor data module

The `sensor_data` module listens over MQTT to AllSky's **Publish Data to Redis/MQTT/REST/influxDB**
module (`allsky_publishdata`, named *AllSKY Redis/MQTT/REST Data Publish* in v2024.12 - an extra
module, installed from the Module Manager). It replaces the *Export Allsky Data* file earlier
releases downloaded, which needed a web-served file location and broke with AllSky v2026.

The connector card shows these steps under the *Sensor data* module (*How to set it up in AllSky*),
with a copy button for each value:

1. Install the module and add it to the **Day and Night pipelines**: it then publishes at every
   image, with that image's data (exposure, gain, brightness, day / night).
   - AllSky v2024.12 needs the pipelines: its *Periodic jobs* run only sees the environment
     (`variables.sh`, the Dew Heater / Fans extra files), not the image variables
     (`DAY_OR_NIGHT`, `AS_GAIN`...), which only exist while an image is processed.
   - AllSky v2026 can also run it in the *Periodic jobs* list (about once a minute, with the last
     image's data): the choice when daytime capture is off, since no daytime image means no
     daytime message.
2. **MQTT** tab: *Publish to MQTT* on; *MQTT Host* and its port, *Username*, *Password*: the broker
   of the MQTT connection chosen on the card. *Enable HA Discovery* is optional (it adds AllSky's own
   sensors to Home Assistant).
3. AllSky v2026: turn **off** *Use SSL* (*Secure Connection*) for a broker on `mqtt://` (port 1883).
   v2024.12 has no TLS: its broker must accept `mqtt://`.
4. **MQTT Topic**: the card's `mqtt_topic` (`allsky` by default).
5. **General** tab, *Extra data to export*: the variables to send - only listed variables are
   published (the default list is empty and sends only a `utc` timestamp). Only what the sensor
   card shows; a variable an install does not have is left out of the message.

   - **v2026**: ticked in the list of the *...* button (nothing can be pasted there), grouped as in
     that list. *Environment* is the shared sensor, so the Dew Heater / Fan temperatures and
     humidity are not needed:

     | Group | Variables |
     |---|---|
     | Image Data | `AS_DAY_OR_NIGHT`, `AS_EXPOSURE_US`, `AS_GAIN`, `AS_MEAN`, `AS_TEMPERATURE_C` |
     | Environment | `AS_TEMP`, `AS_HUMIDITY`, `AS_DEW` |
     | Dew Heater (if installed) | `AS_DEWCONTROLHEATER` |
     | Fan (if installed) | `AS_FANS_FAN_STATE1`, `AS_FANS_TEMP_LIMIT1`, `AS_FANS_PWM_DUTY_PERCENT1` |

   - **v2024.12**: a typed field - paste (no shared sensor; the day/night flag and the version are
     unprefixed, the Fans module publishes `OTH_*`):
     `DAY_OR_NIGHT,ALLSKY_VERSION,AS_TEMPERATURE_C,AS_GAIN,AS_EXPOSURE_US,AS_MEAN,AS_DEWCONTROLAMBIENT,AS_DEWCONTROLHUMIDITY,AS_DEWCONTROLDEW,AS_DEWCONTROLHEATER,OTH_FANS,OTH_TEMPERATURE,OTH_FANT`
6. *Save*, then *Test Module* (*Day* or *Night* is only the context of the test): a first message
   goes out right away and the card's health check turns green.

The message stays under 15 minutes old as long as the module runs: at every image (or every
Periodic jobs run). With daytime capture off and the module in the pipelines only, the card shows no
readings during the day.

How the board receives it: `connectors/mqtt_subscriber.py` (one background thread, one client per
connector, own client id) keeps the **last message** in `data/cache/mqtt_last_allsky.json`, which
`GET /api/connectors/allsky/status` reads. AllSky's messages are not retained by the broker, so
after a board restart the card waits for the next image (or Periodic jobs run). A message older than 15 minutes
(`MQTT_STALE_AFTER_SECONDS`) is no longer shown. Messages larger than 64 KB, or that are not a flat
JSON object, are ignored.

When sensor data is available the Observatory tab shows:

| Field | AllSky variable |
|-------|-----------------|
| Dome temperature | `AS_TEMP` (the environment sensor, AllSky v2026), else `AS_DEWCONTROLAMBIENT` (Dew Heater), else the first fan's `AS_FANS_TEMPERATURE1` (v2024: `OTH_TEMPERATURE`) |
| Camera sensor temperature (hidden when AllSky sends its `0` placeholder) | `AS_TEMPERATURE_C` |
| Humidity | `AS_HUMIDITY`, else `AS_DEWCONTROLHUMIDITY` |
| Dew point | `AS_DEW`, else `AS_DEWCONTROLDEW` |
| Dew heater | `AS_DEWCONTROLHEATER` |
| Gain | `AS_GAIN` |
| Exposure | `AS_EXPOSURE_US`, formatted as µs / ms / s |
| Brightness | `AS_MEAN` |
| Fan (state, PWM duty %, threshold) | `AS_FANS_FAN_STATE1` / `2`, `AS_FANS_PWM_DUTY_PERCENT1` / `2`, `AS_FANS_TEMP_LIMIT1` / `2` (v2024: `OTH_FANS`, `OTH_FANT`) |
| Fan control temperature, only when it is not already the dome temperature (same variable or same reading) | `AS_FANS_TEMPERATURE1` / `2` |
| AllSky version (v2024.12 only: v2026 cannot publish it) | `ALLSKY_VERSION` |
| Updated (when the board received the readings) | the message receive time |

AllSky v2026 declares **one** environment sensor (*Environment* group: `AS_TEMP`, `AS_HUMIDITY`,
`AS_DEW`, `AS_TEMPSENSOR`) that the Dew Heater and Fans modules reuse, so their readings repeat it:
it is read first, so each quantity shows once. v2024 has a sensor per module, read as the fallback.

The **Day / Night badge** on the live image card is populated from `AS_DAY_OR_NIGHT`. It is hidden
when sensor data is disabled or when the variable is not in the list.

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
| Day/Night badge not shown | `sensor_data` module disabled, or `AS_DAY_OR_NIGHT` not in the Publish Data list | Enable `sensor_data`; add `AS_DAY_OR_NIGHT` to *Extra data to export* |
| Keogram / startrails show *Not yet generated* | End-of-night processing not run yet | Normal during the night; images appear after AllSky finishes its end-of-night run |
| Daily timelapse shows empty video player | No timelapse generated yet | Normal; the placeholder appears automatically once AllSky produces the file |
| *No reading received from AllSky yet* | No message on the topic: Publish Data not in the Day / Night pipelines, *Publish to MQTT* off, another broker or topic, or *Use SSL* on against a `mqtt://` broker | Follow the card's steps, then *Test Module*; the health check says whether any message arrived and whether the board is connected to the broker |
| Sensor card nearly empty | *Extra data to export* empty or short (only `utc` is sent by default) | Paste the list from the card (see [Sensor data module](#sensor-data-module)) |
| Readings stop updating after 15 min | AllSky stopped publishing (Pi off, no image - daytime capture off -, module removed from the pipelines) | The card hides readings older than 15 minutes; check AllSky, or (v2026) also add the module to the Periodic jobs |
| Live image stopped loading after upgrading AllSky | Live image moved from `current/tmp/` to `current/` | Detected automatically; run the health check to refresh the detection immediately |

---

## MyAstroShine integration

MyAstroShine is a `BaseConnector` like AllSky — in the `REGISTRY`, listed by
`GET /api/connectors`, saved through `POST /api/connectors/myastroshine/config`, and rendered by
the same card. What is specific to it is declared, not special-cased:

```python
class MyAstroShineConnector(BaseConnector):
    min_version = "v0.4.0"
    target_modules = ["astrodex"]
    MODULES = []  # the round-trip is the whole connector
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
    CONNECTION_FIELD = "mqtt_connection_id"
    CONFIG_FIELDS = {
        "mqtt_connection_id": "",
        "base_topic": "myastroboard",
        "discovery_enabled": True,
        "discovery_prefix": "homeassistant",
        "publish_interval_seconds": 60,
        "client_id": "",
    }
```

The broker (`mqtt://host:1883` or `mqtts://host:8883`), its credentials and the self-signed
certificate switch come from the picked [MQTT connection](#mqtt-connections);
`is_configured()` only needs that connection's URL (anonymous brokers exist). `health_check()` is
one real MQTT connect.

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
| `client_id` | generated | MQTT client id, generated once when blank; must differ from other connectors on the same connection |

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
    MODULES = []  # the slideshow is the whole connector
    SECRET_FIELDS = ()  # nothing admin-entered - see below
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
(connector secrets store, never entered by an admin - same idea as the auto-generated VAPID
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
