# Demo mode

Demo mode turns a MyAstroBoard instance into a public, read-only showcase. A visitor opens the
address and lands straight in the application, signed in on a shared demo account. Everything is
live (tonight's sky, the weather, SkyTonight targets), but nothing a visitor does is saved.

It is meant for one public demo of the project, not for sharing your own observatory: use a
separate instance with its own data, never your personal one.

## What a visitor gets

- **No sign-in.** Opening `/` (or `/login`) signs the visitor in on the demo account. A banner at
  the top of the page says it is a demo and links to the installation guide.
- **Read-only.** Every request that would change stored data (`POST`, `PUT`, `PATCH`, `DELETE`)
  is refused with a `403` and the code `demo_read_only`; the page shows "Read-only demo: changes
  are not saved". The check runs on the server, before any route, so no button can get around it.
- **Calculations still work.** A few non-`GET` endpoints store nothing and stay open: the FOV
  calculator, coordinate conversion and the equipment recommendations for a target
  (`DEMO_ALLOWED_WRITE_ENDPOINTS` in `backend/utils/demo_mode.py`).
- **Own preferences.** Theme, language, density and other UI preferences are kept in the
  visitor's session cookie, not on the shared account, so one visitor never changes what the
  next one sees. Location, notification and MQTT preferences stay as you set them.
- **No notifications.** No visitor is ever asked for notification permission, the
  *Notifications* settings tab is hidden, and the push notification scheduler does not run.
- **No setup wizard**, no location switching, no on-demand translation (it would use your
  DeepL / LibreTranslate quota).

Only the demo account is restricted. Another account signed in on the same instance (yours,
preparing the data) works normally.

## Demo data that keeps living

An empty Astrodex shows nothing, so demo mode fills the demo account by itself and keeps it
moving (`backend/demo/demo_life.py`, a background check every 10 minutes):

- **Location.** A fresh install (no location set yet) gets the Observatoire de Haute-Provence
  (43.9308 N, 5.7133 E, 650 m): a public, well-known site. A location you set yourself is kept.
- **Seed, once**, when the demo account holds no equipment and no Astrodex item: two equipment
  combinations (a Seestar S50, and an 80 mm refractor with an ASI533MC), eight classic targets in
  the Astrodex with one picture each, and a wishlist.
- **Every night**, for each combination: the previous plan becomes an Observation Log session
  (frames and integration filled in), its best target joins the Astrodex with a picture, and a
  new Plan My Night is built from tonight's SkyTonight results - the best-scoring targets that fit
  the combination's field and are not captured yet - then ordered by the plan optimizer. The
  night changes when SkyTonight's morning run computes the next night.
- **Every check** (every 10 minutes): an Astrodex item still without its picture, because no
  survey server answered when it was added, gets another try (three items per check, stopping at
  the first failure). Constellations stored as IAU abbreviations by older versions are expanded to
  the full names the UI translates.
- **History window**: logged nights older than 60 days are deleted, with the Astrodex items they
  added and their pictures (the seed stays). However long the demo runs, it holds about 120
  Astrodex items and 40 MB of pictures at most.

**The pictures are not amateur photos.** Each is a DSS2 colour survey cut-out (CDS / STScI),
framed to the combination's field, and its notes say so. The acquisition figures (frames,
integration, rating) are illustrative values derived from the plan, and each logged session says
so in its notes.

A demo account you prepare by hand (its own equipment, under other names) is never touched: no
seed and no nightly plans. To get the generated data back, delete the demo account with demo mode
off; it is recreated, empty, at the next start in demo mode.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `DEMO_MODE` | off | `true` (or `1`, `yes`, `on`) turns demo mode on |
| `DEMO_USERNAME` | `demo` | The shared account visitors are signed in on. Created at startup or on first visit (role `user`, random password, wizard marked done) if it does not exist |

Both are environment variables on purpose: demo mode is a property of the deployment, and an
instance in demo mode has no admin on the public side to switch it off.

On a demo instance, two kinds of password sign-in are always refused:

- the demo account itself (it is only signed in automatically);
- any account still on the default password (`admin` / `admin`): on a public address, that would
  hand the instance to anyone who tries it.

The real sign-in form stays reachable at `/login?signin` for your own account.

## Installing a demo instance

### 1. Run a separate container

Give the demo its own data directory and port. Do not point it at your personal `data/`: it holds
your home location, your pictures and your accounts.

```yaml
services:
  myastroboard-demo:
    image: myastroboard/myastroboard:latest
    pull_policy: always
    container_name: myastroboard-demo
    ports:
      - "5050:5000"            # any free port; 5000 is your own instance
    volumes:
      - ./data-demo:/app/data
    environment:
      - TZ=UTC
      - DATA_DIR=/app/data
      - DEMO_MODE=false        # off for the first start only (step 2)
      # - DEMO_USERNAME=demo
    restart: unless-stopped
    privileged: false
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:5000/health || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
```

```bash
docker compose -f docker-compose-demo.yml up -d
```

### 2. Secure the admin account (demo mode off)

Open `http://<host>:5050` from your local network and:

1. **Sign in as `admin` / `admin` and change the password.** Demo mode refuses the default
   password, so without this step the admin account stays locked out once demo mode is on.
2. **Protect the admin account** (*Parameters -> Security*): add your local network as a trusted
   network, then set the admin account's scope to *local*. It can then only sign in from your
   network, never through the public address.
3. **Trust the proxy headers** (*Parameters -> Advanced -> Reverse proxy*) when the public address
   goes through a tunnel or reverse proxy. Without it every visitor shares the proxy's IP
   address: one visitor's failed sign-ins would throttle everyone, and if the proxy's address is
   inside a trusted network, every visitor would count as local. The startup log warns when demo
   mode runs without trusted proxy headers.

   Leave *HTTPS-only session cookie* **off** while you reach the instance at `http://<host>:5050`:
   a browser drops a `Secure` cookie on a plain-HTTP page, so the admin, who signs in from the
   local network only, could no longer sign in or out. Turn it on only once every address you use
   is HTTPS, local one included; the setting refuses to turn on from a plain-HTTP page.
4. Leave *Search engine indexing* (*Parameters -> Advanced -> Privacy*) as you want the demo to
   be found or not.

Do not set a location or create the demo account: demo mode does both (next step).

### 3. Turn demo mode on

Set `DEMO_MODE=true` in the compose file, then:

```bash
docker compose -f docker-compose-demo.yml up -d
```

The log shows `DEMO_MODE is on` at startup. Open the address in a private window: you land in the
application with the demo banner, and any save shows the read-only notice. The demo data appears
within a few minutes (next section); tonight's plans once SkyTonight has finished its first
calculation.

### 4. Expose it

Publish the container's port (`5050` above) through your tunnel or reverse proxy of choice. See
[Reverse Proxy & HTTPS Setup](6.REVERSE_PROXY.md) for the general rules. What the demo needs from
it: HTTPS, the client IP forwarded in `X-Forwarded-For`, and nothing else (no extra
authentication in front, or visitors would hit a sign-in page again).

## Updating the demo

- **New version**: `docker compose -f docker-compose-demo.yml pull` then `up -d`. Demo mode and
  the data carry over.
- **Changing the demo data by hand**: the demo account cannot sign in and cannot write while demo
  mode is on. Set `DEMO_MODE=false`, restart, sign in as the demo account from your local network
  (set its password in *Parameters -> Users* first), make the changes, then switch it back on.
  Renaming or removing the generated combinations stops the nightly plans for them.
- **Admin tasks** (logs, metrics, users): sign in at `/login?signin` from your local network
  while demo mode stays on.

## Privacy

- Everything the demo account holds is public by design. Put nothing personal in it.
- The survey pictures come from CDS hips2fits (or its DSS2 mirrors), fetched by the server with
  sky coordinates only, like the object images of any install (see
  [PRIVACY.md](PRIVACY.md#third-parties)).
- Visitors leave their IP address in the application log (trimmed after the log retention
  period, *Parameters -> Advanced -> Privacy*) and in your tunnel or proxy's logs.
- The only cookie is the session cookie, which here also carries the visitor's UI preferences
  (see [PRIVACY.md](PRIVACY.md#cookies)).

## Implementation

- `backend/utils/demo_mode.py` - the switch, the write guard, the demo account and the
  session-scoped preferences.
- `backend/app.py` - `block_demo_writes()` (`before_request`), the automatic sign-in in `index()`,
  the `/login` redirect, and the `demo_mode` template flag.
- `backend/blueprints/auth.py` - refused password sign-ins, `demo_mode` in `/api/auth/status`,
  session-scoped `GET` / `PUT /api/auth/preferences`.
- `backend/demo/demo_life.py` - the demo location, the seed and the nightly plans and logs,
  started from `backend/app.py` with the other schedulers.
- Frontend: the banner in `templates/index.html`, `DEMO_MODE` in `static/js/api_helper.js`, the
  read-only notice in `static/js/auth.js`, the wizard skip in `static/js/first_run.js`.
