#### Equipment — Shared Equipments

- Each equipment item (telescope, camera, mount, filter, accessory) has a new **"Share with all users"** toggle. Shared items are visible to all other users of the instance (e.g. family, astronomy club), but remain read-only for anyone who is not the owner.
- Equipment cards show a **"Shared"** badge on own shared items, and a **"Shared by {username}"** badge on items owned by other users.
- **Equipment combinations** are automatically flagged as shared when all their constituent items (telescope, camera, mount, filters, accessories) are shared. The combination card shows a computed **"Shared"** badge accordingly.
- A **broken-share warning** (⚠) is displayed on a combination when one of its referenced items was previously shared but is no longer accessible (owner removed or unshared it).
- When building or editing a combination, the modal dropdowns show `(shared)` next to own shared items and `(shared by {username})` next to items from other users, so the share impact of each choice is visible at selection time.
- **Field of View Calculator**: telescope and camera dropdowns include shared items from other users, labeled `(shared by {username})`.
- **SkyTonight — Best Telescope For This Target**: shared telescopes from other users are included in recommendations, annotated with a `shared by {username}` badge. Own telescopes are listed first, then shared ones.
- **Astrodex — Add Picture**: equipment-combination and filter dropdowns include shared items from other users.
- **Plan My Night**: shared telescopes appear in the telescope selector (own first, then `──────`, then shared with `(shared by {username})` label) and in the SkyTonight "Add to Plan My Night" picker modal.
- **Orphaned plan detection**: if a shared telescope is later removed or unshared by its owner, any existing plan built around it is preserved and displayed with a `⚠ telescope no longer available` warning. The user can review and delete it manually — no silent data loss.
- Shared equipment data is automatically refreshed (without F5) whenever the user navigates between equipment subtabs or switches back to the Equipment main tab.

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

#### Various

- Improve visualization of the moon with more realistic shadow
- Search on astrodex, add object, is done on multiple catalogues
- Fix date issue when there is no dark night
- Reduce verbose of INFO log