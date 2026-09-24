# MyAstroShine integration

Send a photo from your Astrodex to [MyAstroShine](https://github.com/myastroboard/myastroshine)
for re-processing, then bring the enhanced result back as a **new picture on the same object** -
the original is never touched.

---

## Where to find it

- **Setup**: Parameters -> Connectors -> *MyAstroShine* card
- **Use**: Astrodex -> open an object -> the photo action row shows a
  <i class="bi bi-stars"></i> **Send to MyAstroShine** button next to *Edit* / *Delete*, once the
  integration is configured and enabled.

---

## Why "pull + webhook" and not "push"

MyAstroShine always runs on the local network. MyAstroBoard might not - it can sit on a VPS
behind a reverse proxy. The only server-to-server direction that is always reachable is
**MyAstroShine -> MyAstroBoard** (the board's public URL, or its LAN IP). So:

| Step | Carried by | Direction |
|---|---|---|
| Open MyAstroShine with the source photo | the **browser** (`window.open`) | browser -> shine |
| Read the source image + metadata | **MyAstroShine container** | shine -> board |
| Send the enhanced image home | **MyAstroShine container** | shine -> board |

The browser makes **no cross-origin XHR**, so there is nothing to add to the board's CSP and no
CORS to open on MyAstroShine.

---

## Setup

**Minimum version**: MyAstroShine **v0.4.0** - older releases do not implement the pull + webhook
round-trip described above. The connector card shows this requirement as a *Requires v0.4.0*
line; it is informational, not enforced, since MyAstroShine only reports its own version once a
handoff completes (stored per picture as `enhanced_source_version`).

That version, and everything else the card shows, is declared on `MyAstroShineConnector`
(`backend/connectors/myastroshine_connector.py`) - a `BaseConnector` in the `REGISTRY`, listed by
`GET /api/connectors` and saved through `POST /api/connectors/myastroshine/config` like any other
connector. See [CONNECTORS.md](CONNECTORS.md#myastroshine-connector).

The token and signing secret are declared as `SECRET_FIELDS`, so the listing masks them and a
blank submission keeps the stored value: they are never sent to the browser.

### 1. Create a token in MyAstroShine

MyAstroShine -> Settings -> Tokens -> New. You get a **token** (`mas_...`) and a **signing
secret** (64 hex chars), shown once.

### 2. Fill in the connector card

| Field | Notes |
|---|---|
| **Display label** | Optional, defaults to "MyAstroShine" |
| **MyAstroShine base URL** | What the **browser** opens, e.g. `http://192.168.1.42:8002`. Use a static LAN IP, not a `.local` name. If you open the board from outside your LAN the MyAstroShine tab will not load - that is expected, MyAstroShine is LAN-only. |
| **Token** / **Signing secret** | Paste both from step 1. Stored in `data/connectors_secrets.json` (never in `config.json` or a backup), masked in every API response, "blank = keep current" on save. |
| **Callback URL override** (advanced) | Only if the MyAstroShine container cannot reach this dashboard's public URL on its own (no NAT hair-pinning). e.g. `http://192.168.1.42:5000`, or the board's service name on a shared Docker network. When set, it wins over the URL derived from the reverse-proxy headers. |
| **Copy the source photo's rating** | Off by default - a re-processed image is a new artifact to re-judge. |
| **Enable connector** | The button and endpoints activate only when enabled **and** URL + token + signing secret are all set. |

### 3. Allow the callback on the MyAstroShine side

The board builds the callback URL from `X-Forwarded-Proto` / `X-Forwarded-Host` (so
**Parameters -> Advanced -> Reverse proxy** must be on when behind a proxy), or from the override
field. That URL - the public one **and** the override if you use one - must be in MyAstroShine's
`astrodex_callback_urls` allowlist.

### Test button

The <i class="bi bi-wifi"></i> button probes `<url>/api/health` **from the backend**, best effort.
"Unreachable" is normal when the board is not on the same network as MyAstroShine - the button is
only a convenience for the all-in-one-LAN case. Loopback / link-local / unspecified / multicast
targets are refused (SSRF hardening).

---

## The round trip

```
Browser  --POST /api/astrodex/integration/handoff-->  Board        mints a signed token
Browser  --window.open(<shine>/#/?handoff=<token>)-->  MyAstroShine resumes an edit session
Shine    --GET  /source?handoff=...              -->   Board        picture metadata
Shine    --GET  /source/image?handoff=...        -->   Board        source image bytes
   ... user edits in MyAstroShine ...
Shine    --POST /enhanced  (multipart + signature)-->  Board        new duplicated picture (201)
```

### Handoff token

`base64url(payload) + "." + base64url(HMAC_SHA256(base64url(payload), signing_secret))`

- base64url is **unpadded**; the HMAC is taken over the base64url payload **string**, and the
  signature is the **raw digest** base64url-encoded (not hex).
- Payload: `{ kid, callback_base, item_id, picture_id, user_id, iat, exp, jti }`.
  `kid` = the first 12 chars of the token. `callback_base` is set by the board only (never user
  input) - it is still re-checked against MyAstroShine's allowlist before any callback.
- **TTL 12 h** (`MyAstroShineConnector.HANDOFF_TTL_SECONDS`) - long enough for a full evening editing
  session. **Single use**: the `jti` is marked spent when `/enhanced` succeeds, so a replay is
  rejected with `409`. The spent-jti set is kept in memory and mirrored to
  `data/astrodex/myastroshine_consumed_handoffs.json` so a worker restart still blocks a replay.

### Enhanced upload signature

`multipart/form-data` with `handoff`, `payload` (JSON: `{ parameters, myastroshine_version, note? }`)
and `image` (JPEG). Header:

```
X-Webhook-Signature: sha256=<hex>
signing_input = canonical_json(payload) + "\n" + sha256_hex(image_bytes)
```

`canonical_json` = `json.dumps(obj, separators=(",", ":"), sort_keys=True)` - identical to
MyAstroShine's `app/services/astrodex_integration.py:canonical_json`. The image hash is bound into
the signature instead of the (large) blob itself.

The handoff signature is verified **first**, in constant time, before any disk access. The three
cookieless endpoints are rate-limited per client IP.

---

## The duplicated picture

The board copies the **frozen snapshot** of the source picture's metadata (`date`,
`exposition_time`, `frames`, `integration_minutes`, `iso`, `device`, `filters`, `notes`,
location fields, `combination_id`, `combination_used_components`) onto the new picture, swaps in
the enhanced image file, and stamps immutable provenance fields:

| Field | Value |
|---|---|
| `enhanced_by` | `"myastroshine"` |
| `enhanced_at` | ISO 8601 timestamp of the round-trip |
| `enhanced_from_picture_id` | the source picture's id |
| `enhanced_parameters` | the MyAstroShine parameter dict, verbatim |
| `enhanced_source_version` | MyAstroShine version string |

These are **not** editable - they are absent from `update_picture()`'s allowed fields.

- `is_main` is always `False` - the item already has the source picture, and promotion stays a
  manual choice.
- `rating` is copied only when **Copy the source photo's rating** is on.
- The Edit Photo modal shows a discreet
  "Re-processed with MyAstroShine on <date>" line with a *view settings* disclosure that pretty-prints
  `enhanced_parameters`.
- The board gets no push when the enhanced picture arrives (MyAstroShine calls back
  server-to-server). When the Astrodex browser tab regains focus after a send, it re-fetches and
  re-renders the open item, and toasts "Enhanced photo received from MyAstroShine" - no manual
  reload needed.

---

## Security summary

- `source` / `source/image` / `enhanced`: no session cookie; handoff signature checked first, in
  constant time; rate-limited; upload size capped at `MyAstroShineConnector.MAX_IMAGE_BYTES` (50 MB).
- `callback_base` is board-set and re-verified against MyAstroShine's allowlist.
- The handoff pins `user_id` + `item_id` + `picture_id`, so a return can only ever write into that
  user's Astrodex, on that item. All three are re-checked to a strict uuid shape at every entry
  point (defence in depth on top of the signature), and `get_user_astrodex_file()` confines the
  resulting path to `data/astrodex/` with a realpath barrier.
- Enhanced image is confined to `data/astrodex/images/` with the same realpath barrier as the
  normal upload path.
- `token` / `signing_secret` live in `data/connectors_secrets.json` (outside `config.json` and
  outside the backup ZIP - re-enter them after restoring a backup on another machine), are
  masked in API responses, and "blank = keep".
- No new CSP `connect-src` entry and no CORS: the browser never makes a cross-origin request.

---

## A connector, with two particularities

This is a `BaseConnector` like AllSky — in the `REGISTRY`, listed by `GET /api/connectors`,
stored under `config.connectors.myastroshine`, and rendered by the same card. Two things set it
apart, both declared rather than special-cased:

- **It is bidirectional.** The browser hands a photo to MyAstroShine and the MyAstroShine
  container posts the enhanced result back, so it authenticates — hence `SECRET_FIELDS` and the
  cookieless callback routes in `backend/blueprints/connectors_myastroshine.py` (logic in
  `backend/observation/myastroshine_integration.py`).
- **It surfaces in the Astrodex, not the Observatory** — `target_modules = ["astrodex"]`, and it
  has no Observatory panel.
