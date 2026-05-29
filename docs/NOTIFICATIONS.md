# MyAstroBoard — Notifications

Browser and push notification system for time-critical astrophotography events.

---

## Architecture

The notification system is split into three phases with increasing complexity and infrastructure requirements.

```
Phase A — Browser Notification API     (tab must be open)
Phase B — Settings UI                  (user preferences, localStorage)
Phase C — Web Push / background        (tab may be closed, requires VAPID backend)
```

**Current status:** Phase A skeleton + Phase B settings UI complete. Triggers not yet wired.

---

## Trigger IDs

Each notification type has a stable ID used throughout the codebase.

| ID | Event | Default lead | Configurable |
|----|-------|-------------|--------------|
| `N1` | Plan My Night session starts | 15 min | Yes |
| `N2` | Plan My Night: next target | 5 min | Yes |
| `N3` | ISS solar or lunar transit | 10 min | Yes |
| `N4` | Lunar eclipse totality | 30 min | Yes |
| `N5` | Solar eclipse maximum | 30 min | Yes |
| `N6` | Astronomical darkness begins | 20 min | Yes |
| `N7` | Aurora: Kp index ≥ threshold | immediate | Kp 3–9 |

IDs are defined as `NOTIF_TRIGGERS` constants in `static/js/notifications.js`. Always reference triggers by ID (`N1`–`N7`), never by index or string literal.

---

## Files

| File | Role |
|------|------|
| `static/js/notifications.js` | `NotificationManager` class + settings UI logic |
| `templates/index.html` | Notifications sub-tab (My Settings → Notifications) |
| `static/i18n/*.json` | Translation keys under `settings.notifications_*` |
| `static/sw.js` | Will receive `push` event listener in Phase C |

---

## NotificationManager API

`notificationManager` is a global singleton available after `notifications.js` loads.

### Permission

```javascript
// Check support and current state
notificationManager.isSupported       // boolean
notificationManager.permission        // 'default' | 'granted' | 'denied' | 'unsupported'
notificationManager.canNotify()       // true if granted AND master toggle enabled

// Request permission (safe to call multiple times)
const granted = await notificationManager.requestPermission(); // returns boolean
```

### Preferences

Preferences are stored in `localStorage` under key `myastroboard_notif_prefs`.

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

notificationManager.savePrefs(prefs);

// Per-trigger accessors
notificationManager.isTriggerEnabled('N7')     // boolean
notificationManager.getLeadMinutes('N1')       // number (minutes)
notificationManager.getKpThreshold()           // number (Kp value, N7 only)
```

### Deduplication

Prevents a polling loop from re-firing the same notification every cycle.

```javascript
// Check if this trigger fired recently
if (notificationManager.wasRecentlyNotified('N7', 30 * 60 * 1000)) return; // 30 min cooldown

// Mark as notified (called automatically by notify())
notificationManager.markNotified('N7');
```

### Firing a notification

```javascript
const shown = await notificationManager.notify(
    'N7',                          // trigger ID
    'Aurora Alert',                // title
    'Kp 6 detected — good conditions',  // body
    {
        url: '#forecast-astro/aurora',  // hash to navigate on click
        tag: 'aurora-kp6-2026-05-29',  // dedup tag (optional, auto-generated if omitted)
    }
);
// shown: true if notification was displayed, false if blocked/disabled
```

The `url` option maps to a hash fragment. The notification click handler calls `window.location.hash = url` and `window.focus()`.

---

## Adding a new trigger

1. Add the ID to `NOTIF_TRIGGERS` in `notifications.js`
2. Add default prefs to `_NOTIF_DEFAULTS.triggers` in `notifications.js`
3. Add a row to the settings UI in `index.html` (`#notif-triggers-list`)
4. Add i18n key `settings.notifications_nX` to all 6 language files
5. Add the detection logic in the relevant feature module (see below)
6. Update the trigger table in this document

---

## Wiring triggers — implementation pattern

Each trigger lives in the module that already owns the relevant data. The pattern is always:

```javascript
// 1. After fetching/computing the relevant data...
// 2. Check if the condition is met
// 3. Guard with wasRecentlyNotified to prevent spam
// 4. Call notify()

// Example: N7 Aurora in aurora.js
function _checkAuroraNotification(kpValue) {
    if (!notificationManager.isTriggerEnabled('N7')) return;
    if (kpValue < notificationManager.getKpThreshold()) return;
    if (notificationManager.wasRecentlyNotified('N7', 30 * 60 * 1000)) return;

    notificationManager.notify(
        'N7',
        i18n.t('notifications.aurora_title'),   // "Aurora Alert"
        i18n.t('notifications.aurora_body', { kp: kpValue }),
        { url: '#forecast-astro/aurora' }
    );
}
```

### Module assignments

| Trigger | Module | Data source |
|---------|--------|-------------|
| `N1` | `plan_my_night.js` | `payload.timeline.start` (ISO string) |
| `N2` | `plan_my_night.js` | `payload.plan.entries[].start_time` |
| `N3` | `iss.js` | `data.solar_transits` / `data.lunar_transits` (next upcoming) |
| `N4` | `lunar_eclipse.js` or `events_alerts.js` | Eclipse totality time from events API |
| `N5` | `solar_eclipse.js` or `events_alerts.js` | Eclipse maximum time from events API |
| `N6` | `sun.js` | `data.astronomical_twilight_end` |
| `N7` | `aurora.js` | Current Kp index from aurora API |

---

## Settings UI

Located at **My Settings → Notifications** (`#notifications-subtab`).

Initialized by `initNotificationSettingsUI()` (called from `app.js → switchSubTab`).

### Elements

| ID | Type | Role |
|----|------|------|
| `#notif-permission-banner` | `div.alert` | Shows current permission state |
| `#notif-enable-btn` | `button` | Calls `requestPermission()`, hidden when granted/denied |
| `#notif-master-toggle` | `input[type=checkbox]` | Master enable/disable |
| `#notif-trigger-N1` … `#notif-trigger-N7` | `input[type=checkbox]` | Per-trigger toggle |
| `#notif-lead-N1` … `#notif-lead-N6` | `select` | Lead time in minutes |
| `#notif-kp-threshold` | `select` | Kp threshold (N7 only) |
| `#notif-save-btn` | `button` | Saves prefs to localStorage |
| `#notif-test-btn` | `button` | Fires a sample notification |
| `#notif-save-message` | `div.alert` | Success/error feedback (auto-hides after 3 s) |

---

## Phase C — Web Push (future)

When implementing background push:

1. Generate a VAPID key pair once at startup (never regenerate — invalidates all existing subscriptions)
2. Expose the public key via `GET /api/push/vapid-public-key`
3. After `requestPermission()` is granted, call `pushManager.subscribe()` and `POST /api/push/subscribe`
4. Add `push` and `notificationclick` event listeners to `sw.js`
5. Backend evaluates all triggers on a schedule and sends push to subscribed users

Push payload shape (matches Phase A notification options):
```json
{
  "title": "Plan starts in 15 min",
  "body": "Your observation session begins at 22:30",
  "icon": "/static/ico/android/launchericon-192x192.png",
  "badge": "/static/ico/android/launchericon-72x72.png",
  "data": { "url": "#plan-my-night" },
  "tag": "N1-2026-05-29"
}
```

DB table required:
```sql
push_subscriptions(id, user_id, endpoint TEXT UNIQUE, p256dh TEXT, auth TEXT, created_at)
```

Python dependency: `pywebpush`
