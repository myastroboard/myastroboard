# MyAstroBoard Documentation

Welcome to the comprehensive documentation for MyAstroBoard, the integrated astronomy observation planning system.

> [!NOTE]
> Some parts of the documentation may be generated with AI.
> 
> Why? Documentation is one of the least exciting tasks, but one of the most important.

## 📚 Documentation Index

### Getting Started
- [Installation Guide](1.INSTALLATION.md) - How to install and run MyAstroBoard
- [Quick Start](2.QUICKSTART.md) - Get up and running in 5 minutes
- [Updating](3.UPDATE.md) - How to update to new versions
- [Visual Tour](VISUAL_TOUR.md) - Screenshots and feature walkthrough

### Deployment & Security
- [Reverse Proxy & HTTPS Setup](6.REVERSE_PROXY.md) - Deploy behind NGINX Proxy Manager, Traefik, or other reverse proxies with HTTPS

### Features

#### Astrophotography & Planning
- [Astrophotography Tab](ASTROPHOTOGRAPHY.md) - Best imaging window, Moon, Sun, Aurora, celestial events — formulas and calculations
- [SkyTonight](SKYTONIGHT.md) - SkyTonight calculation engine, AstroScore formula, catalogues, and scheduler
- [Plan My Night](PLAN_MY_NIGHT.md) - Night planning workflow, permissions, and exports
- [Exposure Calculator](EXPOSURE_CALC.md) - Sub-exposure formula, sky background rate, Bortle→SQM table

#### Weather & Conditions
- [Weather & Conditions](WEATHER.md) - Open-Meteo weather, 7Timer seeing forecast, astro-analysis metrics, alerts

#### Collection & Equipment
- [Astrodex](ASTRODEX.md) - Personal astrophotography logbook: data model, image management, catalogue integration
- [Equipment Profiles](EQUIPMENT.md) - Telescopes, cameras, mounts, filters, FOV calculator formulas, equipment sharing

#### Spaceflight
- [Spaceflight Tracker](SPACEFLIGHT.md) - Rocket launches, astronauts, ISS pass prediction (SGP4 algorithm), space events

#### Observatory & Connectors
- [Observatory](OBSERVATORY.md) - Live dashboard fed by external connectors (AllSky panels, sensor data, keogram, timelapse)
- [Connectors](CONNECTORS.md) - Connector architecture, AllSky setup, module reference, and how to add a new connector

### Administration
- [Authentication & Users](AUTHENTICATION.md) - Roles, user management, preferences, session security
- [Configuration](CONFIGURATION.md) - Location setup, SkyTonight constraints, horizon profile, backup/restore, logs, metrics

### Technical Reference
- [API Endpoints](API_ENDPOINTS.md) - Complete route inventory from `backend/app.py` and `backend/skytonight_api.py`
- [Cache System](CACHE_SYSTEM.md) - Cache architecture, per-job TTLs, selective refresh, location change detection
- [Notifications](NOTIFICATIONS.md) - Browser and Web Push notification system (N1–N7 triggers, VAPID, iOS)

### For Contributors
- [Release Guide](4.RELEASE.md) - How to publish new versions and create releases
- [Translation](7.TRANSLATIONS.md) - How to contribute translations
- [Organization](5.ORGANIZATION.md) - Repository and runtime data organization

---

## 🚀 Quick Links

- **Installation**: `docker compose up -d`
- **Access Dashboard**: http://localhost:5000
- **Default credentials**: `admin` / `admin` (change immediately)
- **Update**: `docker compose pull && docker compose up -d`
- **GitHub Repository**: https://github.com/myastroboard/myastroboard
- **Report Issues**: https://github.com/myastroboard/myastroboard/issues

---

## 🔭 Feature Map

| Feature | Tab | Key doc |
|---------|-----|---------|
| Best imaging window | Astrophotography → Window | [ASTROPHOTOGRAPHY.md](ASTROPHOTOGRAPHY.md) |
| Moon phase & planner | Astrophotography → Moon | [ASTROPHOTOGRAPHY.md](ASTROPHOTOGRAPHY.md) |
| Sun & twilight times | Astrophotography → Sun | [ASTROPHOTOGRAPHY.md](ASTROPHOTOGRAPHY.md) |
| Aurora forecast | Astrophotography → Aurora | [ASTROPHOTOGRAPHY.md](ASTROPHOTOGRAPHY.md) |
| Celestial events | Astrophotography → Calendar | [ASTROPHOTOGRAPHY.md](ASTROPHOTOGRAPHY.md) |
| Weather forecast | Weather → Weather | [WEATHER.md](WEATHER.md) |
| Seeing forecast | Weather → Seeing | [WEATHER.md](WEATHER.md) |
| Target catalogue & AstroScore | SkyTonight | [SKYTONIGHT.md](SKYTONIGHT.md) |
| Night planning | Astrodex → Plan My Night | [PLAN_MY_NIGHT.md](PLAN_MY_NIGHT.md) |
| Astrophotography log | Astrodex | [ASTRODEX.md](ASTRODEX.md) |
| Equipment & FOV | Equipment | [EQUIPMENT.md](EQUIPMENT.md) |
| Exposure calculation | Equipment → Exposure Calc | [EXPOSURE_CALC.md](EXPOSURE_CALC.md) |
| Launches & astronauts | Spaceflight | [SPACEFLIGHT.md](SPACEFLIGHT.md) |
| ISS passes | Spaceflight → ISS | [SPACEFLIGHT.md](SPACEFLIGHT.md) |
| AllSky live image & data | Observatory | [OBSERVATORY.md](OBSERVATORY.md) |
| External connectors setup | Parameters → Connectors | [CONNECTORS.md](CONNECTORS.md) |
| Push notifications | My Settings → Notifications | [NOTIFICATIONS.md](NOTIFICATIONS.md) |
| User roles | Parameters → Users | [AUTHENTICATION.md](AUTHENTICATION.md) |
| Location & constraints | Parameters → Configuration | [CONFIGURATION.md](CONFIGURATION.md) |
| Cache & metrics | Parameters → Metrics | [CACHE_SYSTEM.md](CACHE_SYSTEM.md) |
| Backup & restore | Parameters → Backup | [CONFIGURATION.md](CONFIGURATION.md) |

---

## 📄 License

MyAstroBoard is open source software licensed under the AGPL-3.0 License.
Copyright (C) 2025-2026 WorldOfGZ and contributors.

In accordance with AGPL-3.0 requirements for network use, the corresponding source code for deployed versions is available in this repository:
https://github.com/myastroboard/myastroboard
