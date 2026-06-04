# 🔭 MyAstroBoard

**A self-hosted astronomy dashboard for observation planning and astrophotography management.**

MyAstroBoard combines weather analysis, automated sky calculations, and planning tools into a single Docker-first application - designed for amateur astronomers who want full control over their data.

![Demo MyAstroBoard](https://raw.githubusercontent.com/myastroboard/myastroboard/main/docs/img/overview.gif)

---

## ✨ Features

- **SkyTonight** - Automated deep-sky object calculations based on your location and constraints, running twice daily (after astronomical dusk and before astronomical dawn)
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

For complete installation instructions, see the [Installation Guide](https://github.com/myastroboard/myastroboard/blob/main/docs/1.INSTALLATION.md).

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

---

## 📚 Documentation

- [Installation Guide](https://github.com/myastroboard/myastroboard/blob/main/docs/1.INSTALLATION.md)
- [Quick Start](https://github.com/myastroboard/myastroboard/blob/main/docs/2.QUICKSTART.md)
- [Update Guide](https://github.com/myastroboard/myastroboard/blob/main/docs/3.UPDATE.md)
- [Reverse Proxy Setup](https://github.com/myastroboard/myastroboard/blob/main/docs/6.REVERSE_PROXY.md)
- [API Endpoints](https://github.com/myastroboard/myastroboard/blob/main/docs/API_ENDPOINTS.md)
- [Visual Tour](https://github.com/myastroboard/myastroboard/blob/main/docs/VISUAL_TOUR.md)

---

## 🐛 Support

Issues and feature requests: [GitHub Issues](https://github.com/myastroboard/myastroboard/issues)

## 📄 License

Licensed under [AGPL-3.0](https://github.com/myastroboard/myastroboard/blob/main/LICENSE).
Source code available at: [github.com/myastroboard/myastroboard](https://github.com/myastroboard/myastroboard)
