#### Two-factor authentication & local/global accounts

- Optional **two-factor authentication (TOTP)** for any account, compatible with standard
  authenticator apps. Off by default: an admin enables it instance-wide under Parameters ->
  Users (requires at least one trusted network), then each user opts in individually from My
  Settings -> Security. Setup shows a QR code (rendered client-side, no server-side image
  dependency) plus the raw secret as a guaranteed fallback for the "authenticator app on the
  same phone" case. An admin can force-disable a user's 2FA if they lose their device.
- New **trusted networks** list (Parameters -> Users): CIDR blocks or IPs you consider safe.
  Signing in from a trusted network skips the 2FA prompt entirely. 127.0.0.1 and ::1 are always
  trusted and never need to be added, so clearing the list can't lock out local access.
- New **local vs. global account scope**: an account can be restricted to sign in only from a
  trusted network. Defaults to global (sign in from anywhere) for every existing and new
  account. With no trusted network configured, the restriction is inactive (a warning banner
  says so) rather than silently locking everyone out.
- `data/security_settings.json` (trusted networks + the 2FA switch) is host-specific and
  excluded from backups and config export, like `trust_proxy_headers`.

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

#### AstroDex Stream connector

- New **AstroDex Stream** connector under Parameters -> Connectors: a personal, auto-refreshing
  photo slideshow of your AstroDex pictures - paste the URL into Home Assistant's **Generic
  Camera** integration (or any still-image viewer) and it shows up as a live camera, cropped to
  the format you choose (16:9, 9:16, 4:3, 3:4, 1:1), with a discreet object-name-and-date banner.
  Configurable display duration; photos shuffle rather than repeating in a fixed order, and never
  the same one twice in a row.
- Every user gets their own signed URL - nobody can read another user's stream, even on a shared
  install (e.g. an astronomy club). A shared URL (every user's photos merged) is also available,
  but only when Astrodex is not set to private. An admin can rotate the signing key at any time
  to invalidate every URL handed out so far.
- Not a real video stream by design: no new Docker port and no extra native dependency beyond
  Pillow for the crop/banner rendering - see [docs/ASTRODEX_STREAM.md](docs/ASTRODEX_STREAM.md)
  for the full setup guide and the reasoning behind that choice.

#### Connector cards

- Connector settings can now be numbers and advanced checkboxes, the test button sends the
  credentials as typed (never the stored ones to another address), and a failed test shows the
  reason (refused, timeout, not authorized...) instead of a bare *Unreachable*.
