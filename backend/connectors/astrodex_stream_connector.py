"""
AstroDex Stream connector - a personal, auto-refreshing photo slideshow of a user's
AstroDex pictures, rendered as a single "current frame" JPEG that any still-image camera
viewer (Home Assistant's Generic Camera integration, a browser <img> tag, ...) can poll.

Not a real video stream - see feature-astrodex-stream.md §1 for the feasibility study that
rejected RTSP and a pushed MJPEG stream in favour of this. The server renders whichever photo
is "current" as a pure function of wall-clock time, so there is no background thread to
start/stop and nothing needs a new Docker port - it rides the app's existing HTTP port like
every other connector. Deliberately no crossfade: a client polling mid-transition would just
receive one blended frame and keep displaying it, static, until its own next poll - see
astrodex_stream.py's module docstring. See backend/observation/astrodex_stream.py for the
rendering engine and backend/blueprints/astrodex_stream.py for the routes.

Shaped like MyAstroShineConnector: tied to astrodex, no independently-toggleable modules.
Unlike every other connector, nothing here is admin-entered: the per-user signing key that
makes each stream URL unreadable by other users is generated automatically on first use
(astrodex_stream.py::_signing_secret(), same idea as the auto-generated VAPID keys in
utils/push_manager.py) - hence no SECRET_FIELDS and no external url/homepage.
"""

from typing import Any

from connectors.base_connector import BaseConnector


class AstroDexStreamConnector(BaseConnector):
    name = "astrodex_stream"
    label = "AstroDex Stream"
    description = (
        "Personal, auto-refreshing photo slideshow of your AstroDex pictures - "
        "for Home Assistant's Generic Camera or any still-image viewer"
    )
    min_version = ""
    homepage = ""
    target_modules = ["astrodex"]

    # No independently-toggleable features: the slideshow is the whole connector.
    MODULES: list[dict] = []
    SECRET_FIELDS: tuple = ()

    CONFIG_FIELDS: dict[str, Any] = {
        "display_seconds": 20,
        "aspect_ratio": "16:9",
    }

    ENUM_FIELDS: dict[str, tuple] = {
        "aspect_ratio": ("16:9", "9:16", "4:3", "3:4", "1:1"),
    }

    def is_configured(self) -> bool:
        # Nothing external to install - the connector is usable as soon as it's enabled.
        return True

    def health_check(self) -> dict:
        return {"reachable": True, "modules": {}}
