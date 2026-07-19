# 📸 MyAstroBoard - Visual Tour

A visual walkthrough of MyAstroBoard's interface and capabilities - from your first clear-sky forecast to tracking who is orbiting Earth right now.

## Table of Contents
1. [Dashboard](#dashboard)
2. [Astrophotography](#astrophotography)
3. [Weather & Conditions](#weather--conditions)
4. [SkyTonight](#skytonight)
5. [Plan My Night](#plan-my-night)
6. [Astrodex Collections](#astrodex-collections)
7. [Spaceflight](#spaceflight)
8. [Equipment Profiles](#equipment-profiles)
9. [Administration](#administration)
10. [Advanced Features](#advanced-features)

---

## Dashboard

Your command center for all astronomy activities. At a glance, you get current observation conditions, upcoming clear windows, and quick access to every feature - all in one place.

![MyAstroBoard Home](img/overview.gif)

---

## Astrophotography

The heart of MyAstroBoard. Everything you need to decide whether tonight is worth setting up the telescope.

### Astrophotography Advanced Information
Key metrics and detailed weather analysis through an astrophotographer's lens - transparency, seeing, wind, humidity, and more.

![Astrophoto Info](img/astrophoto_main.png)

### Alerts & Advanced Weather Analysis
Comprehensive weather alerts and advanced forecast charts so you can plan your sessions with confidence, even days ahead.

![Advanced Weather Charts](img/weather_main_alerts.png)

### Moon Information
Detailed lunar positions, phases, rise/set times, and altitude charts. Future events like supermoons and lunar eclipses are highlighted automatically.

![Moon](img/astrophoto_moon.png)

### Sun Information
Solar positions, phases, rise/set times, and altitude charts. Twilight windows and future solar events are calculated for your location.

![Sun](img/astrophoto_sun.png)

### Aurora Borealis
Real-time Kp index, geomagnetic activity forecast, and a visibility assessment tailored to your latitude - so you never miss the northern lights.

![Aurora](img/astrophoto_aurora.png)

### Celestial Events
An exhaustive list of upcoming sky events - conjunctions, oppositions, meteor showers, and more - with key parameters to help you prioritize what to observe.

![Events](img/astrophoto_events.png)

---

## Weather & Conditions

### Weather Forecast
Full weather breakdown optimized for night-time astronomy: temperature curves, precipitation probability, cloud cover layers, and atmospheric pressure - all in a single view.

![Weather Dashboard](img/weather_weather.png)

### 7Timer Integration
Seeing and transparency data from 7Timer, rendered directly for your observation location for a quick go/no-go decision.

![7timer](img/weather_7timer.png)

### Observation Conditions Monitor
Time-series graphs of atmospheric conditions - transparency, seeing, jet stream influence - so you can identify the sweet spot of your night.

![Observation Conditions](img/weather_observations.png)

---

## SkyTonight

SkyTonight automatically calculates the best targets for the coming night and scores them with an **AstroScore** based on altitude, darkness, and your equipment. It also generates altitude-over-time charts and respects your custom horizon profile.

### Plot Graph

An interactive scatter plot of every object visible tonight - hover any point for instant details, or click to open the full altitude chart.

![Plot](img/skytonight_plot.png)

### Deep Sky Objects Catalogue
Thousands of deep-sky objects from multiple catalogues, scored and sorted. Filter by type, size, magnitude, or AstroScore to build your target list in seconds.

![Deep Sky Objects](img/skytonight_dso.png)

### Celestial Bodies
Planets, asteroids, and other solar system objects with rise/set times, magnitude, angular size, and observability ratings - updated nightly.

![Bodies](img/skytonight_bodies.png)

### Comets
Currently observable comets ranked by visibility, with ephemeris data and altitude charts updated from live orbital elements.

![Comets](img/skytonight_comets.png)

### Altitude Charts
Interactive altitude-vs-time charts for every DSO, body, and comet. Spot the exact window when your target peaks above the horizon - and above your custom horizon mask.

![Altitude Chart](img/skytonight_alttime_popup.png)

---

## Plan My Night

### Build and Follow Your Night Session Timeline
Plan My Night turns your SkyTonight shortlist into a structured observation schedule. Set durations, drag to reorder, and follow along live as the night progresses - with a visual progress bar showing how much of the dark window you've used.

Built for real field use: readable in low light, quick to update, and exportable for your records.

Shared telescopes (see [Sharing Equipment](#sharing-equipment--perfect-for-families--astronomy-clubs)) appear in the telescope selector alongside your own, so every club member can plan their session around the shared club scope without needing to duplicate it in their own profile.

![Plan My Night](img/astrodex_plan_my_night.png)

---

## Astrodex Collections

### Your Astrophotography Logbook
Astrodex is your personal tracker for every object you've imaged. Browse your collection with rich metadata - coordinates, capture date, equipment, conditions, and your own notes.

![Astrodex Collection](img/astrodex_astrodex.png)

### Object Editor
Log every detail of a capture session:
- Target name, coordinates, and catalogue reference
- Capture date and equipment profile used
- Exposure settings: shutter speed, ISO, aperture
- Atmospheric conditions: seeing, transparency, temperature
- Processing notes and ideas for the next session

![Astrodex Editor](img/astrodex_astrodex_edit.png)

---

## Equipment Profiles

Build a complete catalogue of your gear. Equipment profiles pre-fill fields across Astrodex and feed the SkyTonight scoring engine.

![Equipment combination](img/equipment_combinations.png)

SkyTonight uses your active equipment combination to weight the AstroScore - a rich-field refractor and a long focal-length SCT will see different "best targets" for the same sky.

![Equipment rate](img/skytonight_more_info.png)

### Manage Your Equipment
Track everything in your kit:
- Telescopes & optical tubes
- Cameras (DSLR, mirrorless, dedicated ASI)
- Mounts
- Filters
- Accessories
- **Combine any of the above into a named equipment profile**

![Add telescope](img/equipment_telescopes.png)

![Equipment accessories](img/equipment_accessories_popup.png)

### Sharing Equipment - Perfect for Families & Astronomy Clubs

Every piece of equipment can be marked **"Share with all users"** in its edit form. Shared items are immediately visible to every other user on the instance - without any configuration on their side.

**What sharing looks like:**
- Shared items appear in other users' equipment tabs under a *"Shared by Others"* section, clearly labelled with the owner's name. They are **read-only** for non-owners - nobody can accidentally change your gear settings.
- Your own shared items show a **Shared** badge so you always know what you've made available.
- **Equipment combinations** inherit shared status automatically: a combination is flagged *Shared* only when every piece of equipment it references (telescope, camera, mount, filters, accessories) is individually shared. If one item later becomes private, the combination shows a ⚠ warning.

**Shared equipment flows through the whole app:**

| Feature | What you get |
|---------|-------------|
| **Field of View Calculator** | Shared telescopes & cameras appear in the dropdowns, labelled *(shared by X)* |
| **SkyTonight - Best Equipment For This Target** | Recommendations include shared equipment combinations. Own combinations are listed first. |
| **Astrodex - Add Picture** | Shared equipment combinations and filters appear in the selection dropdowns. |
| **Plan My Night** | Shared telescopes appear in the telescope selector (own first, then shared), so any member can plan a session around the club's scope. |

**When a shared telescope is removed or made private:**
Any observation plan built around it is preserved intact and shown with a ⚠ *"telescope no longer available"* warning. Nothing is deleted silently - the user can review the plan and decide what to do with it.

> **Typical use cases:** A family where one member owns the mount and another owns the camera; an astronomy club with shared club equipment alongside members' personal gear; a pair of astrophotographers splitting a filter set.

---

## Spaceflight

**For space enthusiasts - stay connected to what's happening above the atmosphere.**

### Launches
Upcoming and recent launches from every major agency and operator. Open any launch for a detailed breakdown, and watch the live webcast directly inside the app when a stream is available.

![Launches](img/spaceflight_launches.png)

![Launch detail](img/spaceflight_launches_popup.png)

### Astronauts in Space
See exactly who is orbiting Earth right now, which vehicle they arrived in, their mission role, and how long they've been up there.

![Astronauts](img/spaceflight_astronauts.png)

### Space Events
Mission milestones, EVAs, dockings, and other spaceflight events - curated so you can follow the story behind the launches.

![Space events](img/spaceflight_spaceevents.png)

### ISS Passes
Precise ISS fly-over predictions for your location: azimuth, elevation, duration, and a brightness estimate. Never miss a visible pass again.

![ISS](img/spaceflight_iss.png)

---

## Administration

### User Settings
Each user can personalise their experience: startup tab, display density, time format, and colour theme.

![User settings](img/user_custom.png)

### Global & Advanced Settings
Configure MyAstroBoard for your site: coordinates, timezone, catalogue paths, and low-level tuning options.

![Param settings](img/params_settings.png)

![Advanced settings](img/params_advanced.png)

### User Management
Create and manage accounts with role-based access. Assign **read-only** access for household members or guests, or full **admin** rights for yourself.

![Users](img/params_users.png)

### Metrics
Monitor scheduler health, cache job timings, and system performance at a glance.

![Metrics](img/params_metrics.png)

### Backup, Logs & Issue Reporting
One-click backup and restore of your collection and configuration. Browse logs live in the browser and export them as a single file to attach to a GitHub issue.

![Backup](img/params_backup_restore.png)

![Consult logs](img/params_logs.png)

![Export logs](img/params_log_export.png)

---

## Advanced Features

### Smart Scheduling
- Automated SkyTonight runs with configurable intervals
- Per-catalogue processing for multiple target lists
- Weather refresh before each calculation run
- Version notifications and in-app update prompts

### Configuration System
- Simple location and coordinate setup
- Catalogue selection and filtering by type or source
- Custom horizon profile import for obstructed sites

### Data Analytics
- Historical trend analysis across observation sessions
- Observation success rate metrics
- Weather pattern recognition for your location
- Clear-night predictions based on local patterns

### Mobile Responsive
Every feature works on any screen size:
- Desktop computers
- Tablets
- Mobile devices
- Any modern web browser

---

## 🎯 Start Your Journey

New to MyAstroBoard? Here's the quick path to your first observation session:

1. **Install** - See [Installation Guide](1.INSTALLATION.md)
2. **Configure** - Set your location, timezone, and catalogues
3. **Explore** - Browse tonight's targets in SkyTonight
4. **Plan** - Check the weather and build your observation timeline
5. **Track** - Log your captures in Astrodex and grow your collection

---

## 💡 Pro Tips

- Running MyAstroBoard for a family or club? Enable **"Share with all users"** on your common gear - everyone sees it instantly in their equipment, SkyTonight, Astrodex, and Plan My Night, with no duplicate profiles to maintain
- Cross-reference the weather and astrophotography dashboards to find the true sweet spot of a night
- Use altitude charts to avoid slewing to a target that's already past its peak
- Assign an equipment profile before opening SkyTonight - the AstroScore adapts to your focal length and aperture
- Set your startup tab to whichever section you open first every session
- Export your Astrodex before major upgrades as a quick safety backup

---

*Explore the cosmos with MyAstroBoard - your personal astronomy command center.*

