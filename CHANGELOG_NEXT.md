> [!CAUTION] BREAKING CHANGE !
> ENV variables are now obsolete

### ENV variables

With goal to allow user to deploy this app with low knowledge, the ENV variables are now removed. **Docker**: `docker compose up` now works out of the box with zero manual configuration.

If you used Reverse Proxy, and notification, you need to set new values via UI. As there is only 3 parameters directly concerned, there is no migrating tool.

- `SECRET_KEY` is auto-generated on first startup and stored in `data/secret_key.txt` — sessions survive container rebuilds. Thats mean at first built, you need to reconnect.
-  `VAPID_CONTACT_EMAIL`, `TRUST_PROXY_HEADERS`, and `SESSION_COOKIE_SECURE` have been removed from docker-compose and are now managed via the admin UI. This is the only 3 parameters you need to adapt if you already use it.
- `TZ` default changed from `Europe/Paris` to `UTC` (better practice for server logs; observation timezone is already set in Parameters → Configuration).

### Various change
- **Parameters → Advanced**: two new admin sections:
  - **Notifications** — configure the VAPID contact email for push notification delivery.
  - **Reverse proxy** — enable/disable proxy header trust and HTTPS-only session cookie; prompts container restart when changed.
- **Container restart button**: when proxy settings change, the admin UI proposes a one-click restart with a live progress overlay that reloads the page once the app is back up.
- Updated VAPID misconfiguration warning banner to point admins to the new UI setting instead of referencing an environment variable.
- Notifications are now translated in your language. The language is set at browser storage, so you probably need to change language to activate it first.
