# Phones and Tablets

MyAstroBoard works in any modern mobile browser, and can be installed as an app (a Progressive Web
App) for a full-screen window, an icon on the home screen, an offline page, and push
notifications.

## Requirements

Browsers only allow installation, offline support and notifications on a **secure address**:

| Address | Install, offline page, notifications |
|---|---|
| HTTPS (behind a reverse proxy, see [6.REVERSE_PROXY.md](6.REVERSE_PROXY.md)) | Yes |
| `http://localhost` | Yes |
| Plain HTTP on the network (`http://192.168.1.10:5000`) | No - the site works, but as a plain web page |
| Home Assistant sidebar panel | No - use the Home Assistant app on the phone, and the MQTT connector for alerts ([HOME_ASSISTANT.md](HOME_ASSISTANT.md)) |

## Installing the app

**Android (Chrome, Edge, Samsung Internet)**: an **Install** button appears in the footer when the
browser allows it; otherwise use the browser menu -> *Install app* or *Add to Home screen*.

**iPhone and iPad (Safari)**: tap **Share** -> **Add to Home Screen**, then open MyAstroBoard from
the new icon. Push notifications on iOS need Safari 16.4 or later and only reach the installed app,
never a Safari tab.

**Desktop (Chrome, Edge)**: the install icon in the address bar, or the **Install** button in the
footer.

## Offline

The installed app keeps its shell (pages, styles, translations, icons) on the device. When the
server cannot be reached, an offline page appears and retries the connection every 30 seconds. Data
(forecasts, targets, your Astrodex) always comes from the server: nothing is edited offline.

## Notifications

1. Open **My settings -> Notifications** on the device that should receive them, allow
   notifications when the browser asks, and pick the alerts you want (plan start, ISS and CSS transits,
   eclipses, nightfall, aurora, meteor showers...).
2. Tap **Test**: it sends a real push through the server. On iOS, background or lock the app right
   after tapping to see it.
3. Each device subscribes on its own; the preferences are shared by all your devices.

The administrator must set a real contact email in App settings -> Configuration -> Notifications,
or Apple drops every push. Full reference: [NOTIFICATIONS.md](NOTIFICATIONS.md).

## At the telescope

- **Red Light** theme (My settings -> Customize) keeps your eyes dark-adapted.
- **Compact** density fits more rows on a small screen.
- Set the **startup tab** to the one you open first, Plan My Night for example
  ([USER_SETTINGS.md](USER_SETTINGS.md)).
