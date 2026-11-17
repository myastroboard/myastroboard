# Profiles and Community

An instance is often shared: a family, a group of friends, a club. Until now nothing showed who
else was on it. Profiles give each member a name and a face, and the **Community** tab lets
members who want to see each other's progress, without turning it into a competition.

The rule is **emulation, not ranking**:

- the member directory is alphabetical, and its cards carry no figures;
- the activity feed is chronological;
- the "together" totals add everyone up, and point at what nobody has captured yet;
- no figure is ever put next to another member's to compare them.

---

## The profile (My settings -> Profile)

| Field | What it does |
|---|---|
| Display name | Shown instead of the login name wherever the others see you. The login name does not change. 40 characters at most; it may not be another member's login or display name, so nobody can appear as "admin" or as someone else. |
| Picture | Optional. Cropped to a 256 px square and re-encoded as WebP; the location and camera details of the original file are removed. Without a picture, a round picture with your initials is generated (no third-party service). |
| About me | Optional, 280 characters, shown on your Community profile only. |
| Join the Community | Off by default. On: you appear in the member directory, with the blocks chosen below. You can leave at any time. |
| What the members see | One switch per block - figures, badges, pictures, equipment, activity. |

**Display name and picture everywhere.** Where a member's name was already shown to others -
shared Astrodex pictures, the photo map, shared equipment, the Astrodex Stream banner - the display
name now replaces the login name, with the picture next to it. This exposes nothing new: it is the
same place, with a nicer name. The navbar shows your own name and picture.

**See my profile as the others do** opens your Community profile as a preview, even before you
join, with a banner saying nobody sees it yet.

The same editor is a step of the [first-run wizard](BEGINNER_EXPERIENCE.md#guided-setup-wizard)
("how the others see me"), between Equipment and Notifications.

---

## The Community tab

Shown in the main navigation when the admin has not turned it off.

### Activity

- **Join banner**: shown until you join, with a button to your profile settings.
- **Together**: everything the members who show their figures have done, added up - objects
  captured, integration time, nights, constellations - and, per catalogue, how far the group has
  got, with the first objects **nobody has captured yet** ("Still to capture together (66): M 2,
  M 3, ..."). That list is the shared goal.
- **Latest activity**: one card per member and day with something new - new objects, pictures
  added, badges earned - newest first, the latest 40 days with activity. Clicking a name opens the
  profile.

### Members

The directory: avatar, display name, the start of the bio and the membership date, in alphabetical
order. Clicking a card opens the profile.

### A member's profile

The header (picture, name, membership date, bio) and the blocks the member shows:

| Block | Content | Source |
|---|---|---|
| In figures | Objects captured, integration time, nights, constellations, progress per badge catalogue | Their Observation Log and Astrodex, the same facts as [My Progress](MY_PROGRESS.md) |
| Badges | Earned badges and their date | Same; hidden if the member turned badges off in Customize |
| Latest pictures | Their 12 most recent Astrodex pictures | Astrodex; never shown in private Astrodex mode |
| Equipment | Names of their active combinations, telescope and camera | Equipment; names only, no settings |
| Recent activity | Their last 10 days with something new | As the feed |

---

## Privacy

Private by default, as every sharing feature of MyAstroBoard:

- Nobody is listed until they join. A member who did not join answers 404 to everyone else.
- Only the blocks a member turns on leave their account, and only to signed-in members of the
  instance. There is no public page.
- The **Observation Log stays private**: its notes, its sessions, its locations and its
  conditions are never shown. Only figures derived from it (counts, hours, badges, the day an
  object was first captured) appear, and only when the member shows them.
- No position is ever shown: no location, no coordinates.
- In **private Astrodex mode** (App settings -> Configuration), no picture is ever shown to
  another member, whatever the member chose.
- The profile lives on the account: deleting the account deletes it, and the personal data export
  includes it (`account.json`) with the picture (`profile/`). See [PRIVACY.md](PRIVACY.md).

## For the admin

- **App settings -> Configuration -> Community tab** turns the whole tab off (`community.enabled`,
  on by default). Turning it on shares nothing by itself: every member's profile stays hidden until
  they join. With the tab off, display names and pictures keep working.
- **App settings -> Users -> Reset profile** clears a member's display name, bio and picture
  (moderation). Their account, data and Community choices are kept.
- The users table shows the display name under the login name.
- An admin who is the only account on the instance sees a note on the Activity page with a link to
  that switch: the tab has nobody to show until other members join.

## Demo mode

The demo account's profile cannot be changed (it is shared by every visitor); the Community tab is
read-only like the rest of the demo. See [DEMO_MODE.md](DEMO_MODE.md).

## For developers

| Piece | Where |
|---|---|
| Identity: display name, picture URL, visibility rules, picture processing | `backend/utils/user_identity.py` - imports no feature package, usable anywhere |
| Profile storage | `User.profile` on the account (`backend/utils/auth.py`, `users` table), validated by `user_identity.sanitize_profile()` |
| Pictures | `DATA_DIR/avatars/<user_id>_avatar_<random>.webp`, listed in `user_data_dirs()` (erasure and export) |
| Directory and profile blocks | `backend/community/members.py` |
| Feed and "together" totals | `backend/community/activity.py` |
| Routes | `backend/blueprints/community.py` ([API_ENDPOINTS.md](API_ENDPOINTS.md#profile-and-community-see-docscommunitymd)) |
| Frontend | `static/js/user_identity.js` (avatar and name chip, used everywhere), `static/js/profile.js` (editor), `static/js/community.js` (tab), `static/css/bs_community.css` |

To label a member anywhere in the UI, use `buildUserChip({user_id, display_name})` or
`buildUserAvatar(identity, size)`; on the server, `user_manager.display_names_by_id()` gives the
name to show. Never show `username` to other members directly.

The feed and totals read every listed member's log and Astrodex; they are cached for one minute per
process, and dropped on any profile change.
