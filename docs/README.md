# MyAstroBoard Documentation

Welcome to the comprehensive documentation for MyAstroBoard, the integrated astronomy observation planning system.

> [!NOTE]
> Some part of the documentation can be generated with IA. 
> 
> Why ? Probably because this is one of the least interesting thing to do, but one of the most important part!

## 📚 Documentation Index

### Getting Started
- [Installation Guide](1.INSTALLATION.md) - How to install and run MyAstroBoard
- [Quick Start](2.QUICKSTART.md) - Get up and running in 5 minutes
- [Updating](3.UPDATE.md) - How to update to new versions

### Deployment & Security
- [Reverse Proxy & HTTPS Setup](6.REVERSE_PROXY.md) - Deploy behind NGINX Proxy Manager, Traefik, or other reverse proxies with HTTPS

### For Maintainers
- [Release Guide](4.RELEASE.md) - How to publish new versions and create releases
- [Translation](7.TRANSLATIONS.md) - How to contribute in translation 

### Advanced Topics
- [Organization](5.ORGANIZATION.md) - How the repo is organized
- [API Endpoints](API_ENDPOINTS.md) - Complete route inventory from backend/app.py
- [Plan My Night](PLAN_MY_NIGHT.md) - Night planning workflow and permissions
- [Cache System](CACHE_SYSTEM.md) - Understanding the caching architecture
- [SkyTonight](SKYTONIGHT.md) - Skytonight calculation & astroscore description
- [Exposure Calculator](EXPOSURE_CALC.md) - Formula and calibration for the Equipment exposure calculator
- [Visual Tour](VISUAL_TOUR.md) - Screenshots and feature walkthrough

## 🚀 Quick Links

- **Installation**: `docker compose up -d`
- **Access Dashboard**: http://localhost:5000
- **Update**: `docker compose pull && docker compose up -d`
- **GitHub Repository**: https://github.com/WorldOfGZ/myastroboard
- **Report Issues**: https://github.com/WorldOfGZ/myastroboard/issues

## 📄 License

MyAstroBoard is open source software licensed under the AGPL-3.0 License.
Copyright (C) 2025-2026 WorldOfGZ and contributors.

In accordance with AGPL-3.0 requirements for network use, the corresponding source code for deployed versions is available in this repository:
https://github.com/WorldOfGZ/myastroboard

