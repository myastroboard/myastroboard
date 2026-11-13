# My settings

Every account has its own preferences, in the **My settings** tab. They follow the account on every
device and never affect other users. Instance-wide settings are in App settings, for administrators
([CONFIGURATION.md](CONFIGURATION.md)).

## Customize

| Setting | Choices | What it does |
|---|---|---|
| Startup tab and sub-tab | any tab | What opens after you sign in |
| Time format | Auto, 24h, 12h | *Auto* follows the browser's language |
| Density | Comfortable, Compact | Compact fits more rows, useful on a phone |
| Theme | Auto, Light, Dark, Red Light | *Red Light* keeps your eyes dark-adapted at the telescope; *Auto* follows the device |
| First day of the week | Monday, Sunday | Calendars and date pickers |
| Experience level | Beginner, Intermediate, Advanced | Filters "Tonight for you" and the Beginner Catalog by difficulty ([BEGINNER_EXPERIENCE.md](BEGINNER_EXPERIENCE.md)) |
| Beginner Catalog | on / off | Shows the Beginner sub-tab in SkyTonight |
| "Tonight for you" | on / off | Recommended targets at the top of SkyTonight -> Deep Sky Objects |
| Publish my activity to Home Assistant | on / off (off by default) | Creates a Home Assistant device with your own Astrodex counters, tonight's plan and your log totals, when the administrator runs the MQTT connector ([HOME_ASSISTANT.md](HOME_ASSISTANT.md)) |

**Reset to defaults** restores every choice above. The interface language is picked in the footer
and is remembered for the account too.

## Location

The locations an administrator gave you access to ([LOCATIONS.md](LOCATIONS.md)):

- **Default location**: the one every tab uses when you sign in.
- **Order**: the order of the quick switcher in the sky status widget, where you change the active
  location for the current session.

## Notifications

Which alerts you receive, how long before each event, and on which locations. Not available on a
demo instance. See [NOTIFICATIONS.md](NOTIFICATIONS.md), and [MOBILE.md](MOBILE.md) for phones.

## Security

- **Change password**.
- **Two-factor authentication**: turn on an authenticator app (TOTP), when the administrator allows
  it ([AUTHENTICATION.md](AUTHENTICATION.md#two-factor-authentication)).
- **Download my data**: a ZIP with everything the instance stores about you - account,
  preferences, Astrodex, equipment, plans, observation log, wishlist, pictures and attachments
  ([PRIVACY.md](PRIVACY.md)).

## Reference

The preferences are stored on the account (`users` table, `preferences`) and saved with
`PUT /api/auth/preferences`; the full key list and allowed values are in
[AUTHENTICATION.md](AUTHENTICATION.md#user-preferences).
