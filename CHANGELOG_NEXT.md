#### Notifications

- Fixed duplicate notifications: with background Web Push active, every N1-N9 alert was
  delivered twice on the same device - once by the server-side push scheduler and once by the
  in-app poller (slightly different wording, about a minute apart). The in-app poller now steps
  aside whenever a working push subscription exists and stays only as the fallback for devices
  with no push (plain browser tab, push unsupported, endpoint purged server-side).
- The "astronomical night" (N6) in-app message now matches the push wording exactly, including
  the dusk clock time, and fixes missing accents in the FR/ES/PT strings.

#### Astrodex

- Add/Edit Photo: the equipment combination dropdown is now sorted alphabetically instead of
  creation order.
- Adding a new object now opens that object's detail view straight away, so a photo can be
  attached without hunting for the freshly added card first.
- Fixed a false "already in your Astrodex" match between two different objects that a catalogue
  gives the same common name (e.g. NGC 6992 and NGC 6995, both "Eastern Veil"). Objects that
  resolve to distinct SkyTonight targets are no longer collapsed by a shared alias.

#### SkyTonight

- Sky map: dragging the minimum-AstroScore slider now updates the map only when the handle is
  released, instead of re-rendering on every step of the drag.
