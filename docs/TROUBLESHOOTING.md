# Troubleshooting

Common problems, what causes them, and how to fix them. Each entry links to the page that covers
the subsystem in detail.

## Before you report an issue

1. Open **App settings -> Logs**, set the log file level to `DEBUG`, reproduce the problem.
2. Use **Export logs** in the same sub-tab: it downloads one ZIP with the log files and a summary of
   the instance ([CONFIGURATION.md](CONFIGURATION.md#export-logs)).
3. Attach it to a [GitHub issue](https://github.com/myastroboard/myastroboard/issues), with the
   version (footer) and how you run MyAstroBoard (Docker, Home Assistant app).

The first lines written at each start include a `Host:` line with the CPUs, memory, container
limits and file system of the data directory: it answers most resource questions.

## Installation and resources

### Requests fail at random, or the offline page appears, during the first SkyTonight run

**Cause**: not enough memory. A worker is killed during the SkyTonight calculation; the browser
then sees failed requests, sometimes for actions that went through on the server.

**Fix**: give the container at least 1 GB, 2 GB when other services share the host. App settings ->
Metrics warns below 1 GB. See [system requirements](1.INSTALLATION.md#system-requirements).

### Everything is slow to save

**Cause**: the `data/` directory is on a network share (NFS, SMB), where SQLite cannot use its
write-ahead log. The log says so at startup.

**Fix**: keep `data/` on a local disk ([DATABASE.md](DATABASE.md#network-shares)).

### The container does not start on an old CPU or a Proxmox VM

The image targets plain x86-64 (no x86-64-v2 needed) and arm64. Report the startup output in an
issue: a dependency that needs newer CPU instructions is a bug.

## Signing in

### Lost admin password, or lost authenticator app

Use the recovery command line inside the container:

```bash
docker exec -u appuser myastroboard python backend/db/manage.py reset-password admin
docker exec -u appuser myastroboard python backend/db/manage.py disable-2fa admin
```

See [DATABASE.md](DATABASE.md#recovery-from-the-command-line).

### Cannot sign in, or sign out does nothing, over plain HTTP

**Cause**: the *HTTPS-only session cookie* setting is on and the page is opened over HTTP.

**Fix**: turn the setting off from the HTTPS address, from `http://localhost` (an SSH tunnel works),
or from a browser that is still signed in. See [6.REVERSE_PROXY.md](6.REVERSE_PROXY.md#troubleshooting).

### "Too many failed sign-in attempts"

Five failed sign-ins on one account, or twenty from one address, within 15 minutes block further
attempts for the rest of that window ([AUTHENTICATION.md](AUTHENTICATION.md#security-notes)).

### A local-only account cannot sign in

An account whose scope is *local* only signs in from a trusted network. Check the trusted networks
in App settings -> Users, and *Trust proxy headers* when a reverse proxy sits in front
([AUTHENTICATION.md](AUTHENTICATION.md#local-vs-global-accounts)).

## SkyTonight

### No targets, or the SkyTonight tables never appear

1. The first run takes a few minutes after startup; the tab shows its progress.
2. App settings -> Metrics -> *SkyTonight Scheduler* shows the last run and its error, if any.
3. SkyTonight -> Logs shows the last run's log.
4. Constraints that are too strict hide everything: check minimum altitude, size limits and the
   observable fraction in App settings -> Configuration ([SKYTONIGHT.md](SKYTONIGHT.md#observability-constraints)).
5. **Run SkyTonight Now** (App settings -> Configuration) starts a run at once.

### Object pictures are grey placeholders

The DSS2 sky images come from CDS hips2fits, then from mirrors of the survey. When none answers, a
placeholder is shown and the image is fetched again later ([SKYTONIGHT.md](SKYTONIGHT.md#sky-image)).

## Forecasts and caches

### A card says the data is not ready yet

Forecasts are computed in the background, every 25 minutes for the jobs whose time-to-live ran out.
After a restart or a location change, the first values take a few minutes. App settings -> Metrics
-> *Cache Jobs* shows each job's state and last run ([CACHE_SYSTEM.md](CACHE_SYSTEM.md#troubleshooting)).

### ISS / CSS passes stop updating

Celestrak may block a server that asked too often. A banner explains it; an admin can clear the
block from it ([SPACEFLIGHT.md](SPACEFLIGHT.md)).

## Notifications

### Push notifications never arrive on iPhone or iPad

1. The app must be installed on the Home Screen and opened from there ([MOBILE.md](MOBILE.md)).
2. The contact email must be set in App settings -> Configuration -> Notifications: Apple rejects
   pushes without a real address ([NOTIFICATIONS.md](NOTIFICATIONS.md)).

The *Test* button in My settings -> Notifications sends a real push through the server. When it
reports that delivery failed, the server log says why. On iOS, background or lock the app right
after tapping it to see the notification.

## Connectors and Home Assistant

- AllSky: [CONNECTORS.md](CONNECTORS.md#troubleshooting)
- MQTT / Home Assistant: [HOME_ASSISTANT.md](HOME_ASSISTANT.md#troubleshooting)
- Astrodex Stream: [ASTRODEX_STREAM.md](ASTRODEX_STREAM.md#troubleshooting)
- MyAstroShine: [MYASTROSHINE.md](MYASTROSHINE.md)

From the Home Assistant sidebar, stream addresses and the MyAstroShine return address need an
**External base URL** (App settings -> Configuration -> Reverse proxy).
