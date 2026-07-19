"""
Unit tests for backend utilities (utils.py)
"""
import pytest
import os
import json
import yaml


# Import the functions to test
from utils import (
    IndentDumper,
    _NumpySafeEncoder,
    _sanitize_for_json,
    ensure_directory_exists,
    slugify_location_name,
    safe_file_exists,
    load_json_file,
    save_json_file,
    dms_to_decimal,
    decimal_to_dms,
    validate_coordinates,
    format_file_size,
    get_environment_info
)


class TestDirectoryUtils:
    """Test directory-related utility functions"""
    
    def test_ensure_directory_exists_new_dir(self, temp_dir):
        """Test creating a new directory"""
        new_dir = os.path.join(temp_dir, "test_subdir", "nested")
        ensure_directory_exists(new_dir)
        assert os.path.exists(new_dir)
        assert os.path.isdir(new_dir)
    
    def test_ensure_directory_exists_existing_dir(self, temp_dir):
        """Test with existing directory - should not raise error"""
        ensure_directory_exists(temp_dir)
        assert os.path.exists(temp_dir)
    
    def test_safe_file_exists_true(self, temp_file):
        """Test with existing file"""
        assert safe_file_exists(temp_file) is True
    
    def test_safe_file_exists_false(self):
        """Test with non-existent file"""
        assert safe_file_exists("/tmp/nonexistent_file_12345.txt") is False
    
    def test_safe_file_exists_directory(self, temp_dir):
        """Test with directory instead of file - should return False"""
        assert safe_file_exists(temp_dir) is False
    
    def test_safe_file_exists_invalid_input(self):
        """Test with invalid input - should return False"""
        assert safe_file_exists(None) is False

    def test_slugify_location_name_ascii_and_accents(self):
        """Test location slug generation with accents and spaces"""
        assert slugify_location_name('Bovée sur Barboure') == 'bovee-sur-barboure'

    def test_slugify_location_name_fallback(self):
        """Test location slug generation fallback on empty input"""
        assert slugify_location_name(' !!! ') == 'default-location'


class TestJsonFileOperations:
    """Test JSON file loading and saving"""
    
    def test_load_json_file_success(self, sample_json_file):
        """Test loading a valid JSON file"""
        data = load_json_file(sample_json_file)
        assert isinstance(data, dict)
        assert "locations" in data
        assert data["locations"][0]["name"] == "Test Location"
    
    def test_load_json_file_nonexistent(self):
        """Test loading non-existent file returns default"""
        result = load_json_file("/tmp/nonexistent.json", {"default": True})
        assert result == {"default": True}
    
    def test_load_json_file_no_default(self):
        """Test loading non-existent file with no default"""
        result = load_json_file("/tmp/nonexistent.json")
        assert result == {}
    
    def test_load_json_file_invalid_json(self, temp_file):
        """Test loading invalid JSON returns default"""
        with open(temp_file, 'w') as f:
            f.write("not valid json {")
        result = load_json_file(temp_file, {"error": True})
        assert result == {"error": True}
    
    def test_save_json_file_success(self, temp_dir):
        """Test saving JSON file successfully"""
        file_path = os.path.join(temp_dir, "test.json")
        data = {"test": "value", "number": 42}
        result = save_json_file(file_path, data)
        assert result is True
        assert os.path.exists(file_path)
        
        # Verify content
        with open(file_path, 'r') as f:
            loaded = json.load(f)
        assert loaded == data
    
    def test_save_json_file_creates_parent_dir(self, temp_dir):
        """Test that parent directories are created"""
        file_path = os.path.join(temp_dir, "nested", "dir", "test.json")
        data = {"nested": True}
        result = save_json_file(file_path, data)
        assert result is True
        assert os.path.exists(file_path)
    
    def test_save_json_file_unicode(self, temp_dir):
        """Test saving JSON with unicode characters"""
        file_path = os.path.join(temp_dir, "unicode.json")
        data = {"name": "Café", "emoji": "🌙", "chinese": "月亮"}
        result = save_json_file(file_path, data)
        assert result is True
        
        # Verify unicode is preserved
        loaded = load_json_file(file_path)
        assert loaded["name"] == "Café"
        assert loaded["emoji"] == "🌙"

    def test_save_json_file_unserializable_data(self, temp_dir):
        """Test that unserializable data is handled gracefully"""
        file_path = os.path.join(temp_dir, "bad.json")
        data = {"invalid": {1, 2, 3}}
        result = save_json_file(file_path, data)
        assert result is False


class TestYamlHelpers:
    """Test YAML utility helpers"""

    def test_indent_dumper_is_usable(self):
        """Test that custom dumper can serialize nested lists"""
        payload = {"items": [{"name": "M31"}, {"name": "M42"}]}
        dumped = yaml.dump(payload, Dumper=IndentDumper, sort_keys=False)
        assert "items:" in dumped
        assert "- name: M31" in dumped


class TestCoordinateConversion:
    """Test coordinate conversion utilities"""
    
    def test_dms_to_decimal_positive(self):
        """Test converting positive DMS to decimal"""
        result = dms_to_decimal("48d38m36.16s")
        assert result is not None
        assert abs(result - 48.6434) < 0.001
    
    def test_dms_to_decimal_negative(self):
        """Test converting negative DMS to decimal"""
        result = dms_to_decimal("-45d30m0s")
        assert result is not None
        assert abs(result - (-45.5)) < 0.001
    
    def test_dms_to_decimal_with_symbols(self):
        """Test DMS with degree/minute/second symbols"""
        result = dms_to_decimal("2°20'14.025\"")
        assert result is not None
        assert abs(result - 2.3372) < 0.001
    
    def test_dms_to_decimal_zero(self):
        """Test converting zero degrees"""
        result = dms_to_decimal("0d0m0s")
        assert result == 0.0
    
    def test_dms_to_decimal_invalid_format(self):
        """Test invalid DMS format returns None"""
        assert dms_to_decimal("invalid") is None
        assert dms_to_decimal("") is None
        assert dms_to_decimal("123") is None
    
    def test_dms_to_decimal_none_input(self):
        """Test None input returns None"""
        assert dms_to_decimal(None) is None
    
    def test_decimal_to_dms_positive(self):
        """Test converting positive decimal to DMS"""
        degrees, minutes, seconds = decimal_to_dms(48.6434)
        assert degrees == 48
        assert minutes == 38
        assert abs(seconds - 36.24) < 0.1
    
    def test_decimal_to_dms_negative(self):
        """Test converting negative decimal to DMS"""
        degrees, minutes, seconds = decimal_to_dms(-45.5)
        assert degrees == -45
        assert minutes == 30
        assert abs(seconds - 0.0) < 0.01
    
    def test_decimal_to_dms_zero(self):
        """Test converting zero"""
        degrees, minutes, seconds = decimal_to_dms(0.0)
        assert degrees == 0
        assert minutes == 0
        assert seconds == 0.0
    
    def test_validate_coordinates_valid(self):
        """Test validating valid coordinates"""
        assert validate_coordinates(45.5, -73.5) is True
        assert validate_coordinates(0, 0) is True
        assert validate_coordinates(90, 180) is True
        assert validate_coordinates(-90, -180) is True
    
    def test_validate_coordinates_invalid_latitude(self):
        """Test invalid latitude"""
        assert validate_coordinates(91, 0) is False
        assert validate_coordinates(-91, 0) is False
        assert validate_coordinates(100, 0) is False
    
    def test_validate_coordinates_invalid_longitude(self):
        """Test invalid longitude"""
        assert validate_coordinates(0, 181) is False
        assert validate_coordinates(0, -181) is False
        assert validate_coordinates(0, 200) is False
    
    def test_validate_coordinates_invalid_types(self):
        """Test with invalid types"""
        assert validate_coordinates("not a number", 0) is False
        assert validate_coordinates(0, "not a number") is False
        assert validate_coordinates(None, 0) is False


class TestFileSizeFormatting:
    """Test file size formatting"""
    
    def test_format_file_size_bytes(self):
        """Test formatting bytes"""
        assert format_file_size(0) == "0.0 B"
        assert format_file_size(512) == "512.0 B"
        assert format_file_size(1023) == "1023.0 B"
    
    def test_format_file_size_kilobytes(self):
        """Test formatting kilobytes"""
        assert format_file_size(1024) == "1.0 KB"
        assert format_file_size(2048) == "2.0 KB"
        assert format_file_size(1536) == "1.5 KB"
    
    def test_format_file_size_megabytes(self):
        """Test formatting megabytes"""
        assert format_file_size(1024 * 1024) == "1.0 MB"
        assert format_file_size(1024 * 1024 * 2.5) == "2.5 MB"
    
    def test_format_file_size_gigabytes(self):
        """Test formatting gigabytes"""
        assert format_file_size(1024 * 1024 * 1024) == "1.0 GB"
    
    def test_format_file_size_terabytes(self):
        """Test formatting terabytes"""
        assert format_file_size(1024 * 1024 * 1024 * 1024) == "1.0 TB"


class TestEnvironmentInfo:
    """Test environment info gathering"""

    def test_get_environment_info_returns_dict(self):
        """Test that environment info returns a dictionary"""
        info = get_environment_info()
        assert isinstance(info, dict)

    def test_get_environment_info_contains_expected_keys(self):
        """Test that expected keys are present"""
        info = get_environment_info()
        expected_keys = ['data_dir', 'config_file_exists', 'python_version',
                        'platform', 'working_directory', 'docker_env']
        for key in expected_keys:
            assert key in info

    def test_get_environment_info_data_types(self):
        """Test that values have correct types"""
        info = get_environment_info()
        assert isinstance(info['data_dir'], str)
        assert isinstance(info['python_version'], str)
        assert isinstance(info['platform'], str)
        assert isinstance(info['working_directory'], str)


class TestNumpySafeEncoder:
    """Test the JSON encoder with numpy types."""

    def test_integer_type(self):
        import numpy as np
        result = json.dumps({'v': np.int64(7)}, cls=_NumpySafeEncoder)
        assert '"v": 7' in result

    def test_floating_type_normal(self):
        import numpy as np
        result = json.dumps({'v': np.float64(2.5)}, cls=_NumpySafeEncoder)
        assert '"v": 2.5' in result

    def test_floating_type_nan_becomes_null(self):
        import numpy as np
        # np.float32 is NOT a Python float subclass, so default() is called
        result = json.dumps({'v': np.float32(float('nan'))}, cls=_NumpySafeEncoder)
        assert '"v": null' in result

    def test_floating_type_inf_becomes_null(self):
        import numpy as np
        result = json.dumps({'v': np.float32(float('inf'))}, cls=_NumpySafeEncoder)
        assert '"v": null' in result

    def test_ndarray_becomes_list(self):
        import numpy as np
        result = json.dumps({'v': np.array([1, 2, 3])}, cls=_NumpySafeEncoder)
        assert '[1, 2, 3]' in result

    def test_bool_type(self):
        import numpy as np
        result = json.dumps({'v': np.bool_(True)}, cls=_NumpySafeEncoder)
        assert '"v": true' in result

    def test_sanitize_numpy_integer(self):
        import numpy as np
        assert _sanitize_for_json(np.int64(10)) == 10

    def test_sanitize_numpy_float_normal(self):
        import numpy as np
        assert _sanitize_for_json(np.float64(1.5)) == pytest.approx(1.5)

    def test_sanitize_numpy_float_nan(self):
        import numpy as np
        assert _sanitize_for_json(np.float64(float('nan'))) is None

    def test_sanitize_numpy_bool(self):
        import numpy as np
        assert _sanitize_for_json(np.bool_(False)) is False

    def test_sanitize_numpy_array(self):
        import numpy as np
        assert _sanitize_for_json(np.array([4, 5])) == [4, 5]

    def test_sanitize_float_nan(self):
        assert _sanitize_for_json(float('nan')) is None

    def test_sanitize_float_inf(self):
        assert _sanitize_for_json(float('inf')) is None

    def test_sanitize_tuple_becomes_list(self):
        assert _sanitize_for_json((1, 2, 3)) == [1, 2, 3]

    def test_sanitize_nested_dict(self):
        import numpy as np
        data = {'a': {'b': np.int64(5)}}
        result = _sanitize_for_json(data)
        assert result == {'a': {'b': 5}}
