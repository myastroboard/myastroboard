# MyAstroBoard - Roadmap

This document describes features that could potentially be integrated into MyAstroBoard. There are no guarantees; consider this file a list of ideas that may evolve based on my own ideas or future discussions.

## 🗓️ Release Plan

### v1.0 - Stabilization & Overall Quality
**Objective: First stable release + smooth user experience**
- Stabilization of critical bugs
- Improved mobile interface (responsive)

## New Features

### Multilocation
**Add multiple location possible**
- Location configurable by an admin
- Each location can be attributed to individual users
- Location are stored in uuid
- Limit to X location (check with weather api limit call)
- Cache scheduler & SkyTonight scheduler by location
- Switch to select location on main page with persistant selection between main-tabs (astro, weather, SkyTonight)
- Add location field to astrodex
- User can order as he want location on it's profile

### User profile
- Notification (when/if available in future)

## Upgrade Features

### Various
- Manage old cache files myastroboard.log.1, myastroboard.log.2, ...
- Improve moon_report calculation using vectorized Astropy (batch time grid) to compute all altitudes at once

### Shared equipments
**Possibility to share equipments between users**, for example family, or astronomy club.
- Equipements could be shared between users
- Each elements can have checkbox to allow share (default false)
- For a mount is automatically shared, only if all equipments inside are "shared true"
- Special label "Shared" on each equipement to see them.

### PWA application
**Objective: Real PWA application for mobile**
- PWA notifications for improving conditions (weather, ... ?)

### Ideas in raw
1	Bortle/SQM in AstroScore    Low	        High — corrects score_object for light pollution
2	Solar elongation filter     Low	        Medium — correctness for planets
