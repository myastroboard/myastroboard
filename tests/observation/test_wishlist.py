"""Tests for the wishlist storage module (v1.5).

The two rules this module is built on get the most attention: coordinates are resolved
and frozen at add time, and "captured" is derived on every read rather than stored.
"""

import json
import os
import tempfile

import pytest

from observation import wishlist


@pytest.fixture
def isolated_wishlist(monkeypatch):
    """Point wishlist storage at a temporary directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        directory = os.path.join(tmpdir, 'wishlist')
        monkeypatch.setattr(wishlist, 'WISHLIST_DIR', directory)
        yield directory


@pytest.fixture
def stub_resolver(monkeypatch):
    """A small in-test catalogue standing in for the SkyTonight dataset lookup."""
    catalogue = {
        'M 31': ('dso-ngc0224', 10.68, 41.27, 'Galaxy', 'And'),
        'NGC 224': ('dso-ngc0224', 10.68, 41.27, 'Galaxy', 'And'),
        'M 42': ('dso-ngc1976', 83.82, -5.39, 'Nebula', 'Ori'),
    }

    def fake_resolve_target(name, catalogue_name='', ra=None, dec=None):
        hit = catalogue.get(str(name or '').strip())
        if hit:
            group_id, ra_deg, dec_deg, object_type, constellation = hit
            return {
                'group_id': group_id,
                'target_id': group_id,
                'preferred_name': str(name),
                'object_type': object_type,
                'constellation': constellation,
                'category': 'deep_sky',
                'ra_deg': ra_deg,
                'dec_deg': dec_deg,
                'resolved': True,
                'placed': True,
            }
        return {
            'group_id': '',
            'target_id': '',
            'preferred_name': '',
            'object_type': '',
            'constellation': '',
            'category': '',
            'ra_deg': None,
            'dec_deg': None,
            'resolved': False,
            'placed': False,
        }

    monkeypatch.setattr(wishlist.target_coordinates, 'resolve_target', fake_resolve_target)
    return catalogue


def _add(user_id='user-1', username='tester', **target):
    payload = {'name': 'M 31', 'catalogue': 'Messier'}
    payload.update(target)
    return wishlist.add_targets(user_id, username, [payload])


class TestStorage:

    def test_empty_wishlist_for_a_new_user(self, isolated_wishlist):
        data = wishlist.load_user_wishlist('user-1', 'tester')
        assert data['items'] == []
        assert data['username'] == 'tester'

    def test_add_then_reload(self, isolated_wishlist, stub_resolver):
        report = _add()
        assert report['saved'] is True
        assert len(report['added']) == 1
        assert wishlist.load_user_wishlist('user-1')['items'][0]['name'] == 'M 31'

    def test_file_is_written_where_expected(self, isolated_wishlist, stub_resolver):
        _add()
        path = os.path.join(isolated_wishlist, 'user-1_wishlist.json')
        assert os.path.isfile(path)
        with open(path, encoding='utf-8') as handle:
            assert json.load(handle)['items'][0]['name'] == 'M 31'

    def test_corrupted_file_is_backed_up_and_reset(self, isolated_wishlist, stub_resolver):
        """A truncated write must not take the whole wishlist down with it."""
        _add()
        path = os.path.join(isolated_wishlist, 'user-1_wishlist.json')
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write('{ this is not json')

        assert wishlist.load_user_wishlist('user-1')['items'] == []
        assert any(name.startswith('user-1_wishlist.json.corrupted.') for name in os.listdir(isolated_wishlist))

    def test_non_dict_items_are_dropped_on_load(self, isolated_wishlist, stub_resolver):
        _add()
        path = os.path.join(isolated_wishlist, 'user-1_wishlist.json')
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
        data['items'].append('junk')
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(data, handle)

        assert len(wishlist.load_user_wishlist('user-1')['items']) == 1

    def test_path_traversal_is_refused(self, isolated_wishlist):
        with pytest.raises(ValueError):
            wishlist._safe_wishlist_path(os.path.join(isolated_wishlist, '..', 'escape.json'))

    def test_users_have_separate_files(self, isolated_wishlist, stub_resolver):
        _add(user_id='user-1')
        _add(user_id='user-2', name='M 42')
        assert [item['name'] for item in wishlist.load_user_wishlist('user-1')['items']] == ['M 31']
        assert [item['name'] for item in wishlist.load_user_wishlist('user-2')['items']] == ['M 42']

    def test_load_with_invalid_user_id_returns_default_payload(self, isolated_wishlist):
        """A user id that would resolve outside the wishlist directory degrades to an
        empty payload instead of raising."""
        data = wishlist.load_user_wishlist('../escaped', username='tester')
        assert data['items'] == []

    def test_save_with_invalid_user_id_fails(self, isolated_wishlist):
        assert wishlist.save_user_wishlist('../escaped', {'items': []}) is False

    def test_corrupted_file_backup_failure_is_swallowed(self, isolated_wishlist, stub_resolver, monkeypatch):
        """A backup failure while recovering from corruption must not stop the reset."""
        _add()
        path = os.path.join(isolated_wishlist, 'user-1_wishlist.json')
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write('{ this is not json')

        def _raise(*args, **kwargs):
            raise OSError('backup boom')

        monkeypatch.setattr(wishlist.shutil, 'copy2', _raise)
        assert wishlist.load_user_wishlist('user-1')['items'] == []

    def test_load_swallows_non_json_decode_errors(self, isolated_wishlist, stub_resolver):
        """An unexpected read error (not just malformed JSON) still degrades gracefully
        to an empty payload rather than propagating."""
        _add()
        path = os.path.join(isolated_wishlist, 'user-1_wishlist.json')
        with open(path, 'wb') as handle:
            handle.write(b'\xff\xfe\x00\x01')  # invalid utf-8, so decoding itself fails

        assert wishlist.load_user_wishlist('user-1')['items'] == []

    def test_non_dict_json_root_returns_default_payload(self, isolated_wishlist):
        wishlist.ensure_wishlist_directories()
        path = os.path.join(isolated_wishlist, 'user-3_wishlist.json')
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump([1, 2, 3], handle)
        data = wishlist.load_user_wishlist('user-3')
        assert data['items'] == []
        assert data['user_id'] == 'user-3'

    def test_missing_items_field_defaults_to_empty_list(self, isolated_wishlist):
        wishlist.ensure_wishlist_directories()
        path = os.path.join(isolated_wishlist, 'user-2_wishlist.json')
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump({'username': 'tester'}, handle)
        assert wishlist.load_user_wishlist('user-2')['items'] == []

    def test_backup_creation_failure_does_not_block_save(self, isolated_wishlist, stub_resolver, monkeypatch):
        """A failed backup attempt (e.g. disk hiccup) is logged but never blocks the write
        itself - the atomic replace is the real safety net."""
        _add()
        data = wishlist.load_user_wishlist('user-1')

        def _raise(*args, **kwargs):
            raise OSError('backup boom')

        monkeypatch.setattr(wishlist.shutil, 'copy2', _raise)
        assert wishlist.save_user_wishlist('user-1', data, username='tester') is True

    def test_save_rejects_invalid_payload_and_restores_backup(self, isolated_wishlist, stub_resolver):
        """A payload failing validation leaves the previous file intact."""
        _add()
        good = wishlist.load_user_wishlist('user-1')

        broken = json.loads(json.dumps(good))
        broken['items'] = [{'id': 'x'}]  # missing 'name'
        assert wishlist.save_user_wishlist('user-1', broken, username='tester') is False

        # The original item survived the failed write
        restored = wishlist.load_user_wishlist('user-1')['items']
        assert len(restored) == 1
        assert restored[0]['name'] == 'M 31'

    def test_save_failure_without_prior_file_skips_restore(self, isolated_wishlist):
        """A validation failure on a brand-new file (nothing to back up/restore yet)
        still cleans up its own temp file without erroring on the missing backup."""
        bad_data = {'username': 'tester', 'items': [{'id': 'x'}]}  # missing 'name'
        assert wishlist.save_user_wishlist('user-1', bad_data, username='tester') is False
        assert not os.path.exists(wishlist.get_user_wishlist_file('user-1'))


class TestAddTargets:

    def test_coordinates_are_resolved_and_frozen_at_add_time(self, isolated_wishlist, stub_resolver):
        """The visibility pass must be a pure numeric loop later on."""
        item = _add()['added'][0]
        assert item['ra_deg'] == pytest.approx(10.68)
        assert item['dec_deg'] == pytest.approx(41.27)
        assert item['target_id'] == 'dso-ngc0224'
        assert item['resolved'] is True
        assert item['placed'] is True

    def test_missing_metadata_is_filled_from_the_dataset(self, isolated_wishlist, stub_resolver):
        item = _add(type='', constellation='')['added'][0]
        assert item['type'] == 'Galaxy'
        assert item['constellation'] == 'And'

    def test_client_metadata_wins_over_the_dataset(self, isolated_wishlist, stub_resolver):
        item = _add(type='Spiral Galaxy')['added'][0]
        assert item['type'] == 'Spiral Galaxy'

    def test_an_unresolvable_target_is_still_accepted(self, isolated_wishlist, stub_resolver):
        """An object outside the dataset is a legitimate wish; it just has no window."""
        item = _add(name='Barnard 33 East Lobe', catalogue='')['added'][0]
        assert item['resolved'] is False
        assert item['placed'] is False
        assert item['ra_deg'] is None

    def test_duplicate_by_name_is_skipped(self, isolated_wishlist, stub_resolver):
        _add()
        report = _add()
        assert report['added'] == []
        assert report['skipped_duplicates'] == 1
        assert len(wishlist.load_user_wishlist('user-1')['items']) == 1

    def test_duplicate_across_catalogues_is_skipped(self, isolated_wishlist, stub_resolver):
        """M 31 and NGC 224 are one object, so they are one wish."""
        _add(name='M 31', catalogue='Messier')
        report = _add(name='NGC 224', catalogue='OpenNGC')
        assert report['skipped_duplicates'] == 1
        assert len(wishlist.load_user_wishlist('user-1')['items']) == 1

    def test_duplicate_through_an_alias_is_skipped(self, isolated_wishlist, stub_resolver):
        _add(name='Andromeda Galaxy', catalogue='CommonName', catalogue_aliases={'Messier': 'M 31'})
        report = _add(name='M 31', catalogue='Messier')
        assert report['skipped_duplicates'] == 1

    def test_unnamed_targets_are_rejected(self, isolated_wishlist, stub_resolver):
        report = wishlist.add_targets('user-1', 'tester', [{'name': '   '}, 'not a dict'])
        assert report['added'] == []
        assert report['skipped_invalid'] == 2

    def test_several_targets_in_one_call(self, isolated_wishlist, stub_resolver):
        report = wishlist.add_targets('user-1', 'tester', [{'name': 'M 31'}, {'name': 'M 42'}, {'name': 'M 31'}])
        assert len(report['added']) == 2
        assert report['skipped_duplicates'] == 1

    def test_cap_is_enforced(self, isolated_wishlist, stub_resolver, monkeypatch):
        monkeypatch.setattr(wishlist, 'MAX_WISHLIST_ITEMS', 2)
        report = wishlist.add_targets(
            'user-1', 'tester', [{'name': 'Target A'}, {'name': 'Target B'}, {'name': 'Target C'}]
        )
        assert len(report['added']) == 2
        assert report['skipped_full'] == 1
        assert len(wishlist.load_user_wishlist('user-1')['items']) == 2

    def test_invalid_priority_falls_back_to_the_default(self, isolated_wishlist, stub_resolver):
        assert _add(priority='urgent')['added'][0]['priority'] == wishlist.DEFAULT_PRIORITY

    def test_valid_priority_is_kept(self, isolated_wishlist, stub_resolver):
        assert _add(priority='high')['added'][0]['priority'] == 'high'

    def test_invalid_source_falls_back_to_the_default(self, isolated_wishlist, stub_resolver):
        assert _add(source='somewhere')['added'][0]['source'] == wishlist.DEFAULT_SOURCE

    def test_known_source_is_kept(self, isolated_wishlist, stub_resolver):
        assert _add(source='beginner_catalog')['added'][0]['source'] == 'beginner_catalog'

    def test_captured_is_never_stored(self, isolated_wishlist, stub_resolver):
        """Storing it would go stale the moment a session is edited."""
        assert 'captured' not in _add()['added'][0]

    def test_save_failure_after_adding_reports_saved_false(self, isolated_wishlist, stub_resolver, monkeypatch):
        monkeypatch.setattr(wishlist, 'save_user_wishlist', lambda *args, **kwargs: False)
        report = wishlist.add_targets('user-1', 'tester', [{'name': 'M 31'}])
        assert report['added'] == []
        assert report['saved'] is False


class TestItemKey:
    """Cross-catalogue identity used for wishlist de-duplication."""

    def test_uses_the_catalogue_group_id_when_present(self):
        item = {'catalogue_group_id': 'dso-ngc0224', 'name': 'M 31'}
        assert wishlist.item_key(item) == 'dso-ngc0224'

    def test_falls_back_to_the_normalized_name_when_unresolved(self):
        item = {'catalogue_group_id': '', 'name': 'Barnard 33'}
        assert wishlist.item_key(item) == wishlist._normalize_key('Barnard 33')


class TestUpdateAndDelete:

    def test_update_priority_and_notes(self, isolated_wishlist, stub_resolver):
        item_id = _add()['added'][0]['id']
        updated = wishlist.update_item('user-1', item_id, {'priority': 'high', 'notes': 'wide field'})
        assert updated is not None
        assert updated['priority'] == 'high'
        assert updated['notes'] == 'wide field'

    def test_invalid_priority_is_refused(self, isolated_wishlist, stub_resolver):
        item_id = _add()['added'][0]['id']
        assert wishlist.update_item('user-1', item_id, {'priority': 'urgent'}) is None
        assert wishlist.load_user_wishlist('user-1')['items'][0]['priority'] == 'normal'

    def test_frozen_fields_cannot_be_changed(self, isolated_wishlist, stub_resolver):
        item_id = _add()['added'][0]['id']
        wishlist.update_item('user-1', item_id, {'name': 'Something else', 'ra_deg': 0.0, 'notes': 'x'})
        stored = wishlist.load_user_wishlist('user-1')['items'][0]
        assert stored['name'] == 'M 31'
        assert stored['ra_deg'] == pytest.approx(10.68)

    def test_update_unknown_item(self, isolated_wishlist, stub_resolver):
        _add()
        assert wishlist.update_item('user-1', 'nope', {'notes': 'x'}) is None

    def test_delete_item(self, isolated_wishlist, stub_resolver):
        item_id = _add()['added'][0]['id']
        assert wishlist.delete_item('user-1', item_id) is True
        assert wishlist.load_user_wishlist('user-1')['items'] == []

    def test_delete_unknown_item(self, isolated_wishlist, stub_resolver):
        assert wishlist.delete_item('user-1', 'nope') is False

    def test_remove_items_in_bulk(self, isolated_wishlist, stub_resolver):
        report = wishlist.add_targets('user-1', 'tester', [{'name': 'M 31'}, {'name': 'M 42'}])
        ids = [item['id'] for item in report['added']]
        assert wishlist.remove_items('user-1', ids) == 2
        assert wishlist.load_user_wishlist('user-1')['items'] == []

    def test_remove_items_with_nothing_to_remove(self, isolated_wishlist, stub_resolver):
        _add()
        assert wishlist.remove_items('user-1', []) == 0
        assert wishlist.remove_items('user-1', ['nope']) == 0


class TestDerivedCapturedState:

    def _item(self, name='M 31', group_id='dso-ngc0224', aliases=None):
        return {
            'id': 'item-1',
            'name': name,
            'catalogue_group_id': group_id,
            'catalogue_aliases': aliases or {},
        }

    def test_matching_group_id_marks_captured(self):
        index = wishlist.build_captured_index(['dso-ngc0224'])
        assert wishlist.annotate_captured([self._item()], index)[0]['captured'] is True

    def test_matching_name_marks_captured(self):
        """An Astrodex-only object has no group id, only a name."""
        index = wishlist.build_captured_index([], ['M 31'])
        assert wishlist.annotate_captured([self._item(group_id='')], index)[0]['captured'] is True

    def test_matching_alias_marks_captured(self):
        index = wishlist.build_captured_index([], ['NGC 224'])
        item = self._item(name='Andromeda Galaxy', group_id='', aliases={'OpenNGC': 'NGC 224'})
        assert wishlist.annotate_captured([item], index)[0]['captured'] is True

    def test_unrelated_captures_do_not_match(self):
        index = wishlist.build_captured_index(['dso-ngc1976'], ['M 42'])
        assert wishlist.annotate_captured([self._item()], index)[0]['captured'] is False

    def test_empty_index_marks_nothing(self):
        assert wishlist.annotate_captured([self._item()], set())[0]['captured'] is False

    def test_annotation_does_not_mutate_the_stored_item(self):
        item = self._item()
        wishlist.annotate_captured([item], wishlist.build_captured_index(['dso-ngc0224']))
        assert 'captured' not in item

    def test_progress_counters(self):
        index = wishlist.build_captured_index(['dso-ngc0224'])
        items = [self._item(), self._item(name='M 42', group_id='dso-ngc1976')]
        annotated = wishlist.annotate_captured(items, index)
        assert wishlist.progress(annotated) == {'captured': 1, 'total': 2}

    def test_progress_of_an_empty_wishlist(self):
        assert wishlist.progress([]) == {'captured': 0, 'total': 0}


class TestWishlistIndex:
    """The preloaded index used to annotate SkyTonight rows with in_wishlist."""

    def test_index_covers_every_identifier(self):
        items = [{'name': 'M 31', 'catalogue_group_id': 'dso-ngc0224', 'catalogue_aliases': {'OpenNGC': 'NGC 224'}}]
        index = wishlist.build_wishlist_index(items)
        assert wishlist.is_target_in_index(index, 'M 31') is True
        assert wishlist.is_target_in_index(index, 'NGC 224') is True
        assert wishlist.is_target_in_index(index, '', 'dso-ngc0224') is True

    def test_unrelated_target_is_not_in_the_index(self):
        index = wishlist.build_wishlist_index([{'name': 'M 31', 'catalogue_group_id': 'dso-ngc0224'}])
        assert wishlist.is_target_in_index(index, 'M 42') is False

    def test_empty_index_short_circuits(self):
        assert wishlist.is_target_in_index(set(), 'M 31') is False

    def test_non_dict_members_are_ignored(self):
        assert wishlist.build_wishlist_index(['junk', None]) == set()


class TestSorting:

    def _item(self, name, captured=False, priority='normal', hours=None):
        return {
            'id': name,
            'name': name,
            'captured': captured,
            'priority': priority,
            'observable_hours_next': hours,
        }

    def test_visibility_sort_puts_the_most_observable_first(self):
        items = [self._item('A', hours=1.0), self._item('B', hours=5.0), self._item('C', hours=3.0)]
        assert [item['name'] for item in wishlist.sort_items(items, 'visibility')] == ['B', 'C', 'A']

    def test_visibility_sort_puts_unknown_windows_last(self):
        """Unknown is not now - an item with no computed window must not lead the list."""
        items = [self._item('A', hours=None), self._item('B', hours=0.5)]
        assert [item['name'] for item in wishlist.sort_items(items, 'visibility')] == ['B', 'A']

    def test_captured_items_sink_to_the_bottom(self):
        items = [self._item('A', captured=True, hours=9.0), self._item('B', hours=1.0)]
        assert [item['name'] for item in wishlist.sort_items(items, 'visibility')] == ['B', 'A']

    def test_priority_sort(self):
        items = [self._item('A', priority='low'), self._item('B', priority='high'), self._item('C')]
        assert [item['name'] for item in wishlist.sort_items(items, 'priority')] == ['B', 'C', 'A']

    def test_priority_sort_tolerates_a_missing_priority(self):
        items = [{'id': 'A', 'name': 'A'}, self._item('B', priority='high')]
        assert [item['name'] for item in wishlist.sort_items(items, 'priority')] == ['B', 'A']

    def test_name_sort(self):
        items = [self._item('Zeta'), self._item('alpha')]
        assert [item['name'] for item in wishlist.sort_items(items, 'name')] == ['alpha', 'Zeta']

    def test_unknown_sort_falls_back_to_visibility(self):
        items = [self._item('A', hours=1.0), self._item('B', hours=5.0)]
        assert [item['name'] for item in wishlist.sort_items(items, 'nonsense')] == ['B', 'A']


class TestValidation:

    def test_valid_payload_passes(self, isolated_wishlist, stub_resolver):
        _add()
        path = os.path.join(isolated_wishlist, 'user-1_wishlist.json')
        assert wishlist.validate_wishlist_json(path) == (True, '')

    def test_item_without_an_id_is_rejected(self, isolated_wishlist, stub_resolver):
        _add()
        path = os.path.join(isolated_wishlist, 'user-1_wishlist.json')
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
        del data['items'][0]['id']
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(data, handle)
        is_valid, message = wishlist.validate_wishlist_json(path)
        assert is_valid is False
        assert 'id' in message

    def test_item_with_an_invalid_priority_is_rejected(self, isolated_wishlist, stub_resolver):
        _add()
        path = os.path.join(isolated_wishlist, 'user-1_wishlist.json')
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
        data['items'][0]['priority'] = 'urgent'
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(data, handle)
        assert wishlist.validate_wishlist_json(path)[0] is False

    def test_missing_items_list_is_rejected(self, isolated_wishlist):
        wishlist.ensure_wishlist_directories()
        path = os.path.join(isolated_wishlist, 'user-1_wishlist.json')
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump({'username': 'tester'}, handle)
        assert wishlist.validate_wishlist_json(path)[0] is False

    def test_non_dict_root_is_rejected(self, isolated_wishlist):
        wishlist.ensure_wishlist_directories()
        path = os.path.join(isolated_wishlist, 'array.json')
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump([1, 2, 3], handle)
        is_valid, message = wishlist.validate_wishlist_json(path)
        assert is_valid is False
        assert 'dictionary' in message

    def test_missing_username_field_is_rejected(self, isolated_wishlist):
        wishlist.ensure_wishlist_directories()
        path = os.path.join(isolated_wishlist, 'no_username.json')
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump({'items': []}, handle)
        is_valid, message = wishlist.validate_wishlist_json(path)
        assert is_valid is False
        assert 'username' in message

    def test_item_that_is_not_a_dict_is_rejected(self, isolated_wishlist):
        wishlist.ensure_wishlist_directories()
        path = os.path.join(isolated_wishlist, 'bad_item.json')
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump({'username': 'tester', 'items': ['not a dict']}, handle)
        is_valid, message = wishlist.validate_wishlist_json(path)
        assert is_valid is False
        assert 'object' in message

    def test_item_without_a_name_is_rejected(self, isolated_wishlist):
        wishlist.ensure_wishlist_directories()
        path = os.path.join(isolated_wishlist, 'no_name.json')
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump({'username': 'tester', 'items': [{'id': 'x'}]}, handle)
        is_valid, message = wishlist.validate_wishlist_json(path)
        assert is_valid is False
        assert 'name' in message

    def test_malformed_json_is_reported(self, isolated_wishlist):
        wishlist.ensure_wishlist_directories()
        path = os.path.join(isolated_wishlist, 'broken.json')
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write('{ this is not json')
        is_valid, message = wishlist.validate_wishlist_json(path)
        assert is_valid is False
        assert 'Invalid JSON' in message

    def test_path_outside_directory_is_a_validation_error(self, isolated_wishlist):
        outside_path = os.path.join(isolated_wishlist, '..', 'outside.json')
        is_valid, message = wishlist.validate_wishlist_json(outside_path)
        assert is_valid is False
        assert 'Validation error' in message


class TestMovingTargets:
    """Planets and comets move, so a frozen RA/Dec would be wrong within weeks."""

    def test_a_planet_keeps_the_wish_but_not_a_position(self, isolated_wishlist, monkeypatch):
        monkeypatch.setattr(
            wishlist.target_coordinates,
            'resolve_target',
            lambda *args, **kwargs: {
                'group_id': 'body-jupiter',
                'target_id': 'body-jupiter',
                'preferred_name': 'Jupiter',
                'object_type': 'Planet',
                'constellation': '',
                'category': 'bodies',
                'ra_deg': 55.0,
                'dec_deg': 20.0,
                'resolved': True,
                'placed': True,
            },
        )
        item = _add(name='Jupiter', catalogue='Bodies')['added'][0]
        assert item['moving'] is True
        assert item['ra_deg'] is None
        assert item['dec_deg'] is None
        assert item['placed'] is False
        assert item['resolved'] is True

    def test_a_comet_is_detected_by_its_type(self, isolated_wishlist, monkeypatch):
        monkeypatch.setattr(
            wishlist.target_coordinates,
            'resolve_target',
            lambda *args, **kwargs: {
                'group_id': '',
                'target_id': '',
                'preferred_name': '',
                'object_type': 'Comet',
                'constellation': '',
                'category': '',
                'ra_deg': 120.0,
                'dec_deg': 10.0,
                'resolved': False,
                'placed': True,
            },
        )
        item = _add(name='C/2023 A3', catalogue='Comets', type='Comet')['added'][0]
        assert item['moving'] is True
        assert item['ra_deg'] is None

    def test_a_deep_sky_object_is_not_moving(self, isolated_wishlist, stub_resolver):
        item = _add()['added'][0]
        assert item['moving'] is False
        assert item['ra_deg'] is not None

    def test_detector_recognises_categories_and_types(self):
        assert wishlist._is_moving_target('bodies', '') is True
        assert wishlist._is_moving_target('comets', '') is True
        assert wishlist._is_moving_target('', 'Dwarf Planet') is True
        assert wishlist._is_moving_target('', 'Minor Planet') is True
        assert wishlist._is_moving_target('deep_sky', 'Galaxy') is False
        assert wishlist._is_moving_target(None, None) is False
