# MyAstroBoard - Notifications

Browser and push notification system for time-critical astrophotography events.

---

## Architecture overview

```
Phase A - NotificationManager + background poller    ✅ Done
Phase B - Settings UI (My Settings → Notifications)  ✅ Done
Phase C - Web Push / background (tab may be closed)  ✅ Done
```

### Phase A - Browser Notification API
- `notifications.js` - `NotificationManager` singleton + `startNotificationPoller()` (5 min interval)
- Notifications fire when the tab is open; poller runs regardless of which tab is active

### Phase B - Settings UI
- My Settings → Notifications sub-tab (N1–N7 toggles, lead times, Kp threshold, test button)
- Preferences stored server-side in `data/users.json` under `preferences.notifications`

### Phase C - Web Push
- Notifications fire even when the app tab is closed
- VAPID key pair persisted in `data/vapid.json` (generated once on first startup)
- Push subscriptions stored per-user in `data/users.json` under `push_subscriptions[]`
- Background scheduler (`push_scheduler.py`) evaluates triggers every 5 minutes

---

## Trigger IDs

| ID | Event | Default lead | Module (`_check_*` fn) |
|----|-------|-------------|----------------------|
| `N1` | Plan My Night session starts | 15 min | `plan_my_night.js` / `push_scheduler.py` |
| `N2` | Plan My Night: next target | 5 min | `plan_my_night.js` / `push_scheduler.py` |
| `N3` | ISS solar or lunar transit | 10 min | `iss.js` / `push_scheduler.py` |
| `N4` | Lunar eclipse totality | 30 min | `events_alerts.js` / `push_scheduler.py` |
| `N5` | Solar eclipse maximum | 30 min | `events_alerts.js` / `push_scheduler.py` |
| `N6` | Astronomical darkness begins | 20 min | `sun.js` / `push_scheduler.py` |
| `N7` | Aurora: Kp index ≥ threshold | immediate | `aurora.js` / `push_scheduler.py` |

IDs are defined as `NOTIF_TRIGGERS` constants in `static/js/notifications.js` and referenced by string in `push_scheduler.py`.

---

## Files

| File | Role |
|------|------|
| `static/js/notifications.js` | `NotificationManager`, settings UI, background poller, Web Push subscription |
| `backend/push_manager.py` | VAPID key generation/persistence, `send_push()` wrapper around pywebpush |
| `backend/push_scheduler.py` | Background thread; evaluates N1–N7 server-side every 5 min; sends push |
| `templates/index.html` | Notifications sub-tab (My Settings → Notifications) |
| `static/sw.js` | `push` + `notificationclick` event listeners |
| `static/i18n/*.json` | `notifications.*` namespace (N1–N7 titles/bodies) + `settings.notifications_*` |
| `data/vapid.json` | Generated VAPID key pair - **never delete or regenerate** (invalidates all subscriptions) |

---

## NotificationManager API

`notificationManager` is a global singleton available after `notifications.js` loads.

### Permission

```javascript
notificationManager.isSupported       // boolean
notificationManager.permission        // 'default' | 'granted' | 'denied' | 'unsupported'
notificationManager.canNotify()       // true if granted AND master toggle enabled

const granted = await notificationManager.requestPermission();
// Also calls _subscribeToPush() automatically on grant
```

### Preferences

Stored server-side in `users.json` under `preferences.notifications`. Read via `window.myastroboardUserPreferences.notifications`.

```javascript
const prefs = notificationManager.getPrefs();
// {
//   enabled: true,
//   permission_asked: false,
//   triggers: {
//     N1: { enabled: true, lead_minutes: 15 },
//     ...
//     N7: { enabled: true, kp_threshold: 5 }
//   }
// }

await notificationManager.savePrefs(prefs); // async - POSTs to /api/auth/preferences
notificationManager.isTriggerEnabled('N7')
notificationManager.getLeadMinutes('N1')
notificationManager.getKpThreshold()
```

### Deduplication

In-memory, resets on page reload. The background poller uses server-side cooldowns in `push_scheduler.py`.

```javascript
if (notificationManager.wasRecentlyNotified('N7', 30 * 60 * 1000)) return;
notificationManager.markNotified('N7'); // called automatically by notify()
```

### Firing a notification (Phase A - tab open)

```javascript
await notificationManager.notify(
    'N7',
    i18n.t('notifications.n7_title'),
    i18n.t('notifications.n7_body', { kp: '6.0', visibility: 'Good' }),
    { url: '#forecast-astro/aurora' }
);
```

---

## Background poller (Phase A)

`startNotificationPoller()` starts a `setInterval` every 5 minutes after app init (`app.js → initializeApp()`). It fetches minimal API data for each enabled trigger and calls the same `_check*` functions defined in each feature module.

```javascript
// Called automatically - no manual invocation needed
startNotificationPoller();  // wired in app.js initializeApp()
stopNotificationPoller();   // available but not normally called
```

The `_check*` functions are defined at the bottom of their respective feature modules and are global-scope functions callable from anywhere.

---

## Web Push (Phase C)

### iOS requirements

Web Push on iOS requires **Safari 16.4+** and the app must be **installed as a PWA** (Add to Home Screen). Push is not delivered to a regular Safari browser tab.

The `VAPID_CONTACT_EMAIL` environment variable must be set to a real email address. Apple APNs silently rejects pushes when the VAPID `sub` claim contains an invalid domain (e.g. `.local`). See [docs/1.INSTALLATION.md](1.INSTALLATION.md) for setup instructions.

The in-app **Test** button calls `POST /api/push/test`, which sends a real server-side push through the full VAPID → push service → service worker pipeline. On iOS, background the app immediately after tapping to see the notification appear.

### VAPID keys

Generated once on first startup by `push_manager.load_or_generate_vapid_keys()` and saved to `data/vapid.json`:

```json
{ "private_key": "<43-char base64url raw EC scalar>", "public_key": "<87-char base64url uncompressed point>" }
```

The private key is stored as a raw base64url-encoded 32-byte EC scalar (the format expected by `py_vapid.Vapid.from_string()`). PEM format is **not** used — older `vapid.json` files containing `-----BEGIN ... KEY-----` are automatically migrated to the correct format on startup.

**Never delete or regenerate `vapid.json`** - doing so invalidates all existing push subscriptions. `_subscribeToPush()` detects VAPID key rotation via `PushSubscription.options.applicationServerKey` comparison and forces a transparent re-subscribe if the key changed.

### Push subscription flow

1. User clicks "Enable notifications" → `requestPermission()` granted
2. `_subscribeToPush()` fetches `GET /api/push/vapid-public-key`
3. Browser calls `pushManager.subscribe({ applicationServerKey: publicKey })`
4. Subscription POSTed to `POST /api/push/subscribe`
5. Stored under user's `push_subscriptions[]` in `users.json`

### API routes

| Method | Route | Auth | Description |
|--------|-------|------|-------------|
| `GET` | `/api/push/vapid-public-key` | Public | Returns base64url public key for `applicationServerKey` |
| `GET` | `/api/push/vapid-config-status` | Public | Returns whether `VAPID_CONTACT_EMAIL` is correctly configured |
| `POST` | `/api/push/subscribe` | `@login_required` | Stores subscription (deduplicates by endpoint) |
| `DELETE` | `/api/push/unsubscribe` | `@login_required` | Removes subscription by endpoint |
| `GET`  | `/api/push/subscriptions` | `@login_required` | Lists subscriptions for the current user. Returns `{"subscriptions": [{index, provider, created_at, endpoint_tail}]}`. `provider` is one of `apple`, `google`, `mozilla`, `other`. Full endpoints are not exposed — only the last 20 chars as `endpoint_tail`. |
| `DELETE` | `/api/push/subscriptions` | `@login_required` | Removes **all** server-side subscriptions for the current user. The UI also calls `pushManager.getSubscription().unsubscribe()` to clean the browser side. Returns `{"removed": N}`. |
| `POST` | `/api/push/test` | `@login_required` | Sends an immediate test push to all subscriptions of the current user; removes dead (410/404) endpoints automatically. Returns `{"delivered": N, "total": N, "cleaned": N}` |

### User model

`push_subscriptions` is a top-level field on the user object (not inside `preferences`):

```json
{
  "user_id": "...",
  "preferences": { ... },
  "push_subscriptions": [
    { "endpoint": "https://fcm.googleapis.com/...", "keys": { "p256dh": "...", "auth": "..." }, "created_at": "..." }
  ]
}
```

### Push scheduler (`push_scheduler.py`)

Daemon thread started at app startup. Polls every 5 minutes:

- Loads cached data once per cycle (aurora, sun, ISS, solar/lunar eclipse)
- Loads per-user plan data via `get_plan_with_timeline()`
- Skips users with no push subscriptions or notifications disabled
- Notification title/body are translated using the user's `preferences.language` field via `i18n_utils.get_translated_message()` (keys: `settings.push_n*`)
- Sends push via `push_manager.send_push()` (pywebpush)
- Dead subscriptions (delivery failure) are automatically removed
- In-memory cooldowns reset on server restart (acceptable: worst case one duplicate per restart)

### sw.js handlers

```javascript
// push - fires when server sends a push
self.addEventListener('push', event => { ... showNotification() ... });

// notificationclick - focuses app window and navigates to data.url
self.addEventListener('notificationclick', event => { ... });
```

### Push payload shape

```json
{
  "title": "Plan My Night",
  "body": "Your session starts in 14 min",
  "icon": "/static/ico/android/launchericon-192x192.png",
  "badge": "/static/ico/android/launchericon-72x72.png",
  "tag": "N1-20260529",
  "data": { "url": "/#astrodex/plan-my-night" }
}
```

---

## Settings UI elements

| ID | Type | Role |
|----|------|------|
| `#notif-permission-banner` | `div.alert` | Permission state + push status (two lines when granted) |
| `#notif-enable-btn` | `button.btn-warning` | Calls `requestPermission()` + `_subscribeToPush()`; hidden when granted/denied |
| `#notif-master-toggle` | `input[checkbox]` | Master enable/disable |
| `#notif-trigger-N1` … `#notif-trigger-N7` | `input[checkbox]` | Per-trigger toggle |
| `#notif-lead-N1` … `#notif-lead-N6` | `select` | Lead time in minutes |
| `#notif-kp-threshold` | `select` | Kp threshold (N7 only) |
| `#notif-save-btn` | `button.btn-primary` | Async save to server |
| `#notif-test-btn` | `button.btn-outline-secondary` | Fires a sample notification |
| `#notif-save-message` | `div.alert` | Feedback (auto-hides after 3 s) |

---

## Adding a new trigger

1. Add the ID to `NOTIF_TRIGGERS` in `notifications.js`
2. Add default prefs to `_NOTIF_DEFAULTS.triggers` in `notifications.js`
3. Add a row to `#notif-triggers-list` in `templates/index.html`
4. Add `notifications.nX_title` and `notifications.nX_body` keys to all 6 i18n files
5. Add `_check_nX()` function in the relevant feature module (called by the background poller)
6. Add the poller call in `_runNotificationChecks()` in `notifications.js`
7. Add the server-side check in `push_scheduler.py`
8. Update the trigger table in this document

---

## i18n namespaces

| Namespace | Content |
|-----------|---------|
| `settings.notifications_*` | UI strings: banner text, button labels, toggle labels, trigger labels |
| `notifications.nX_title` / `notifications.nX_body` | Notification payload strings (title + body with `{placeholder}`) |

Keys in `notifications` namespace are ordered N1→N7 per trigger, `_title` before `_body`.
