"""
Tests for Astrodex module
"""
import pytest
import os
import json
import tempfile
import sys

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from observation import astrodex
from observation import catalogue_aliases
from skytonight import skytonight_targets


@pytest.fixture
def temp_data_dir(monkeypatch):
    """Create a temporary directory for astrodex data"""
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setenv('DATA_DIR', tmpdir)
        # Reset module-level variables
        astrodex.ASTRODEX_DIR = os.path.join(tmpdir, 'astrodex')
        astrodex.ASTRODEX_IMAGES_DIR = os.path.join(astrodex.ASTRODEX_DIR, 'images')
        yield tmpdir


class TestAstrodexDataModel:
    """Test Astrodex data model and storage"""
    
    def test_ensure_directories(self, temp_data_dir):
        """Test directory creation"""
        astrodex.ensure_astrodex_directories()
        assert os.path.exists(astrodex.ASTRODEX_DIR)
        assert os.path.exists(astrodex.ASTRODEX_IMAGES_DIR)
    
    def test_load_empty_astrodex(self, temp_data_dir):
        """Test loading empty astrodex"""
        data = astrodex.load_user_astrodex('testuser', username='testuser')
        assert data['username'] == 'testuser'
        assert data['items'] == []
        assert 'created_at' in data
    
    def test_create_item(self, temp_data_dir):
        """Test creating an astrodex item"""
        item_data = {
            'name': 'M31',
            'type': 'Galaxy',
            'constellation': 'Andromeda',
            'magnitude': '3.44',
            'notes': 'Andromeda Galaxy'
        }
        
        item = astrodex.create_astrodex_item('testuser', item_data)
        
        assert item is not None
        assert item['name'] == 'M31'
        assert item['type'] == 'Galaxy'
        assert item['constellation'] == 'Andromeda'
        assert 'id' in item
        assert item['pictures'] == []
        assert 'ra' not in item
        assert 'dec' not in item
        assert 'magnitude' not in item
        assert 'size' not in item
        assert 'catalogue_aliases' not in item
        assert 'catalogue_group_id' not in item
        # No location on the item itself (v1.2) - the same object can be
        # re-photographed from different sites across sessions, so location
        # lives only on individual pictures.
        assert 'location_id' not in item
        assert 'location_name' not in item
    
    def test_duplicate_item(self, temp_data_dir):
        """Test that duplicate items are rejected"""
        item_data = {
            'name': 'M31',
            'type': 'Galaxy'
        }
        
        # Create first item
        item1 = astrodex.create_astrodex_item('testuser', item_data)
        assert item1 is not None
        
        # Try to create duplicate
        item2 = astrodex.create_astrodex_item('testuser', item_data)
        assert item2 is None
    
    def test_get_item(self, temp_data_dir):
        """Test retrieving an item"""
        item_data = {'name': 'M42', 'type': 'Nebula'}
        created_item = astrodex.create_astrodex_item('testuser', item_data)
        
        retrieved_item = astrodex.get_astrodex_item('testuser', created_item['id'])
        
        assert retrieved_item is not None
        assert retrieved_item['id'] == created_item['id']
        assert retrieved_item['name'] == 'M42'
    
    def test_update_item(self, temp_data_dir):
        """Test updating an item"""
        item_data = {'name': 'M42', 'type': 'Nebula'}
        created_item = astrodex.create_astrodex_item('testuser', item_data)
        
        updates = {
            'notes': 'Great Orion Nebula',
            'constellation': 'Orion'
        }
        
        updated_item = astrodex.update_astrodex_item('testuser', created_item['id'], updates)
        
        assert updated_item is not None
        assert updated_item['notes'] == 'Great Orion Nebula'
        assert updated_item['constellation'] == 'Orion'
    
    def test_delete_item(self, temp_data_dir):
        """Test deleting an item"""
        item_data = {'name': 'M45', 'type': 'Star Cluster'}
        created_item = astrodex.create_astrodex_item('testuser', item_data)
        
        # Delete the item
        result = astrodex.delete_astrodex_item('testuser', created_item['id'])
        assert result is True
        
        # Verify it's gone
        retrieved_item = astrodex.get_astrodex_item('testuser', created_item['id'])
        assert retrieved_item is None
    
    def test_is_item_in_astrodex(self, temp_data_dir):
        """Test checking if item is in astrodex"""
        item_data = {'name': 'NGC 2244', 'type': 'Star Cluster'}
        astrodex.create_astrodex_item('testuser', item_data)
        
        assert astrodex.is_item_in_astrodex('testuser', 'NGC 2244') is True
        assert astrodex.is_item_in_astrodex('testuser', 'M31') is False
    
    def test_user_isolation(self, temp_data_dir):
        """Test that users have separate astrodex collections"""
        item_data = {'name': 'M31', 'type': 'Galaxy'}
        
        # Create item for user1
        astrodex.create_astrodex_item('user1', item_data)
        
        # Check user2 doesn't have it
        assert astrodex.is_item_in_astrodex('user2', 'M31') is False


class TestAstrodexPictures:
    """Test picture management"""
    
    def test_add_picture(self, temp_data_dir):
        """Test adding a picture to an item"""
        item_data = {'name': 'M31', 'type': 'Galaxy'}
        item = astrodex.create_astrodex_item('testuser', item_data)
        
        picture_data = {
            'filename': 'test_image.jpg',
            'date': '2024-01-15',
            'exposition_time': '120x30s',
            'device': 'Canon EOS',
            'filters': 'LRGB'
        }
        
        picture = astrodex.add_picture_to_item('testuser', item['id'], picture_data)
        
        assert picture is not None
        assert picture['filename'] == 'test_image.jpg'
        assert picture['date'] == '2024-01-15'
        assert picture['is_main'] is True  # First picture is main
    
    def test_add_picture_with_combination_and_rating(self, temp_data_dir):
        """combination_id, combination_used_components and rating persist on a new picture."""
        item = astrodex.create_astrodex_item('testuser', {'name': 'M31', 'type': 'Galaxy'})
        picture_data = {
            'filename': 'test_image.jpg',
            'combination_id': 'combo-1',
            'combination_used_components': {'telescope': True, 'camera': True, 'filter_ids': ['f1']},
            'rating': 4.5,
        }

        picture = astrodex.add_picture_to_item('testuser', item['id'], picture_data)

        assert picture['combination_id'] == 'combo-1'
        assert picture['combination_used_components'] == {
            'telescope': True,
            'camera': True,
            'filter_ids': ['f1'],
        }
        assert picture['rating'] == 4.5

    def test_add_picture_without_combination_defaults_to_none(self, temp_data_dir):
        """The 'Other equipment' free-text path leaves combination_id/rating unset (None)."""
        item = astrodex.create_astrodex_item('testuser', {'name': 'M31', 'type': 'Galaxy'})
        picture = astrodex.add_picture_to_item('testuser', item['id'], {'filename': 'pic.jpg', 'device': 'DSLR'})

        assert picture['combination_id'] is None
        assert picture['combination_used_components'] is None
        assert picture['rating'] is None

    def test_update_picture_combination_and_rating_fields(self, temp_data_dir):
        """update_picture accepts combination_id/combination_used_components/rating."""
        item = astrodex.create_astrodex_item('testuser', {'name': 'M31', 'type': 'Galaxy'})
        picture = astrodex.add_picture_to_item('testuser', item['id'], {'filename': 'pic.jpg'})

        updated = astrodex.update_picture(
            'testuser',
            item['id'],
            picture['id'],
            {
                'combination_id': 'combo-2',
                'combination_used_components': {'telescope': False, 'camera': True},
                'rating': 3.0,
            },
        )

        assert updated['combination_id'] == 'combo-2'
        assert updated['combination_used_components'] == {'telescope': False, 'camera': True}
        assert updated['rating'] == 3.0

    def test_add_multiple_pictures(self, temp_data_dir):
        """Test adding multiple pictures"""
        item_data = {'name': 'M42', 'type': 'Nebula'}
        item = astrodex.create_astrodex_item('testuser', item_data)
        
        # Add first picture
        pic1_data = {'filename': 'pic1.jpg', 'date': '2024-01-15'}
        pic1 = astrodex.add_picture_to_item('testuser', item['id'], pic1_data)
        
        # Add second picture
        pic2_data = {'filename': 'pic2.jpg', 'date': '2024-01-16'}
        pic2 = astrodex.add_picture_to_item('testuser', item['id'], pic2_data)
        
        assert pic1['is_main'] is True
        assert pic2['is_main'] is False
        
        # Verify item has both pictures
        updated_item = astrodex.get_astrodex_item('testuser', item['id'])
        assert len(updated_item['pictures']) == 2
    
    def test_set_main_picture(self, temp_data_dir):
        """Test setting a different picture as main"""
        item_data = {'name': 'M31', 'type': 'Galaxy'}
        item = astrodex.create_astrodex_item('testuser', item_data)
        
        # Add two pictures
        astrodex.add_picture_to_item('testuser', item['id'], {'filename': 'pic1.jpg'})
        pic2 = astrodex.add_picture_to_item('testuser', item['id'], {'filename': 'pic2.jpg'})

        # Set second picture as main
        result = astrodex.set_main_picture('testuser', item['id'], pic2['id'])
        assert result is True
        
        # Verify
        updated_item = astrodex.get_astrodex_item('testuser', item['id'])
        assert updated_item['pictures'][0]['is_main'] is False
        assert updated_item['pictures'][1]['is_main'] is True
    
    def test_delete_picture(self, temp_data_dir):
        """Test deleting a picture"""
        item_data = {'name': 'M42', 'type': 'Nebula'}
        item = astrodex.create_astrodex_item('testuser', item_data)
        
        # Add pictures
        pic1 = astrodex.add_picture_to_item('testuser', item['id'], {'filename': 'pic1.jpg'})
        astrodex.add_picture_to_item('testuser', item['id'], {'filename': 'pic2.jpg'})

        # Delete first picture (which is main)
        result = astrodex.delete_picture('testuser', item['id'], pic1['id'])
        assert result is True
        
        # Verify second picture became main
        updated_item = astrodex.get_astrodex_item('testuser', item['id'])
        assert len(updated_item['pictures']) == 1
        assert updated_item['pictures'][0]['is_main'] is True
    
    def test_get_main_picture(self, temp_data_dir):
        """Test getting main picture"""
        item_data = {'name': 'M31', 'type': 'Galaxy'}
        item = astrodex.create_astrodex_item('testuser', item_data)
        
        # No pictures
        main_pic = astrodex.get_main_picture(item)
        assert main_pic is None
        
        # Add pictures
        astrodex.add_picture_to_item('testuser', item['id'], {'filename': 'pic1.jpg'})
        astrodex.add_picture_to_item('testuser', item['id'], {'filename': 'pic2.jpg'})

        updated_item = astrodex.get_astrodex_item('testuser', item['id'])
        main_pic = astrodex.get_main_picture(updated_item)
        
        assert main_pic is not None
        assert main_pic['filename'] == 'pic1.jpg'


class TestCombinationPhotoStats:
    """Test count_pictures_for_combination, build_combination_photo_index, summarize_combination_pictures."""

    def test_count_pictures_for_combination(self, temp_data_dir):
        item = astrodex.create_astrodex_item('testuser', {'name': 'M31', 'type': 'Galaxy'})
        astrodex.add_picture_to_item('testuser', item['id'], {'filename': 'a.jpg', 'combination_id': 'combo-1'})
        astrodex.add_picture_to_item('testuser', item['id'], {'filename': 'b.jpg', 'combination_id': 'combo-1'})
        astrodex.add_picture_to_item('testuser', item['id'], {'filename': 'c.jpg', 'combination_id': 'combo-2'})
        astrodex.add_picture_to_item('testuser', item['id'], {'filename': 'd.jpg'})  # no combination

        assert astrodex.count_pictures_for_combination('combo-1') == 2
        assert astrodex.count_pictures_for_combination('combo-2') == 1
        assert astrodex.count_pictures_for_combination('combo-missing') == 0
        assert astrodex.count_pictures_for_combination('') == 0

    def test_count_pictures_for_combination_no_directory(self, temp_data_dir):
        """No astrodex directory at all → 0, not an error."""
        assert astrodex.count_pictures_for_combination('combo-1') == 0

    def test_build_combination_photo_index_and_summarize(self, temp_data_dir):
        item = astrodex.create_astrodex_item('alice', {'name': 'M31', 'type': 'Galaxy'}, username='alice')
        astrodex.add_picture_to_item(
            'alice', item['id'], {'filename': 'a.jpg', 'combination_id': 'combo-1', 'rating': 4.0}
        )
        astrodex.add_picture_to_item(
            'alice', item['id'], {'filename': 'b.jpg', 'combination_id': 'combo-1', 'rating': 5.0}
        )
        astrodex.add_picture_to_item('alice', item['id'], {'filename': 'c.jpg', 'combination_id': 'combo-1'})  # unrated
        astrodex.add_picture_to_item('alice', item['id'], {'filename': 'd.jpg'})  # no combination at all

        index = astrodex.build_combination_photo_index('alice', 'alice', private_mode=True)

        assert set(index.keys()) == {'combo-1'}
        assert len(index['combo-1']) == 3
        assert all('item_id' in picture and 'item_name' in picture for picture in index['combo-1'])

        stats = astrodex.summarize_combination_pictures(index['combo-1'])
        assert stats['photo_count'] == 3
        assert stats['average_rating'] == 4.5  # mean of 4.0 and 5.0 only - unrated excluded
        assert len(stats['picture_refs']) == 3

    def test_summarize_combination_pictures_empty(self):
        stats = astrodex.summarize_combination_pictures([])
        assert stats == {'photo_count': 0, 'average_rating': None, 'picture_refs': []}

    def test_summarize_combination_pictures_all_unrated(self):
        stats = astrodex.summarize_combination_pictures([{'rating': None}, {'rating': None}])
        assert stats['photo_count'] == 2
        assert stats['average_rating'] is None


class TestAstrodexStats:
    """Test statistics generation"""
    
    def test_stats_empty(self, temp_data_dir):
        """Test stats for empty astrodex"""
        stats = astrodex.get_astrodex_stats('testuser')
        
        assert stats['total_items'] == 0
        assert stats['items_with_pictures'] == 0
        assert stats['items_without_pictures'] == 0
        assert stats['total_pictures'] == 0
        assert stats['types'] == {}
    
    def test_stats_with_items(self, temp_data_dir):
        """Test stats with items"""
        # Create items
        astrodex.create_astrodex_item('testuser', {'name': 'M31', 'type': 'Galaxy'})
        astrodex.create_astrodex_item('testuser', {'name': 'M42', 'type': 'Nebula'})
        astrodex.create_astrodex_item('testuser', {'name': 'M45', 'type': 'Star Cluster'})
        
        # Add picture to one item
        item = astrodex.get_astrodex_item('testuser', 
                                          astrodex.load_user_astrodex('testuser')['items'][0]['id'])
        astrodex.add_picture_to_item('testuser', item['id'], {'filename': 'test.jpg'})
        
        stats = astrodex.get_astrodex_stats('testuser')
        
        assert stats['total_items'] == 3
        assert stats['items_with_pictures'] == 1
        assert stats['items_without_pictures'] == 2
        assert stats['total_pictures'] == 1
        assert stats['types']['Galaxy'] == 1
        assert stats['types']['Nebula'] == 1
        assert stats['types']['Star Cluster'] == 1


class TestAstrodexBackupMechanism:
    """Test backup and recovery mechanism for data safety"""
    
    def test_validate_astrodex_json_valid(self, temp_data_dir):
        """Test validation of valid astrodex JSON"""
        # Create a valid astrodex file
        item_data = {'name': 'M31', 'type': 'Galaxy'}
        astrodex.create_astrodex_item('testuser', item_data)

        file_path = astrodex.get_user_astrodex_file('testuser')
        is_valid, error_msg = astrodex.validate_astrodex_json(file_path)
        
        assert is_valid is True
        assert error_msg == ""
    
    def test_validate_astrodex_json_invalid(self, temp_data_dir):
        """Test validation of invalid JSON"""
        file_path = astrodex.get_user_astrodex_file('testuser')
        
        # Write invalid JSON
        with open(file_path, 'w') as f:
            f.write("{ invalid json }")
        
        is_valid, error_msg = astrodex.validate_astrodex_json(file_path)
        
        assert is_valid is False
        assert "Invalid JSON" in error_msg
    
    def test_validate_astrodex_json_missing_fields(self, temp_data_dir):
        """Test validation of JSON with missing required fields"""
        file_path = astrodex.get_user_astrodex_file('testuser')
        
        # Write JSON without required fields
        with open(file_path, 'w') as f:
            json.dump({'invalid': 'data'}, f)
        
        is_valid, error_msg = astrodex.validate_astrodex_json(file_path)
        
        assert is_valid is False
        assert "username" in error_msg or "items" in error_msg
    
    def test_backup_created_during_save(self, temp_data_dir):
        """Test that backup is created during save operation"""
        # Create initial item
        item_data = {'name': 'M31', 'type': 'Galaxy'}
        item = astrodex.create_astrodex_item('testuser', item_data)
        
        file_path = astrodex.get_user_astrodex_file('testuser')
        backup_path = file_path + '.backup'
        
        # Backup should not exist after successful save
        assert not os.path.exists(backup_path)
        
        # Update item (triggers save)
        astrodex.update_astrodex_item('testuser', item['id'], {'notes': 'Test update'})
        
        # Backup should still not exist (cleaned up after success)
        assert not os.path.exists(backup_path)
    
    def test_save_recovery_from_corruption(self, temp_data_dir, monkeypatch):
        """Test that backup is restored if write fails"""
        # Create initial valid item
        item_data = {'name': 'M31', 'type': 'Galaxy'}
        item = astrodex.create_astrodex_item('testuser', item_data)
        
        file_path = astrodex.get_user_astrodex_file('testuser')
        
        # Read original content
        with open(file_path, 'r') as f:
            original_content = f.read()
        
        # Monkey patch json.dump to fail
        original_dump = json.dump
        def failing_dump(*args, **kwargs):
            raise ValueError("Simulated write failure")
        
        monkeypatch.setattr(json, 'dump', failing_dump)
        
        # Try to update - should fail but restore backup
        result = astrodex.update_astrodex_item('testuser', item['id'], {'notes': 'Should fail'})
        
        # Restore original json.dump
        monkeypatch.setattr(json, 'dump', original_dump)
        
        assert result is None  # Update failed
        
        # Original file should still be intact (restored from backup)
        with open(file_path, 'r') as f:
            current_content = f.read()
        
        assert current_content == original_content
    
    def test_validation_prevents_corrupt_save(self, temp_data_dir, monkeypatch):
        """Test that validation prevents saving corrupt data"""
        # Create initial item
        item_data = {'name': 'M31', 'type': 'Galaxy'}
        item = astrodex.create_astrodex_item('testuser', item_data)
        
        file_path = astrodex.get_user_astrodex_file('testuser')
        
        # Read original content
        with open(file_path, 'r') as f:
            original_data = json.load(f)
        
        # Monkey patch validation to fail
        def failing_validation(*args, **kwargs):
            return False, "Simulated validation failure"
        
        monkeypatch.setattr(astrodex, 'validate_astrodex_json', failing_validation)
        
        # Try to update - should fail validation
        result = astrodex.update_astrodex_item('testuser', item['id'], {'notes': 'Should fail validation'})
        
        assert result is None  # Update failed
        
        # Original file should still be intact
        with open(file_path, 'r') as f:
            current_data = json.load(f)
        
        assert current_data == original_data
    
    def test_temp_file_cleanup_on_error(self, temp_data_dir, monkeypatch):
        """Test that temporary files are cleaned up on error"""
        # Create initial item
        item_data = {'name': 'M31', 'type': 'Galaxy'}
        item = astrodex.create_astrodex_item('testuser', item_data)
        
        file_path = astrodex.get_user_astrodex_file('testuser')
        temp_path = file_path + '.tmp'
        backup_path = file_path + '.backup'
        
        # Monkey patch validation to fail
        def failing_validation(*args, **kwargs):
            return False, "Simulated validation failure"
        
        monkeypatch.setattr(astrodex, 'validate_astrodex_json', failing_validation)
        
        # Try to update - should fail
        result = astrodex.update_astrodex_item('testuser', item['id'], {'notes': 'Should fail'})
        
        assert result is None
        
        # Temporary and backup files should be cleaned up
        assert not os.path.exists(temp_path)
        assert not os.path.exists(backup_path)
    
    def test_save_works_for_new_user(self, temp_data_dir):
        """Test that save works correctly for new user with no existing file"""
        item_data = {'name': 'M31', 'type': 'Galaxy'}
        astrodex.create_astrodex_item('newuser', item_data)


class TestAstrodexAliases:
    """Test aliases table integration in Astrodex"""

    @staticmethod
    def _fake_alias_entry(catalogue: str, object_name: str) -> dict:
        entry = {
            'group_id': 'OBJ000001',
            'aliases': {
                'GaryImm': 'M81',
                'Messier': 'M 81',
                'OpenNGC': 'NGC 3031'
            }
        }

        if catalogue == 'GaryImm' and object_name == 'M81':
            return entry
        if catalogue == 'Messier' and object_name == 'M 81':
            return entry
        if catalogue == 'OpenNGC' and object_name == 'NGC 3031':
            return entry
        return {}

    def test_alias_deduplication_across_catalogues(self, temp_data_dir, monkeypatch):
        """Test duplicate detection using catalogue aliases"""
        monkeypatch.setattr(skytonight_targets, 'get_lookup_entry', self._fake_alias_entry)

        item_data = {
            'name': 'M81',
            'type': 'Galaxy',
            'catalogue': 'GaryImm'
        }
        item = astrodex.create_astrodex_item('testuser', item_data)
        assert item is not None

        assert astrodex.is_item_in_astrodex('testuser', 'NGC 3031', 'OpenNGC') is True

    def test_alias_matching_with_decorated_target_name(self, temp_data_dir, monkeypatch):
        """Test matching still works when target labels contain extra description text."""
        monkeypatch.setattr(skytonight_targets, 'get_lookup_entry', self._fake_alias_entry)

        item = astrodex.create_astrodex_item(
            'testuser',
            {'name': 'M81', 'type': 'Galaxy', 'catalogue': 'GaryImm'}
        )
        assert item is not None

        label = 'Bode\'s Galaxy (M 81, size: 27\', foto: 0.65, mag: 6.9)'
        assert astrodex.is_item_in_astrodex('testuser', label, 'Messier') is True

    def test_alias_matching_catalogue_key_case_insensitive(self, temp_data_dir, monkeypatch):
        """Test matching with different catalogue key casing."""
        monkeypatch.setattr(skytonight_targets, 'get_lookup_entry', self._fake_alias_entry)

        item = astrodex.create_astrodex_item(
            'testuser',
            {'name': 'M81', 'type': 'Galaxy', 'catalogue': 'GaryImm'}
        )
        assert item is not None

        assert astrodex.is_item_in_astrodex('testuser', 'NGC 3031', 'openngc') is True

    def test_alias_metadata_enrichment(self, temp_data_dir, monkeypatch):
        """Test alias metadata is attached to items when available"""
        monkeypatch.setattr(skytonight_targets, 'get_lookup_entry', self._fake_alias_entry)
        monkeypatch.setattr(catalogue_aliases, 'get_alias_entry', self._fake_alias_entry)

        item_data = {
            'name': 'M81',
            'type': 'Galaxy',
            'catalogue': 'GaryImm'
        }
        item = astrodex.create_astrodex_item('testuser', item_data)
        assert item is not None

        enriched = astrodex.enrich_item_with_catalogue_aliases(item)
        assert 'catalogue_group_id' not in enriched
        assert enriched.get('catalogue_aliases', {}).get('OpenNGC') == 'NGC 3031'

    def test_save_sanitizes_legacy_transient_and_unused_fields(self, temp_data_dir):
        """Test persisted astrodex drops transient aliases/group and unused data fields."""
        item = astrodex.create_astrodex_item('testuser', {'name': 'M42', 'type': 'Nebula'})
        assert item is not None

        astrodex_data = astrodex.load_user_astrodex('testuser')
        astrodex_data['items'][0]['catalogue_aliases'] = {'OpenNGC': 'NGC 1976'}
        astrodex_data['items'][0]['catalogue_group_id'] = 'OBJ000111'
        astrodex_data['items'][0]['ra'] = '05h35m'
        astrodex_data['items'][0]['dec'] = '-05d23m'
        astrodex_data['items'][0]['magnitude'] = '4.0'
        astrodex_data['items'][0]['size'] = '65x60'

        assert astrodex.save_user_astrodex('testuser', astrodex_data)

        reloaded = astrodex.load_user_astrodex('testuser')
        persisted_item = reloaded['items'][0]
        assert 'catalogue_aliases' not in persisted_item
        assert 'catalogue_group_id' not in persisted_item
        assert 'ra' not in persisted_item
        assert 'dec' not in persisted_item
        assert 'magnitude' not in persisted_item
        assert 'size' not in persisted_item

    def test_switch_item_catalogue_name(self, temp_data_dir, monkeypatch):
        """Test switching displayed name to another catalogue alias"""
        monkeypatch.setattr(skytonight_targets, 'get_lookup_entry', self._fake_alias_entry)
        monkeypatch.setattr(catalogue_aliases, 'get_alias_entry', self._fake_alias_entry)

        item_data = {
            'name': 'M81',
            'type': 'Galaxy',
            'catalogue': 'GaryImm'
        }
        item = astrodex.create_astrodex_item('testuser', item_data)
        assert item is not None

        updated = astrodex.switch_item_catalogue_name('testuser', item['id'], 'OpenNGC')
        assert updated is not None
        assert updated['name'] == 'NGC 3031'
        assert updated['catalogue'] == 'OpenNGC'

    def test_switch_item_catalogue_name_duplicate(self, temp_data_dir, monkeypatch):
        """Test switching fails when an equivalent object already exists"""
        monkeypatch.setattr(skytonight_targets, 'get_lookup_entry', self._fake_alias_entry)
        monkeypatch.setattr(catalogue_aliases, 'get_alias_entry', self._fake_alias_entry)

        first_item = astrodex.create_astrodex_item(
            'testuser',
            {'name': 'M81', 'type': 'Galaxy', 'catalogue': 'GaryImm'}
        )
        assert first_item is not None

        astrodex_data = astrodex.load_user_astrodex('testuser')
        astrodex_data['items'].append({
            'id': 'manual-duplicate',
            'name': 'NGC 3031',
            'type': 'Galaxy',
            'catalogue': 'OpenNGC',
            'pictures': [],
            'created_at': first_item['created_at'],
            'updated_at': first_item['updated_at']
        })
        assert astrodex.save_user_astrodex('testuser', astrodex_data)

        with pytest.raises(ValueError):
            astrodex.switch_item_catalogue_name('testuser', first_item['id'], 'OpenNGC')


class TestAstrodexVisibilityModes:
    """Test private/public astrodex visibility and shared items behavior."""

    @staticmethod
    def _fake_alias_entry(catalogue: str, object_name: str) -> dict:
        entry = {
            'group_id': 'OBJ000001',
            'aliases': {
                'GaryImm': 'M81',
                'OpenNGC': 'NGC 3031'
            }
        }

        if catalogue == 'GaryImm' and object_name == 'M81':
            return entry
        if catalogue == 'OpenNGC' and object_name == 'NGC 3031':
            return entry
        return {}

    def test_public_mode_merges_shared_items_and_pictures(self, temp_data_dir, monkeypatch):
        """Public mode merges equivalent objects and keeps owner metadata per picture."""
        monkeypatch.setattr(skytonight_targets, 'get_lookup_entry', self._fake_alias_entry)
        monkeypatch.setattr(catalogue_aliases, 'get_alias_entry', self._fake_alias_entry)

        user1_item = astrodex.create_astrodex_item(
            'user1',
            {'name': 'M81', 'type': 'Galaxy', 'catalogue': 'GaryImm'},
            username='alice'
        )
        assert user1_item is not None

        user2_item = astrodex.create_astrodex_item(
            'user2',
            {'name': 'NGC 3031', 'type': 'Galaxy', 'catalogue': 'OpenNGC'},
            username='bob'
        )
        assert user2_item is not None

        astrodex.add_picture_to_item('user1', user1_item['id'], {'filename': 'u1_pic.jpg'})
        astrodex.add_picture_to_item('user2', user2_item['id'], {'filename': 'u2_pic.jpg'})

        payload = astrodex.get_visible_astrodex(
            current_user_id='user1',
            current_username='alice',
            private_mode=False,
            usernames_by_id={'user1': 'alice', 'user2': 'bob'}
        )

        assert payload['private_mode'] is False
        assert len(payload['items']) == 1

        merged_item = payload['items'][0]
        assert merged_item['is_owned_by_current_user'] is True
        assert merged_item['own_pictures_count'] == 1
        assert merged_item['total_pictures'] == 2

        owners = {picture.get('owner_username') for picture in merged_item.get('pictures', [])}
        assert owners == {'alice', 'bob'}

    def test_private_mode_shows_only_own_items(self, temp_data_dir, monkeypatch):
        """Private mode hides other users items and pictures."""
        monkeypatch.setattr(skytonight_targets, 'get_lookup_entry', self._fake_alias_entry)
        monkeypatch.setattr(catalogue_aliases, 'get_alias_entry', self._fake_alias_entry)

        user1_item = astrodex.create_astrodex_item(
            'user1',
            {'name': 'M81', 'type': 'Galaxy', 'catalogue': 'GaryImm'},
            username='alice'
        )
        assert user1_item is not None

        user2_item = astrodex.create_astrodex_item(
            'user2',
            {'name': 'NGC 3031', 'type': 'Galaxy', 'catalogue': 'OpenNGC'},
            username='bob'
        )
        assert user2_item is not None

        astrodex.add_picture_to_item('user1', user1_item['id'], {'filename': 'u1_private.jpg'})
        astrodex.add_picture_to_item('user2', user2_item['id'], {'filename': 'u2_private.jpg'})

        payload = astrodex.get_visible_astrodex(
            current_user_id='user1',
            current_username='alice',
            private_mode=True,
            usernames_by_id={'user1': 'alice', 'user2': 'bob'}
        )

        assert payload['private_mode'] is True
        assert len(payload['items']) == 1

        own_item = payload['items'][0]
        assert own_item['is_owned_by_current_user'] is True
        assert own_item['total_pictures'] == 1
        assert own_item['own_pictures_count'] == 1
        assert own_item['pictures'][0]['filename'] == 'u1_private.jpg'

    def test_public_mode_non_owned_item_is_slideshow_only_source(self, temp_data_dir):
        """If current user has no item, merged item is marked as non-owned with zero own pictures."""
        user2_item = astrodex.create_astrodex_item(
            'user2',
            {'name': 'M42', 'type': 'Nebula', 'catalogue': 'Messier'},
            username='bob'
        )
        assert user2_item is not None
        astrodex.add_picture_to_item('user2', user2_item['id'], {'filename': 'u2_only.jpg'})

        payload = astrodex.get_visible_astrodex(
            current_user_id='user1',
            current_username='alice',
            private_mode=False,
            usernames_by_id={'user1': 'alice', 'user2': 'bob'}
        )

        assert len(payload['items']) == 1
        visible_item = payload['items'][0]
        assert visible_item['is_owned_by_current_user'] is False
        assert visible_item['own_pictures_count'] == 0
        assert visible_item['total_pictures'] == 1

    def test_can_user_view_image_respects_privacy_mode(self, temp_data_dir):
        """Image access helper restricts private mode to own pictures only."""
        user1_item = astrodex.create_astrodex_item('user1', {'name': 'M31', 'type': 'Galaxy'}, username='alice')
        user2_item = astrodex.create_astrodex_item('user2', {'name': 'M42', 'type': 'Nebula'}, username='bob')
        assert user1_item is not None
        assert user2_item is not None

        astrodex.add_picture_to_item('user1', user1_item['id'], {'filename': 'alice_img.jpg'})
        astrodex.add_picture_to_item('user2', user2_item['id'], {'filename': 'bob_img.jpg'})

        assert astrodex.can_user_view_image('user1', 'alice_img.jpg', private_mode=True) is True
        assert astrodex.can_user_view_image('user1', 'bob_img.jpg', private_mode=True) is False

        assert astrodex.can_user_view_image('user1', 'bob_img.jpg', private_mode=False) is True

    def test_public_mode_strips_coordinates_from_other_users_pictures(self, temp_data_dir):
        """Coordinates are private to a picture's owner (v1.2) - the merged/
        shared view must keep location_name visible but never leak another
        user's exact capture coordinates (which, for a 'home' preset, is
        effectively their address)."""
        user1_item = astrodex.create_astrodex_item('user1', {'name': 'M51', 'type': 'Galaxy'}, username='alice')
        user2_item = astrodex.create_astrodex_item('user2', {'name': 'M51', 'type': 'Galaxy'}, username='bob')
        assert user1_item is not None
        assert user2_item is not None

        astrodex.add_picture_to_item('user1', user1_item['id'], {
            'filename': 'alice_pic.jpg',
            'location_id': 'loc-alice-home',
            'location_name': 'Alice Backyard',
            'latitude': 45.1, 'longitude': 5.2, 'elevation': 300,
        })
        astrodex.add_picture_to_item('user2', user2_item['id'], {
            'filename': 'bob_pic.jpg',
            'location_id': 'loc-bob-home',
            'location_name': 'Bob Backyard',
            'latitude': 48.8, 'longitude': 2.3, 'elevation': 35,
        })

        payload = astrodex.get_visible_astrodex(
            current_user_id='user1',
            current_username='alice',
            private_mode=False,
            usernames_by_id={'user1': 'alice', 'user2': 'bob'}
        )

        assert len(payload['items']) == 1
        merged = payload['items'][0]
        by_owner = {p['owner_username']: p for p in merged['pictures']}
        assert set(by_owner) == {'alice', 'bob'}

        # Alice viewing her own picture: full coordinates present.
        assert by_owner['alice']['latitude'] == 45.1
        assert by_owner['alice']['location_name'] == 'Alice Backyard'

        # Alice viewing Bob's picture: name stays, coordinates are gone.
        assert by_owner['bob']['location_name'] == 'Bob Backyard'
        assert 'latitude' not in by_owner['bob']
        assert 'longitude' not in by_owner['bob']
        assert 'elevation' not in by_owner['bob']

        # own_pictures (Alice's own list) is never stripped either way.
        assert merged['own_pictures'][0]['latitude'] == 45.1


class TestAstrodexMapPoints:
    """Test get_astrodex_map_points() - the Photo Map's dedicated, map_private-gated view."""

    def test_map_private_true_shows_only_own_points(self, temp_data_dir):
        user1_item = astrodex.create_astrodex_item('user1', {'name': 'M51', 'type': 'Galaxy'}, username='alice')
        user2_item = astrodex.create_astrodex_item('user2', {'name': 'M42', 'type': 'Nebula'}, username='bob')
        assert user1_item is not None
        assert user2_item is not None

        astrodex.add_picture_to_item('user1', user1_item['id'], {
            'filename': 'alice_pic.jpg', 'latitude': 45.1, 'longitude': 5.2,
        })
        astrodex.add_picture_to_item('user2', user2_item['id'], {
            'filename': 'bob_pic.jpg', 'latitude': 48.8, 'longitude': 2.3,
        })

        payload = astrodex.get_astrodex_map_points(
            current_user_id='user1',
            current_username='alice',
            map_private=True,
            usernames_by_id={'user1': 'alice', 'user2': 'bob'},
        )

        assert payload['map_private'] is True
        assert len(payload['points']) == 1
        assert payload['points'][0]['filename'] == 'alice_pic.jpg'
        assert payload['points'][0]['owner_username'] == 'alice'

    def test_map_private_false_shows_all_users_points_with_real_coordinates(self, temp_data_dir):
        """Unlike get_visible_astrodex(), the map never strips other users' coordinates."""
        user1_item = astrodex.create_astrodex_item('user1', {'name': 'M51', 'type': 'Galaxy'}, username='alice')
        user2_item = astrodex.create_astrodex_item('user2', {'name': 'M51', 'type': 'Galaxy'}, username='bob')
        assert user1_item is not None
        assert user2_item is not None

        astrodex.add_picture_to_item('user1', user1_item['id'], {
            'filename': 'alice_pic.jpg', 'location_name': 'Alice Backyard',
            'latitude': 45.1, 'longitude': 5.2,
        })
        astrodex.add_picture_to_item('user2', user2_item['id'], {
            'filename': 'bob_pic.jpg', 'location_name': 'Bob Backyard',
            'latitude': 48.8, 'longitude': 2.3,
        })

        payload = astrodex.get_astrodex_map_points(
            current_user_id='user1',
            current_username='alice',
            map_private=False,
            usernames_by_id={'user1': 'alice', 'user2': 'bob'},
        )

        assert payload['map_private'] is False
        assert len(payload['points']) == 2
        by_owner = {p['owner_username']: p for p in payload['points']}
        assert by_owner['alice']['latitude'] == 45.1
        # Bob's coordinates are NOT stripped for the map, unlike get_visible_astrodex().
        assert by_owner['bob']['latitude'] == 48.8
        assert by_owner['bob']['longitude'] == 2.3
        assert by_owner['bob']['is_owned_by_current_user'] is False

    def test_pictures_without_coordinates_are_excluded_and_counted(self, temp_data_dir):
        item = astrodex.create_astrodex_item('user1', {'name': 'M31', 'type': 'Galaxy'}, username='alice')
        assert item is not None

        astrodex.add_picture_to_item('user1', item['id'], {
            'filename': 'geotagged.jpg', 'latitude': 45.1, 'longitude': 5.2,
        })
        astrodex.add_picture_to_item('user1', item['id'], {'filename': 'no_location.jpg'})

        payload = astrodex.get_astrodex_map_points(
            current_user_id='user1', current_username='alice', map_private=True,
        )

        assert len(payload['points']) == 1
        assert payload['points'][0]['filename'] == 'geotagged.jpg'
        assert payload['total_geotagged'] == 1
        assert payload['total_without_location'] == 1

    def test_map_privacy_is_independent_from_general_astrodex_private_flag(self, temp_data_dir):
        """The map's own map_private flag governs it - the general 'private' flag must not matter."""
        user1_item = astrodex.create_astrodex_item('user1', {'name': 'M31', 'type': 'Galaxy'}, username='alice')
        user2_item = astrodex.create_astrodex_item('user2', {'name': 'M42', 'type': 'Nebula'}, username='bob')
        assert user1_item is not None
        assert user2_item is not None

        astrodex.add_picture_to_item('user1', user1_item['id'], {
            'filename': 'alice_pic.jpg', 'latitude': 45.1, 'longitude': 5.2,
        })
        astrodex.add_picture_to_item('user2', user2_item['id'], {
            'filename': 'bob_pic.jpg', 'latitude': 48.8, 'longitude': 2.3,
        })

        # General astrodex visibility set to private=True would hide Bob's item entirely
        # from get_visible_astrodex(); the map's map_private=False must still show him.
        general_view = astrodex.get_visible_astrodex(
            current_user_id='user1', current_username='alice', private_mode=True,
            usernames_by_id={'user1': 'alice', 'user2': 'bob'},
        )
        assert len(general_view['items']) == 1  # only alice's, general flag is private

        map_view = astrodex.get_astrodex_map_points(
            current_user_id='user1', current_username='alice', map_private=False,
            usernames_by_id={'user1': 'alice', 'user2': 'bob'},
        )
        owners = {p['owner_username'] for p in map_view['points']}
        assert owners == {'alice', 'bob'}


class TestAstrodexMissingBranches:
    """Tests targeting uncovered branches in astrodex.py helper functions."""

    def test_extract_name_candidates_empty_string(self):
        result = astrodex._extract_name_candidates('')
        assert result == []

    def test_get_alias_for_catalogue_no_catalogue(self):
        result = astrodex._get_alias_for_catalogue({'NGC': 'NGC 224'}, '')
        assert result == ''

    def test_get_alias_for_catalogue_direct_hit(self):
        result = astrodex._get_alias_for_catalogue({'Messier': 'M31'}, 'Messier')
        assert result == 'M31'

    def test_get_alias_for_catalogue_no_match(self):
        result = astrodex._get_alias_for_catalogue({'Messier': 'M31'}, 'NGC')
        assert result == ''

    def test_get_alias_metadata_non_dict_aliases(self, monkeypatch):
        monkeypatch.setattr(skytonight_targets, 'get_lookup_entry',
                            lambda cat, name: {'group_id': 'g1', 'aliases': 'not-a-dict'})
        group_id, aliases = astrodex._get_alias_metadata('Messier', 'M31')
        assert aliases == {}

    def test_sanitize_item_not_dict(self):
        astrodex._sanitize_item_for_persistence(None)

    def test_sanitize_astrodex_not_dict(self):
        astrodex._sanitize_astrodex_for_persistence(None)

    def test_sanitize_astrodex_items_not_list(self):
        astrodex._sanitize_astrodex_for_persistence({'items': 'not-a-list'})

    def test_attach_picture_owner_metadata_not_a_list(self):
        item = {'pictures': 'not-a-list'}
        astrodex._attach_picture_owner_metadata(item, 'u1', 'alice', 'u1')
        assert item['pictures'] == []

    def test_attach_picture_owner_metadata_non_dict_picture(self):
        item = {'pictures': ['bad-picture']}
        astrodex._attach_picture_owner_metadata(item, 'u1', 'alice', 'u1')

    def test_update_picture_success(self, temp_data_dir):
        item = astrodex.create_astrodex_item('user1', {'name': 'M42'}, username='alice')
        pic = astrodex.add_picture_to_item('user1', item['id'], {'date': '2025-01-01', 'device': 'Camera'})
        assert pic is not None
        updated = astrodex.update_picture('user1', item['id'], pic['id'], {'notes': 'Test notes', 'iso': 800})
        assert updated is not None
        assert updated['notes'] == 'Test notes'
        assert updated['iso'] == 800

    def test_update_picture_location_is_editable(self, temp_data_dir):
        """Unlike Astrodex items (location frozen at creation), a picture's
        location can be corrected/backfilled after the fact - it's often
        uploaded well after the session, or predates this field entirely."""
        item = astrodex.create_astrodex_item('user1', {'name': 'M42'}, username='alice')
        pic = astrodex.add_picture_to_item('user1', item['id'], {'filename': 'old.jpg'})
        assert pic['location_id'] is None  # old/untagged picture starts with no location

        updated = astrodex.update_picture('user1', item['id'], pic['id'], {
            'location_id': 'loc-1',
            'location_name': 'Backyard',
            'latitude': 45.1,
            'longitude': 5.2,
            'elevation': 300,
        })
        assert updated['location_id'] == 'loc-1'
        assert updated['location_name'] == 'Backyard'
        assert updated['latitude'] == 45.1
        assert updated['longitude'] == 5.2
        assert updated['elevation'] == 300

        # Clearing it back out (e.g. via the UI's "no location" option).
        cleared = astrodex.update_picture('user1', item['id'], pic['id'], {
            'location_id': None, 'location_name': None,
            'latitude': None, 'longitude': None, 'elevation': None,
        })
        assert cleared['location_id'] is None
        assert cleared['latitude'] is None

    def test_update_picture_item_not_found(self, temp_data_dir):
        result = astrodex.update_picture('user1', 'nonexistent-item', 'pic1', {'notes': 'x'})
        assert result is None

    def test_update_picture_pic_not_found(self, temp_data_dir):
        item = astrodex.create_astrodex_item('user1', {'name': 'M42'}, username='alice')
        result = astrodex.update_picture('user1', item['id'], 'nonexistent-pic', {'notes': 'x'})
        assert result is None

    def test_delete_picture_removes_file(self, temp_data_dir):
        astrodex.ensure_astrodex_directories()
        item = astrodex.create_astrodex_item('user1', {'name': 'M42'}, username='alice')
        fake_filename = 'fake_img.jpg'
        fake_path = os.path.join(astrodex.ASTRODEX_IMAGES_DIR, fake_filename)
        with open(fake_path, 'w') as f:
            f.write('fake image data')
        pic = astrodex.add_picture_to_item('user1', item['id'], {'filename': fake_filename})
        result = astrodex.delete_picture('user1', item['id'], pic['id'])
        assert result is True
        assert not os.path.exists(fake_path)

    def test_delete_main_picture_promotes_next(self, temp_data_dir):
        item = astrodex.create_astrodex_item('user1', {'name': 'M42'}, username='alice')
        pic1 = astrodex.add_picture_to_item('user1', item['id'], {'notes': 'first'})
        astrodex.add_picture_to_item('user1', item['id'], {'notes': 'second'})
        astrodex.set_main_picture('user1', item['id'], pic1['id'])
        astrodex.delete_picture('user1', item['id'], pic1['id'])
        reloaded = astrodex.get_astrodex_item('user1', item['id'])
        assert len(reloaded['pictures']) == 1
        assert reloaded['pictures'][0]['is_main'] is True

    def test_set_main_picture_picture_not_found(self, temp_data_dir):
        item = astrodex.create_astrodex_item('user1', {'name': 'M42'}, username='alice')
        result = astrodex.set_main_picture('user1', item['id'], 'nonexistent-pic')
        assert result is False

    def test_is_item_in_preloaded_astrodex_empty(self):
        result = astrodex.is_item_in_preloaded_astrodex({}, 'M42')
        assert result is False

    def test_is_item_in_preloaded_astrodex_none_data(self):
        result = astrodex.is_item_in_preloaded_astrodex(None, 'M42')
        assert result is False

    def test_is_item_in_preloaded_astrodex_found_by_name(self, temp_data_dir):
        astrodex.create_astrodex_item('user1', {'name': 'M42'}, username='alice')
        data = astrodex.load_user_astrodex('user1', 'alice')
        result = astrodex.is_item_in_preloaded_astrodex(data, 'M42')
        assert result is True

    def test_is_item_in_preloaded_astrodex_not_found(self, temp_data_dir):
        astrodex.create_astrodex_item('user1', {'name': 'M42'}, username='alice')
        data = astrodex.load_user_astrodex('user1', 'alice')
        result = astrodex.is_item_in_preloaded_astrodex(data, 'M99')
        assert result is False

    def test_load_user_astrodex_json_error(self, temp_data_dir):
        astrodex.ensure_astrodex_directories()
        file_path = astrodex.get_user_astrodex_file('testuser')
        with open(file_path, 'w') as f:
            f.write('{ invalid json !!!}')
        data = astrodex.load_user_astrodex('testuser', username='testuser')
        assert data['items'] == []
        assert data['username'] == 'testuser'

    def test_validate_astrodex_json_missing_username(self, temp_data_dir):
        import tempfile, json as _json
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            _json.dump({'items': []}, f)
            tmp_path = f.name
        is_valid, msg = astrodex.validate_astrodex_json(tmp_path)
        assert not is_valid
        assert 'username' in msg
        os.unlink(tmp_path)

    def test_validate_astrodex_json_missing_items(self, temp_data_dir):
        import tempfile, json as _json
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            _json.dump({'username': 'alice'}, f)
            tmp_path = f.name
        is_valid, msg = astrodex.validate_astrodex_json(tmp_path)
        assert not is_valid
        assert 'items' in msg
        os.unlink(tmp_path)

    def test_validate_astrodex_json_not_dict(self, temp_data_dir):
        import tempfile, json as _json
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            _json.dump([1, 2, 3], f)
            tmp_path = f.name
        is_valid, msg = astrodex.validate_astrodex_json(tmp_path)
        assert not is_valid
        assert 'dictionary' in msg
        os.unlink(tmp_path)

    def test_validate_astrodex_json_item_missing_id(self, temp_data_dir):
        import tempfile, json as _json
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            _json.dump({'username': 'alice', 'items': [{'name': 'M42'}]}, f)
            tmp_path = f.name
        is_valid, msg = astrodex.validate_astrodex_json(tmp_path)
        assert not is_valid
        assert 'id' in msg
        os.unlink(tmp_path)

    def test_validate_astrodex_json_item_missing_name(self, temp_data_dir):
        import tempfile, json as _json
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            _json.dump({'username': 'alice', 'items': [{'id': 'abc'}]}, f)
            tmp_path = f.name
        is_valid, msg = astrodex.validate_astrodex_json(tmp_path)
        assert not is_valid
        assert 'name' in msg
        os.unlink(tmp_path)

    def test_validate_astrodex_json_invalid_json(self, temp_data_dir):
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('{bad json')
            tmp_path = f.name
        is_valid, msg = astrodex.validate_astrodex_json(tmp_path)
        assert not is_valid
        assert 'JSON' in msg
        os.unlink(tmp_path)

    def test_can_user_view_image_empty_filename(self, temp_data_dir):
        result = astrodex.can_user_view_image('user1', '', private_mode=True)
        assert result is False

    def test_get_item_merge_key_via_alias_names(self, temp_data_dir, monkeypatch):
        monkeypatch.setattr(skytonight_targets, 'get_lookup_entry',
                            lambda cat, name: {'group_id': '', 'aliases': {'NGC': 'NGC 1234'}})
        item = {'id': 'i1', 'name': 'NGC 1234', 'catalogue': 'NGC'}
        key = astrodex._get_item_merge_key(item)
        assert 'alias:' in key or 'name:' in key or 'id:' in key

    def test_get_item_merge_key_fallback_to_id(self, monkeypatch):
        """Item with empty name and no aliases → falls back to id: prefix."""
        monkeypatch.setattr(skytonight_targets, 'get_lookup_entry', lambda cat, name: {})
        item = {'id': 'xyz-123', 'name': '', 'catalogue': ''}
        key = astrodex._get_item_merge_key(item)
        assert key == 'id:xyz-123'

    def test_load_user_astrodex_username_mismatch_triggers_save(self, temp_data_dir, monkeypatch):
        """Loading with a different username than stored updates the record."""
        # Create with original username
        astrodex.create_astrodex_item('testuser', {'name': 'M99'}, username='oldname')
        # Load with a different username - should update username in file
        data = astrodex.load_user_astrodex('testuser', username='newname')
        assert data['username'] == 'newname'

    def test_load_user_astrodex_generic_exception_returns_empty(self, temp_data_dir, monkeypatch):
        """Generic exception in load_user_astrodex → returns empty skeleton."""
        astrodex.ensure_astrodex_directories()
        # Write a valid file first
        file_path = astrodex.get_user_astrodex_file('testuser')
        with open(file_path, 'w') as f:
            json.dump({'username': 'testuser', 'items': []}, f)
        # Patch open to raise a non-JSON exception
        original_open = open
        def bad_open(path, *args, **kwargs):
            if path == file_path:
                raise PermissionError("access denied")
            return original_open(path, *args, **kwargs)
        monkeypatch.setattr('builtins.open', bad_open)
        data = astrodex.load_user_astrodex('testuser', username='testuser')
        assert data['items'] == []

    def test_load_user_astrodex_corrupted_backup_failure(self, temp_data_dir, monkeypatch):
        """Backup copy fails when recovering from corrupted JSON."""
        import shutil
        astrodex.ensure_astrodex_directories()
        file_path = astrodex.get_user_astrodex_file('testuser')
        with open(file_path, 'w') as f:
            f.write('{ corrupted json !!!')
        def fail_copy2(*args, **kwargs):
            raise OSError("disk full")
        monkeypatch.setattr(shutil, 'copy2', fail_copy2)
        data = astrodex.load_user_astrodex('testuser', username='testuser')
        assert data['items'] == []

    def test_validate_astrodex_json_general_exception(self, temp_data_dir):
        """Non-JSON exception in validate_astrodex_json → Validation error."""
        is_valid, msg = astrodex.validate_astrodex_json('/nonexistent/path/file.json')
        assert not is_valid
        assert 'Validation error' in msg or 'Invalid JSON' in msg or len(msg) > 0

    def test_save_backup_creation_failure_continues(self, temp_data_dir, monkeypatch):
        """Backup creation raises but save still proceeds."""
        import shutil
        # Create an existing file first so backup would be attempted
        astrodex.create_astrodex_item('testuser', {'name': 'M31'})
        original_copy2 = shutil.copy2
        call_count = [0]
        def fail_first_copy2(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise OSError("disk full")
            return original_copy2(*args, **kwargs)
        monkeypatch.setattr(shutil, 'copy2', fail_first_copy2)
        # Save should still succeed despite backup failure
        data = astrodex.load_user_astrodex('testuser')
        result = astrodex.save_user_astrodex('testuser', data)
        assert result is True

    def test_save_backup_cleanup_failure_on_success(self, temp_data_dir, monkeypatch):
        """Backup cleanup raises after successful save."""
        # Create item so file exists
        astrodex.create_astrodex_item('testuser', {'name': 'M31'})
        original_remove = os.remove
        def fail_remove(path):
            if path.endswith('.backup'):
                raise OSError("cannot remove")
            return original_remove(path)
        monkeypatch.setattr(os, 'remove', fail_remove)
        data = astrodex.load_user_astrodex('testuser')
        result = astrodex.save_user_astrodex('testuser', data)
        # Save succeeds even if backup cleanup fails
        assert result is True

    def test_save_backup_restore_failure_on_error(self, temp_data_dir, monkeypatch):
        """Backup restore raises when save fails."""
        import shutil
        astrodex.create_astrodex_item('testuser', {'name': 'M31'})
        call_count = [0]
        original_copy2 = shutil.copy2
        def selective_copy2(src, dst):
            call_count[0] += 1
            if call_count[0] > 1:  # 2nd call = restore attempt
                raise OSError("cannot restore")
            return original_copy2(src, dst)
        monkeypatch.setattr(shutil, 'copy2', selective_copy2)
        # Also make json.dump fail to trigger the error path
        import json as _json
        def fail_dump(*args, **kwargs):
            raise ValueError("write fail")
        monkeypatch.setattr(_json, 'dump', fail_dump)
        data = astrodex.load_user_astrodex('testuser')
        result = astrodex.save_user_astrodex('testuser', data)
        assert result is False

    def test_create_astrodex_item_empty_name_returns_none(self, temp_data_dir):
        """create_astrodex_item with empty name returns None."""
        result = astrodex.create_astrodex_item('testuser', {'name': '', 'type': 'Galaxy'})
        assert result is None

    def test_create_astrodex_item_save_failure_returns_none(self, temp_data_dir, monkeypatch):
        """create_astrodex_item returns None when save fails."""
        monkeypatch.setattr(astrodex, 'save_user_astrodex', lambda *a, **kw: False)
        result = astrodex.create_astrodex_item('testuser', {'name': 'M999', 'type': 'Galaxy'})
        assert result is None

    def test_delete_astrodex_item_with_existing_image(self, temp_data_dir):
        """Deletes the physical image file associated with a deleted item."""
        astrodex.ensure_astrodex_directories()
        item = astrodex.create_astrodex_item('testuser', {'name': 'M42'}, username='alice')
        fake_filename = 'image_to_delete.jpg'
        fake_path = os.path.join(astrodex.ASTRODEX_IMAGES_DIR, fake_filename)
        with open(fake_path, 'w') as f:
            f.write('fake data')
        data = astrodex.load_user_astrodex('testuser')
        data['items'][0]['pictures'] = [{'filename': fake_filename, 'id': 'p1', 'is_main': True}]
        astrodex.save_user_astrodex('testuser', data)
        result = astrodex.delete_astrodex_item('testuser', item['id'])
        assert result is True
        assert not os.path.exists(fake_path)

    def test_delete_astrodex_item_image_oserror_continues(self, temp_data_dir, monkeypatch):
        """OSError when deleting image file is swallowed."""
        astrodex.ensure_astrodex_directories()
        item = astrodex.create_astrodex_item('testuser', {'name': 'M42'}, username='alice')
        data = astrodex.load_user_astrodex('testuser')
        data['items'][0]['pictures'] = [{'filename': 'ghost.jpg', 'id': 'p1', 'is_main': True}]
        astrodex.save_user_astrodex('testuser', data)
        original_exists = os.path.exists
        def fake_exists(path):
            if 'ghost.jpg' in path:
                return True
            return original_exists(path)
        def fail_remove(path):
            raise OSError("cannot delete")
        monkeypatch.setattr(os.path, 'exists', fake_exists)
        monkeypatch.setattr(os, 'remove', fail_remove)
        # Should still succeed even if image deletion fails
        result = astrodex.delete_astrodex_item('testuser', item['id'])
        assert result is True

    def test_add_picture_save_failure_returns_none(self, temp_data_dir, monkeypatch):
        """add_picture_to_item returns None when save fails."""
        item = astrodex.create_astrodex_item('testuser', {'name': 'M42'})
        # Patch save to always fail — add_picture calls it exactly once
        monkeypatch.setattr(astrodex, 'save_user_astrodex', lambda *a, **kw: False)
        result = astrodex.add_picture_to_item('testuser', item['id'], {'filename': 'test.jpg'})
        assert result is None

    def test_update_picture_save_failure_returns_none(self, temp_data_dir, monkeypatch):
        """update_picture returns None when save fails."""
        item = astrodex.create_astrodex_item('testuser', {'name': 'M42'})
        pic = astrodex.add_picture_to_item('testuser', item['id'], {'filename': 'test.jpg'})
        assert pic is not None
        # Patch save to always fail — update_picture calls it exactly once
        monkeypatch.setattr(astrodex, 'save_user_astrodex', lambda *a, **kw: False)
        result = astrodex.update_picture('testuser', item['id'], pic['id'], {'notes': 'x'})
        assert result is None

    def test_delete_picture_oserror_is_swallowed(self, temp_data_dir, monkeypatch):
        """OSError when deleting physical file is swallowed."""
        astrodex.ensure_astrodex_directories()
        item = astrodex.create_astrodex_item('testuser', {'name': 'M42'})
        # Create a real file to delete
        fake_file = os.path.join(astrodex.ASTRODEX_IMAGES_DIR, 'oserr.jpg')
        with open(fake_file, 'w') as f:
            f.write('data')
        pic = astrodex.add_picture_to_item('testuser', item['id'], {'filename': 'oserr.jpg'})
        original_remove = os.remove
        def fail_remove(path):
            if 'oserr.jpg' in path:
                raise OSError("permission denied")
            return original_remove(path)
        monkeypatch.setattr(os, 'remove', fail_remove)
        result = astrodex.delete_picture('testuser', item['id'], pic['id'])
        # Metadata removed even if physical file deletion fails
        assert result is True

    def test_get_main_picture_fallback_to_first_when_no_main_flag(self):
        """get_main_picture returns first picture when no is_main=True."""
        item = {
            'pictures': [
                {'id': 'p1', 'filename': 'first.jpg', 'is_main': False},
                {'id': 'p2', 'filename': 'second.jpg', 'is_main': False},
            ]
        }
        result = astrodex.get_main_picture(item)
        assert result is not None
        assert result['filename'] == 'first.jpg'

    def test_is_item_in_astrodex_alias_intersection_match(self, temp_data_dir, monkeypatch):
        """Alias intersection match in is_item_in_astrodex_with_catalogue."""
        def fake_alias_entry(catalogue, name):
            if name in ('M31', 'Andromeda', 'NGC 224'):
                return {'group_id': 'G001', 'aliases': {'Messier': 'M31', 'NGC': 'NGC 224'}}
            return {}
        monkeypatch.setattr(skytonight_targets, 'get_lookup_entry', fake_alias_entry)
        astrodex.create_astrodex_item('testuser', {'name': 'M31', 'catalogue': 'Messier'})
        # Check by NGC alias name - should match via alias intersection
        result = astrodex.is_item_in_astrodex('testuser', 'NGC 224', 'NGC')
        assert result is True

    def test_is_item_in_preloaded_group_id_match(self, temp_data_dir, monkeypatch):
        """Group ID match in is_item_in_preloaded_astrodex."""
        def fake_alias_entry(catalogue, name):
            return {'group_id': 'G001', 'aliases': {'Messier': 'M31', 'NGC': 'NGC 224'}}
        monkeypatch.setattr(skytonight_targets, 'get_lookup_entry', fake_alias_entry)
        astrodex.create_astrodex_item('testuser', {'name': 'M31', 'catalogue': 'Messier'})
        data = astrodex.load_user_astrodex('testuser')
        # Force group_id into the stored item
        data['items'][0]['catalogue_group_id'] = 'G001'
        result = astrodex.is_item_in_preloaded_astrodex(data, 'NGC 224', 'NGC')
        assert result is True

    def test_is_item_in_preloaded_alias_intersection_match(self, temp_data_dir, monkeypatch):
        """Alias intersection match in is_item_in_preloaded_astrodex."""
        def fake_alias_entry(catalogue, name):
            return {'group_id': '', 'aliases': {'Messier': 'M31', 'NGC': 'NGC 224'}}
        monkeypatch.setattr(skytonight_targets, 'get_lookup_entry', fake_alias_entry)
        data = {
            'items': [
                {
                    'id': 'i1',
                    'name': 'NGC 224',
                    'catalogue': 'NGC',
                    'catalogue_group_id': '',
                    'catalogue_aliases': {'Messier': 'M31', 'NGC': 'NGC 224'},
                }
            ]
        }
        result = astrodex.is_item_in_preloaded_astrodex(data, 'M31', 'Messier')
        assert result is True

    def test_switch_item_catalogue_name_no_aliases_raises(self, temp_data_dir, monkeypatch):
        """switch_item_catalogue_name raises when item has no aliases."""
        monkeypatch.setattr(skytonight_targets, 'get_lookup_entry', lambda c, n: {})
        monkeypatch.setattr(catalogue_aliases, 'get_alias_entry', lambda c, n: {})
        item = astrodex.create_astrodex_item('testuser', {'name': 'M42', 'catalogue': ''})
        with pytest.raises(ValueError, match='No catalogue aliases'):
            astrodex.switch_item_catalogue_name('testuser', item['id'], 'OpenNGC')

    def test_switch_item_catalogue_name_wrong_catalogue_raises(self, temp_data_dir, monkeypatch):
        """switch_item_catalogue_name raises when requested catalogue not in aliases."""
        def fake_alias_entry(catalogue, name):
            if name == 'M31':
                return {'group_id': 'G1', 'aliases': {'Messier': 'M31', 'OpenNGC': 'NGC 224'}}
            return {}
        monkeypatch.setattr(skytonight_targets, 'get_lookup_entry', fake_alias_entry)
        monkeypatch.setattr(catalogue_aliases, 'get_alias_entry', fake_alias_entry)
        item = astrodex.create_astrodex_item('testuser', {'name': 'M31', 'catalogue': 'Messier'})
        # Enrich so aliases are in item
        data = astrodex.load_user_astrodex('testuser')
        data['items'][0]['catalogue_aliases'] = {'Messier': 'M31', 'OpenNGC': 'NGC 224'}
        astrodex.save_user_astrodex('testuser', data)
        with pytest.raises(ValueError, match='not available'):
            astrodex.switch_item_catalogue_name('testuser', item['id'], 'SIMBAD')

    def test_switch_item_catalogue_name_no_target_aliases_pops_field(self, temp_data_dir, monkeypatch):
        """When _get_alias_metadata returns empty, fallback aliases from item are used."""
        def fake_lookup_entry(catalogue, name):
            # Only return aliases for the original name 'M31', not for the switched name 'Alt31'
            if name == 'M31':
                return {'group_id': '', 'aliases': {'Messier': 'M31', 'AltCat': 'Alt31'}}
            return {}
        def fake_alias_entry(catalogue, name):
            # Return proper entry so enrich_item_with_catalogue_aliases keeps the field
            if name == 'M31':
                return {'group_id': '', 'aliases': {'Messier': 'M31', 'AltCat': 'Alt31'}}
            return {}
        monkeypatch.setattr(skytonight_targets, 'get_lookup_entry', fake_lookup_entry)
        monkeypatch.setattr(catalogue_aliases, 'get_alias_entry', fake_alias_entry)
        item = astrodex.create_astrodex_item('testuser', {'name': 'M31', 'catalogue': 'Messier'})
        data = astrodex.load_user_astrodex('testuser')
        data['items'][0]['catalogue_aliases'] = {'Messier': 'M31', 'AltCat': 'Alt31'}
        astrodex.save_user_astrodex('testuser', data)
        # 'Alt31' has no lookup entry → _get_alias_metadata returns {} →  executes
        result = astrodex.switch_item_catalogue_name('testuser', item['id'], 'AltCat')
        assert result is not None  # switch succeeded, covering the fallback alias path

    def test_switch_item_catalogue_name_save_failure_returns_none(self, temp_data_dir, monkeypatch):
        """switch_item_catalogue_name returns None when save fails."""
        def fake_alias_entry(catalogue, name):
            return {'group_id': 'G1', 'aliases': {'Messier': 'M31', 'NGC': 'NGC 224'}}
        monkeypatch.setattr(skytonight_targets, 'get_lookup_entry', fake_alias_entry)
        monkeypatch.setattr(catalogue_aliases, 'get_alias_entry', fake_alias_entry)
        item = astrodex.create_astrodex_item('testuser', {'name': 'M31', 'catalogue': 'Messier'})
        data = astrodex.load_user_astrodex('testuser')
        data['items'][0]['catalogue_aliases'] = {'Messier': 'M31', 'NGC': 'NGC 224'}
        astrodex.save_user_astrodex('testuser', data)
        monkeypatch.setattr(astrodex, 'save_user_astrodex', lambda *a, **kw: False)
        result = astrodex.switch_item_catalogue_name('testuser', item['id'], 'NGC')
        assert result is None

    def test_switch_item_duplicate_name_check_raises(self, temp_data_dir, monkeypatch):
        """switch raises when another item has the same target name."""
        def fake_alias_entry(catalogue, name):
            return {'group_id': '', 'aliases': {'Messier': 'M31', 'NGC': 'NGC 224'}}
        monkeypatch.setattr(skytonight_targets, 'get_lookup_entry', fake_alias_entry)
        monkeypatch.setattr(catalogue_aliases, 'get_alias_entry', fake_alias_entry)
        # First item
        item1 = astrodex.create_astrodex_item('testuser', {'name': 'M31', 'catalogue': 'Messier'})
        # Add a second item with the target name we'll try to switch to
        data = astrodex.load_user_astrodex('testuser')
        import uuid
        data['items'].append({
            'id': str(uuid.uuid4()),
            'name': 'NGC 224',
            'catalogue': 'NGC',
            'pictures': [],
            'created_at': '2026-01-01T00:00:00+00:00',
            'updated_at': '2026-01-01T00:00:00+00:00',
        })
        astrodex.save_user_astrodex('testuser', data)
        data = astrodex.load_user_astrodex('testuser')
        data['items'][0]['catalogue_aliases'] = {'Messier': 'M31', 'NGC': 'NGC 224'}
        astrodex.save_user_astrodex('testuser', data)
        with pytest.raises(ValueError):
            astrodex.switch_item_catalogue_name('testuser', item1['id'], 'NGC')


class TestAstrodexyRemainingBranches:
    """Cover remaining uncovered branches in astrodex.py."""

    def test_get_item_merge_key_plain_name(self, monkeypatch):
        """item with name but no catalogue aliases → 'name:...' key."""
        monkeypatch.setattr(skytonight_targets, 'get_lookup_entry', lambda *_: {})
        item = {'id': 'xyz', 'name': 'Custom Object', 'catalogue': ''}
        key = astrodex._get_item_merge_key(item)
        assert key.startswith('name:')

    def test_save_failure_cleanup_no_backup_no_temp(self, temp_data_dir, monkeypatch):
        """save fails before temp file created (no backup)."""
        def bad_sanitize(data):
            raise ValueError("sanitize failed")
        monkeypatch.setattr(astrodex, '_sanitize_astrodex_for_persistence', bad_sanitize)
        data = {'user_id': 'newuser', 'username': 'alice', 'items': []}
        result = astrodex.save_user_astrodex('newuser', data)
        assert result is False

    def test_delete_item_picture_file_not_on_disk(self, temp_data_dir):
        """item has picture filename but image file doesn't exist."""
        astrodex.ensure_astrodex_directories()
        item = astrodex.create_astrodex_item('user1', {'name': 'M42'}, username='alice')
        raw = astrodex.load_user_astrodex('user1')
        raw['items'][0]['pictures'] = [{'id': 'p1', 'filename': 'ghost.jpg', 'is_main': True}]
        astrodex.save_user_astrodex('user1', raw)
        result = astrodex.delete_astrodex_item('user1', item['id'])
        assert result is True

    def test_delete_second_nonmain_picture(self, temp_data_dir):
        """delete non-main picture (first pic doesn't match)."""
        astrodex.ensure_astrodex_directories()
        item = astrodex.create_astrodex_item('user1', {'name': 'M42'}, username='alice')
        pic1 = astrodex.add_picture_to_item('user1', item['id'], {'notes': 'first'})
        pic2 = astrodex.add_picture_to_item('user1', item['id'], {'notes': 'second'})
        result = astrodex.delete_picture('user1', item['id'], pic2['id'])
        assert result is True
        updated = astrodex.get_astrodex_item('user1', item['id'])
        assert len(updated['pictures']) == 1
        assert updated['pictures'][0]['id'] == pic1['id']

    def test_delete_picture_not_found_in_item(self, temp_data_dir):
        """delete_picture with non-existent picture_id."""
        astrodex.ensure_astrodex_directories()
        item = astrodex.create_astrodex_item('user1', {'name': 'M42'}, username='alice')
        astrodex.add_picture_to_item('user1', item['id'], {'notes': 'only'})
        result = astrodex.delete_picture('user1', item['id'], 'no-such-pic-id')
        assert result is False

    def test_is_item_in_astrodex_alias_name_match(self, temp_data_dir, monkeypatch):
        """requested_alias_names set → existing item matched by alias name."""
        def fake_lookup(catalogue, name):
            return {'group_id': '', 'aliases': {'Messier': 'M31', 'NGC': 'NGC 224'}}
        monkeypatch.setattr(skytonight_targets, 'get_lookup_entry', fake_lookup)
        astrodex.create_astrodex_item('testuser', {'name': 'NGC 224', 'catalogue': 'NGC'})
        result = astrodex.is_item_in_astrodex_with_catalogue('testuser', 'M31', 'Messier')
        assert result is True

    def test_is_item_in_astrodex_catalogue_alias_false_branch(self, temp_data_dir, monkeypatch):
        """catalogue alias doesn't match → False branch, loop continues."""
        def fake_lookup(catalogue, name):
            if catalogue == 'CatB' and name == 'BName':
                return {'group_id': '', 'aliases': {'CatA': 'OtherName', 'CatB': 'BName'}}
            return {}
        monkeypatch.setattr(skytonight_targets, 'get_lookup_entry', fake_lookup)
        astrodex.create_astrodex_item('testuser', {'name': 'BName', 'catalogue': 'CatB'})
        result = astrodex.is_item_in_astrodex_with_catalogue('testuser', 'SomeItem', 'CatA')
        assert result is False

    def test_preloaded_existing_name_in_alias_names(self, monkeypatch):
        """item name is in requested alias names (no alias intersection)."""
        def fake_lookup(catalogue, name):
            if catalogue == 'Messier' and name == 'M31':
                return {'group_id': '', 'aliases': {'Messier': 'M31', 'PopName': 'Andromeda'}}
            return {}
        monkeypatch.setattr(skytonight_targets, 'get_lookup_entry', fake_lookup)
        data = {'items': [{'id': 'i1', 'name': 'Andromeda', 'catalogue': ''}]}
        result = astrodex.is_item_in_preloaded_astrodex(data, 'M31', 'Messier')
        assert result is True

    def test_preloaded_catalogue_alias_match(self, monkeypatch):
        """catalogue alias in existing item matches requested normalized names."""
        def fake_lookup(catalogue, name):
            if catalogue == 'Messier' and name == 'M42':
                return {'group_id': '', 'aliases': {'Messier': 'M42', 'NGC': 'NGC 1976'}}
            return {}
        monkeypatch.setattr(skytonight_targets, 'get_lookup_entry', fake_lookup)
        data = {'items': [{'id': 'i1', 'name': 'M42', 'catalogue': 'Messier'}]}
        result = astrodex.is_item_in_preloaded_astrodex(data, 'NGC 1976', 'NGC')
        assert result is True

    def test_update_picture_second_picture_match(self, temp_data_dir):
        """for loop iterates past first non-matching picture to find the second."""
        item = astrodex.create_astrodex_item('testuser', {'name': 'M31'})
        pic1 = astrodex.add_picture_to_item('testuser', item['id'], {'filename': 'a.jpg'})
        pic2 = astrodex.add_picture_to_item('testuser', item['id'], {'filename': 'b.jpg'})
        assert pic1 is not None and pic2 is not None
        result = astrodex.update_picture('testuser', item['id'], pic2['id'], {'notes': 'second'})
        assert result is not None
        assert result['notes'] == 'second'

    def test_is_item_in_astrodex_name_in_alias_names(self, temp_data_dir, monkeypatch):
        """item name is in requested_alias_names (no alias intersection)."""
        def fake_lookup(catalogue, name):
            if catalogue == 'Messier' and name == 'M31':
                return {'group_id': '', 'aliases': {'Messier': 'M31', 'PopName': 'M31pop'}}
            return {}
        monkeypatch.setattr(skytonight_targets, 'get_lookup_entry', fake_lookup)
        astrodex.create_astrodex_item('testuser', {'name': 'M31pop', 'catalogue': ''})
        result = astrodex.is_item_in_astrodex_with_catalogue('testuser', 'M31', 'Messier')
        assert result is True

    def test_preloaded_both_false_branches(self, monkeypatch):
        """No match in either the group_id or the alias-intersection check."""
        def fake_lookup(catalogue, name):
            if catalogue == 'Messier' and name == 'M31':
                return {'group_id': '', 'aliases': {'Messier': 'M31', 'PopName': 'Andromeda'}}
            if catalogue == 'SomeCat' and name == 'SomeObject':
                return {'group_id': '', 'aliases': {'SomeCat': 'SomeObject', 'OtherCat': 'OtherName'}}
            return {}
        monkeypatch.setattr(skytonight_targets, 'get_lookup_entry', fake_lookup)
        data = {'items': [{'id': 'i1', 'name': 'SomeObject', 'catalogue': 'SomeCat'}]}
        result = astrodex.is_item_in_preloaded_astrodex(data, 'M31', 'Messier')
        assert result is False

    def test_switch_item_name_check_false_branch(self, temp_data_dir, monkeypatch):
        """existing item name != target_name → loop continues."""
        def fake_lookup(catalogue, name):
            if catalogue == 'NGC' and name == 'NGC 224':
                return {'group_id': '', 'aliases': {'Messier': 'M31', 'NGC': 'NGC 224'}}
            return {}
        monkeypatch.setattr(skytonight_targets, 'get_lookup_entry', fake_lookup)
        astrodex.create_astrodex_item('testuser', {'name': 'Other Object', 'catalogue': ''})
        item2 = astrodex.create_astrodex_item('testuser', {'name': 'NGC 224', 'catalogue': 'NGC'})
        assert item2 is not None
        monkeypatch.setattr(astrodex, 'enrich_item_with_catalogue_aliases', lambda i: i.update({'catalogue_aliases': {'Messier': 'M31', 'NGC': 'NGC 224'}}) or i)
        result = astrodex.switch_item_catalogue_name('testuser', item2['id'], 'Messier')
        assert result is not None

    # -----------------------------------------------------------------------
    # find_item_in_astrodex
    # -----------------------------------------------------------------------

    def test_find_item_returns_item_by_exact_name(self, temp_data_dir):
        item = astrodex.create_astrodex_item('testuser', {'name': 'M42', 'catalogue': ''})
        result = astrodex.find_item_in_astrodex('testuser', 'M42')
        assert result is not None
        assert result['id'] == item['id']
        assert result['name'] == 'M42'

    def test_find_item_returns_none_when_not_found(self, temp_data_dir):
        astrodex.create_astrodex_item('testuser', {'name': 'M42', 'catalogue': ''})
        result = astrodex.find_item_in_astrodex('testuser', 'M31')
        assert result is None

    def test_find_item_returns_none_on_empty_astrodex(self, temp_data_dir):
        result = astrodex.find_item_in_astrodex('testuser', 'M42')
        assert result is None

    def test_find_item_matches_via_catalogue_alias(self, temp_data_dir, monkeypatch):
        def fake_lookup(catalogue, name):
            if name in ('M31', 'NGC 224') or catalogue in ('Messier', 'OpenNGC'):
                return {'group_id': 'GRP001', 'aliases': {'Messier': 'M31', 'OpenNGC': 'NGC 224'}}
            return {}
        monkeypatch.setattr(skytonight_targets, 'get_lookup_entry', fake_lookup)
        item = astrodex.create_astrodex_item('testuser', {'name': 'M31', 'catalogue': 'Messier'})
        result = astrodex.find_item_in_astrodex('testuser', 'NGC 224', 'OpenNGC')
        assert result is not None
        assert result['id'] == item['id']

    def test_find_item_matches_via_alias_intersection(self, temp_data_dir, monkeypatch):
        """existing alias names intersect with requested alias names."""
        def fake_lookup(catalogue, name):
            if (catalogue == 'Messier' and name == 'M31') or (catalogue == 'PopName' and name == 'M31pop'):
                return {'group_id': '', 'aliases': {'Messier': 'M31', 'PopName': 'M31pop'}}
            return {}
        monkeypatch.setattr(skytonight_targets, 'get_lookup_entry', fake_lookup)
        item = astrodex.create_astrodex_item('testuser', {'name': 'M31', 'catalogue': 'Messier'})
        # Searching 'M31pop'/'PopName' builds requested_alias_names={'m31','m31pop'};
        # the stored item's aliases also contain those names → intersection fires .
        result = astrodex.find_item_in_astrodex('testuser', 'M31pop', 'PopName')
        assert result is not None
        assert result['id'] == item['id']

    def test_find_item_matches_via_name_in_alias_names(self, temp_data_dir, monkeypatch):
        """existing item name is itself inside the requested alias set."""
        def fake_lookup(catalogue, name):
            if catalogue == 'Messier' and name == 'M31':
                return {'group_id': '', 'aliases': {'Messier': 'M31', 'PopName': 'M31pop'}}
            return {}
        monkeypatch.setattr(skytonight_targets, 'get_lookup_entry', fake_lookup)
        # Item stored with bare name 'M31pop' (no catalogue → no aliases of its own)
        item = astrodex.create_astrodex_item('testuser', {'name': 'M31pop', 'catalogue': ''})
        # Searching 'M31'/'Messier' builds requested_alias_names={'m31','m31pop'};
        # the item name 'm31pop' is in that set → fires .
        result = astrodex.find_item_in_astrodex('testuser', 'M31', 'Messier')
        assert result is not None
        assert result['id'] == item['id']

    def test_find_item_matches_via_catalogue_specific_alias(self, temp_data_dir, monkeypatch):
        """Match via per-catalogue alias when the search term has no lookup aliases of its own."""
        def fake_lookup(catalogue, name):
            if catalogue == 'Messier' and name == 'M31':
                return {'group_id': '', 'aliases': {'Messier': 'M31', 'OpenNGC': 'NGC 224'}}
            return {}
        monkeypatch.setattr(skytonight_targets, 'get_lookup_entry', fake_lookup)
        item = astrodex.create_astrodex_item('testuser', {'name': 'M31', 'catalogue': 'Messier'})
        result = astrodex.find_item_in_astrodex('testuser', 'NGC 224', 'OpenNGC')
        assert result is not None
        assert result['id'] == item['id']

    def test_find_item_no_match_when_item_name_not_in_alias_set(self, temp_data_dir, monkeypatch):
        """Item with no catalogue aliases whose name isn't in search aliases doesn't match early; loop continues to the next item."""
        def fake_lookup(catalogue, name):
            if catalogue == 'Messier' and name == 'M31':
                return {'group_id': '', 'aliases': {'Messier': 'M31', 'PopName': 'Andromeda'}}
            return {}
        monkeypatch.setattr(skytonight_targets, 'get_lookup_entry', fake_lookup)
        astrodex.create_astrodex_item('testuser', {'name': 'Unrelated', 'catalogue': ''})
        item = astrodex.create_astrodex_item('testuser', {'name': 'M31', 'catalogue': 'Messier'})
        result = astrodex.find_item_in_astrodex('testuser', 'M31', 'Messier')
        assert result is not None
        assert result['id'] == item['id']

    def test_find_item_skips_item_whose_catalogue_alias_does_not_match(self, temp_data_dir, monkeypatch):
        """Item whose per-catalogue alias doesn't match the search name is skipped; loop continues to the matching item."""
        def fake_lookup(catalogue, name):
            if catalogue == 'Messier' and name == 'M51':
                return {'group_id': '', 'aliases': {'Messier': 'M51', 'OpenNGC': 'NGC 5194'}}
            if catalogue == 'Messier' and name == 'M31':
                return {'group_id': '', 'aliases': {'Messier': 'M31', 'OpenNGC': 'NGC 224'}}
            return {}
        monkeypatch.setattr(skytonight_targets, 'get_lookup_entry', fake_lookup)
        astrodex.create_astrodex_item('testuser', {'name': 'M51', 'catalogue': 'Messier'})
        item = astrodex.create_astrodex_item('testuser', {'name': 'M31', 'catalogue': 'Messier'})
        result = astrodex.find_item_in_astrodex('testuser', 'NGC 224', 'OpenNGC')
        assert result is not None
        assert result['id'] == item['id']
