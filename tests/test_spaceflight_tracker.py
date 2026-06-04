"""Tests for spaceflight_tracker.py — pure normaliser functions and helpers."""
import os
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from spaceflight_tracker import (
    _normalise_astronaut,
    _normalise_event,
    _normalise_expedition,
    _normalise_launch,
    prune_image_cache,
    spaceflight_cache_images_intact,
)


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
