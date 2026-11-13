# Glossary

The terms MyAstroBoard shows on screen, in plain words, with the page that explains how each one is
computed.

| Term | Meaning |
|---|---|
| **Airmass** | How much atmosphere the light crosses, relative to straight up (1 at the zenith, 2 at 30 degrees of altitude). The higher, the more blur and extinction. SkyTonight's default limit is 2 ([SKYTONIGHT.md](SKYTONIGHT.md#observability-constraints)). |
| **Altitude / azimuth** | Height of an object above the horizon (degrees) and its direction along the horizon, from north through east. |
| **AstroScore** | MyAstroBoard's 0-to-1 rating of how good a target is tonight from your location: visibility 40%, sky quality 25%, brightness 25%, comfort 10%, plus small bonuses ([SKYTONIGHT.md](SKYTONIGHT.md#astroscore)). |
| **Astronomical night** | The Sun more than 18 degrees below the horizon: the sky is fully dark. The best imaging window is searched inside it ([ASTROPHOTOGRAPHY.md](ASTROPHOTOGRAPHY.md)). |
| **Bortle class** | A 1 (pristine) to 9 (inner city) scale of light pollution at your site, set per location ([SKYTONIGHT.md](SKYTONIGHT.md#light-pollution-integration)). |
| **Culmination / transit** | The moment an object is highest in the sky, crossing the meridian. |
| **Dark window** | The part of the night with no Sun and no Moon in the sky. |
| **Difficulty** | MyAstroBoard's 0-to-100 estimate of how hard a target is for a beginner, used by "Tonight for you" ([BEGINNER_EXPERIENCE.md](BEGINNER_EXPERIENCE.md#difficulty-model)). |
| **DSO** | Deep-sky object: galaxy, nebula, star cluster - anything beyond the solar system. |
| **Equipment combination** | A named set of telescope (or lens), camera, mount and filters that you image with ([EQUIPMENT.md](EQUIPMENT.md)). |
| **FOV (field of view)** | The patch of sky your camera covers through your telescope, in arcminutes ([EQUIPMENT.md](EQUIPMENT.md)). |
| **Integration time** | The total exposure time accumulated on a target, all sub-exposures added ([EXPOSURE_CALC.md](EXPOSURE_CALC.md)). |
| **Kp index** | A 0-to-9 measure of geomagnetic activity; the higher, the further from the poles aurorae can be seen ([ASTROPHOTOGRAPHY.md](ASTROPHOTOGRAPHY.md)). |
| **Magnitude** | Brightness on a reversed scale: the smaller the number, the brighter the object. For extended objects, the same light spread over a larger area looks fainter. |
| **Meridian flip** | On an equatorial mount, the turn the telescope must make when the target crosses the meridian; imaging pauses for a few minutes ([PLAN_MY_NIGHT.md](PLAN_MY_NIGHT.md)). |
| **Nautical twilight** | The Sun between 6 and 12 degrees below the horizon. SkyTonight runs one hour after nautical dawn and one hour before nautical dusk. |
| **Opposition** | A planet opposite the Sun in the sky: closest, brightest, visible all night. AstroScore adds a bonus. |
| **Seeing** | Steadiness of the air, which blurs fine detail; matters most for planets and small targets ([WEATHER.md](WEATHER.md)). |
| **SQM** | Sky Quality Meter reading, in magnitudes per square arcsecond: the darker the sky, the higher the value (about 22 at a dark site) ([EXPOSURE_CALC.md](EXPOSURE_CALC.md)). |
| **Sub-exposure** | One single frame of a series; many are stacked to reach the integration time. |
| **Transparency** | Clarity of the air (haze, humidity, dust), which dims faint objects ([WEATHER.md](WEATHER.md)). |
| **TLE** | Two-line element set: the orbit data used to predict ISS and CSS passes ([SPACEFLIGHT.md](SPACEFLIGHT.md)). |
