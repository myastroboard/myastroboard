# Home Assistant integration (MQTT publisher)

MyAstroBoard can publish its state to an MQTT broker, with **Home Assistant MQTT Discovery**:
enable the connector, point it at the broker Home Assistant already uses, and a "MyAstroBoard"
device appears in Home Assistant together with one device per location - sky period, night
score, sun and moon times, tonight's best window and top target, current weather-for-astro,
upcoming events - and, for users who opted in, one device per user with their Astrodex counters,
tonight's plan and its equipment, observation log totals and the latest Astrodex picture.

It is **publish-only**: MyAstroBoard never reads commands from the broker. The only thing it
subscribes to is Home Assistant's own birth message, so entities come back by themselves after a
Home Assistant restart.

Ready-made Lovelace cards live in a separate repository:
[lovelace-myastroboard-card](https://github.com/myastroboard/lovelace-myastroboard-card).

---

## Requirements

| | |
|---|---|
| MQTT broker | Any MQTT 3.1.1 broker: the Home Assistant **Mosquitto** add-on, a standalone Mosquitto, EMQX... reachable from the MyAstroBoard container |
| Home Assistant | **2024.11 or newer** (device-based MQTT discovery) with the [MQTT integration](https://www.home-assistant.io/integrations/mqtt/) configured and discovery enabled (the default) |
| MyAstroBoard | 1.6.0 or newer, an admin account |

---

## Setup

1. **Broker.** Create a user for MyAstroBoard on the broker (Mosquitto add-on: Settings ->
   Add-ons -> Mosquitto -> Configuration, or a Home Assistant user - the add-on accepts those).
   Note the broker's IP address and port (1883, or 8883 for TLS).
2. **MyAstroBoard.** Parameters -> Connectors -> **MQTT / Home Assistant** -> Configure:
   - *Broker URL*: `mqtt://192.168.1.10:1883` (or `mqtts://host:8883` for TLS). Use the IP
     address rather than a `.local` name - mDNS does not resolve inside the container.
   - *Username* / *Password*: the broker user. Leave both blank for an anonymous broker.
   - Press the **test** button (wifi icon): it opens one real connection to the broker with the
     credentials as typed and reports *Reachable* or the reason it is not (refused, timeout, not
     authorized, TLS...).
   - Tick the modules you want (see [Modules](#modules)), switch **Enable connector** on, **Save**.
3. **Home Assistant.** Settings -> Devices & services -> MQTT: within a minute a **MyAstroBoard**
   device and one **MyAstroBoard - <location>** device per location preset appear. The card's
   status line shows *Connected*, the last publish time and the number of devices and entities.

Nothing has to be added to `configuration.yaml`.

### Per-user activity

Location and board data are install-level and published as soon as the connector is on. A
**user's** data (Astrodex, plan, observation log, pictures) is private, so it is published only
when that user asks for it: Parameters -> Customize -> *Publish my activity to Home Assistant
(MQTT)*. The switch only shows once an admin has enabled the connector, and it only ever covers
the user's own data - an admin cannot publish another user's activity. The admin-side
*User activity* and *Latest Astrodex picture* modules must be on as well.

---

## Modules

| Module | Default | Device | What it publishes |
|---|---|---|---|
| Sky conditions | on | per location | sky period, night score, sun and moon times, dark window, best window, top target, SkyTonight night window |
| Weather now | on | per location | current weather for astrophotography: temperature, humidity, dew point, clouds by layer, wind, precipitation, pressure, visibility, plus seeing, transparency, limiting magnitude, dew risk, tracking impact, weather alert |
| Upcoming events | off | per location | next event, next ISS / CSS pass, aurora Kp and probability, next solar / lunar eclipse |
| User activity | off | per opted-in user | Astrodex counters, plan state and progress, current and next target, active equipment, observation log totals |
| Latest Astrodex picture | off | per opted-in user | the newest Astrodex picture as an `image` entity |
| Board diagnostics | on | board | version, update entity, cache readiness, SkyTonight scheduler state, last publish, published counts |

Every location the cache scheduler keeps warm gets a device (in practice every preset). Disable
the entities you do not need from the device page in Home Assistant.

### Settings

| Field | Default | Notes |
|---|---|---|
| Broker URL | - | `mqtt://host[:1883]` or `mqtts://host[:8883]` |
| Username / Password | blank | The password is stored in `data/connectors_secrets.json`, **outside** `config.json`, and is never part of a backup or config export: re-enter it after restoring a backup on another machine |
| Home Assistant MQTT Discovery | on | Off = only the plain state topics are published (for another consumer than Home Assistant) |
| Base topic (advanced) | `myastroboard` | Root of every topic; two boards on one broker use two base topics |
| Discovery prefix (advanced) | `homeassistant` | Must match the MQTT integration's discovery prefix |
| Publish interval (advanced) | 60 s | Minimum 15 s. States are only sent when they changed; everything is resent every 30 min and whenever Home Assistant restarts |
| Client ID (advanced) | generated | `myastroboard-<8 hex>`, generated once and reused across restarts |
| Accept self-signed certificates (advanced) | off | `mqtts://` only - skips certificate verification for a LAN broker with its own CA |

### Buttons

- **Publish now** - full republish of discovery and every state on the next tick (a few seconds).
- **Remove from Home Assistant** - switches the connector off and deletes every retained
  MyAstroBoard topic from the broker; Home Assistant drops the devices (their history is lost).
  Broker settings and modules are kept, so enabling the connector again recreates everything.
  Simply switching the connector off, by contrast, leaves the devices in place as *unavailable*.
  See [Long-term statistics](#long-term-statistics) for the one thing a removal leaves behind.

### Long-term statistics

Home Assistant records long-term statistics for every sensor that declares a `state_class`,
and keeps them after the entity disappears. Only the six counters that track **your own
progress** declare one (`state_class: total`): Astrodex objects, objects with pictures,
pictures, constellations, observation sessions and total integration - the numbers a
*Statistics graph* card can show growing month after month. Everything else (sky, Moon, best
window, weather, aurora, plan progress) is an ephemeris or a forecast that MyAstroBoard
recomputes at any time, so it deliberately records **no** long-term statistics; the recorder's
short-term history (10 days by default) still draws them in a history graph.

After *Remove from Home Assistant* (or a user opting out), those six series per user stay in
the recorder as orphans. Home Assistant lists them under Developer tools -> Statistics with a
*Fix issue* action that deletes them; Spook reports the same list. Nothing else is left behind.

---

## Topics

`<base>` is the base topic (`myastroboard` by default), `<prefix>` the discovery prefix.

| Topic | Payload | Retained |
|---|---|---|
| `<base>/status` | `online` / `offline` (last will) - the availability of every entity | yes |
| `<base>/board/state` | JSON, board diagnostics | yes |
| `<base>/location/<location_id>/state` | JSON, one object with every enabled location module's keys | yes |
| `<base>/user/<user_id>/state` | JSON, user activity keys | yes |
| `<base>/user/<user_id>/astrodex/latest_image` | raw JPEG (max 1280 px, max 1 MB) | yes |
| `<prefix>/device/<base>_board/config` | device discovery message | yes |
| `<prefix>/device/<base>_loc_<location_id>/config` | device discovery message | yes |
| `<prefix>/device/<base>_user_<user_id>/config` | device discovery message | yes |

Every timestamp is ISO 8601 with a UTC offset; an unknown value is JSON `null` (the entity
shows *unknown*). A location device carries `location_id`, `location_name` and `timezone`
next to the entity keys; a user device carries `user_id` and `username`.

The MQTT integration's own `homeassistant/status` topic is the connector's only subscription:
`online` triggers a full republish.

---

## Entities

Home Assistant builds each entity id from the **device name and the entity name** (never from
the JSON key): the *Top target tonight* sensor of the "MyAstroBoard - Backyard" device is
`sensor.myastroboard_backyard_top_target_tonight`, the *Astronomical night* binary sensor is
`binary_sensor.myastroboard_backyard_astronomical_night`, the picture is
`image.myastroboard_alice_latest_astrodex_picture`. `unique_id` is
`<base>_loc_<location_id>_<key>`, so renaming a preset later keeps the entity history. The
tables below are generated from `backend/connectors/mqtt_payloads.py`.

### Board device (Board diagnostics)

| Key | Entity name | Kind | Notes |
|---|---|---|---|
| `version` | Version | sensor | diagnostic |
| `update` | Update | update | diagnostic - installed/latest version, links to the changelog; no Install button (no remote self-update) |
| `caches_ready` | Caches ready | binary sensor | diagnostic |
| `skytonight_running` | SkyTonight calculating | binary sensor (running) | diagnostic |
| `skytonight_last_run` | SkyTonight last run | sensor (timestamp) | diagnostic |
| `skytonight_next_run` | SkyTonight next run | sensor (timestamp) | diagnostic |
| `last_publish` | Last publish | sensor (timestamp) | updated every publish cycle - a heartbeat; diagnostic |
| `locations_published` | Locations published | sensor | diagnostic |
| `users_published` | Users published | sensor | diagnostic |

### Location device - Sky conditions

| Key | Entity name | Kind | Notes |
|---|---|---|---|
| `sky_period` | Sky period | sensor (enum) | `day`, `civil_twilight`, `nautical_twilight`, `astronomical_twilight`, `astronomical_night`, `unknown` |
| `next_period` | Next sky period | sensor (enum) |  |
| `next_period_at` | Next sky period at | sensor (timestamp) |  |
| `is_astronomical_night` | Astronomical night | binary sensor |  |
| `observation_score` | Observation score | sensor | the app-wide **night score** (same value as the sky widget) |
| `sunrise` | Sunrise | sensor (timestamp) |  |
| `sunset` | Sunset | sensor (timestamp) |  |
| `civil_dusk` | Civil dusk | sensor (timestamp) |  |
| `civil_dawn` | Civil dawn | sensor (timestamp) |  |
| `nautical_dusk` | Nautical dusk | sensor (timestamp) |  |
| `nautical_dawn` | Nautical dawn | sensor (timestamp) |  |
| `astronomical_dusk` | Astronomical dusk | sensor (timestamp) |  |
| `astronomical_dawn` | Astronomical dawn | sensor (timestamp) |  |
| `true_night_hours` | True night duration | sensor (duration, h) |  |
| `moon_phase` | Moon phase | sensor |  |
| `moon_illumination` | Moon illumination | sensor (%) |  |
| `moon_altitude` | Moon altitude | sensor (°) |  |
| `moon_azimuth` | Moon azimuth | sensor (°) |  |
| `moon_distance` | Moon distance | sensor (distance, km) |  |
| `next_moonrise` | Next moonrise | sensor (timestamp) |  |
| `next_moonset` | Next moonset | sensor (timestamp) |  |
| `next_full_moon` | Next full moon | sensor (timestamp) |  |
| `next_new_moon` | Next new moon | sensor (timestamp) |  |
| `dark_window_start` | Dark window start | sensor (timestamp) | next moonless astronomical night |
| `dark_window_end` | Dark window end | sensor (timestamp) |  |
| `best_window_start` | Best window start | sensor (timestamp) | the *practical* best window |
| `best_window_end` | Best window end | sensor (timestamp) |  |
| `best_window_duration` | Best window duration | sensor (duration, h) |  |
| `best_window_score` | Best window score | sensor |  |
| `best_window_moon` | Best window moon condition | sensor |  |
| `top_target` | Top target tonight | sensor | attributes: type, constellation, magnitude, max altitude, observable hours, `top_targets` (top 5) |
| `top_target_score` | Top target AstroScore | sensor |  |
| `night_start` | SkyTonight night start | sensor (timestamp) |  |
| `night_end` | SkyTonight night end | sensor (timestamp) |  |
| `skytonight_calculated_at` | SkyTonight calculated at | sensor (timestamp) | diagnostic |

### Location device - Weather now

Nearest hourly forecast row plus the astro analysis.

| Key | Entity name | Kind | Notes |
|---|---|---|---|
| `temperature` | Temperature | sensor (temperature, °C) |  |
| `dew_point` | Dew point | sensor (temperature, °C) |  |
| `humidity` | Humidity | sensor (humidity, %) |  |
| `cloud_cover` | Cloud cover | sensor (%) |  |
| `cloud_cover_low` | Low clouds | sensor (%) |  |
| `cloud_cover_mid` | Mid clouds | sensor (%) |  |
| `cloud_cover_high` | High clouds | sensor (%) |  |
| `wind_speed` | Wind speed | sensor (wind_speed, km/h) |  |
| `wind_direction` | Wind direction | sensor (°) |  |
| `precipitation_probability` | Precipitation probability | sensor (%) |  |
| `precipitation` | Precipitation | sensor (precipitation, mm) |  |
| `pressure` | Pressure | sensor (atmospheric_pressure, hPa) |  |
| `visibility` | Visibility | sensor (distance, m) |  |
| `weather_code` | Weather code | sensor | WMO weather code |
| `seeing` | Seeing | sensor | Pickering scale |
| `transparency` | Transparency | sensor |  |
| `limiting_magnitude` | Limiting magnitude | sensor |  |
| `dew_risk` | Dew risk | sensor (enum) | `LOW`, `MODERATE`, `HIGH`, `CRITICAL`, `UNKNOWN` |
| `dew_point_spread` | Dew point spread | sensor (temperature, °C) |  |
| `wind_tracking_impact` | Wind tracking impact | sensor (enum) | `NONE`, `LOW`, `MODERATE`, `HIGH`, `SEVERE`, `UNKNOWN` |
| `tracking_stability` | Tracking stability | sensor |  |
| `weather_alert` | Weather alert | sensor | first alert; attributes: all alerts |
| `forecast_updated_at` | Forecast updated at | sensor (timestamp) | diagnostic |

### Location device - Upcoming events

| Key | Entity name | Kind | Notes |
|---|---|---|---|
| `next_event` | Next event | sensor | same "next event" as the dashboard banner; attributes: event_type, description, start / peak / end, importance, events_count, plus the event's raw (untranslated) variable piece where applicable - `eclipse_type` (solar/lunar eclipses), `planet`/`planet2` (planetary conjunction/opposition/elongation/retrograde, moon conjunction), `shower_name` (meteor showers), `comet_name` (comet appearances); state and `description` are English-only by design (MQTT is a background publish loop with no session language to read) - clients that want a localized display should translate client-side off `event_type` and these attributes, the same way `top_target_attributes.object_type` already needs to be |
| `next_event_at` | Next event at | sensor (timestamp) |  |
| `next_iss_pass_at` | Next ISS pass | sensor (timestamp) |  |
| `next_iss_pass_peak_altitude` | Next ISS pass peak altitude | sensor (°) |  |
| `next_iss_pass_duration` | Next ISS pass duration | sensor (duration, min) |  |
| `next_iss_pass_score` | Next ISS pass visibility score | sensor |  |
| `next_css_pass_at` | Next CSS pass | sensor (timestamp) |  |
| `next_css_pass_peak_altitude` | Next CSS pass peak altitude | sensor (°) |  |
| `next_css_pass_duration` | Next CSS pass duration | sensor (duration, min) |  |
| `next_css_pass_score` | Next CSS pass visibility score | sensor |  |
| `aurora_kp` | Aurora Kp index | sensor |  |
| `aurora_probability` | Aurora probability | sensor (%) |  |
| `aurora_visibility` | Aurora visibility | sensor |  |
| `next_solar_eclipse_at` | Next solar eclipse | sensor (timestamp) | attributes: type, obscuration, start, end, visible |
| `next_lunar_eclipse_at` | Next lunar eclipse | sensor (timestamp) | attributes: type, start, end, visible |

### User device - User activity

| Key | Entity name | Kind | Notes |
|---|---|---|---|
| `astrodex_objects` | Astrodex objects | sensor |  |
| `astrodex_objects_with_pictures` | Astrodex objects with pictures | sensor |  |
| `astrodex_pictures` | Astrodex pictures | sensor |  |
| `astrodex_constellations` | Astrodex constellations | sensor |  |
| `astrodex_last_picture_at` | Last Astrodex picture | sensor (timestamp) |  |
| `astrodex_last_picture_object` | Last Astrodex picture object | sensor | attributes: catalogue, type, constellation, date, equipment, rating |
| `plan_state` | Plan state | sensor (enum) | `none`, `current`, `previous` |
| `plan_active` | Plan in progress | binary sensor (running) | the plan's night is in progress |
| `plan_progress` | Plan progress | sensor (%) |  |
| `plan_current_target` | Plan current target | sensor | attributes: catalogue, type, planned minutes, slot start / end, visibility, meridian flip |
| `plan_next_target` | Plan next target | sensor |  |
| `plan_night_start` | Plan night start | sensor (timestamp) |  |
| `plan_night_end` | Plan night end | sensor (timestamp) |  |
| `plan_targets_total` | Plan targets | sensor |  |
| `plan_targets_done` | Plan targets done | sensor |  |
| `plan_location` | Plan location | sensor |  |
| `active_equipment` | Active equipment | sensor | the plan's combination; attributes: telescope, camera, guide camera, mount, filters, accessories, focal length, aperture, disabled |
| `sessions_total` | Observation sessions | sensor |  |
| `integration_hours_total` | Total integration | sensor (duration, h) | observation log |
| `last_session_date` | Last observation session | sensor (date) |  |

### User device - Latest Astrodex picture

| Key | Entity name | Kind | Notes |
|---|---|---|---|
| `latest_picture` | Latest Astrodex picture | image | raw JPEG resized to 1280 px / 1 MB max; attributes: object, catalogue, date, equipment, rating, picture id. Picture coordinates are never published |

---

## Automation ideas

```yaml
# Red observatory light at astronomical dusk
trigger:
  - platform: state
    entity_id: sensor.myastroboard_backyard_sky_period
    to: astronomical_night
action:
  - service: light.turn_on
    target: { entity_id: light.observatory }
    data: { rgb_color: [255, 0, 0], brightness: 40 }

# Tonight looks good
trigger:
  - platform: numeric_state
    entity_id: sensor.myastroboard_backyard_observation_score
    above: 7
condition:
  - condition: state
    entity_id: binary_sensor.myastroboard_backyard_astronomical_night
    state: "on"
action:
  - service: notify.mobile_app_phone
    data:
      message: "Night score {{ states('sensor.myastroboard_backyard_observation_score') }} - top target {{ states('sensor.myastroboard_backyard_top_target_tonight') }}"
```

---

## Privacy and security

- Outbound only. No command topic exists; nothing Home Assistant publishes is acted upon.
- The password lives in `data/connectors_secrets.json` (owner-only permissions), never in
  `config.json`, backups, the config export or any API response (the card only sees a mask).
- The card's test button never pairs the stored password with a URL that differs from the saved
  one, and the MQTT routes are admin-only.
- `mqtts://` gives TLS; *Accept self-signed certificates* is meant for a LAN broker with its own
  CA, nothing else.
- A user's data is published only while that user's own switch is on. Location devices carry the
  preset name and timezone, not its coordinates; pictures are published without location data.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Test says *connection refused* | wrong IP / port, or the broker only listens on localhost | use the LAN IP, check the broker's listener (`0.0.0.0:1883`) |
| Test says *not authorized* | wrong user / password, or the broker requires one | create a broker user, re-enter the password |
| Test says *TLS handshake failed* | self-signed certificate | `mqtts://` + *Accept self-signed certificates*, or use `mqtt://` on the LAN |
| Status shows *Connected* but no device in Home Assistant | discovery off, or the discovery prefix differs from the MQTT integration's | tick *Home Assistant MQTT Discovery*, align the prefix (`homeassistant` by default) |
| Devices are *unavailable* | the connector is off or the container is down | enable the connector / check the card's status line and `data/myastroboard.log` |
| No user device | the user has not opted in, or the *User activity* module is off | Parameters -> Customize -> *Publish my activity...*; module on |
| No picture entity | *Latest Astrodex picture* module off, no picture yet, or the picture exceeds 1 MB even at 640 px | see the log line; the entity appears after the next picture is added |
| Values show *unknown* | the cache behind them is not warm yet (fresh install, new location) | wait for the cache scheduler's next cycle |
| Two boards on one broker fight over devices | same base topic | give each board its own base topic |
| Stale devices after renaming the base topic | old retained topics | *Remove from Home Assistant* before renaming, or delete the topics with `mosquitto_sub`/your broker's tools |

Log lines are prefixed `MQTT publisher:` in `data/myastroboard.log`.

Tested against Home Assistant 2024.11+ discovery format; re-check the release notes of the Home
Assistant version you run if entities fail to appear.
