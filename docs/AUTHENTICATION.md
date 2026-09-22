# Authentication & User Management

MyAstroBoard uses a simple session-based multi-user system with three roles.

**Module**: `backend/utils/auth.py`

---

## Default credentials

On first startup, a single admin account is created automatically:

| Username | Password |
|----------|----------|
| `admin` | `admin` |

**Change the default password immediately** after first login via **My Settings → Security → Change Password**, or via the admin user management panel.

---

## Roles

| Role | Description | Permissions |
|------|-------------|-------------|
| `admin` | Full administrator | All features + user management, system config, admin API endpoints |
| `user` | Standard user | All observatory features (observe, plan, record, edit own data) |
| `read-only` | View-only access | Browse Astrodex, SkyTonight, and weather; cannot write any data |

### Role comparison

| Action | admin | user | read-only |
|--------|-------|------|-----------|
| View dashboard, weather, SkyTonight | ✅ | ✅ | ✅ |
| View Astrodex | ✅ | ✅ | ✅ |
| Add/edit Astrodex items | ✅ | ✅ | ❌ |
| Plan My Night (read) | ✅ | ✅ | ✅ |
| Plan My Night (create/edit) | ✅ | ✅ | ❌ |
| Manage own equipment | ✅ | ✅ | ❌ |
| Change own password/preferences | ✅ | ✅ | ✅ |
| Manage all users | ✅ | ❌ | ❌ |
| Change system configuration | ✅ | ❌ | ❌ |
| View metrics and logs | ✅ | ❌ | ❌ |
| Trigger SkyTonight recalculation | ✅ | ❌ | ❌ |

---

## Users storage

All user accounts are stored in `data/users.json`. This file contains:

```json
[
  {
    "user_id": "<uuid>",
    "username": "admin",
    "password_hash": "<werkzeug bcrypt hash>",
    "role": "admin",
    "created_at": "2025-01-01T00:00:00+00:00",
    "last_login": "2026-06-01T20:00:00+00:00",
    "preferences": { ... },
    "push_subscriptions": [ ... ],
    "account_scope": "global",
    "totp_secret": null,
    "totp_enabled": false,
    "totp_confirmed_at": null
  }
]
```

Passwords are hashed using **Werkzeug's `generate_password_hash`** (PBKDF2-SHA256 by default). Plain-text passwords are never stored.

`account_scope`, `totp_secret`, `totp_enabled` and `totp_confirmed_at` are documented in full under
[Two-factor authentication](#two-factor-authentication) and
[Local vs. global accounts](#local-vs-global-accounts) below. Entries written before these fields
existed load with `account_scope: "global"` and the three 2FA fields falsy - no migration script
is needed.

---

## Sessions

MyAstroBoard uses Flask server-side sessions (cookie-based, signed with a persistent `SECRET_KEY`).

The `SECRET_KEY` is generated once on first startup and stored in `data/secret_key.txt`. It persists across container restarts so existing sessions remain valid. **Never delete `secret_key.txt`** — doing so invalidates all active sessions.

The session cookie name is `session`. Session expiry follows Flask defaults (browser session unless `SESSION_COOKIE_SECURE` is enabled).

---

## User preferences

Each user has a `preferences` object stored inside `users.json`. These are saved via `PUT /api/auth/preferences`.

| Preference | Allowed values | Default | Description |
|------------|---------------|---------|-------------|
| `startup_main_tab` | `forecast-astro`, `forecast-weather`, `skytonight`, `spaceflight`, `astrodex`, `equipment`, `my-settings`, `parameters` | `forecast-astro` | Which tab opens on login |
| `startup_subtab` | (list of valid sub-tab IDs) | `astro-weather` | Which sub-tab opens on login |
| `time_format` | `auto`, `12h`, `24h` | `auto` | Time display format (`auto` follows browser locale) |
| `density` | `comfortable`, `compact` | `comfortable` | UI row density |
| `theme_mode` | `auto`, `light`, `dark`, `red` | `auto` | Colour theme (`auto` follows OS preference) |
| `first_day_of_week` | `monday`, `sunday` | `monday` | Calendar and date picker start day |
| `language` | `en`, `fr`, plus community translations | `en` | Interface language |
| `experience_level` | `beginner`, `intermediate`, `advanced` | `advanced` | Filters SkyTonight recommendations and the Beginner Catalog by difficulty (see [BEGINNER_EXPERIENCE.md](BEGINNER_EXPERIENCE.md)) |
| `beginner_catalog_enabled` | boolean | `true` | Shows/hides the "Beginner" SkyTonight sub-tab |
| `wizard` | Object (`completed`, `skipped` booleans) | both `false` | Guided setup wizard completion state (see [BEGINNER_EXPERIENCE.md](BEGINNER_EXPERIENCE.md)) |
| `notifications` | Object (see [NOTIFICATIONS.md](NOTIFICATIONS.md)) | enabled, defaults per trigger | Push and in-browser notification settings; includes `disabled_location_ids` per-location mutes (v1.2) |
| `location` | Object (see [LOCATIONS.md](LOCATIONS.md)) | empty attribution, install default | v1.2 multi-location block: `attributed_location_ids` (admin-set), `default_location_id` (user's "what I see when I connect"), `active_location_id` (session-scoped, reset to default at login), `order` |

---

## User management (admin)

The **Parameters → Users** panel (admin only) allows:

- **Create user**: username, password, role, and optionally the account scope (see
  [Local vs. global accounts](#local-vs-global-accounts)).
- **Edit user**: change username, password, role, or account scope.
- **Delete user**: removes account; Astrodex and equipment data are **not** automatically deleted (data persists in their per-user files).
- **Reset 2FA**: shown only when the user has two-factor authentication active. Clears it
  unconditionally, no password check - see
  [Lost-authenticator recovery](#lost-authenticator-recovery).

**API endpoints** (admin only):

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/users` | List all users (without password hashes or TOTP secrets); each entry includes `account_scope` and `totp_enabled` |
| `POST` | `/api/users` | Create a new user (`account_scope` optional, defaults to `global`) |
| `PUT` | `/api/users/<user_id>` | Update username, password, role, or `account_scope` |
| `DELETE` | `/api/users/<user_id>` | Delete a user |
| `DELETE` | `/api/users/<user_id>/2fa` | Clear a user's two-factor authentication (admin only, no password check) |

---

## Authentication API

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/auth/login` | Public | Submit `{"username": ..., "password": ...}` → sets session cookie, or returns `{"status": "2fa_required"}` when a second step is needed (see [Two-factor authentication](#two-factor-authentication)), or `403` when a local-scoped account signs in from an untrusted network |
| `POST` | `/api/auth/login/verify-2fa` | pending session | Second login step: submit `{"code": "123456"}` to complete a login that returned `2fa_required` |
| `POST` | `/api/auth/logout` | login | Clears session |
| `GET` | `/api/auth/status` | Public | Returns `{"authenticated": bool, "role": ..., "username": ..., "two_factor_available": bool, "totp_enabled": bool, "account_scope": ...}` |
| `POST` | `/api/auth/change-password` | login | Change own password |
| `GET` | `/api/auth/preferences` | login | Get current user's preferences |
| `PUT` | `/api/auth/preferences` | login | Update preferences (partial update supported) |
| `POST` | `/api/auth/2fa/setup` | login | Generate (or regenerate) this user's TOTP secret, returns `{"secret": ..., "otpauth_uri": ...}` |
| `POST` | `/api/auth/2fa/confirm` | login | Submit `{"code": "123456"}` to activate 2FA after setup |
| `POST` | `/api/auth/2fa/disable` | login | Submit `{"password": ...}` to turn 2FA off (self-service, re-authenticates) |
| `GET` | `/api/auth/security-settings` | admin | Read the trusted-network list and the instance-wide 2FA switch |
| `POST` | `/api/auth/security-settings` | admin | Save the trusted-network list and the instance-wide 2FA switch (validation rules below) |

---

## Advanced settings (admin)

Stored in `data/app_settings.json` via `backend/utils/app_settings.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `vapid_contact_email` | `""` | Contact email embedded in Web Push VAPID tokens (required for iOS push; see [NOTIFICATIONS.md](NOTIFICATIONS.md)) |
| `trust_proxy_headers` | `false` | Set `true` when behind a reverse proxy sending `X-Forwarded-For` / `X-Forwarded-Proto` headers (see [6.REVERSE_PROXY.md](6.REVERSE_PROXY.md)) |
| `session_cookie_secure` | `false` | Set `true` to restrict the session cookie to HTTPS connections only (recommended when using HTTPS) |
| `search_engine_indexing` | `false` | Set `true` to let search engines crawl and index the login page. Instances are private by default (`/robots.txt` disallows everything, login page is `noindex, nofollow`) |

These are managed in **Parameters → Advanced → Application** in the admin UI, or via `GET/POST /api/admin/app-settings`.

---

## Trusted networks

**Module**: `backend/utils/security_settings.py` · **File**: `data/security_settings.json`

Trusted networks are the shared foundation for both two-factor authentication and local/global
accounts below: an admin-managed list of CIDR blocks or bare IP addresses, matched against the
client IP of each login attempt. Two independent features read the same list for opposite
purposes - two-factor authentication trusts the network to **skip** a step, local/global accounts
trust it to **allow** a step - but they are otherwise unrelated checks.

```json
{
  "trusted_networks": ["192.168.1.0/24"],
  "two_factor_enabled": false
}
```

- Each entry is normalized with Python's `ipaddress.ip_network(value, strict=False)`, so
  `192.168.1.5/24` and `192.168.1.0/24` are stored as the same, single entry. Both IPv4 and IPv6
  are supported.
- `127.0.0.0/8` and `::1/128` are **always** implicitly trusted. They are hardcoded and never
  written to the file, so clearing the configured list can never lock an admin out of localhost
  access.
- The client IP is `request.remote_addr`, which already resolves the real client IP behind a
  reverse proxy when `trust_proxy_headers` is enabled (see [Advanced settings](#advanced-settings-admin) above) - no separate configuration is needed for trusted networks to work correctly behind a proxy.
- **Not included in backups**: `security_settings.json` is excluded from both
  `/api/backup/download` and `/api/config/export`, for the same reason as `trust_proxy_headers` -
  see [docs/CONFIGURATION.md](CONFIGURATION.md#backup-and-restore).

Managed in **Parameters → Users**, in the "Trusted networks and two-factor authentication" panel
(admin only), or via `GET/POST /api/auth/security-settings`.

### Validation rules (enforced server-side, in `POST /api/auth/security-settings`)

1. Each entry must parse as a valid IP network. The whole save is rejected with `400` and
   `error_key: settings.invalid_trusted_network` otherwise, naming the bad entry.
2. `two_factor_enabled` cannot be set to `true` while the resulting `trusted_networks` list is
   empty. Rejected with `error_key: settings.2fa_requires_trusted_network`.
3. If a save removes the last entry from `trusted_networks` while `two_factor_enabled` was
   previously `true`, it is **silently forced to `false`** as part of the same save (not an
   error - a documented cascade) and a warning is logged. The admin UI shows a confirmation
   dialog before this happens when removing the last entry.

---

## Two-factor authentication

Optional TOTP (Time-based One-Time Password) second factor, compatible with any standard
authenticator app (Google Authenticator, Authy, 1Password, etc.). Off by default; an admin must
enable it instance-wide before any individual user can turn it on for their own account.

**Dependency**: [`pyotp`](https://pypi.org/project/pyotp/) (pure Python, no transitive
dependencies) generates secrets, verifies codes, and builds the `otpauth://` provisioning URI.
QR codes are rendered **client-side** from a small vendored JS library
(`static/vendor/qrcode/qrcode.min.js`) - the backend never renders an image, so no
`qrcode`/Pillow-style dependency was added for this.

### Two levels of control

1. **Instance switch** (`security_settings.json`, `two_factor_enabled`): an admin turns 2FA on or
   off for the whole install. Requires at least one trusted network (see above). Managed in
   **Parameters → Users**.
2. **Per-user opt-in** (`users.json`, `totp_enabled`): once the instance switch is on, each user
   individually enables 2FA for their own account in **My Settings → Security**. A user whose
   account was never opted in is never challenged at login, even with the instance switch on.

### Trusted-network bypass

2FA is skipped entirely - no code is asked for - when the login request's client IP falls inside
a trusted network (including the always-trusted loopback ranges). This is deliberate: the
trusted network already establishes who is signing in, so the second factor would be redundant
from there.

### Setup flow (My Settings → Security)

1. **Enable 2FA** → `POST /api/auth/2fa/setup` generates a TOTP secret and persists it
   immediately with `totp_enabled: false`. It is **not** held in server memory or the Flask
   session: the container runs `gunicorn -w 2` (two worker processes), so an in-memory pending
   secret would randomly fail confirmation depending on which worker handled it.
2. The setup modal shows:
   - A QR code (rendered client-side) - scan it **from a different device** than the one showing
     it.
   - The raw secret as selectable text - the reliable fallback when the authenticator app is on
     the same phone as the browser (QR scanning is then impossible).
   - An `otpauth://` link/button to open directly in an authenticator app - best effort, not every
     app registers the URI scheme as a system handler.
3. **Confirm** with a 6-digit code → `POST /api/auth/2fa/confirm` verifies it against the
   just-generated secret (`pyotp.TOTP(secret).verify(code, valid_window=1)`, tolerating +/-30
   seconds of clock drift) and sets `totp_enabled: true`, `totp_confirmed_at` to the current
   timestamp.
4. **Disable** (self-service) → `POST /api/auth/2fa/disable` requires the current password
   (re-authentication) and clears `totp_secret`, `totp_enabled`, `totp_confirmed_at`.

### Login flow

After password verification (never before - see [Security notes](#security-notes)) and after the
local/global account check:

1. If the instance switch is on, the user has `totp_enabled: true`, and the client IP is not
   trusted: `POST /api/auth/login` does **not** set the session. It stores a pending state in the
   session instead (`pending_2fa_user_id`, a 5-minute expiry, an attempt counter) and returns
   `{"status": "2fa_required"}`, `200`. The session is never `permanent` in this pending state,
   regardless of `remember_me` - the 30-day cookie only applies once fully authenticated.
2. The login page shows a second step (6-digit code input). `POST /api/auth/login/verify-2fa`
   verifies the code against the pending user's secret and, on success, finishes the login exactly
   as a normal password-only login would (same session keys, same response shape).
3. **Brute-force guard**: up to 5 incorrect codes per pending login, and the pending state expires
   after 5 minutes; either condition forces a fresh `/api/auth/login` call. A 6-digit TOTP code is
   a much smaller search space than a password, so this endpoint is throttled even though the app
   has no login rate-limiting elsewhere (see [Security notes](#security-notes)).
4. `login_required` needs no special handling for the pending state: it only checks for
   `'username' in session`, which stays unset throughout - every existing authenticated route
   stays correctly locked out mid-2FA.

### Admin: forced disable

An admin can clear any user's 2FA from **Parameters → Users** (shown only when that user has it
active), via `DELETE /api/users/<user_id>/2fa`. No password check - admin authority is the check.
Intended for a lost or reset authenticator device.

### Lost-authenticator recovery

If a user loses their authenticator device and no other admin is available to disable 2FA for
them via the Users panel, an admin with filesystem access to `data/users.json` can manually edit
that user's entry, setting `"totp_enabled": false` (the secret can be left in place or cleared).
`UserManager` reloads the file automatically on next access (mtime-based, no restart required) -
the user can log in with just their password on the next attempt.

---

## Local vs. global accounts

Each account has an `account_scope` of `global` (default - can sign in from anywhere) or `local`
(can only sign in from a trusted network). This reuses the same trusted-network list as
two-factor authentication above, but for the opposite purpose: trusting the network to **allow**
the login rather than to **skip** a step.

- Managed per user from **Parameters → Users** ("Scope" column and action button), or via
  `PUT /api/users/<user_id>` with `{"account_scope": "local"}`. `POST /api/users` also accepts
  `account_scope` at creation time.
- Enforced in `POST /api/auth/login`, after password verification and before the 2FA check: a
  `local` account signing in from outside every trusted network (including loopback) is rejected
  with `403` and `error_key: auth.local_account_network_restricted`.
- **Fallback rule**: when `trusted_networks` is empty, the local/global check is **not**
  performed at all - a `local` account can sign in from anywhere in that state. Without any
  configured network, "local" is undefined, and blocking every non-localhost login for every
  `local` account would be a silent full lockout. **Parameters → Users** shows a warning banner
  when this fallback is active and at least one account is scoped `local`.

---

## Security notes

- Session cookies are `HttpOnly` by default (not accessible by JavaScript).
- Enable `session_cookie_secure = true` + `trust_proxy_headers = true` when deploying with HTTPS behind a reverse proxy.
- The API does not implement rate limiting on login attempts at the application level — use a reverse proxy with rate-limiting rules for public-facing deployments. `POST /api/auth/login/verify-2fa` is the one exception: it has its own 5-attempt, 5-minute limit (see [Two-factor authentication](#two-factor-authentication)), since a 6-digit code is a much smaller search space than a password.
- There is no email-based password reset: an admin must reset passwords via the Users panel.
- Network and 2FA checks in `POST /api/auth/login` run strictly **after** password verification. Checking them first would let an unauthenticated caller probe account existence or configuration (local scope, 2FA status) without a valid credential.
- Two-factor secrets live directly on the `User` record in `users.json`, the same file and precedent as `password_hash` (already a sensitive field included in backups) - not in the `connectors_secrets.json`-style sidecar used for connector credentials, since that pattern exists specifically to keep those out of backups.
