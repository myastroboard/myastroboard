# 🔭 MyAstroBoard

**A self-hosted astronomy dashboard for observation planning and astrophotography management.**

MyAstroBoard combines weather analysis, automated sky calculations, and planning tools into a single Docker-first application - designed for amateur astronomers who want full control over their data.

![Demo MyAstroBoard](https://raw.githubusercontent.com/myastroboard/myastroboard/main/docs/img/overview.gif)

**👉 Try it live: [demo.myastroboard.org](https://demo.myastroboard.org/)** - a public, read-only instance with no sign-in. Everything is live (tonight's sky, the weather, SkyTonight targets), but nothing you change is saved.

---

## ✨ Features

- **SkyTonight** - Automated deep-sky object calculations based on your location and constraints, running twice daily (1 hour after nautical dawn and 1 hour before nautical dusk)
- **Beginner-friendly** - Guided setup wizard, skill-aware "Tonight for you" recommendations, difficulty ratings, and a curated Beginner Catalog
- **Weather & Conditions** - Observing condition analysis powered by Open-Meteo
- **Astronomy Events** - Moon, sun, eclipses, aurora forecasts, ISS passes
- **Astrodex** - Personal astrophotography catalog with image management
- **Plan My Night** - Visual timeline builder with CSV/PDF export
- **Equipment Profiles** - Field-of-view calculator per instrument
- **Multi-user** - Authentication system with admin/user roles
- **i18n** - English, French, and community translations

---

## 🚀 Quick Start

```bash
docker pull myastroboard/myastroboard:latest
```

Full setup with Docker Compose:

```yaml
services:
  myastroboard:
    image: myastroboard/myastroboard:latest
    ports:
      - "5000:5000"
    volumes:
      - ./data:/app/data
    restart: unless-stopped
```

For complete installation instructions, see the [Installation Guide](https://docs.myastroboard.org/1.INSTALLATION.html).

---

## 🐳 Available Tags

| Tag | Description |
|-----|-------------|
| `latest` | Latest stable release |
| `x.y.z` | Specific version (e.g. `0.6.5`) |
| `x.y` | Latest patch of a minor version |
| `x` | Latest minor of a major version |

---

## 🖥️ Supported Platforms

| Platform | Architecture |
|----------|-------------|
| `linux/amd64` | x86_64 - PC, server, most NAS (Synology Intel/AMD) |
| `linux/arm64` | ARM 64-bit - Raspberry Pi 4/5, Apple Silicon |

---

## 📋 Requirements

- Docker and Docker Compose
- Linux host or compatible Docker environment
- At least 1 GB of memory and 1 CPU core for the container ([system requirements](https://docs.myastroboard.org/1.INSTALLATION.html#system-requirements))

---

## 📚 Documentation

Everything is at **[docs.myastroboard.org](https://docs.myastroboard.org/)**. To get started:

- [Installation Guide](https://docs.myastroboard.org/1.INSTALLATION.html)
- [Quick Start](https://docs.myastroboard.org/2.QUICKSTART.html)
- [Update Guide](https://docs.myastroboard.org/3.UPDATE.html)
- [Reverse Proxy Setup](https://docs.myastroboard.org/6.REVERSE_PROXY.html)
- [API Endpoints](https://docs.myastroboard.org/API_ENDPOINTS.html)
- [Visual Tour](https://docs.myastroboard.org/VISUAL_TOUR.html)
- [Beginner Experience](https://docs.myastroboard.org/BEGINNER_EXPERIENCE.html)
- [Troubleshooting](https://docs.myastroboard.org/TROUBLESHOOTING.html)

---

## 🐛 Support

Issues and feature requests: [GitHub Issues](https://github.com/myastroboard/myastroboard/issues)

## 📄 License

Licensed under [AGPL-3.0](https://github.com/myastroboard/myastroboard/blob/main/LICENSE).
Source code available at: [github.com/myastroboard/myastroboard](https://github.com/myastroboard/myastroboard)
