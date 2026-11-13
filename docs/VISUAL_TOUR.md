# MyAstroBoard - Visual Tour

A walkthrough of MyAstroBoard's interface, tab by tab - from tonight's go/no-go decision to the
logbook of everything you have imaged. Each section links to the page that documents the feature
in full.

![MyAstroBoard overview](img/overview.gif)

## Table of Contents

1. [Astrophotography](#astrophotography)
2. [Weather](#weather)
3. [SkyTonight](#skytonight)
4. [Astrodex](#astrodex)
5. [Spaceflight](#spaceflight)
6. [Observatory](#observatory)
7. [Equipment](#equipment)
8. [My settings](#my-settings)
9. [App settings](#app-settings)
10. [Everywhere](#everywhere)

---

## Astrophotography

Everything you need to decide whether tonight is worth setting up the telescope.
Details: [ASTROPHOTOGRAPHY.md](ASTROPHOTOGRAPHY.md).

### Astrophotography

The night's conditions through an astrophotographer's eyes - clouds, transparency, seeing, wind,
humidity, dew risk - with alerts when something will spoil the session.

![Astrophoto Info](img/astrophoto_main.png)

![Weather alerts](img/weather_main_alerts.png)

### Best window

The best imaging window of the night, computed in three modes: Moon below the
horizon, Moon below 5 degrees, or Moon less than 15% lit.

![Best window](img/astrophoto_best_window.png)

### Moon

Phase, rise and set, altitude chart, dark-sky window, the next nights and a monthly phase calendar.
Lunar eclipses are highlighted.

![Moon](img/astrophoto_moon.png)

### Sun

Twilight times, altitude chart and the next solar eclipse for your location.

![Sun](img/astrophoto_sun.png)

### Aurora Borealis

Kp forecast and a visibility assessment for your latitude.

![Aurora](img/astrophoto_aurora.png)

### Events Calendar

Upcoming sky events - conjunctions, oppositions, meteor showers, eclipses, ISS transits - with the
parameters that help you prioritize them. An event can be turned into a share card.

![Events](img/astrophoto_events.png)

---

## Weather

Details: [WEATHER.md](WEATHER.md).

### Weather

Hourly forecast for the night from Open-Meteo: temperature, precipitation, cloud layers, wind,
pressure.

![Weather Dashboard](img/weather_weather.png)

### Seeing Forecast

Seeing and transparency from 7Timer for your location.

![7timer](img/weather_7timer.png)

### Observation Conditions

Time series of the atmospheric conditions to find the sweet spot of the night.

![Observation Conditions](img/weather_observations.png)

---

## SkyTonight

SkyTonight computes the best targets for the coming night from a dozen catalogues and ranks them
with an **AstroScore** (visibility, sky quality, brightness, comfort). Details:
[SKYTONIGHT.md](SKYTONIGHT.md).

### Plot

A polar map of the sky with the path of every observable target tonight; click a target to
inspect it.

![Plot](img/skytonight_plot.png)

### Deep Sky Objects

Thousands of deep-sky objects, scored and sorted. Filter by type, size, magnitude, constellation,
AstroScore, or by how well a target fits your equipment. "Tonight for you" picks a few targets
matched to your experience level ([BEGINNER_EXPERIENCE.md](BEGINNER_EXPERIENCE.md)).

![Deep Sky Objects](img/skytonight_dso.png)

Each target opens a details panel with catalogue names, transit time, a visibility calendar over
the year, and the equipment combinations that suit it best.

![More info](img/skytonight_more_info.png)

The Beginner catalogue is a curated list of forgiving targets, each with an explanation.

![Beginner Catalogue](img/skytonight_beginnercatalogue.png)

### Solar System Bodies and Comets

The Moon and planets, and the comets currently observable, from live orbital elements.

![Bodies](img/skytonight_bodies.png)

![Comets](img/skytonight_comets.png)

### Altitude charts

An altitude-vs-time chart for every target, with the astronomical night and the observable zone,
and your horizon profile.

![Altitude Chart](img/skytonight_alttime_popup.png)

### Framing simulator

Your sensor's field drawn over a real image of the sky around a target, with rotation and up to
three equipment combinations compared side by side. Also opens from the Wishlist, Plan My Night
and the Astrodex. See [SKYTONIGHT.md](SKYTONIGHT.md#framing-simulator).

---

## Astrodex

Your logbook, from the plan to the finished picture: Plan -> Observe -> Log -> Astrodex.

### Astrodex

Your collection of imaged objects, with your pictures, their acquisition details, ratings and
notes. A picture can be turned into a share card, or sent to MyAstroShine for re-processing
([MYASTROSHINE.md](MYASTROSHINE.md)). Details: [ASTRODEX.md](ASTRODEX.md).

![Astrodex Collection](img/astrodex_astrodex.png)

![Astrodex Editor](img/astrodex_astrodex_edit.png)

### Plan my night

Turn your SkyTonight shortlist into a timeline for the night: durations, ordering (by hand or by
the optimizer), live progress during the night, CSV and PDF export. Shared equipment combinations
appear in the combination selector alongside your own. Details: [PLAN_MY_NIGHT.md](PLAN_MY_NIGHT.md).

![Plan My Night](img/astrodex_plan_my_night.png)

### Observation Log

One record per night: conditions, equipment, and what you shot on each target. A plan becomes a
session in one click, and frames logged on a target add it to the Astrodex. Details:
[OBSERVATION_LOG.md](OBSERVATION_LOG.md).

![Observation Log](img/astrodex_observationlog.png)

![Observation Session Detail](img/astrodex_observationlog_session.png)

### Your Sky

Everything the Observation Log knows, read back to you: total integration time, the object types
and constellations you favour, which equipment did the work, and how your ratings line up with the
seeing, transparency, SQM and Moon you recorded. Every comparison shows its own sample count, and a
group with too few nights behind it says so. Details: [SESSION_ANALYTICS.md](SESSION_ANALYTICS.md).

![Your Sky](img/astrodex_analytics_1.png)

The sky coverage chart draws your captures over the Milky Way and the ecliptic, with the band of
sky that never rises from your location shaded out.

![The sky you have covered](img/astrodex_analytics_2.png)

### Wishlist

The targets you want to image next, with a priority, when each one is next visible, and how many
you have already captured.

### Photo Map

Where your pictures were taken, on a map, from the locations you entered on them. Whether other
users' pictures appear is an administrator setting.

![Astrodex Photo Map](img/astrodex_photomap.png)

### Catalogue Collection

Pick a catalogue (Messier, Caldwell, Herschel 400...) and see which of its objects you have
already caught.

---

## Spaceflight

Details: [SPACEFLIGHT.md](SPACEFLIGHT.md).

### Launches

Upcoming and recent launches, with a detailed view and the webcast when one is available.

![Launches](img/spaceflight_launches.png)

![Launch detail](img/spaceflight_launches_popup.png)

### Astronauts

Who is in space right now, on which vehicle, and for how long.

![Astronauts](img/spaceflight_astronauts.png)

### Space Events

Mission milestones, spacewalks, dockings and other spaceflight events.

![Space events](img/spaceflight_spaceevents.png)

### Orbital Stations

Visible passes of the ISS and the China Space Station (Tiangong) over your location, and their
transits across the Sun and the Moon.

![ISS](img/spaceflight_iss.png)

---

## Observatory

A live panel fed by your own equipment through connectors: AllSky camera image, keogram, startrails,
timelapse and sensor data. The tab appears once a connector is enabled. Details:
[OBSERVATORY.md](OBSERVATORY.md), [CONNECTORS.md](CONNECTORS.md).

---

## Equipment

Telescopes, cameras, mounts, filters and accessories, combined into named equipment combinations.
Combinations feed the target recommendations, the field-of-view filters, the framing simulator and
the exposure calculator. Details: [EQUIPMENT.md](EQUIPMENT.md), [EXPOSURE_CALC.md](EXPOSURE_CALC.md).

![Equipment combination](img/equipment_combinations.png)

![Add telescope](img/equipment_telescopes.png)

![Equipment accessories](img/equipment_accessories_popup.png)

### Sharing equipment

Every piece of equipment can be marked **Share with all users**. Shared items show up, read-only,
for every other user: in their Equipment tab, the FOV calculator, the target recommendations, the
Astrodex picture form and the Plan My Night combination selector. A combination counts as shared
only when every piece it uses is shared. When a shared combination goes away, plans built on it
are kept and show a warning. Useful for a family or a club that shares a mount or a filter set.

---

## My settings

Each user's own preferences: theme (including a red night-vision theme), startup tab, density,
time format, experience level, their locations, notifications, password and two-factor
authentication, and the download of their personal data. Details: [USER_SETTINGS.md](USER_SETTINGS.md).

![User settings](img/user_custom.png)

---

## App settings

Administration of the instance (admin only). Details: [CONFIGURATION.md](CONFIGURATION.md).

- **Locations**: up to five location presets, attributed to users ([LOCATIONS.md](LOCATIONS.md)).
- **Configuration**: SkyTonight constraints, Astrodex privacy, notifications contact, reverse proxy,
  MQTT connections.

![Param settings](img/params_settings.png)

![Advanced settings](img/params_advanced.png)

- **Connectors**: AllSky, MyAstroShine, MQTT / Home Assistant, Astrodex Stream
  ([CONNECTORS.md](CONNECTORS.md), [HOME_ASSISTANT.md](HOME_ASSISTANT.md)).
- **Logs**: live log viewer, levels, retention, and an export to attach to a GitHub issue.

![Consult logs](img/params_logs.png)

![Export logs](img/params_log_export.png)

- **Users**: accounts and roles (admin, user, read-only), trusted networks, two-factor policy
  ([AUTHENTICATION.md](AUTHENTICATION.md)).

![Users](img/params_users.png)

- **Metrics**: system, database, scheduler and cache job health.

![Metrics](img/params_metrics.png)

- **Backup / Restore**: one archive with your configuration, accounts and collections.

![Backup](img/params_backup_restore.png)

---

## Everywhere

- **Sky status widget** in the header: the current state of the night and the active location,
  with a switcher when you have several.
- **Share cards**: a picture, a session, tonight's sky or an event as a ready-to-post image
  ([SHARE_CARDS.md](SHARE_CARDS.md)).
- **Phones**: installable as an app, with push notifications ([MOBILE.md](MOBILE.md)).
- **Six languages**: English, French, Spanish, German, Italian, Portuguese.
