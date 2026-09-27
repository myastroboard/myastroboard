# Privacy & GDPR

This page is for people who **run** a MyAstroBoard instance. It lists what personal data the
application stores, where it goes, how long it stays, and which built-in features help you meet
the EU General Data Protection Regulation (GDPR). It ends with a privacy notice template you can
adapt for your users.

> [!IMPORTANT]
> This is a technical description, not legal advice. MyAstroBoard is self-hosted software: the
> project never receives any of your data. **Whoever operates an instance is the data controller**
> for it and remains responsible for its compliance.

---

## Who is responsible?

| Situation | GDPR status |
|---|---|
| You run MyAstroBoard for yourself and your household | Usually covered by the *household exemption* (Art. 2(2)(c)) - the GDPR does not apply. |
| An astronomy club, association or company runs it for its members | The GDPR applies. The organisation is the controller; this page and the template below are a starting point. |
| Someone else hosts it on your behalf | They are your processor; you need a processing agreement with them (Art. 28). |

The MyAstroBoard maintainers are neither controller nor processor: the software sends no telemetry
and has no analytics, tracking or advertising code.

---

## What personal data is stored

Everything lives in the `data/` directory (the Docker volume). Per-user files are named
`<user_id>_...`, where `user_id` is a random UUID.

| Data | Location in `data/` | Notes |
|---|---|---|
| Account: username, password hash, role, creation date, last login | `users.json` | Passwords are hashed (werkzeug); never stored in clear. |
| Two-factor secret (if enabled) | `users.json` | TOTP seed, needed to verify codes. |
| Preferences (language, time format, default/active location...) | `users.json` | |
| Web Push subscriptions | `users.json` | Browser push endpoint + keys, only if the user enabled notifications. |
| Observing locations: name, latitude, longitude, timezone | `config.json` | A location is often the user's home: treat coordinates as personal data. |
| Astrodex: observed objects, notes, pictures, optional picture coordinates | `astrodex/` | See [Photo metadata](#photo-metadata) below. |
| Observation log: sessions, notes, conditions, attachments | `observation_sessions/` | |
| Equipment profiles | `equipments/` | |
| Plan My Night plans | `projects/` | |
| Wishlist | `wishlist/` | |
| Application log | `myastroboard.log*` | Contains usernames and client IP addresses (sign-ins, refused access). See [Retention](#retention). |

The browser keeps only the session cookie and a few display settings in `localStorage`
(language, time format, a photo filter, the last seen app version). None of them is used for tracking.

### Photo metadata

Camera and phone pictures usually embed EXIF metadata: the GPS position where the picture was
taken (often the observer's garden), camera serial numbers, sometimes the owner's name. Because
Astrodex pictures and session attachments can be seen by other users of the instance, MyAstroBoard
**removes this metadata when a picture is uploaded** (JPEG, PNG, WebP):

- removed: EXIF (GPS, serial numbers, owner, dates), XMP, IPTC, comments, PNG text chunks, and
  secondary images some phones append to the file (HDR gain maps, depth maps);
- kept: the pixels, byte for byte - nothing is re-encoded, astrophotos keep their full quality -,
  the ICC colour profile and the orientation;
- GIF files are stored as sent (the format carries no EXIF/GPS).

Pictures uploaded before this protection existed still carry their original metadata. Non-image
attachments (PDF, Word, text) are stored as sent: remove author metadata before uploading them if
it matters.

The coordinates a user types **manually** on an Astrodex picture are different: they are
deliberate data used by the photo map. On a new installation the map is private: each user only sees
their own pictures. Installations created before this default keep sharing the map with every user
whose Astrodex is shared, until an administrator enables *Configuration -> Astrodex -> Photo map
private* (see [Astrodex](ASTRODEX.md)).

---

## Cookies

MyAstroBoard sets a single cookie: the Flask **session cookie**, which keeps the user signed in
(`HttpOnly`, `SameSite=Lax`, `Secure` when enabled in *Parameters -> Advanced*). It lasts until the
browser closes, or 30 days when *Remember me* is ticked. It is strictly necessary for the service,
so no consent banner is required (ePrivacy Directive, Art. 5(3)).

---

## Third parties

MyAstroBoard contacts external services to compute forecasts and display maps. None of them
receives account data, but some receive coordinates or the user's IP address.

| Service | What it receives | Sent by | Why |
|---|---|---|---|
| [Open-Meteo](https://open-meteo.com) (Switzerland/EU) | Coordinates of each location | Server | Weather forecast |
| [7Timer!](https://www.7timer.info) (China) | Coordinates of each location | Server | Seeing / transparency forecast |
| [Nominatim - OpenStreetMap](https://nominatim.openstreetmap.org) (EU) | Coordinates + the browser's IP | Browser | Naming a location, only when the user clicks *Use my location* |
| Esri ArcGIS map tiles (USA) | The browser's IP + the map area viewed | Browser | Background of the maps (locations, photo map) |
| Browser push services (Google FCM, Mozilla, Apple) | An opaque notification payload | Server | Web Push, only for users who enabled notifications |
| CelesTrak, The Space Devs, NOAA SWPC, JPL, Minor Planet Center, CDS Strasbourg, wheretheiss.at | Nothing personal | Server | Satellites, launches, space weather, ephemerides, object images |
| GitHub | Nothing personal | Server | Check for new releases |
| MyMemory | Public spaceflight texts only | Server | On-demand translation of launch descriptions |

Optional integrations send data only when an administrator enables them:

- **MQTT / Home Assistant** - to your own broker; a user's data is published only while that user's
  own switch is on, location devices carry no coordinates and pictures are sent without location
  data ([details](HOME_ASSISTANT.md#privacy-and-security)).
- **MyAstroShine** - the chosen picture is sent to the MyAstroShine instance configured by the
  administrator ([details](MYASTROSHINE.md)).
- **Astrodex Stream** - a signed URL that exposes one user's pictures to whoever holds it
  ([details](ASTRODEX_STREAM.md)).
- **AllSky** and other connectors - the application reads from them; it does not send user data.

Transfers outside the EU: 7Timer (China) receives location coordinates and Esri (USA) receives
the browser IP. Mention them in your privacy notice.

---

## Retention

| Data | Kept until |
|---|---|
| Account and all per-user files | The account is deleted (see below). |
| Locations | An administrator deletes them. |
| Application log | 90 days by default: older lines are removed once a day (*Parameters -> Advanced -> Privacy*, 0 to 3650 days; 0 keeps only the size limit of 10 MB x 6 files). |
| Backups downloaded from *Configuration* | Under your control, outside the application: they contain everything listed above. |

---

## Data subject rights

| Right | How to fulfil it today |
|---|---|
| Access (Art. 15) | *My Settings -> Security -> Your data* downloads a ZIP of everything stored about the user; an administrator can download the same archive for any user from *Parameters -> Users -> Export data*. |
| Rectification (Art. 16) | Users edit their own data; an administrator edits accounts and locations. |
| Erasure (Art. 17) | An administrator deletes the account in *Users*. This removes the account **and every per-user file**: Astrodex and pictures, observation sessions and attachments, equipment, plans and wishlist. Log lines mentioning the user remain until rotation. |
| Portability (Art. 20) | The same ZIP: account and preferences, locations, Astrodex, observation log, equipment, plans and wishlist as JSON, with pictures and attachments as the original files. Password hashes and two-factor secrets are left out. |
| Objection / restriction | Handled by the administrator (disable the account, remove a location). |

Accounts deleted **before** full erasure existed may have left files behind. To find them, compare
the `<user_id>` prefixes of the files in `data/` with the ids in `data/users.json`, and delete the
files whose id no longer exists.

---

## Security measures

- Password hashing, optional two-factor authentication (TOTP), and throttled sign-in: 5 failed
  passwords per username and address, or 20 per address, within 15 minutes
  ([details](AUTHENTICATION.md#security-notes)).
- Session cookie `HttpOnly`, `SameSite=Lax`, optional `Secure` flag; serve the instance over HTTPS
  behind a reverse proxy ([guide](6.REVERSE_PROXY.md)).
- Role-based access (admin / user / read-only) and *local-only* accounts restricted to trusted
  networks ([details](AUTHENTICATION.md)).
- Private by default towards search engines: `robots.txt` disallows crawling and the login page is
  `noindex` unless you opt in (*Parameters -> Advanced -> Privacy*).
- Connector secrets are stored apart from the configuration, with owner-only file permissions, and
  never appear in exports or API responses.
- All front-end libraries are served locally: no CDN, font or analytics request leaves the browser
  except the map tiles and geocoding listed above.

Protect the `data/` volume and your backups: they hold everything on this page.

---

## Privacy notice template

Adapt the bracketed parts and publish the notice where your users can read it (club website,
sign-up email...).

```text
Privacy notice - [Instance name]

Controller: [Club / association name], [address], contact: [email].

What we collect: your username, a hashed password, your preferences, the observing
locations you record (name and coordinates), and the content you add (Astrodex pictures
and notes, observation logs, equipment, plans, wishlist). Our server logs record your
username and IP address when you sign in, for security.

Why: to provide the MyAstroBoard service you signed up for (Art. 6(1)(b) GDPR) and to
keep it secure (legitimate interest, Art. 6(1)(f)).

Who can see it: administrators of this instance; other members only for what you share
(shared Astrodex, photo map). Pictures are stripped of their GPS metadata on upload.

Third parties: weather providers (Open-Meteo, 7Timer! - China) receive the coordinates
of the observing locations; map tiles (Esri - USA) and place names (OpenStreetMap) are
loaded by your browser. [Add enabled integrations: MQTT, MyAstroShine...]

Retention: your data is kept while your account exists and deleted with it. Server logs
are kept for [90] days.

You can download all your data at any time from My Settings -> Security -> Your data.

Your rights: access, rectification, erasure, portability, objection. Contact [email].
You may lodge a complaint with your data protection authority ([e.g. CNIL]).

Cookies: one session cookie, strictly necessary to keep you signed in.
```
