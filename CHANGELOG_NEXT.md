#### MQTT publisher & Home Assistant integration (v1.6)

- New **MQTT / Home Assistant** connector under Parameters -> Connectors. Point it at the MQTT
  broker your Home Assistant already uses and MyAstroBoard shows up there by itself, no YAML:
  a *MyAstroBoard* device plus one device per observing location with the sky period, the
  night score, sun and moon times, the dark window, tonight's best window and top target, the
  current weather-for-astro numbers (clouds, wind, dew risk, seeing, transparency), and -
  optionally - the next event, next ISS / CSS pass, aurora activity and next eclipses. Publish
  only: nothing is read back from the broker. Full guide: [docs/HOME_ASSISTANT.md](docs/HOME_ASSISTANT.md).
- **Your own activity, on your own terms.** Astrodex counters, tonight's plan (state, progress,
  current and next target, the equipment on it), observation log totals and your latest Astrodex
  picture as an image entity are published as a device in *your* name - but only after you
  switch *Publish my activity to Home Assistant* on under Parameters -> Customize. An admin
  enables the connector; nobody can publish another user's data.
- Six modules to pick from (sky conditions, weather, events, user activity, latest picture,
  diagnostics), a **test** button that really connects to the broker and says why it could not,
  a live status line, **Publish now**, and **Remove from Home Assistant** which deletes every
  MyAstroBoard device from Home Assistant in one click. TLS (`mqtts://`) and self-signed brokers
  are supported. Ready-made dashboard cards are coming as a separate HACS repository.
- Connector credentials (the MQTT password, the MyAstroShine token and signing secret) are now
  stored **outside `config.json`** and are **no longer part of backups or the config export**.
  Existing installs are migrated automatically. After restoring a backup on another machine,
  re-enter the connector credentials once - the same rule the push notification keys already
  follow.

#### Connector cards

- Connector settings can now be numbers and advanced checkboxes, the test button sends the
  credentials as typed (never the stored ones to another address), and a failed test shows the
  reason (refused, timeout, not authorized...) instead of a bare *Unreachable*.
