#### 1.2 Version - Multi-location Profiles and more!

Observers travel - to the backyard, to the club field, to that dark-sky site three hours away. Until now, MyAstroBoard only knew about one of those places at a time.

This release introduces multi-location profiles: admins can create up to 5 location presets (each with its own coordinates, timezone, Bortle/SQM sky quality and custom horizon profile) and attribute them to users. Every user picks a favorite default and can switch the active location instantly from the sky status widget - forecasts, SkyTonight, ISS/CSS passes, events and notifications all follow. Switching is instant because every location keeps its own warm cache; no recompute, no waiting.

#### Refactor equipments

Equipments was one of the first piece of the MyAstroBoard puzzle! As I was a telescope owner without camera I focused my project on telescope and telescope combination. On some place we could choose telescope, on other combination, but only telescope was computed.

I unfortunately still don't own a camera (dream, dream...), but I worked a lot to solve this situation which could be a non-sence. Now the key of the system is "combination". Combinations already exists but have been improved, it's not only question of a telescope + mount, this can be your combination, with only camera, with a telescope, a camera, a guide, ...

A combination is now computed for SkyTonight, for Plan my Night, using the entire equipment, not only the telescope.
A combination is now linked to a photo also.

#### Astrodex improvments

As now MyAstroBoard is multi-location, and can use combination, all these data are now linked to a photo.
And even a photo can be rated by yourself.
Why ? Because now (and more later, see roadmap), all these data will be allow you to lear more on your equipment and the result.

As location can be added to your picture, a World Photo Map is now available to see your different spot. On photo, you are not limited by recorded location, you can also indicate GPS coordinate if you take pictures in holidays!

A note about privacy. As Astrodex, World Photo Map can be private or public. That's mean, if map is set as public, all users of your server can see the position on the map. This point is documented in UI. As this is a local tool, this shouldn't be an issue, specially because you can turn it in private. In all of case the location is provided to "logged" users only for the map, never to others.

#### Notable change

- Add admin-managed location presets (Parameters -> Locations): create/edit/delete up to `MAX_LOCATIONS = 5` presets, each with name, coordinates, elevation, timezone, Bortle/SQM and a per-preset custom horizon profile (moved from Advanced constraints) - see docs/LOCATIONS.md
- Add per-user location attribution (admin assigns presets to users, many-to-many), per-user default location ("what I see when I connect"), per-user ordering, and a session-scoped active location reset to the default on each fresh login
- Add location switcher inside the sky status widget panel: users with more than one attributed location can switch the active location in one tap; single-location installs see no visual change. The panel opens on click/tap only (no hover), shows each location's current observation score, and flags when the active location's timezone differs from yours
- Add a minimap preview (Leaflet) to each admin location card (Parameters -> Locations)
- Add per-location cache slots: editing one preset's coordinates invalidates only that preset's caches, and switching locations serves already-warm data instantly (see docs/CACHE_SYSTEM.md)
- Add per-location SkyTonight: the nightly calculation runs once per scheduler location (shared dataset build, per-preset night tables, alt-time graphs, skymap and horizon overlays), every /api/skytonight endpoint serves the requester's active location, and existing results migrate automatically to the new per-location layout
- Add location pinning to Plan My Night plans (created against the active location, with a warning banner when viewing from a different location) and plain-text location snapshots on Astrodex items (never deleted with the preset)
- Add per-location push notification handling: messages mention the location name when a user has several locations, and each location can be muted individually in My Settings -> Notifications
- Add an optimizer service for a plan in plan-my-night
- Complete reorganization of `backend` folder because the app had grown too much to remain organized.
- Add notification for meteor shower
- Precipitation is now used for astroscore calculation
