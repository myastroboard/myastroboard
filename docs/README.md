# MyAstroBoard Documentation

> [!NOTE]
> Some parts of the documentation may be generated with AI.
>
> Why? Documentation is one of the least exciting tasks, but one of the most important.

The pages are grouped by who reads them: **using** MyAstroBoard, **running** an instance, and
**contributing** to the code. Not sure where a screen is documented? See
[Where is it?](#where-is-it) below.

## Using MyAstroBoard

### Getting started

- [Quick Start](2.QUICKSTART.md) - from a fresh install to your first night plan
- [Visual Tour](VISUAL_TOUR.md) - every tab, with screenshots
- [Beginner Experience](BEGINNER_EXPERIENCE.md) - setup wizard, difficulty ratings, "Tonight for you", Beginner Catalog
- [Glossary](GLOSSARY.md) - AstroScore, airmass, Bortle, seeing and the other terms on screen
- [My settings](USER_SETTINGS.md) - theme, startup tab, locations, notifications, password and 2FA, your data
- [Phones and tablets](MOBILE.md) - install the app, offline page, push notifications

### Tonight

- [Astrophotography tab](ASTROPHOTOGRAPHY.md) - best imaging window, Moon, Sun, aurora, events calendar
- [Weather](WEATHER.md) - Open-Meteo forecast, 7Timer seeing, astro-analysis, alerts
- [SkyTonight](SKYTONIGHT.md) - targets, AstroScore, catalogues, visibility calendar, framing simulator
- [Spaceflight](SPACEFLIGHT.md) - launches, astronauts, ISS and CSS passes and transits

### Planning and logging

- [Plan My Night](PLAN_MY_NIGHT.md) - the night's timeline, optimizer, exports
- [Observation Log](OBSERVATION_LOG.md) - one record per night, what you shot and in which conditions
- [Astrodex](ASTRODEX.md) - your collection of imaged objects, pictures, Photo Map, Catalogue Collection
- [Your Sky and Wishlist](SESSION_ANALYTICS.md) - progress, sky coverage, best months, what to image next
- [Share Cards](SHARE_CARDS.md) - ready-to-post images of a picture, a session, tonight's sky or an event

### Equipment

- [Equipment](EQUIPMENT.md) - telescopes, cameras, mounts, filters, combinations, FOV, sharing
- [Exposure Calculator](EXPOSURE_CALC.md) - sub-exposure length, sky background, integration time

### Observatory and integrations

- [Observatory](OBSERVATORY.md) - live AllSky image, keogram, timelapse, sensor data
- [Home Assistant](HOME_ASSISTANT.md) - sky conditions, targets, events and your activity as Home Assistant devices
- [Astrodex Stream](ASTRODEX_STREAM.md) - your Astrodex as a Home Assistant camera
- [MyAstroShine](MYASTROSHINE.md) - send a picture out for re-processing, get the result back

## Running an instance

- [Installation](1.INSTALLATION.md) - Docker, Home Assistant app, system requirements
- [Updating](3.UPDATE.md) - update notice, update, back up, roll back
- [Reverse Proxy & HTTPS](6.REVERSE_PROXY.md) - NGINX Proxy Manager, Traefik, secure cookies
- [Troubleshooting](TROUBLESHOOTING.md) - common problems and how to report one
- [Configuration](CONFIGURATION.md) - the App settings tab: constraints, application settings, backup, logs, metrics
- [Locations](LOCATIONS.md) - up to five location presets, attribution, per-user active location
- [Users and authentication](AUTHENTICATION.md) - roles, sessions, trusted networks, two-factor authentication
- [Connectors](CONNECTORS.md) - AllSky, MQTT, MyAstroShine and Astrodex Stream setup
- [Notifications](NOTIFICATIONS.md) - browser and Web Push notifications (triggers N1-N9, VAPID, iOS)
- [Database](DATABASE.md) - SQLite storage, upgrade from 1.6, recovery command line
- [Privacy & GDPR](PRIVACY.md) - personal data inventory, third parties, retention, user rights
- [Demo Mode](DEMO_MODE.md) - a public, read-only demo instance
- [Security policy](../SECURITY.md) - security model, reporting a vulnerability

## Contributing

- [Contributing guide](../CONTRIBUTING.md) - setup, style, tests, pull requests
- [Organization](5.ORGANIZATION.md) - architecture, source tree, runtime data
- [Extending MyAstroBoard](EXTENDING.md) - extension points and the no-new-dependency-cycles rule
- [API Endpoints](API_ENDPOINTS.md) - every HTTP route
- [Cache System](CACHE_SYSTEM.md) - background cache, per-job TTLs, per-location slots, map tiles
- [Translations](7.TRANSLATIONS.md) - adding or improving a language
- [Release Guide](4.RELEASE.md) - publishing a version
- [Changelog](../CHANGELOG.md) - released and unreleased changes

## Where is it?

| Tab | Sub-tab | Page |
|---|---|---|
| Astrophotography | Astrophotography, Best window, Moon, Sun, Aurora Borealis, Events Calendar | [ASTROPHOTOGRAPHY.md](ASTROPHOTOGRAPHY.md) |
| Weather | Weather, Seeing Forecast, Observation Conditions | [WEATHER.md](WEATHER.md) |
| SkyTonight | Plot, Deep Sky Objects, Solar System Bodies, Comets, Logs, DSO not found? | [SKYTONIGHT.md](SKYTONIGHT.md) |
| SkyTonight | Beginner | [BEGINNER_EXPERIENCE.md](BEGINNER_EXPERIENCE.md) |
| Astrodex | Astrodex, Photo Map, Catalogue Collection | [ASTRODEX.md](ASTRODEX.md) |
| Astrodex | Plan my night | [PLAN_MY_NIGHT.md](PLAN_MY_NIGHT.md) |
| Astrodex | Observation Log | [OBSERVATION_LOG.md](OBSERVATION_LOG.md) |
| Astrodex | Your Sky, Wishlist | [SESSION_ANALYTICS.md](SESSION_ANALYTICS.md) |
| Spaceflight | Launches, Astronauts, Space Events, Orbital Stations | [SPACEFLIGHT.md](SPACEFLIGHT.md) |
| Observatory | (appears with a connector) | [OBSERVATORY.md](OBSERVATORY.md) |
| Equipment | Combinations, FOV Calculator, Telescopes, Cameras, Mounts, Filters, Accessories | [EQUIPMENT.md](EQUIPMENT.md) |
| Equipment | Exposure Calc | [EXPOSURE_CALC.md](EXPOSURE_CALC.md) |
| My settings | Customize, Location, Notifications, Security | [USER_SETTINGS.md](USER_SETTINGS.md) |
| App settings | Locations | [LOCATIONS.md](LOCATIONS.md) |
| App settings | Configuration, Logs, Metrics, Backup / Restore | [CONFIGURATION.md](CONFIGURATION.md) |
| App settings | Connectors | [CONNECTORS.md](CONNECTORS.md) |
| App settings | Users | [AUTHENTICATION.md](AUTHENTICATION.md) |
| Header | Sky status widget, location switcher | [LOCATIONS.md](LOCATIONS.md) |
| Footer | Update notice, *What's new* | [3.UPDATE.md](3.UPDATE.md) |
| Several | Framing simulator | [SKYTONIGHT.md](SKYTONIGHT.md#framing-simulator) |
| Several | Share cards | [SHARE_CARDS.md](SHARE_CARDS.md) |

## Quick links

- **Install**: `docker compose up -d`, then open http://localhost:5000
- **Default credentials**: `admin` / `admin` (change them at once)
- **Update**: `docker compose pull && docker compose up -d`
- **Source code**: https://github.com/myastroboard/myastroboard
- **Report an issue**: https://github.com/myastroboard/myastroboard/issues

## License

MyAstroBoard is open source software licensed under the AGPL-3.0 License.
Copyright (C) 2025-2026 WorldOfGZ and contributors.

In accordance with AGPL-3.0 requirements for network use, the corresponding source code for deployed versions is available in this repository:
https://github.com/myastroboard/myastroboard
