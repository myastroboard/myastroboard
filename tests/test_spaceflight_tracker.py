"""Tests for spaceflight_tracker.py — pure normaliser functions and helpers."""
import time
from contextlib import contextmanager
from unittest.mock import patch, MagicMock
import requests

import spaceflight_tracker

_cache_image = spaceflight_tracker._cache_image
_get = spaceflight_tracker._get
_normalise_astronaut = spaceflight_tracker._normalise_astronaut
_normalise_event = spaceflight_tracker._normalise_event
_normalise_expedition = spaceflight_tracker._normalise_expedition
_normalise_launch = spaceflight_tracker._normalise_launch
get_upcoming_launches = spaceflight_tracker.get_upcoming_launches
get_past_launches = spaceflight_tracker.get_past_launches
get_iss_crew = spaceflight_tracker.get_iss_crew
get_astronauts_in_space = spaceflight_tracker.get_astronauts_in_space
get_upcoming_space_events = spaceflight_tracker.get_upcoming_space_events
get_launch_vidurls = spaceflight_tracker.get_launch_vidurls
prune_image_cache = spaceflight_tracker.prune_image_cache
spaceflight_cache_images_intact = spaceflight_tracker.spaceflight_cache_images_intact


@contextmanager
def _no_cache():
    with patch("spaceflight_tracker._cache_image", side_effect=lambda url: url):
        yield


# ---------------------------------------------------------------------------
# _normalise_launch
# ---------------------------------------------------------------------------


class TestNormaliseLaunch:

    def _raw(self, **overrides):
        base = {
            "id": "abc-123",
            "name": "Falcon 9 | Starlink",
            "slug": "falcon-9-starlink",
            "net": "2026-07-01T12:00:00Z",
            "window_start": "2026-07-01T11:50:00Z",
            "window_end": "2026-07-01T12:30:00Z",
            "status": {"id": 1, "abbrev": "Go", "name": "Go for Launch", "description": "Go"},
            "rocket": {"configuration": {"full_name": "Falcon 9 Block 5", "family": "Falcon", "name": "Falcon 9"}},
            "mission": {
                "name": "Starlink 6-10",
                "type": "Communications",
                "description": "Batch",
                "orbit": {"abbrev": "LEO"},
            },
            "pad": {"name": "SLC-40", "location": {"name": "Cape Canaveral", "country_code": "USA"}},
            "launch_service_provider": {"name": "SpaceX", "abbrev": "SpX", "type": "Commercial"},
            "image": "https://example.com/img.jpg",
            "webcast_live": True,
            "vidURLs": [{"url": "https://youtube.com/watch?v=x"}],
        }
        base.update(overrides)
        return base

    def test_all_fields_mapped(self):
        with _no_cache():
            result = _normalise_launch(self._raw())
        assert result["id"] == "abc-123"
        assert result["name"] == "Falcon 9 | Starlink"
        assert result["status_abbrev"] == "Go"
        assert result["rocket_name"] == "Falcon 9 Block 5"
        assert result["rocket_family"] == "Falcon"
        assert result["mission_name"] == "Starlink 6-10"
        assert result["mission_type"] == "Communications"
        assert result["orbit"] == "LEO"
        assert result["pad_name"] == "SLC-40"
        assert result["pad_location_name"] == "Cape Canaveral"
        assert result["pad_location_country"] == "USA"
        assert result["agency_name"] == "SpaceX"
        assert result["agency_abbrev"] == "SpX"
        assert result["webcast_live"] is True

    def test_empty_raw(self):
        with _no_cache():
            result = _normalise_launch({})
        assert result["id"] is None
        assert result["name"] is None
        assert result["status_abbrev"] is None
        assert result["webcast_live"] is False

    def test_nested_none_values(self):
        raw = self._raw()
        raw["rocket"] = None
        raw["mission"] = None
        raw["pad"] = None
        raw["launch_service_provider"] = None
        raw["status"] = None
        with _no_cache():
            result = _normalise_launch(raw)
        assert result["rocket_name"] is None
        assert result["mission_name"] is None
        assert result["pad_name"] is None
        assert result["agency_name"] is None

    def test_image_as_dict(self):
        raw = self._raw()
        raw["image"] = {"image_url": "https://example.com/dict.jpg"}
        with _no_cache():
            result = _normalise_launch(raw)
        assert result["image_url"] == "https://example.com/dict.jpg"

    def test_video_url_from_vidurls(self):
        raw = self._raw()
        raw.pop("vidURL", None)
        raw["vidURLs"] = [{"url": "https://youtube.com/v/abc"}]
        with _no_cache():
            result = _normalise_launch(raw)
        assert result["video_url"] == "https://youtube.com/v/abc"


# ---------------------------------------------------------------------------
# _normalise_astronaut
# ---------------------------------------------------------------------------


class TestNormaliseAstronaut:

    def _raw(self, **overrides):
        base = {
            "id": 7,
            "name": "Samantha Cristoforetti",
            "nationality": "Italian",
            "agency": {"name": "ESA", "abbrev": "ESA"},
            "profile_image": "https://example.com/sam.jpg",
            "status": {"name": "Active"},
            "in_space": True,
            "time_in_space": "P365D",
            "bio": "Italian ESA astronaut.",
            "wiki": "https://en.wikipedia.org/wiki/Samantha_Cristoforetti",
        }
        base.update(overrides)
        return base

    def test_all_fields_mapped(self):
        with _no_cache():
            result = _normalise_astronaut(self._raw())
        assert result["id"] == 7
        assert result["name"] == "Samantha Cristoforetti"
        assert result["nationality"] == "Italian"
        assert result["agency_name"] == "ESA"
        assert result["agency_abbrev"] == "ESA"
        assert result["status"] == "Active"
        assert result["currently_in_space"] is True
        assert result["time_in_space"] == "P365D"

    def test_empty_raw(self):
        with _no_cache():
            result = _normalise_astronaut({})
        assert result["id"] is None
        assert result["name"] is None
        assert result["agency_name"] is None
        assert result["currently_in_space"] is None

    def test_no_agency(self):
        raw = self._raw()
        raw["agency"] = None
        with _no_cache():
            result = _normalise_astronaut(raw)
        assert result["agency_name"] is None
        assert result["agency_abbrev"] is None


# ---------------------------------------------------------------------------
# _normalise_expedition
# ---------------------------------------------------------------------------


class TestNormaliseExpedition:

    def _raw(self, **overrides):
        base = {
            "id": 71,
            "name": "Expedition 71",
            "start": "2024-03-04T00:00:00Z",
            "end": None,
            "crew": [
                {
                    "astronaut": {
                        "name": "Oleg Kononenko",
                        "nationality": "Russian",
                        "agency": {"name": "Roscosmos", "abbrev": "RFSA"},
                        "profile_image": "https://example.com/oleg.jpg",
                    },
                    "role": {"role": "Commander"},
                }
            ],
            "mission_patch": "https://example.com/patch.png",
            "wiki": "https://en.wikipedia.org/wiki/Expedition_71",
        }
        base.update(overrides)
        return base

    def test_all_fields_mapped(self):
        with _no_cache():
            result = _normalise_expedition(self._raw())
        assert result["id"] == 71
        assert result["name"] == "Expedition 71"
        assert result["start"] == "2024-03-04T00:00:00Z"
        assert result["crew_count"] == 1
        assert result["crew"][0]["name"] == "Oleg Kononenko"
        assert result["crew"][0]["role"] == "Commander"
        assert result["crew"][0]["agency_abbrev"] == "RFSA"

    def test_empty_crew(self):
        raw = self._raw()
        raw["crew"] = []
        with _no_cache():
            result = _normalise_expedition(raw)
        assert result["crew_count"] == 0
        assert result["crew"] == []

    def test_crew_member_no_role(self):
        raw = self._raw()
        raw["crew"][0]["role"] = None
        with _no_cache():
            result = _normalise_expedition(raw)
        assert result["crew"][0]["role"] is None

    def test_empty_raw(self):
        with _no_cache():
            result = _normalise_expedition({})
        assert result["id"] is None
        assert result["crew_count"] == 0


# ---------------------------------------------------------------------------
# _normalise_event
# ---------------------------------------------------------------------------


class TestNormaliseEvent:

    def _raw(self, **overrides):
        base = {
            "id": 555,
            "name": "ISS Crew Rotation",
            "slug": "iss-crew-rotation",
            "type": {"name": "Docking"},
            "description": "Crew swap event.",
            "date": "2026-09-01T14:00:00Z",
            "location": "ISS",
            "video_url": "https://youtube.com/live",
            "webcast_live": True,
            "news_url": "https://nasa.gov/news",
            "programs": [{"name": "ISS"}, {"name": "Commercial Crew"}],
            "feature_image": "https://example.com/event.jpg",
        }
        base.update(overrides)
        return base

    def test_all_fields_mapped(self):
        result = _normalise_event(self._raw())
        assert result["id"] == 555
        assert result["name"] == "ISS Crew Rotation"
        assert result["type_name"] == "Docking"
        assert result["location"] == "ISS"
        assert result["webcast_live"] is True
        assert result["programs"] == ["ISS", "Commercial Crew"]

    def test_empty_programs(self):
        raw = self._raw()
        raw["programs"] = []
        result = _normalise_event(raw)
        assert result["programs"] == []

    def test_feature_image_as_dict(self):
        raw = self._raw()
        raw["feature_image"] = {"image_url": "https://example.com/dict_event.jpg"}
        result = _normalise_event(raw)
        assert result["image_url"] == "https://example.com/dict_event.jpg"

    def test_empty_raw(self):
        result = _normalise_event({})
        assert result["id"] is None
        assert result["type_name"] is None
        assert result["webcast_live"] is False
        assert result["programs"] == []


# ---------------------------------------------------------------------------
# prune_image_cache
# ---------------------------------------------------------------------------


class TestPruneImageCache:

    def test_no_dir_does_nothing(self, tmp_path):
        with patch("spaceflight_tracker._SPACEFLIGHT_IMAGES_DIR", str(tmp_path / "nonexistent")):
            prune_image_cache([])

    def test_removes_unreferenced_files(self, tmp_path):
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        (img_dir / "old.jpg").write_bytes(b"data")
        (img_dir / "keep.jpg").write_bytes(b"data")

        with patch("spaceflight_tracker._SPACEFLIGHT_IMAGES_DIR", str(img_dir)):
            prune_image_cache(["/api/spaceflight/img/keep.jpg"])

        assert not (img_dir / "old.jpg").exists()
        assert (img_dir / "keep.jpg").exists()

    def test_keeps_all_referenced_files(self, tmp_path):
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        (img_dir / "a.jpg").write_bytes(b"x")
        (img_dir / "b.jpg").write_bytes(b"x")

        with patch("spaceflight_tracker._SPACEFLIGHT_IMAGES_DIR", str(img_dir)):
            prune_image_cache(["/api/spaceflight/img/a.jpg", "/api/spaceflight/img/b.jpg"])

        assert (img_dir / "a.jpg").exists()
        assert (img_dir / "b.jpg").exists()

    def test_empty_active_list_removes_all(self, tmp_path):
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        (img_dir / "orphan.jpg").write_bytes(b"x")

        with patch("spaceflight_tracker._SPACEFLIGHT_IMAGES_DIR", str(img_dir)):
            prune_image_cache([])

        assert not (img_dir / "orphan.jpg").exists()


# ---------------------------------------------------------------------------
# spaceflight_cache_images_intact
# ---------------------------------------------------------------------------


class TestSpaceflightCacheImagesIntact:

    def test_none_cache_returns_true(self):
        assert spaceflight_cache_images_intact(None) is True

    def test_empty_dict_returns_true(self):
        assert spaceflight_cache_images_intact({}) is True

    def test_no_image_paths_returns_true(self):
        data = {"results": [{"name": "Falcon 9", "status": "Go"}]}
        assert spaceflight_cache_images_intact(data) is True

    def test_present_image_returns_true(self, tmp_path):
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        (img_dir / "abc.jpg").write_bytes(b"data")

        with patch("spaceflight_tracker._SPACEFLIGHT_IMAGES_DIR", str(img_dir)):
            data = {"image_url": "/api/spaceflight/img/abc.jpg"}
            assert spaceflight_cache_images_intact(data) is True

    def test_missing_image_returns_false(self, tmp_path):
        img_dir = tmp_path / "images"
        img_dir.mkdir()

        with patch("spaceflight_tracker._SPACEFLIGHT_IMAGES_DIR", str(img_dir)):
            data = {"image_url": "/api/spaceflight/img/missing.jpg"}
            assert spaceflight_cache_images_intact(data) is False

    def test_nested_list_structure(self, tmp_path):
        img_dir = tmp_path / "images"
        img_dir.mkdir()

        with patch("spaceflight_tracker._SPACEFLIGHT_IMAGES_DIR", str(img_dir)):
            data = {"results": [{"image_url": "/api/spaceflight/img/gone.jpg"}]}
            assert spaceflight_cache_images_intact(data) is False

    def test_non_spaceflight_url_ignored(self):
        data = {"image": "https://cdn.example.com/some.jpg"}
        assert spaceflight_cache_images_intact(data) is True


# ---------------------------------------------------------------------------
# _cache_image
# ---------------------------------------------------------------------------


class TestCacheImage:

    def test_none_url_returns_none(self):
        result = _cache_image(None)
        assert result is None

    def test_empty_string_returns_empty(self):
        result = _cache_image("")
        assert result == ""

    def test_successful_download(self, tmp_path):
        """Cache a new image: downloads and writes file, returns local path."""
        mock_resp = MagicMock()
        mock_resp.iter_content.return_value = [b"fakebytes"]
        with patch("spaceflight_tracker._SPACEFLIGHT_IMAGES_DIR", str(tmp_path)):
            with patch("requests.get", return_value=mock_resp):
                result = _cache_image("https://example.com/test.jpg")
        assert result.startswith("/api/spaceflight/img/")
        assert result.endswith(".jpg")

    def test_already_cached_file_not_redownloaded(self, tmp_path):
        """If file already exists, no request is made."""
        url = "https://example.com/cached.jpg"
        import hashlib
        url_hash = hashlib.md5(url.encode()).hexdigest()
        cached_file = tmp_path / f"{url_hash}.jpg"
        cached_file.write_bytes(b"existing")
        with patch("spaceflight_tracker._SPACEFLIGHT_IMAGES_DIR", str(tmp_path)):
            with patch("requests.get") as mock_get:
                result = _cache_image(url)
        mock_get.assert_not_called()
        assert result.startswith("/api/spaceflight/img/")

    def test_unknown_extension_defaults_to_jpg(self, tmp_path):
        """Non-standard extension falls back to .jpg."""
        mock_resp = MagicMock()
        mock_resp.iter_content.return_value = [b"data"]
        with patch("spaceflight_tracker._SPACEFLIGHT_IMAGES_DIR", str(tmp_path)):
            with patch("requests.get", return_value=mock_resp):
                result = _cache_image("https://example.com/image.bmp")
        assert result.endswith(".jpg")

    def test_request_error_returns_original_url(self, tmp_path):
        """On download failure, graceful fallback to original URL."""
        url = "https://example.com/fail.jpg"
        with patch("spaceflight_tracker._SPACEFLIGHT_IMAGES_DIR", str(tmp_path)):
            with patch("requests.get", side_effect=requests.RequestException("timeout")):
                result = _cache_image(url)
        assert result == url

    def test_makedirs_error_returns_original_url(self):
        """If makedirs fails, fallback to original URL."""
        url = "https://example.com/img.png"
        with patch("os.makedirs", side_effect=OSError("permission denied")):
            result = _cache_image(url)
        assert result == url

    def test_png_extension_preserved(self, tmp_path):
        mock_resp = MagicMock()
        mock_resp.iter_content.return_value = [b"pngdata"]
        with patch("spaceflight_tracker._SPACEFLIGHT_IMAGES_DIR", str(tmp_path)):
            with patch("requests.get", return_value=mock_resp):
                result = _cache_image("https://example.com/image.png")
        assert result.endswith(".png")


# ---------------------------------------------------------------------------
# _get (HTTP helper with backoff)
# ---------------------------------------------------------------------------


class TestGet:

    def setup_method(self):
        """Clear backoff dict before each test."""
        spaceflight_tracker._backoff_until.clear()

    def test_successful_get_returns_json(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"count": 1, "results": []}
        with patch("requests.get", return_value=mock_resp):
            result = _get("/launch/upcoming/", params={"limit": 5})
        assert result == {"count": 1, "results": []}

    def test_backoff_active_returns_none(self):
        """If backoff is active for a path, skip the request."""
        spaceflight_tracker._backoff_until["/launch/upcoming/"] = time.time() + 3600
        with patch("requests.get") as mock_get:
            result = _get("/launch/upcoming/")
        mock_get.assert_not_called()
        assert result is None

    def test_expired_backoff_cleared_and_request_made(self):
        """Expired backoff should be cleared and request made."""
        spaceflight_tracker._backoff_until["/test/"] = time.time() - 1  # already expired
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True}
        with patch("requests.get", return_value=mock_resp):
            result = _get("/test/")
        assert result == {"ok": True}
        assert "/test/" not in spaceflight_tracker._backoff_until

    def test_timeout_exception_sets_backoff(self):
        with patch("requests.get", side_effect=requests.exceptions.Timeout()):
            result = _get("/timeout/")
        assert result is None
        assert spaceflight_tracker._backoff_until.get("/timeout/", 0) > time.time()

    def test_http_429_sets_long_backoff(self):
        mock_exc_resp = MagicMock()
        mock_exc_resp.status_code = 429
        mock_exc_resp.headers = {"Retry-After": "120"}
        exc = requests.exceptions.HTTPError(response=mock_exc_resp)
        with patch("requests.get", side_effect=exc):
            result = _get("/rate-limited/")
        assert result is None
        remaining = spaceflight_tracker._backoff_until.get("/rate-limited/", 0) - time.time()
        assert remaining > 60

    def test_http_429_without_retry_after_header(self):
        mock_exc_resp = MagicMock()
        mock_exc_resp.status_code = 429
        mock_exc_resp.headers = {}
        exc = requests.exceptions.HTTPError(response=mock_exc_resp)
        with patch("requests.get", side_effect=exc):
            result = _get("/rate-limited2/")
        assert result is None
        assert "/rate-limited2/" in spaceflight_tracker._backoff_until

    def test_http_500_sets_short_backoff(self):
        mock_exc_resp = MagicMock()
        mock_exc_resp.status_code = 500
        exc = requests.exceptions.HTTPError(response=mock_exc_resp)
        with patch("requests.get", side_effect=exc):
            result = _get("/server-error/")
        assert result is None
        assert "/server-error/" in spaceflight_tracker._backoff_until

    def test_generic_exception_sets_backoff(self):
        with patch("requests.get", side_effect=RuntimeError("network down")):
            result = _get("/generic-fail/")
        assert result is None
        assert "/generic-fail/" in spaceflight_tracker._backoff_until

    def test_success_clears_stale_backoff(self):
        """A successful request clears any prior backoff for that path."""
        spaceflight_tracker._backoff_until["/clean/"] = time.time() - 1  # expired
        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        with patch("requests.get", return_value=mock_resp):
            _get("/clean/")
        assert "/clean/" not in spaceflight_tracker._backoff_until


# ---------------------------------------------------------------------------
# Public fetch functions
# ---------------------------------------------------------------------------


class TestGetUpcomingLaunches:

    def setup_method(self):
        spaceflight_tracker._backoff_until.clear()

    def test_returns_none_when_api_fails(self):
        with patch("spaceflight_tracker._get", return_value=None):
            result = get_upcoming_launches()
        assert result is None

    def test_normalises_results(self):
        raw = {
            "count": 1,
            "results": [
                {
                    "id": "abc",
                    "name": "Test Launch",
                    "status": {"abbrev": "Go"},
                    "rocket": {"configuration": {"full_name": "Falcon 9"}},
                    "mission": {},
                    "pad": {"location": {}},
                    "launch_service_provider": {},
                    "image": None,
                }
            ],
        }
        with _no_cache():
            with patch("spaceflight_tracker._get", return_value=raw):
                result = get_upcoming_launches(limit=5)
        assert result["count"] == 1
        assert len(result["results"]) == 1
        assert result["results"][0]["name"] == "Test Launch"
        assert "fetched_at" in result

    def test_empty_results_list(self):
        with _no_cache():
            with patch("spaceflight_tracker._get", return_value={"count": 0, "results": []}):
                result = get_upcoming_launches()
        assert result["count"] == 0
        assert result["results"] == []


class TestGetPastLaunches:

    def setup_method(self):
        spaceflight_tracker._backoff_until.clear()

    def test_returns_none_when_api_fails(self):
        with patch("spaceflight_tracker._get", return_value=None):
            assert get_past_launches() is None

    def test_normalises_results(self):
        raw = {
            "count": 2,
            "results": [
                {"id": "x", "name": "Past 1", "status": {}, "rocket": {"configuration": {}},
                 "mission": {}, "pad": {"location": {}}, "launch_service_provider": {}, "image": None},
                {"id": "y", "name": "Past 2", "status": {}, "rocket": {"configuration": {}},
                 "mission": {}, "pad": {"location": {}}, "launch_service_provider": {}, "image": None},
            ],
        }
        with _no_cache():
            with patch("spaceflight_tracker._get", return_value=raw):
                result = get_past_launches(limit=10)
        assert result["count"] == 2
        assert len(result["results"]) == 2


class TestGetIssCrew:

    def setup_method(self):
        spaceflight_tracker._backoff_until.clear()

    def test_returns_none_when_api_fails(self):
        with patch("spaceflight_tracker._get", return_value=None):
            assert get_iss_crew() is None

    def test_empty_expeditions(self):
        with patch("spaceflight_tracker._get", return_value={"results": []}):
            result = get_iss_crew()
        assert result["expeditions"] == []
        assert "fetched_at" in result

    def test_returns_current_expedition(self):
        raw = {
            "results": [
                {
                    "id": 71,
                    "name": "Expedition 71",
                    "start": "2024-03-04T00:00:00Z",
                    "end": None,
                    "crew": [],
                    "mission_patch": None,
                    "wiki": None,
                }
            ]
        }
        with _no_cache():
            with patch("spaceflight_tracker._get", return_value=raw):
                result = get_iss_crew()
        assert result["current_expedition"]["name"] == "Expedition 71"
        assert "fetched_at" in result


class TestGetAstronautsInSpace:

    def setup_method(self):
        spaceflight_tracker._backoff_until.clear()

    def test_returns_none_when_api_fails(self):
        with patch("spaceflight_tracker._get", return_value=None):
            assert get_astronauts_in_space() is None

    def test_normalises_astronauts(self):
        raw = {
            "count": 1,
            "results": [
                {
                    "id": 7,
                    "name": "Test Astronaut",
                    "nationality": "American",
                    "agency": {"name": "NASA", "abbrev": "NASA"},
                    "profile_image": None,
                    "status": {"name": "Active"},
                    "in_space": True,
                    "time_in_space": "P100D",
                    "bio": "Bio text",
                    "wiki": None,
                }
            ],
        }
        with _no_cache():
            with patch("spaceflight_tracker._get", return_value=raw):
                result = get_astronauts_in_space()
        assert result["count"] == 1
        assert result["results"][0]["name"] == "Test Astronaut"


class TestGetUpcomingSpaceEvents:

    def setup_method(self):
        spaceflight_tracker._backoff_until.clear()

    def test_returns_none_when_api_fails(self):
        with patch("spaceflight_tracker._get", return_value=None):
            assert get_upcoming_space_events() is None

    def test_normalises_events(self):
        raw = {
            "count": 1,
            "results": [
                {
                    "id": 100,
                    "name": "ISS Docking",
                    "slug": "iss-docking",
                    "type": {"name": "Docking"},
                    "description": "Docking event",
                    "date": "2026-10-01T10:00:00Z",
                    "location": "ISS",
                    "video_url": None,
                    "webcast_live": False,
                    "news_url": None,
                    "programs": [],
                    "feature_image": None,
                }
            ],
        }
        with patch("spaceflight_tracker._get", return_value=raw):
            result = get_upcoming_space_events(limit=5)
        assert result["count"] == 1
        assert result["results"][0]["name"] == "ISS Docking"


# ---------------------------------------------------------------------------
# get_launch_vidurls (cached, sorted)
# ---------------------------------------------------------------------------


class TestGetLaunchVidurls:

    def setup_method(self):
        spaceflight_tracker._backoff_until.clear()
        spaceflight_tracker._vidurls_cache.clear()

    def test_returns_empty_list_when_api_fails(self):
        with patch("spaceflight_tracker._get", return_value=None):
            result = get_launch_vidurls("launch-abc")
        assert result == []

    def test_returns_sorted_results_youtube_first(self):
        raw = {
            "vidURLs": [
                {"url": "https://vimeo.com/video", "title": "Vimeo", "source": "vimeo",
                 "publisher": "Pub", "type": {"name": "Live"}, "priority": 10},
                {"url": "https://www.youtube.com/watch?v=abc", "title": "YT",
                 "source": "youtube", "publisher": "SpX", "type": {"name": "Live"}, "priority": 5},
            ]
        }
        with patch("spaceflight_tracker._get", return_value=raw):
            result = get_launch_vidurls("launch-123")
        assert result[0]["url"] == "https://www.youtube.com/watch?v=abc"

    def test_cached_result_returned_without_api_call(self):
        spaceflight_tracker._vidurls_cache["cached-id"] = {
            "data": [{"url": "https://example.com", "title": "Test"}],
            "ts": time.time(),
        }
        with patch("spaceflight_tracker._get") as mock_get:
            result = get_launch_vidurls("cached-id")
        mock_get.assert_not_called()
        assert result[0]["url"] == "https://example.com"

    def test_expired_cache_refetched(self):
        spaceflight_tracker._vidurls_cache["old-id"] = {
            "data": [{"url": "https://old.com"}],
            "ts": time.time() - 9999,
        }
        raw = {"vidURLs": [{"url": "https://new.com", "title": "New", "source": "x",
                             "publisher": "y", "type": {"name": "Live"}, "priority": 1}]}
        with patch("spaceflight_tracker._get", return_value=raw):
            result = get_launch_vidurls("old-id")
        assert result[0]["url"] == "https://new.com"

    def test_vidurls_without_url_filtered(self):
        raw = {
            "vidURLs": [
                {"url": None, "title": "No URL"},
                {"url": "https://example.com/v", "title": "Valid", "source": "x",
                 "publisher": "y", "type": {"name": "Live"}, "priority": 0},
            ]
        }
        with patch("spaceflight_tracker._get", return_value=raw):
            result = get_launch_vidurls("filter-id")
        assert len(result) == 1
        assert result[0]["url"] == "https://example.com/v"

    def test_empty_vidurls(self):
        raw = {"vidURLs": []}
        with patch("spaceflight_tracker._get", return_value=raw):
            result = get_launch_vidurls("empty-id")
        assert result == []

    def test_no_vidurls_key(self):
        raw = {}
        with patch("spaceflight_tracker._get", return_value=raw):
            result = get_launch_vidurls("nokey-id")
        assert result == []

    def test_youtube_com_without_www_also_sorted_first(self):
        raw = {
            "vidURLs": [
                {"url": "https://vimeo.com/v", "title": "V", "source": "vimeo",
                 "publisher": "x", "type": {"name": "Live"}, "priority": 100},
                {"url": "https://youtube.com/watch?v=xyz", "title": "YT bare",
                 "source": "youtube", "publisher": "y", "type": None, "priority": 1},
            ]
        }
        with patch("spaceflight_tracker._get", return_value=raw):
            result = get_launch_vidurls("bare-yt-id")
        assert result[0]["url"].startswith("https://youtube.com/")


# ---------------------------------------------------------------------------
# prune_image_cache - OSError on remove
# ---------------------------------------------------------------------------


class TestPruneImageCacheOsError:

    def test_oserror_on_remove_logged_not_raised(self, tmp_path):
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        (img_dir / "orphan.jpg").write_bytes(b"x")

        with patch("spaceflight_tracker._SPACEFLIGHT_IMAGES_DIR", str(img_dir)):
            with patch("os.remove", side_effect=OSError("locked")):
                # Should not raise
                prune_image_cache([])

    def test_non_matching_paths_skipped_in_in_use_build(self, tmp_path):
        """Line 373->372: active_data paths not starting with /api/spaceflight/img/ → skipped."""
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        (img_dir / "active.jpg").write_bytes(b"x")

        with patch("spaceflight_tracker._SPACEFLIGHT_IMAGES_DIR", str(img_dir)):
            prune_image_cache([
                None,
                42,
                "/other/path/active.jpg",
            ])
        assert (img_dir / "active.jpg").exists() is False


# ---------------------------------------------------------------------------
# spaceflight_cache_images_intact - tuple branch
# ---------------------------------------------------------------------------


class TestSpaceflightCacheImagesIntactTuple:

    def test_tuple_values_checked(self, tmp_path):
        img_dir = tmp_path / "images"
        img_dir.mkdir()
        (img_dir / "abc.jpg").write_bytes(b"data")

        with patch("spaceflight_tracker._SPACEFLIGHT_IMAGES_DIR", str(img_dir)):
            # tuple of image paths
            data = ("/api/spaceflight/img/abc.jpg",)
            result = spaceflight_cache_images_intact(data)
        assert result is True

    def test_tuple_with_missing_image(self, tmp_path):
        img_dir = tmp_path / "images"
        img_dir.mkdir()

        with patch("spaceflight_tracker._SPACEFLIGHT_IMAGES_DIR", str(img_dir)):
            data = ("/api/spaceflight/img/missing.jpg",)
            result = spaceflight_cache_images_intact(data)
        assert result is False
