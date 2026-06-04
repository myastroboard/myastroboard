# Contributing to MyAstroBoard

First off, thank you for considering contributing to MyAstroBoard! It's people like you that make MyAstroBoard such a great tool for the astronomy community.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Process](#development-process)
- [How Can I Contribute?](#how-can-i-contribute)
- [Style Guidelines](#style-guidelines)
- [Testing](#testing)
- [Pull Request Process](#pull-request-process)
- [Community](#community)

## Code of Conduct

This project and everyone participating in it is governed by our [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code. Please report unacceptable behavior to the project maintainers.

## Getting Started

### Prerequisites

Before you begin, make sure you have:
- Docker and Docker Compose installed
- Python 3.12 or higher (for local development)
- Git for version control
- A GitHub account

### Setting Up Your Development Environment

1. **Fork the Repository**
   ```bash
   # Fork on GitHub, then clone your fork
   git clone https://github.com/YOUR_USERNAME/myastroboard.git
   cd myastroboard
   ```

2. **Add Upstream Remote**
   ```bash
   git remote add upstream https://github.com/WorldOfGZ/myastroboard.git
   ```

3. **Set Up Development Environment**
   ```bash
   # Option 1: Using Docker (recommended)
   docker-compose -f docker-compose-dev.yml up --build
   
   # Option 2: Local Python environment
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements-dev.txt
   ```

4. **Verify Installation**
   - Access the application at http://localhost:5000
   - Check that all features load correctly

### Project Documentation

Please read through our documentation before contributing:
- [Installation Guide](docs/1.INSTALLATION.md)
- [Quick Start](docs/2.QUICKSTART.md)
- [Organization](docs/5.ORGANIZATION.md)
- [Cache System](docs/CACHE_SYSTEM.md)
- [Translations](docs/7.TRANSLATIONS.md)

## Development Process

### Branching Strategy

We use a simplified Git workflow:

- `main` - Production-ready code
- Feature branches - Named `feature/description` or `fix/description`

### Creating a Branch

```bash
# Update your main branch
git checkout main
git pull upstream main

# Create a feature branch
git checkout -b feature/your-feature-name
# or
git checkout -b fix/issue-description
```

## How Can I Contribute?

### Reporting Bugs

Before creating bug reports, please check existing issues to avoid duplicates.

When you create a bug report, include:
- **Clear descriptive title**
- **Detailed description** of the issue
- **Steps to reproduce** the problem
- **Expected behavior** vs actual behavior
- **Environment details** (OS, Docker version, Python version)
- **Screenshots** if applicable
- **Log files** from `data/myastroboard.log`

### Suggesting Enhancements

Enhancement suggestions are tracked as GitHub issues. When creating an enhancement suggestion:
- **Use a clear descriptive title**
- **Provide detailed description** of the suggested enhancement
- **Explain why this enhancement would be useful**
- **Include mockups or examples** if applicable

### Your First Code Contribution

Unsure where to begin? Look for issues labeled:
- `good first issue` - Good for newcomers
- `help wanted` - Extra attention needed
- `documentation` - Documentation improvements

### Pull Requests

1. **Create an Issue First** - For significant changes, create an issue to discuss your approach
2. **Write Code** - Follow our style guidelines
3. **Add Tests** - Include tests for new functionality
4. **Update Documentation** - Update relevant documentation
5. **Submit PR** - Use our Pull Request template

## Style Guidelines

### Language Requirement

**IMPORTANT**: All code, comments, documentation, and user-facing text MUST be in English.

This includes:
- Variable names, function names, class names
- Comments and docstrings
- Error messages and UI text
- Documentation and commit messages
- Pull request descriptions

### Python Style Guide

We follow [PEP 8](https://pep8.org/) with these specifics:

#### Code Formatting
- Maximum line length: **120 characters**
- Use **4 spaces** for indentation (no tabs)
- Use **f-strings** for string formatting
- Use **type hints** where beneficial

#### Example:
```python
from typing import Optional, Dict, List
from logging_config import get_logger

logger = get_logger(__name__)

def calculate_observation_score(
    altitude: float,
    magnitude: float,
    moon_separation: float,
    weather_quality: Optional[float] = None
) -> Dict[str, float]:
    """
    Calculate observation quality score for a celestial object.
    
    Args:
        altitude: Object altitude in degrees
        magnitude: Object visual magnitude
        moon_separation: Angular separation from moon in degrees
        weather_quality: Optional weather quality factor (0-1)
    
    Returns:
        Dictionary containing score components and total score
    """
    logger.debug(f"Calculating score for altitude={altitude}, mag={magnitude}")
    
    # Implementation here
    score = {
        'altitude_score': altitude / 90.0,
        'magnitude_score': max(0, 1 - magnitude / 10),
        'moon_score': moon_separation / 180.0
    }
    
    return score
```

### Logging Guidelines

**MANDATORY**: Use centralized logging system

```python
from logging_config import get_logger

logger = get_logger(__name__)

# Use appropriate log levels
logger.debug("Detailed debugging information")
logger.info("General information about program execution")
logger.warning("Warning about unexpected situation")
logger.error(f"Error occurred: {error_details}")
logger.exception("Critical error with stack trace")
```

**NEVER**:
- Use `print()` statements for logging
- Import `logging` directly
- Create your own logger configuration

### JavaScript Style Guide

- Use **ES6+** modern syntax
- Use **camelCase** for variable and function names
- Use **const** by default, **let** when reassignment needed
- Add **JSDoc comments** for functions
- Keep functions small and focused

#### Example:
```javascript
/**
 * Fetches observation data for a specific catalogue
 * @param {string} catalogueName - Name of the catalogue to fetch
 * @param {Object} options - Fetch options
 * @returns {Promise<Object>} Observation data
 */
async function fetchCatalogueData(catalogueName, options = {}) {
    try {
        const response = await fetch(`/api/catalogue/${catalogueName}`, options);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return await response.json();
    } catch (error) {
        console.error(`Error fetching catalogue ${catalogueName}:`, error);
        throw error;
    }
}
```

### CSS Style Guide

- Use **BEM** naming convention where applicable
- Group related properties together
- Use CSS variables for colors and common values
- Mobile-first responsive design

### Git Commit Messages

Follow these conventions:

- Use present tense ("Add feature" not "Added feature")
- Use imperative mood ("Move cursor to..." not "Moves cursor to...")
- Limit first line to 72 characters
- Reference issues and pull requests when applicable

#### Format:
```
<type>: <subject>

<body>

<footer>
```

#### Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, no code change)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

#### Examples:
```
feat: Add aurora prediction functionality

Implement aurora borealis predictions using space weather data.
Includes API endpoint, frontend display, and caching.

Closes #123
```

```
fix: Correct moon phase calculation for southern hemisphere

The moon phase calculation was not accounting for observer latitude.
Updated algorithm to properly handle southern hemisphere observations.

Fixes #456
```

## Testing

### Running Tests

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_utils.py

# Run with coverage
pytest --cov=backend --cov-report=html

# Run in Docker
docker-compose -f docker-compose-dev.yml run myastroboard pytest
```

### Writing Tests

- Place tests in the `tests/` directory
- Name test files `test_*.py`
- Name test functions `test_*`
- Use descriptive test names
- Include docstrings explaining what is tested
- Use fixtures from `conftest.py`

#### Example:
```python
import pytest
from backend.utils import parse_coordinates

def test_parse_coordinates_valid_input():
    """Test coordinate parsing with valid decimal degrees."""
    lat, lon = parse_coordinates("48.8566", "2.3522")
    assert lat == pytest.approx(48.8566)
    assert lon == pytest.approx(2.3522)

def test_parse_coordinates_invalid_format():
    """Test coordinate parsing handles invalid format gracefully."""
    with pytest.raises(ValueError):
        parse_coordinates("invalid", "coordinates")
```

### Test Coverage

- Aim for **80%+ code coverage** for new code
- Test both success and failure paths
- Test edge cases and boundary conditions
- Mock external dependencies (Docker, APIs, etc.)

## Pull Request Process

### Before Submitting

1. **Update your branch** with latest main
   ```bash
   git checkout main
   git pull upstream main
   git checkout your-branch
   git rebase main
   ```

2. **Run tests and linting**
   ```bash
   pytest
   black backend/
   flake8 backend/
   ```

3. **Update documentation** if needed

4. **Update VERSION** file if applicable (maintainers will handle for releases)

### Submitting the Pull Request

1. **Push to your fork**
   ```bash
   git push origin your-branch
   ```

2. **Create Pull Request** on GitHub:
   - Use the pull request template
   - Link related issues
   - Provide clear description of changes
   - Add screenshots for UI changes
   - Ensure CI checks pass (`validate-i18n`, `docker-publish`)

3. **Address Review Comments**:
   - Respond to all feedback
   - Make requested changes
   - Push updates to the same branch
   - Re-request review when ready

### PR Checklist

- [ ] Code follows project style guidelines
- [ ] All text is in English
- [ ] Self-review completed
- [ ] Comments added for complex code
- [ ] Documentation updated
- [ ] Tests added/updated
- [ ] All tests passing
- [ ] No merge conflicts
- [ ] Logging uses centralized system (no `print()`)
- [ ] Commit messages follow conventions

### Review Process

- Maintainers will review your PR
- At least one approval required
- CI checks must pass
- Squash and merge strategy used

## Community

### Getting Help

- **Issues**: Check existing issues or create a new one
- **Discussions**: Use GitHub Discussions for questions
- **Documentation**: Read the [docs/](docs/) folder

### Recognition

Contributors will be acknowledged in:
- Release notes
- Project documentation
- GitHub contributors list

## Directory-Specific Contribution Notes

### Backend (`backend/`)
- All modules must use centralized logging
- Add type hints to function signatures
- Follow existing patterns for API endpoints
- Update relevant tests in `tests/`
- If you add or modify user-facing text, update the translation files — see [docs/7.TRANSLATIONS.md](docs/7.TRANSLATIONS.md)

### Frontend (`static/js/`, `static/css/`, `templates/`)
- Maintain vanilla JavaScript (no frameworks)
- Follow existing CSS structure (separate files per feature)
- Ensure mobile responsiveness
- Test in multiple browsers

### Documentation (`docs/`)
- Use clear, concise language
- Include code examples
- Add screenshots for visual features
- Keep table of contents updated

### Tests (`tests/`)
- Mirror backend structure
- Use pytest fixtures from `conftest.py`
- Add integration tests for new features
- Mock external dependencies

### Target Catalogues (`backend/catalogues/`)
- Follow JSON format of existing catalogues
- Include comprehensive README updates
- Validate catalogue data

## Questions?

Don't hesitate to ask questions by:
- Creating an issue with the `question` label
- Starting a discussion in GitHub Discussions
- Commenting on relevant issues or PRs

Thank you for contributing to MyAstroBoard! 🌙✨
