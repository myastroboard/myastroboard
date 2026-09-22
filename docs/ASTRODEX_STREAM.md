# AstroDex Stream connector

A personal, auto-refreshing photo slideshow of your AstroDex pictures - cropped to the format
you choose, with a discreet object-name-and-date banner - that shows up as a live camera in
**Home Assistant** (or any still-image viewer) without exposing your photos to anyone who
doesn't have your URL.

---

## Where to find it

- **Setup**: Parameters -> Connectors -> *AstroDex Stream* card
- **Your URL**: Astrodex -> the small <i class="bi bi-collection-play"></i> icon next to the
  page title, once the connector is enabled

---

## Why not a real video stream

The original idea was an RTSP stream. That does not fit this project's zero-manual-Docker-config
promise: RTSP needs a real media server (ffmpeg + something like MediaMTX) listening on a **new**
port, and Docker port mappings are fixed at container creation - nothing running inside the
container can publish a new port to the host afterwards, no matter how that server is started or
stopped. The only way to reconcile RTSP with "nothing to configure" would be to reserve that port
in the official `docker-compose.yml` for every install, whether the feature is used or not -
rejected as a permanent cost for an optional feature.

A continuously pushed MJPEG stream avoids the new-port problem (it can ride the existing HTTP
port), but the app runs `gunicorn` with **synchronous workers** and no thread pool: a long-lived
streaming connection would pin a worker for as long as it stays open, and two simultaneous
viewers (a browser tab plus one Home Assistant card is a very ordinary case) would starve the
whole app for everyone else.

So instead the server renders whichever photo is "current" as a **pure function of wall-clock
time**, and a client just polls the same URL periodically, exactly like AllSky's `live_image`
module already does for an external camera. No open connection, no new port, no background
thread, no ffmpeg. Home Assistant's built-in **Generic Camera** integration does exactly this
kind of polling natively - see [Using it in Home Assistant](#using-it-in-home-assistant).

**No crossfade between photos, on purpose.** A blended transition was considered and dropped: a
client that happens to poll mid-transition would receive one half-blended frame and then keep
displaying it, unchanged, until its own next poll - which can be much later than the transition
itself. The result would be a broken-looking static image sitting on the dashboard for a long
stretch, not a smooth fade. Every served frame is always one full, clean photo; only *which*
photo changes between slots (see [Shuffling](#shuffling) below).

---

## Setup

Parameters -> Connectors -> **AstroDex Stream** -> Configure:

| Field | Notes |
|---|---|
| **Display duration per photo** | Seconds each photo stays "current". Keep it generous (tens of seconds) - see the note below about Home Assistant's own refresh rate. |
| **Format** | Center-crop applied to every photo before it is served: `16:9` / `9:16` / `4:3` / `3:4` / `1:1`. |
| **Enable connector** | Turns the feature on for every user - there is nothing else to install (no URL, no credentials). |

There is nothing to type beyond these two fields: no URL, no username, no password. The
per-user signing key that protects each stream is generated automatically the first time it is
needed (see [Security](#security)).

### Shuffling

Photos are not shown in a fixed, repeating order. Which photo is "current" in a given slot is a
pseudo-random - but fully reproducible - function of the slot's position in time: every viewer
polling at the same moment sees the same photo, without the server keeping track of "where we
are" for anyone. The same photo never repeats twice back-to-back. There is nothing to configure
here; it is always on.

---

## Using the URLs

Astrodex -> the <i class="bi bi-collection-play"></i> icon next to the page title opens a modal
with:

- **Your personal stream URL** - always shown once the connector is enabled. Shows only your own
  photos. Treat it like a password: anyone who has the URL can view your stream, so it is not
  shown anywhere else in the interface.
- **The shared stream URL** - shown only when Astrodex is **not** set to private
  (Parameters -> Configuration). Shows every user's photos merged, GPS coordinates stripped, with
  an owner-name in the banner so a shared viewer (e.g. an astronomy club's screen) can tell whose
  photo is on display.

Both are plain JPEG URLs (`.../current.jpg`) - paste either into a browser tab to see it work
before wiring up Home Assistant.

---

## Using it in Home Assistant

No custom Lovelace card is needed - Home Assistant's built-in **Generic Camera** integration
already does this:

1. Settings -> Devices & services -> Add integration -> **Generic Camera**.
2. **Still Image URL**: paste the URL from the AstroDex modal, exactly as copied. The signing
   token is already embedded in it - **no username or password field to fill in**, unlike a
   typical camera setup.
3. Leave **Stream URL** empty - this connector does not serve RTSP (see
   [Why not a real video stream](#why-not-a-real-video-stream)).
4. Add the resulting camera entity to a dashboard (picture-entity, picture-glance, glance...).

Home Assistant - not this connector - decides how often it re-fetches the still image. Set
**Display duration per photo** generously (tens of seconds, not two or three) so a typical
refresh cadence reliably lands on each photo instead of mostly skipping between them.

---

## Security

- **One token per user, nothing stored per user.** A stream URL embeds
  `HMAC-SHA256(user_id, signing_secret)`. The signing secret is 32 random bytes generated once on
  first use and kept in `data/connectors_secrets.json` (excluded from backups, like the MQTT
  password and the MyAstroShine token) - never shown to or entered by an admin. Verifying a
  request just recomputes the token from the user id in the URL, so nothing is stored per user
  and a lost/rotated token needs no cleanup.
- **A club's members cannot read each other's streams.** The token is specific to one `user_id`;
  swapping the id in a URL without the matching token is rejected (`404`, not `403` - an invalid
  URL must not confirm that a given user id even exists).
- **The shared URL respects "private" live, not at mint time.** Whether `.../shared/...` serves
  anything is re-checked against Astrodex's private-mode setting on every request. Turning
  private mode on immediately 404s the shared URL for anyone who still has it - no key rotation
  needed for that case.
- **Rotating keys.** If a personal URL leaks, the card's **Rotate keys** action
  (`POST /api/connectors/astrodex_stream/rotate`) issues a new signing secret, which invalidates
  **every** stream URL at once (personal and shared) - there is no way to rotate a single user's
  key without affecting everyone, since nothing per-user is stored to make that possible. Anyone
  with a camera already configured (Home Assistant included) needs the new URL afterwards.
- **The token does not expire, by design** - it is meant to be pasted into Home Assistant once
  and keep working indefinitely, unlike MyAstroShine's 12-hour, single-use handoff token. That
  makes the URL a long-lived bearer secret: **treat it exactly like a password**, never paste it
  anywhere other than the camera integration's own field. This matters most for an install
  reachable from the internet (a reverse-proxied public domain, not just a LAN): the URL is not
  brute-forceable (128 bits of entropy in the token), but it *will* appear in plaintext in any
  access log along the request path - this app's own log, a reverse proxy's, or a CDN/WAF's in
  front of it, exactly like a Stripe checkout link or an AWS presigned URL would. If a URL is
  ever visible somewhere it shouldn't be (a shared log, a screen share, a pasted browser
  history), rotate keys.
- **No EXIF/GPS leak in the served image.** A photo's original file may carry embedded EXIF GPS
  coordinates (common for phone/camera photos) - the JSON-level `latitude`/`longitude` fields are
  already stripped for the shared/merged Astrodex view, and the same applies here: the rendering
  pipeline re-encodes every frame through Pillow without forwarding the source file's EXIF block,
  so the served JPEG carries no metadata beyond what the banner already shows on its face
  (object name, date, and - shared feed only - the owner's username).

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| The <i class="bi bi-collection-play"></i> icon does not appear on the Astrodex page | The connector is not enabled - Parameters -> Connectors -> AstroDex Stream. |
| The modal has no shared URL | Astrodex is set to private (Parameters -> Configuration) - the personal URL still works. |
| The image shows a dark placeholder instead of a photo | The user has no eligible pictures yet (own photos for the personal URL, any visible photo for the shared one). |
| Home Assistant's camera stopped updating after a "Rotate keys" | Expected - re-add the camera in Home Assistant with the new URL from the AstroDex modal. |
| Photos change less often than expected in Home Assistant | Home Assistant polls a still image on its own schedule; it is not pushed. Increase *Display duration per photo* rather than expecting frame-accurate sync. |
