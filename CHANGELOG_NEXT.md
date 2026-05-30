#### Equipment — Shared Equipment

You can now share your equipment with everyone on your MyAstroBoard instance — perfect for families or astronomy clubs sharing a common set of gear.

- Any telescope, camera, mount, filter, or accessory can be shared with a single toggle. Shared gear is visible to all users, but only you can edit or delete your own items.
- Shared items are clearly labeled throughout the app — your own shared gear shows a **"Shared"** badge, and gear from others shows **"Shared by [name]"**.
- Equipment combinations are automatically considered shared when all their parts are shared — no extra steps needed.
- Shared gear shows up everywhere it's useful: equipment combinations, Field of View Calculator, Plan My Night telescope picker, SkyTonight recommendations, and Astrodex picture logging.
- If someone un-shares a telescope you had used in a plan, your plan is kept safe with a warning rather than disappearing silently.

#### SkyTonight

- Light pollution (Bortle/SQM) integration: configure your site's Bortle class once in Location Settings to weight AstroScore by sky darkness. Galaxies are most affected; planets are immune. Integration is inactive when no Bortle class is configured. Optional SQM field for users with a real SQM meter (overrides the Bortle midpoint estimate).
- Add solar elongation calculations and display in reports
- Alt vs time graph considere both nautic and astro night
- New "DSO not found?" sub-tab
  - You observed yesterday a DSO, but didn't find it on SkyTonight ? Probably because it was filtered out by the constrainst you setted.
  - Check the calcultation and compare to the constrainst
  - And finally, you can adapt your configuration according these results.
- Possibility to filter by catalogue
- Add catalogues: Abell PNe, Abell Clusters, Arp, Barnard, GaryImm, Sharpless, vdB

#### Plan my Night

- Plan my night display now partial alttime graph instead of progressbar
- PDF export is now more than a list. Better display, graph, ...

#### Notifications

MyAstroBoard can now alert you to time-critical astronomy events — even when the app is in the background or your phone is locked.

**7 event triggers, fully configurable per user:**

| Trigger | Default lead |
|---------|-------------|
| Plan My Night session starts | 15 min |
| Plan My Night: next target | 5 min |
| ISS solar or lunar transit | 10 min |
| Lunar eclipse totality | 30 min |
| Solar eclipse maximum | 30 min |
| Astronomical darkness begins | 20 min |
| Aurora: Kp index above your threshold | immediate |

**Two notification modes:**
- **In-app** — fires when the browser tab is open (any tab, not just the relevant one)
- **Background push** — fires even when the app is closed or your screen is off, via Web Push

**Smart polling:** the app checks every 5 minutes by default, switching automatically to every 1 minute during an active observation session or within 30 minutes of your plan starting — so short lead times (2–5 min) are never missed.

**Per-user settings** (My Settings → Notifications):
- Enable/disable all notifications or individual triggers
- Adjust lead time per trigger
- Set your personal Kp threshold for aurora alerts (3–9)
- Test button to verify notifications work before your next session

Notification preferences are saved to your account and follow you across devices.

#### Various

- Improve visualization of the moon with more realistic shadow
- Search on astrodex, add object, is done on multiple catalogues
- Fix date issue when there is no dark night
- Reduce verbose of INFO log
- IERS earth orientation data is now managed by internal cache system.
- Moon calendar in plan my night