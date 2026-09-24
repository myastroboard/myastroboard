"""
Tests for the Astrodex Stream engine (backend/observation/astrodex_stream.py):
token generation/verification, slot timing, picture shuffling, and rendering.
"""

import io
import os
import tempfile
import time

import pytest
from PIL import Image

from observation import astrodex
from observation import astrodex_stream


@pytest.fixture
def temp_data_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setenv('DATA_DIR', tmpdir)
        astrodex.ASTRODEX_DIR = os.path.join(tmpdir, 'astrodex')
        astrodex.ASTRODEX_IMAGES_DIR = os.path.join(astrodex.ASTRODEX_DIR, 'images')
        astrodex.ensure_astrodex_directories()
        astrodex_stream._FRAME_CACHE.clear()
        yield tmpdir
        astrodex_stream._FRAME_CACHE.clear()


def _cfg(**overrides):
    cfg = {'display_seconds': 20, 'aspect_ratio': '16:9'}
    cfg.update(overrides)
    return cfg


def _seed_picture(user_id, filename='pic.jpg', item_name='M31', date='2026-09-20T21:00:00', size=(2000, 1000)):
    item = astrodex.create_astrodex_item(user_id, {'name': item_name, 'type': 'Galaxy', 'catalogue': 'Messier'})
    picture = astrodex.add_picture_to_item(user_id, item['id'], {'filename': filename, 'date': date})
    Image.new('RGB', size, (80, 40, 40)).save(os.path.join(astrodex.ASTRODEX_IMAGES_DIR, filename), 'JPEG')
    return item, picture


class TestTokens:

    def test_personal_token_is_deterministic_and_user_specific(self, temp_data_dir):
        t1 = astrodex_stream.personal_token('user-a')
        t2 = astrodex_stream.personal_token('user-a')
        assert t1 == t2
        assert astrodex_stream.personal_token('user-b') != t1

    def test_verify_personal_token_rejects_wrong_user_or_token(self, temp_data_dir):
        token = astrodex_stream.personal_token('user-a')
        assert astrodex_stream.verify_personal_token('user-a', token) is True
        assert astrodex_stream.verify_personal_token('user-b', token) is False
        assert astrodex_stream.verify_personal_token('user-a', token[:-1] + ('0' if token[-1] != '0' else '1')) is False
        assert astrodex_stream.verify_personal_token('user-a', '') is False

    def test_shared_token_is_independent_of_any_user_token(self, temp_data_dir):
        shared = astrodex_stream.shared_token()
        assert astrodex_stream.verify_shared_token(shared) is True
        assert astrodex_stream.verify_personal_token('__shared__', shared) is False

    def test_rotate_invalidates_previously_issued_tokens(self, temp_data_dir):
        old_token = astrodex_stream.personal_token('user-a')
        astrodex_stream.rotate_signing_secret()
        assert astrodex_stream.verify_personal_token('user-a', old_token) is False
        new_token = astrodex_stream.personal_token('user-a')
        assert astrodex_stream.verify_personal_token('user-a', new_token) is True
        assert new_token != old_token

    def test_signing_secret_generation_survives_a_persist_failure(self, temp_data_dir, monkeypatch):
        """A token must still be produced (just won't survive a restart) if the sidecar
        write fails on first use - not critical enough to break the whole feature."""
        monkeypatch.setattr(astrodex_stream, 'save_secrets', lambda name, values: False)

        token = astrodex_stream.personal_token('user-a')

        assert token  # still got a usable, non-empty token

    def test_rotate_raises_when_the_new_secret_cannot_be_persisted(self, temp_data_dir, monkeypatch):
        monkeypatch.setattr(astrodex_stream, 'save_secrets', lambda name, values: False)

        with pytest.raises(RuntimeError):
            astrodex_stream.rotate_signing_secret()


class TestSlotTiming:

    def test_slot_is_stable_within_a_cycle(self, temp_data_dir):
        assert astrodex_stream._current_slot(0.0, display_seconds=10) == 0
        assert astrodex_stream._current_slot(9.9, display_seconds=10) == 0

    def test_slot_advances_to_the_next_cycle(self, temp_data_dir):
        assert astrodex_stream._current_slot(10.0, display_seconds=10) == 1
        assert astrodex_stream._current_slot(29.0, display_seconds=10) == 2

    def test_zero_or_negative_display_seconds_does_not_divide_by_zero(self, temp_data_dir):
        # max(1, ...) guard - a misconfigured 0 still produces a well-defined, changing slot.
        assert astrodex_stream._current_slot(5.0, display_seconds=0) == 5


class TestShuffling:

    def test_same_seed_and_slot_always_picks_the_same_index(self, temp_data_dir):
        """The property every simultaneous viewer relies on: no shared state, just a
        reproducible function of (seed, slot)."""
        first = astrodex_stream._slot_to_picture_index('user-a', slot=7, count=10)
        second = astrodex_stream._slot_to_picture_index('user-a', slot=7, count=10)
        assert first == second

    def test_different_seeds_can_diverge_for_the_same_slot(self, temp_data_dir):
        """Not a strict inequality (they could coincidentally match), just proof the seed
        actually participates in the selection rather than being ignored."""
        picks = {astrodex_stream._slot_to_picture_index(f'user-{i}', slot=3, count=1000) for i in range(20)}
        assert len(picks) > 1

    def test_picks_stay_within_bounds(self, temp_data_dir):
        for slot in range(50):
            idx = astrodex_stream._slot_to_picture_index('seed', slot, count=5)
            assert 0 <= idx < 5

    def test_never_repeats_the_previous_slot_across_many_seeds_and_collection_sizes(self, temp_data_dir):
        """The actual guarantee: no two adjacent slots ever pick the same index, for any
        collection size (including the count == 2 edge case, which has only one valid
        non-repeating arrangement at all: strict alternation) and across cycle boundaries."""
        for seed_n in range(20):
            seed = f'seed-{seed_n}'
            for count in (2, 3, 4, 5, 7, 10, 25):
                previous = None
                for slot in range(count * 6 + 3):  # a few full cycles plus a partial one
                    idx = astrodex_stream._slot_to_picture_index(seed, slot, count)
                    assert 0 <= idx < count
                    if previous is not None:
                        assert idx != previous
                    previous = idx

    def test_single_picture_always_resolves_to_index_zero(self, temp_data_dir):
        for slot in range(10):
            assert astrodex_stream._slot_to_picture_index('seed', slot, count=1) == 0

    def test_render_current_frame_never_repeats_the_previous_slot_back_to_back(self, temp_data_dir, monkeypatch):
        """End-to-end: two adjacent slots never render the same photo - checked here on the
        actual output pixels, not just the index-selection helper in isolation."""
        user_id = 'user-shuffle'
        colors = [(200, 0, 0), (0, 200, 0), (0, 0, 200)]
        for i, color in enumerate(colors):
            item = astrodex.create_astrodex_item(user_id, {'name': f'M{i}', 'type': 'Galaxy'})
            astrodex.add_picture_to_item(user_id, item['id'], {'filename': f'p{i}.jpg', 'date': '2026-09-20'})
            Image.new('RGB', (200, 100), color).save(os.path.join(astrodex.ASTRODEX_IMAGES_DIR, f'p{i}.jpg'), 'JPEG')

        display_seconds = 10
        previous_bytes = None
        for slot in range(15):
            monkeypatch.setattr(astrodex_stream.time, 'time', lambda s=slot: float(s * display_seconds))
            data = astrodex_stream.personal_frame(user_id, _cfg(display_seconds=display_seconds))
            astrodex_stream._FRAME_CACHE.clear()  # each simulated slot must actually re-render
            if previous_bytes is not None:
                assert data != previous_bytes
            previous_bytes = data


class TestRendering:

    def test_zero_pictures_renders_a_placeholder_at_the_configured_size(self, temp_data_dir):
        data = astrodex_stream.personal_frame('nobody', _cfg(aspect_ratio='4:3'))
        img = Image.open(io.BytesIO(data))
        assert img.size == (1280, 960)
        assert img.format == 'JPEG'

    @pytest.mark.parametrize(
        'aspect_ratio,expected',
        [
            ('16:9', (1280, 720)),
            ('9:16', (720, 1280)),
            ('4:3', (1280, 960)),
            ('3:4', (960, 1280)),
            ('1:1', (1280, 1280)),
        ],
    )
    def test_crops_to_every_configured_aspect_ratio(self, temp_data_dir, aspect_ratio, expected):
        user_id = 'user-crop'
        _seed_picture(user_id)
        data = astrodex_stream.personal_frame(user_id, _cfg(aspect_ratio=aspect_ratio))
        img = Image.open(io.BytesIO(data))
        assert img.size == expected

    def test_frame_cache_key_includes_aspect_ratio_not_just_the_feed(self, temp_data_dir):
        """Regression test: a first render must not be reused for a different aspect ratio
        requested within the same cache-TTL window (found via manual smoke testing before
        the cache key included the config fingerprint)."""
        user_id = 'user-cache'
        _seed_picture(user_id)
        wide = Image.open(io.BytesIO(astrodex_stream.personal_frame(user_id, _cfg(aspect_ratio='16:9'))))
        tall = Image.open(io.BytesIO(astrodex_stream.personal_frame(user_id, _cfg(aspect_ratio='9:16'))))
        assert wide.size == (1280, 720)
        assert tall.size == (720, 1280)

    def test_same_config_within_the_ttl_window_is_served_from_cache(self, temp_data_dir):
        user_id = 'user-cache2'
        _seed_picture(user_id)
        first = astrodex_stream.personal_frame(user_id, _cfg())
        second = astrodex_stream.personal_frame(user_id, _cfg())
        assert first == second  # identical bytes: the second call hit the cache, not a re-render

    def test_cache_eviction_sweeps_older_buckets_then_falls_back_to_oldest_first(self, temp_data_dir):
        """Older-bucket entries (the common case - they simply aged out) are swept first;
        if that alone isn't enough (many distinct feeds landing in the very same bucket),
        the cache falls back to plain insertion-order eviction to stay under the cap."""
        astrodex_stream._FRAME_CACHE.clear()
        max_entries = astrodex_stream._FRAME_CACHE_MAX_ENTRIES
        bucket = int(time.time() // astrodex_stream._FRAME_CACHE_TTL_SECONDS)

        for i in range(3):
            astrodex_stream._FRAME_CACHE[(f'old-{i}', 'fp', bucket - 1)] = b'stale'
        for i in range(max_entries + 2):
            astrodex_stream._FRAME_CACHE[(f'same-{i}', 'fp', bucket)] = b'stale'

        astrodex_stream._render_cached('new-feed', [], _cfg())

        assert len(astrodex_stream._FRAME_CACHE) <= max_entries
        assert not any(key[2] == bucket - 1 for key in astrodex_stream._FRAME_CACHE)

    def test_shared_feed_includes_owner_username_in_the_banner_personal_does_not(self, temp_data_dir):
        """Not asserting on rendered pixels - just that the banner-line builder picks up
        owner_username for the shared/merged view and leaves it out for the personal one."""
        personal_lines = astrodex_stream._banner_lines(
            {'item_name': 'M31', 'date': '2026-09-20', 'owner_username': None}
        )
        shared_lines = astrodex_stream._banner_lines(
            {'item_name': 'M31', 'date': '2026-09-20', 'owner_username': 'alice'}
        )
        assert personal_lines == ['M31', '2026-09-20']
        assert shared_lines == ['M31', '2026-09-20', 'alice']

    def test_missing_picture_file_on_disk_falls_back_to_placeholder(self, temp_data_dir):
        user_id = 'user-missing-file'
        item = astrodex.create_astrodex_item(user_id, {'name': 'M31', 'type': 'Galaxy'})
        astrodex.add_picture_to_item(user_id, item['id'], {'filename': 'never_written.jpg', 'date': '2026-09-20'})
        data = astrodex_stream.personal_frame(user_id, _cfg())
        img = Image.open(io.BytesIO(data))
        assert img.size == (1280, 720)  # did not crash despite the file not existing on disk

    def test_corrupted_picture_file_on_disk_falls_back_to_placeholder(self, temp_data_dir):
        """A file that exists but isn't a valid image (truncated upload, disk corruption)
        must be treated the same as a missing one, not crash the stream."""
        user_id = 'user-corrupt-file'
        item = astrodex.create_astrodex_item(user_id, {'name': 'M31', 'type': 'Galaxy'})
        astrodex.add_picture_to_item(user_id, item['id'], {'filename': 'corrupt.jpg', 'date': '2026-09-20'})
        with open(os.path.join(astrodex.ASTRODEX_IMAGES_DIR, 'corrupt.jpg'), 'wb') as f:
            f.write(b'not a real jpeg')

        data = astrodex_stream.personal_frame(user_id, _cfg())

        img = Image.open(io.BytesIO(data))
        assert img.size == (1280, 720)

    def test_crops_a_portrait_source_to_a_landscape_target_by_trimming_height(self, temp_data_dir):
        """The source's own aspect ratio can be narrower than the target's (unlike every
        other crop test here, which uses a wide source) - that path trims top/bottom
        instead of left/right."""
        user_id = 'user-portrait-crop'
        _seed_picture(user_id, size=(1000, 2000))  # tall source, ratio 0.5

        data = astrodex_stream.personal_frame(user_id, _cfg(aspect_ratio='16:9'))  # wide target, ratio 1.78

        img = Image.open(io.BytesIO(data))
        assert img.size == (1280, 720)

    def test_format_date_handles_a_missing_value(self):
        assert astrodex_stream._format_date(None) == ""
        assert astrodex_stream._format_date("") == ""

    def test_banner_lines_skips_missing_name_and_date(self):
        lines = astrodex_stream._banner_lines({'item_name': '', 'date': None, 'owner_username': None})
        assert lines == []

    def test_draw_banner_is_a_noop_with_no_lines(self):
        img = Image.new('RGB', (100, 50), (10, 20, 30))

        result = astrodex_stream._draw_banner(img, [])

        assert result is img

    def test_encode_jpeg_converts_a_non_rgb_image(self):
        img = Image.new('RGBA', (10, 10), (1, 2, 3, 4))

        data = astrodex_stream._encode_jpeg(img)

        assert Image.open(io.BytesIO(data)).mode == 'RGB'


class TestSharedFeed:

    def test_shared_feed_strips_gps_and_merges_across_users(self, temp_data_dir):
        item_a = astrodex.create_astrodex_item('user-a', {'name': 'M31', 'type': 'Galaxy'})
        astrodex.add_picture_to_item(
            'user-a',
            item_a['id'],
            {'filename': 'a.jpg', 'date': '2026-09-20', 'latitude': 45.0, 'longitude': 5.0},
        )
        pictures = astrodex_stream._eligible_pictures_shared()
        assert any(p['item_name'] == 'M31' for p in pictures)
        # _eligible_pictures_shared only carries filename/date/item_name/owner_username -
        # GPS fields are never copied through in the first place.
        assert all(set(p.keys()) == {'filename', 'date', 'item_name', 'owner_username'} for p in pictures)

    def test_shared_feed_skips_pictures_without_a_filename(self, temp_data_dir, monkeypatch):
        """A picture record can exist without a filename (e.g. an upload that failed
        partway through) - it must never be offered to the stream as a photo to render."""
        astrodex.create_astrodex_item('user-a', {'name': 'M31', 'type': 'Galaxy'})
        monkeypatch.setattr(
            astrodex,
            'get_visible_astrodex',
            lambda **kwargs: {'items': [{'name': 'M31', 'pictures': [{'filename': '', 'date': '2026-09-20'}]}]},
        )

        assert astrodex_stream._eligible_pictures_shared() == []


class TestPersonalEligiblePictures:

    def test_personal_feed_skips_pictures_without_a_filename(self, temp_data_dir):
        user_id = 'user-no-filename'
        astrodex.create_astrodex_item(user_id, {'name': 'M31', 'type': 'Galaxy'})
        data = astrodex.load_user_astrodex(user_id)
        data['items'][0]['pictures'] = [{'filename': '', 'date': '2026-09-20'}]
        astrodex.save_user_astrodex(user_id, data)

        assert astrodex_stream._eligible_pictures_personal(user_id) == []
