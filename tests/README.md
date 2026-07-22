# Tests Directory

This directory contains comprehensive unit tests for the MyAstroBoard application.

## Test Coverage

The test suite mirrors `backend/`'s package layout, one subdirectory per package:

- **`blueprints/`**: Flask route/API-level tests (`test_app_routes.py` is the main route-coverage file; per-domain files for astrodex, connectors, plan-my-night, push, skytonight, sky-widget, and the `test_route_inventory.py` API-contract guard)
- **`utils/`**: Cross-cutting support modules — config (`test_config.py`, `test_locations.py`), auth (`test_auth.py`), i18n (`test_i18n_utils.py`), logging (`test_logging_config.py`), push (`test_push_manager.py`, `test_push_scheduler.py`), metrics, version checking, txtconf loading, and shared utilities (`test_utils.py`)
- **`cache/`**: Shared JSON cache store and background scheduler/updater (`test_cache_store.py`, `test_cache_scheduler.py`, `test_cache_updater.py`)
- **`skytonight/`**: SkyTonight calculation pipeline — bodies, calculator, catalogue builder, comets, models, scheduler, storage, targets
- **`astroweather/`**: Astronomical/atmospheric forecast services — moon/sun phases, eclipses, aurora, horizon graph, seeing forecast
- **`weather/`**: Weather forecast clients and astrophotography weather analysis (sky quality/Bortle, Open-Meteo, weather_astro)
- **`observation/`**: Observation logbook, planning, and events business logic — astrodex, beginner catalog, object info, plan-my-night, planetary/solar-system events, sidereal time
- **`space/`**: ISS/CSS pass prediction and spaceflight tracking
- **`equipment/`**: Equipment profiles and the exposure-calculator formula
- **`connectors/`**: AllSky connector

Test files follow `backend/<package>/<module>.py` → `tests/<package>/test_<module>.py`.

## Running Tests

### Quick Start

```bash
# Run all tests
python -m pytest tests/ -v

# Run all tests (quiet mode)
python -m pytest tests/ -q

# Run specific test file
python -m pytest tests/utils/test_utils.py -v

# Run specific test class
python -m pytest tests/utils/test_utils.py::TestCoordinateConversion -v

# Run specific test
python -m pytest tests/utils/test_utils.py::TestCoordinateConversion::test_dms_to_decimal_positive -v

# Run every test for one backend package
python -m pytest tests/skytonight/ -v
```

### With Coverage

```bash
# Run tests with coverage report
python -m pytest tests/ --cov=backend --cov-report=term

# Generate HTML coverage report
python -m pytest tests/ --cov=backend --cov-report=html

# View HTML report (opens in browser)
# Report is generated in htmlcov/index.html
```

### Test Options

```bash
# Run tests with detailed output
python -m pytest tests/ -v

# Run tests with short traceback
python -m pytest tests/ --tb=short

# Run tests matching a pattern
python -m pytest tests/ -k "coordinate"

# Stop at first failure
python -m pytest tests/ -x

# Show local variables in tracebacks
python -m pytest tests/ -l
```

## Test Structure

### Test Organization

Tests mirror the `backend/` package structure:
- Each backend package has a matching `tests/` subdirectory (e.g., `backend/skytonight/` → `tests/skytonight/`)
- Each backend module has a corresponding test file (e.g., `utils/logging_config.py` → `tests/utils/test_logging_config.py`)
- Tests are grouped into classes by functionality
- Each test class focuses on a specific aspect or function
- Don't add new top-level "coverage boost" grab-bag files spanning several unrelated modules - extend the test file for the module actually under test instead, even if that means several small additions across files

### Fixtures

Common test fixtures are defined in `conftest.py`:
- `temp_dir`: Temporary directory for test files
- `temp_file`: Temporary file for testing
- `sample_config`: Sample configuration dictionary
- `sample_json_file`: Temporary JSON file with sample data
- `sample_coordinates`: Test coordinate data

### Environment Setup

Tests automatically configure environment variables to avoid permissions issues and ensure isolation:
- `DATA_DIR`, `OUTPUT_DIR`, `CONFIG_DIR`: Set to temporary directories
- `LOG_LEVEL`, `CONSOLE_LOG_LEVEL`: Set to ERROR to reduce noise

## Requirements

Test dependencies are listed in `requirements-dev.txt`:

```bash
pip install -r requirements-dev.txt
```

Main testing packages:
- `pytest>=7.4.0`: Test framework
- `pytest-cov>=4.1.0`: Coverage reporting

## CI/CD Integration

Tests can be integrated into CI/CD pipelines:

```yaml
# Example GitHub Actions workflow
- name: Install dependencies
  run: pip install -r requirements-dev.txt

- name: Run tests
  run: python -m pytest tests/ -v --cov=backend --cov-report=xml
```

## Writing New Tests

### Test Naming Convention

- Test files: `test_<module_name>.py`
- Test classes: `Test<Functionality>`
- Test functions: `test_<what_it_tests>`

### Example Test

```python
import pytest
from module_name import function_to_test

class TestFunctionality:
    """Test specific functionality"""
    
    def test_basic_case(self):
        """Test basic usage"""
        result = function_to_test(input_data)
        assert result == expected_output
    
    def test_edge_case(self):
        """Test edge case"""
        result = function_to_test(edge_input)
        assert result is not None
    
    def test_error_handling(self):
        """Test error handling"""
        with pytest.raises(ValueError):
            function_to_test(invalid_input)
```

### Best Practices

1. **One assertion per test** (when possible)
2. **Use descriptive test names** that explain what is being tested
3. **Test both success and failure cases**
4. **Use fixtures** for common setup
5. **Keep tests independent** - no test should depend on another
6. **Mock external dependencies** (APIs, file system when needed)
7. **Test edge cases** and boundary conditions

## Troubleshooting

### Common Issues

1. **Import errors**: Ensure `PYTHONPATH` includes the backend directory
   ```bash
   PYTHONPATH=/path/to/backend python -m pytest tests/
   ```

2. **Permission errors**: Tests use temporary directories, but check environment variables
   ```bash
   DATA_DIR=/tmp/test python -m pytest tests/
   ```

3. **Slow tests**: Some astronomical calculations are computationally intensive
   - Use `-k` to run specific tests during development
   - Full suite takes ~2 minutes to run

## Contributing

When adding new backend functionality:
1. Write tests for the new code
2. Ensure all tests pass: `python -m pytest tests/`
3. Check coverage: `python -m pytest tests/ --cov=backend`
4. Aim for >80% coverage on new code
