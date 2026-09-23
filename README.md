# MyAstroBoard
![GitHub Release](https://img.shields.io/github/v/release/worldofgz/myastroboard)
[![astropy](https://img.shields.io/badge/powered%20by-AstroPy-orange.svg?style=flat)](https://www.astropy.org/)
[![Docker Pulls](https://img.shields.io/docker/pulls/myastroboard/myastroboard)](https://hub.docker.com/r/myastroboard/myastroboard)
[![Docker Image Size](https://img.shields.io/docker/image-size/myastroboard/myastroboard/latest)](https://hub.docker.com/r/myastroboard/myastroboard)
[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0--or--later-blue.svg)](LICENSE)

MyAstroBoard is a self-hosted astronomy dashboard with Docker-first deployment.
It combines weather and astronomical conditions, automated SkyTonight execution,
and planning tools for observation and astrophotography sessions.

This project is inspired by `mawinkler/uptonight`. Previously this project run UpTonight in Docker CLI to generate data.
Now MyAstroBoard has removed its dependency on UpTonight to better meet its needs and gain full control over display and calculations.

![Demo MyAstroBoard](docs/img/overview.gif)

If you want see more, maybe look at the [visual tour](docs/VISUAL_TOUR.md).

## Features

- SkyTonight integration with automated runs and report/log browsing
- Beginner-friendly: guided setup wizard, skill-aware "Tonight for you" recommendations, difficulty ratings, and a curated Beginner Catalog ([details](docs/BEGINNER_EXPERIENCE.md))
- Weather and observing-condition analysis (Open-Meteo)
- Moon, sun, eclipses, aurora, ISS passes, and astronomy event endpoints
- Astrodex: personal astrophotography catalog and image management
- Observation Log, Your Sky and Wishlist: a private observing logbook, what it adds up to, and what is still on your list ([details](docs/OBSERVATION_LOG.md))
- Plan My Night timeline builder with CSV/PDF export
- Equipment profiles and field-of-view calculator
- Observatory: live dashboard fed by external connectors
- Connectors: AllSky all-sky camera integration (live image, keogram, startrails, timelapse, sensor data)
- Home Assistant: publish sky conditions, weather, tonight's targets and your activity to an MQTT broker with automatic discovery ([details](docs/HOME_ASSISTANT.md))
- Multi-user auth system with admin/user roles
- Multi-location profiles: up to 5 admin-managed observing sites with per-user attribution, one-tap switching, and per-location caches ([details](docs/LOCATIONS.md))
- i18n support (English/French plus community translations)

### A real observing logbook

Plenty of tools tell you what to shoot tonight. MyAstroBoard keeps the other half - what you
actually did, and what it adds up to over the years.

| Question | Answered by |
|---|---|
| "What do I want to shoot tonight?" | **Plan My Night** |
| "What did I actually do on the night of 12 August?" | **Observation Log** |
| "Everything I have ever captured, as a gallery" | **Astrodex** |
| "How is my observing actually going?" | **Your Sky** |
| "What do I still want to capture?" | **Wishlist** |

A **session** is a trip, not a row in a table. It has a location, an equipment combination, and one
or more **nights** - each with its own start and end times and its own measured conditions: SQM,
seeing, transparency, Moon illumination. Under it, one entry per target records the real numbers:
frame count, sub-exposure length, integration minutes, a 0-5 rating and your own notes. A
multi-night dark-sky trip stays a single session. A target you switched telescopes for halfway
through the night carries its own equipment combination.

**Your Sky** reads the whole log back: hours collected month by month, the object types and
constellations you gravitate towards, which gear actually did the work, and how your own ratings
line up against the conditions you recorded - reported honestly, with sample counts, and never
dressed up as a prediction. It also draws every object you have captured onto a sky chart, against
the Milky Way and the ecliptic, each dot sized by the integration time behind it and each reading
back as the month that object is at its best.

Your log is **permanently private**. There is no shared mode and no admin-wide view, even on an
instance where the Astrodex gallery is shared between users. Each session exports to a
print-friendly PDF, and the log, the gallery and the wishlist all travel in the admin backup
archive.

See it in the [visual tour](docs/VISUAL_TOUR.md#your-sky), or read the details in
[docs/OBSERVATION_LOG.md](docs/OBSERVATION_LOG.md) and
[docs/SESSION_ANALYTICS.md](docs/SESSION_ANALYTICS.md).

### Also for space enthusiasts

- **Spaceflight tracker**: upcoming and past rocket launches with video links (via Launch Library 2)
- **ISS real-time tracking**: live ISS position and upcoming visible passes for your location
- **Astronauts in space**: current ISS crew and all humans currently in orbit
- **Space events**: upcoming spacewalks, dockings, and other spaceflight milestones

## Quick Start

- Installation: [docs/1.INSTALLATION.md](docs/1.INSTALLATION.md)
- Quick Start: [docs/2.QUICKSTART.md](docs/2.QUICKSTART.md)
- Update Guide: [docs/3.UPDATE.md](docs/3.UPDATE.md)
- Reverse Proxy: [docs/6.REVERSE_PROXY.md](docs/6.REVERSE_PROXY.md)
- Connectors: [docs/CONNECTORS.md](docs/CONNECTORS.md)
- Home Assistant / MQTT: [docs/HOME_ASSISTANT.md](docs/HOME_ASSISTANT.md)
- API Endpoints: [docs/API_ENDPOINTS.md](docs/API_ENDPOINTS.md)
- Visual Tour: [docs/VISUAL_TOUR.md](docs/VISUAL_TOUR.md)

## SkyTonight Data Model

Execution is done 2 times by day:
- 1 hour after last astronic night
- 1 hour previous next astronimic night

Data generated (table of objects, altitude vs time graph, interactive plot, ...) are based on user location and constrainst.
Deep-sky data is produced from the current SkyTonight/PyOngc pipeline.

## Requirements

- Docker and Docker Compose
- Linux host or compatible Docker environment

Python dependencies are listed in `requirements.txt`.

## Versioning

This project follows Semantic Versioning.
Current version is stored in `VERSION`.
See [CHANGELOG.md](CHANGELOG.md) for released and upcoming changes.

## Contributing

See `CONTRIBUTING.md` and `CODE_OF_CONDUCT.md`.

## License

Licensed under AGPL-3.0.
See `LICENSE` for details.

## Source Code Availability

In accordance with AGPL network-use requirements, source code for deployed versions
is available in this repository:
https://github.com/myastroboard/myastroboard

## Support

Open issues and feature requests on GitHub:
https://github.com/myastroboard/myastroboard/issues
