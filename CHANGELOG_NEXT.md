#### Notifications

- Fixed duplicate notifications: with background Web Push active, every N1-N9 alert was
  delivered twice on the same device - once by the server-side push scheduler and once by the
  in-app poller (slightly different wording, about a minute apart). The in-app poller now steps
  aside whenever a working push subscription exists and stays only as the fallback for devices
  with no push (plain browser tab, push unsupported, endpoint purged server-side).
- The "astronomical night" (N6) in-app message now matches the push wording exactly, including
  the dusk clock time, and fixes missing accents in the FR/ES/PT strings.
