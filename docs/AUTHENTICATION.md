# Authentication & User Management

MyAstroBoard uses a simple session-based multi-user system with three roles.

**Module**: `backend/auth.py`

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
    "push_subscriptions": [ ... ]
  }
]
```

Passwords are hashed using **Werkzeug's `generate_password_hash`** (PBKDF2-SHA256 by default). Plain-text passwords are never stored.

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
| `notifications` | Object (see [NOTIFICATIONS.md](NOTIFICATIONS.md)) | enabled, defaults per trigger | Push and in-browser notification settings |

---

## User management (admin)

The **Parameters → Users** panel (admin only) allows:

- **Create user**: username, password, role.
- **Edit user**: change username, password, or role.
- **Delete user**: removes account; Astrodex and equipment data are **not** automatically deleted (data persists in their per-user files).

**API endpoints** (admin only):

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/users` | List all users (without password hashes) |
| `POST` | `/api/users` | Create a new user |
| `PUT` | `/api/users/<user_id>` | Update username, password, or role |
| `DELETE` | `/api/users/<user_id>` | Delete a user |

---

## Authentication API

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/auth/login` | Public | Submit `{"username": ..., "password": ...}` → sets session cookie |
| `POST` | `/api/auth/logout` | login | Clears session |
| `GET` | `/api/auth/status` | Public | Returns `{"authenticated": bool, "role": ..., "username": ...}` |
| `POST` | `/api/auth/change-password` | login | Change own password |
| `GET` | `/api/auth/preferences` | login | Get current user's preferences |
| `PUT` | `/api/auth/preferences` | login | Update preferences (partial update supported) |

---

## Advanced settings (admin)

Stored in `data/app_settings.json` via `backend/app_settings.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `vapid_contact_email` | `""` | Contact email embedded in Web Push VAPID tokens (required for iOS push; see [NOTIFICATIONS.md](NOTIFICATIONS.md)) |
| `trust_proxy_headers` | `false` | Set `true` when behind a reverse proxy sending `X-Forwarded-For` / `X-Forwarded-Proto` headers (see [6.REVERSE_PROXY.md](6.REVERSE_PROXY.md)) |
| `session_cookie_secure` | `false` | Set `true` to restrict the session cookie to HTTPS connections only (recommended when using HTTPS) |

These are managed in **Parameters → Advanced → Application** in the admin UI, or via `GET/POST /api/admin/app-settings`.

---

## Security notes

- Session cookies are `HttpOnly` by default (not accessible by JavaScript).
- Enable `session_cookie_secure = true` + `trust_proxy_headers = true` when deploying with HTTPS behind a reverse proxy.
- The API does not implement rate limiting on login attempts at the application level — use a reverse proxy with rate-limiting rules for public-facing deployments.
- There is no email-based password reset: an admin must reset passwords via the Users panel.
