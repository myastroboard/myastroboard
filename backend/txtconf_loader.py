"""Load repository metadata from text files."""

import os
from logging_config import get_logger

logger = get_logger(__name__)


def get_repo_version():
    """
    Load the repository version from VERSION file

    Returns:
        str: Repository version string (e.g., "v0.9.0")
    """
    version_file = os.path.join(os.path.dirname(__file__), '..', 'VERSION')

    try:
        with open(version_file, 'r') as f:
            version = f.read().strip()
            return version
    except Exception as e:
        logger.error(f"Error loading repository version: {e}")
        return "1.0.0"
