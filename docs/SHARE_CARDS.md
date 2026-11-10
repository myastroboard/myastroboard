# Share Cards

A share card is a ready-to-post image made from data MyAstroBoard already holds: a picture with its
acquisition details, a logged session, tonight's sky, an upcoming event. It answers the question
every posted astrophoto gets - "what gear, how many subs?" - without retyping anything.

## Where to find them

The share button (a share icon) opens the card:

| Card | Where | What it shows |
|---|---|---|
| **Astrodex picture** | Astrodex -> an object -> the share button under one of your pictures | The picture, uncropped, with the object name, type and constellation, date, equipment, exposures (frames x sub-exposure), total integration, and filters when they were entered as free text |
| **Observing session** | Astrodex -> Observation Log -> a session -> share button in the toolbar | Date, equipment combination, total integration, number of targets and nights, average SQM and Moon illumination, the list of targets, and the session's first linked picture when there is one |
| **My sky tonight** | SkyTonight -> "Tonight for you" card header | Night score, best imaging window and its duration, Moon phase and illumination, the three recommended targets |
| **Event** | Calendar -> an event in the timeline | The event title, when it happens (in the location's time zone), whether it is happening now, and its description |

The framing simulator has its own export, see [SKYTONIGHT.md](SKYTONIGHT.md#framing-simulator).

## Options

- **Format**: the shapes the main image networks show without cropping. 4:5 is the default.

  | Format | Size | Fits |
  |---|---|---|
  | 4:5 | 1080 x 1350 | Portrait feed post: Instagram, Facebook, Threads |
  | 1:1 | 1080 x 1080 | Square, accepted everywhere |
  | 16:9 | 1920 x 1080 | Landscape: X, Facebook, forums. Picture and text sit side by side |
  | 9:16 | 1080 x 1920 | Full screen: stories and reels. Not a feed format: a feed crops it |
- **Theme**: dark or light. The card has its own palette and looks the same whatever the
  application theme, the red night-vision theme included.
- **Show on the card**: every fact can be unchecked before export. A fact with no value is not
  offered at all - a card never shows an empty or invented figure.
- **MyAstroBoard signature**: a footer with the project name and address, on by default.
- **Download** saves a PNG. **Share** appears when the browser can hand a file to the system share
  sheet (mostly phones) and opens it with the image.

A picture is never cropped: it is drawn whole, and the text block takes the room it needs beside or
below it. Where the picture does not fill its area (a tall photo in a wide card), the bands show a
blurred, darkened copy of the picture on browsers whose canvas supports filters, plain black
otherwise.

## Privacy

- The card is drawn on a canvas **in the browser**. Nothing is uploaded; it leaves the device only
  when the user downloads or shares it.
- A card **never contains a location**: no coordinates, no location name, no map. The card model has
  no field for them, and the Astrodex and Observation Log callers do not pass the ones they hold.
  Sky quality (SQM) and Moon illumination are the only conditions shown.
- Pictures were already stripped of their EXIF metadata when they were uploaded, and the exported
  PNG is a new image with no metadata of its own.

## Implementation

`static/js/share_card.js` holds the engine and the four card builders:

- `openShareCard(model)` - the modal: preview, options, download and share. A model is a plain
  object: `kicker`, `heading`, `subheading`, an optional same-origin `imageUrl`, an optional `hero`
  figure, `facts` (each with an `id` so it can be unchecked), an optional `list` and `paragraph`.
- `drawShareCard(canvas, model, options, image)` - the drawing. The text block is planned first
  (fonts shrink to fit, long lines are clamped), then the picture gets the remaining height.
- `shareAstrodexPicture`, `shareObservationSession`, `shareTonight`, `shareEvent` - build a model
  from the data their caller already has. `shareTonight` fetches what the dashboard shows
  (`/api/sky-widget`, `/api/moon/report`, `/api/tonight/best-window`,
  `/api/skytonight/recommendations`); a part that is unavailable is left out.
- `createShareButton(onClick)` - the icon button used at each entry point.

There is no backend part and no new route. Adding a card is one builder function and one button.
