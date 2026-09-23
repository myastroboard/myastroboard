"""
Authentication and User Management Module
Handles user authentication, authorization, and session management
"""

import json
import os
import uuid
import re
import shutil
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
import pyotp
from flask import session, jsonify, request
from werkzeug.security import generate_password_hash, check_password_hash
from utils.file_lock import interprocess_lock
from utils.logging_config import get_logger
from utils.i18n_utils import SUPPORTED_LANGUAGES

logger = get_logger(__name__)

# User roles
ROLE_ADMIN = 'admin'
ROLE_USER = 'user'
ROLE_READ_ONLY = 'read-only'

# Account scope: a 'local' account may only sign in from a trusted network
# (see utils/security_settings.py). Every account is 'global' unless told otherwise.
ACCOUNT_SCOPE_GLOBAL = 'global'
ACCOUNT_SCOPE_LOCAL = 'local'
ALLOWED_ACCOUNT_SCOPES = {ACCOUNT_SCOPE_GLOBAL, ACCOUNT_SCOPE_LOCAL}

# Issuer shown by the authenticator app next to the account name
TOTP_ISSUER = 'MyAstroBoard'

# pyotp verifies the current 30s step plus one step either side, tolerating a
# +/-30s clock drift between the server and the authenticator device.
TOTP_VALID_WINDOW = 1

# Default admin credentials
DEFAULT_ADMIN_USERNAME = 'admin'
DEFAULT_ADMIN_PASSWORD = 'admin'

# User customization defaults and allowed values
ALLOWED_STARTUP_MAIN_TABS = {
    'forecast-astro',
    'forecast-weather',
    'skytonight',
    'spaceflight',
    'astrodex',
    'equipment',
    'my-settings',
    'parameters',
}
ALLOWED_STARTUP_SUBTABS = {
    'astro-weather',
    'window',
    'moon',
    'sun',
    'aurora',
    'calendar',
    'weather',
    'seeing',
    'trend',
    'launches',
    'astronauts',
    'space-events',
    'iss',
    'astrodex',
    'plan-my-night',
    'combinations',
    'fov',
    'telescopes',
    'cameras',
    'mounts',
    'filters',
    'accessories',
    'customize',
    'location',
    'security',
    'locations',
    'configuration',
    'logs',
    'users',
    'metrics',
}
ALLOWED_TIME_FORMATS = {'auto', '12h', '24h'}
ALLOWED_DENSITY_MODES = {'comfortable', 'compact'}
ALLOWED_THEME_MODES = {'auto', 'light', 'dark', 'red'}
ALLOWED_FIRST_DAY_OF_WEEK = {'monday', 'sunday'}
ALLOWED_LANGUAGES = set(SUPPORTED_LANGUAGES)
ALLOWED_EXPERIENCE_LEVELS = {'beginner', 'intermediate', 'advanced'}

DEFAULT_USER_PREFERENCES = {
    'startup_main_tab': 'forecast-astro',
    'startup_subtab': 'astro-weather',
    'time_format': 'auto',
    'density': 'comfortable',
    'theme_mode': 'auto',
    'first_day_of_week': 'monday',
    'language': 'en',
    'experience_level': 'advanced',
    'beginner_catalog_enabled': True,
    'recommendations_enabled': True,
    # v1.6: publish this user's own Astrodex / plan activity through the MQTT connector.
    # Off by default and user-scoped: an admin enables the connector, never another user's data.
    'mqtt_publish_enabled': False,
    'wizard': {
        'completed': False,
        'skipped': False,
    },
    'notifications': {
        'enabled': True,
        'permission_asked': False,
        'disabled_location_ids': [],
        'triggers': {
            'N1': {'enabled': True, 'lead_minutes': 15},
            'N2': {'enabled': True, 'lead_minutes': 5},
            'N3': {'enabled': True, 'lead_minutes': 10},
            'N4': {'enabled': True, 'lead_minutes': 30},
            'N5': {'enabled': True, 'lead_minutes': 30},
            'N6': {'enabled': True, 'lead_minutes': 20},
            'N7': {'enabled': True, 'kp_threshold': 6},
            'N8': {'enabled': True, 'lead_minutes': 10},
        },
    },
    # Multi-location profiles (v1.2):
    # - attributed_location_ids: admin-assigned; empty = install default only
    # - default_location_id: durable "what I see when I connect" preference
    # - active_location_id: what drives calculations right now, this session
    # - order: user-chosen display order in the switcher
    'location': {
        'attributed_location_ids': [],
        'default_location_id': None,
        'active_location_id': None,
        'order': [],
    },
}

# Users storage file
USERS_FILE = os.path.join(os.environ.get('DATA_DIR', '/app/data'), 'users.json')


def normalize_account_scope(value):
    """Coerce a stored account_scope to a known value.

    Unlike `role`, an unrecognised scope does not invalidate the whole users file:
    an admin hand-editing users.json (the documented lost-authenticator recovery
    path) must not be able to lock everyone out with a typo. It falls back to
    'global', which is also the default for entries that predate the field.
    """
    if value is None:
        return ACCOUNT_SCOPE_GLOBAL
    if value in ALLOWED_ACCOUNT_SCOPES:
        return value
    logger.warning(f"Unknown account_scope {value!r}, falling back to '{ACCOUNT_SCOPE_GLOBAL}'")
    return ACCOUNT_SCOPE_GLOBAL


class User:
    """User model"""

    def __init__(
        self,
        username,
        password_hash,
        role,
        user_id=None,
        created_at=None,
        last_login=None,
        preferences=None,
        push_subscriptions=None,
        account_scope=None,
        totp_secret=None,
        totp_enabled=False,
        totp_confirmed_at=None,
    ):
        self.user_id = user_id or str(uuid.uuid4())
        self.username = username
        self.password_hash = password_hash
        self.role = role
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()
        self.last_login = last_login
        self.preferences = preferences.copy() if isinstance(preferences, dict) else DEFAULT_USER_PREFERENCES.copy()
        self.push_subscriptions = push_subscriptions if isinstance(push_subscriptions, list) else []
        self.account_scope = normalize_account_scope(account_scope)
        # Base32 TOTP shared secret. It is persisted as soon as setup starts (with
        # totp_enabled still False) rather than being kept in memory or in the Flask
        # session: the container runs gunicorn with several workers, so a pending
        # secret held in one worker would be missing from the one handling /confirm.
        self.totp_secret = totp_secret if isinstance(totp_secret, str) and totp_secret else None
        self.totp_enabled = bool(totp_enabled) and bool(self.totp_secret)
        self.totp_confirmed_at = totp_confirmed_at

    def to_dict(self):
        """Convert user to dictionary"""
        return {
            'user_id': self.user_id,
            'username': self.username,
            'password_hash': self.password_hash,
            'role': self.role,
            'created_at': self.created_at,
            'last_login': self.last_login,
            'preferences': self.preferences,
            'push_subscriptions': self.push_subscriptions,
            'account_scope': self.account_scope,
            'totp_secret': self.totp_secret,
            'totp_enabled': self.totp_enabled,
            'totp_confirmed_at': self.totp_confirmed_at,
        }

    @staticmethod
    def from_dict(data):
        """Create user from dictionary.

        The 2FA and account-scope keys default to falsy/'global' so entries written by
        an older version load unchanged - no migration script is needed.
        """
        return User(
            user_id=data.get('user_id'),
            username=data['username'],
            password_hash=data['password_hash'],
            role=data['role'],
            created_at=data.get('created_at'),
            last_login=data.get('last_login'),
            preferences=data.get('preferences'),
            push_subscriptions=data.get('push_subscriptions'),
            account_scope=data.get('account_scope'),
            totp_secret=data.get('totp_secret'),
            totp_enabled=data.get('totp_enabled', False),
            totp_confirmed_at=data.get('totp_confirmed_at'),
        )

    def check_password(self, password):
        """Check if password matches"""
        return check_password_hash(self.password_hash, password)

    def get_totp_uri(self, issuer=TOTP_ISSUER):
        """Return the otpauth:// provisioning URI for this user's current secret."""
        if not self.totp_secret:
            raise ValueError("No TOTP secret set for this user")
        return pyotp.TOTP(self.totp_secret).provisioning_uri(name=self.username, issuer_name=issuer)

    def verify_totp(self, code):
        """Check a 6-digit TOTP code against this user's secret (clock-drift tolerant)."""
        if not self.totp_secret or not code:
            return False
        try:
            return pyotp.TOTP(self.totp_secret).verify(str(code).strip(), valid_window=TOTP_VALID_WINDOW)
        except Exception as e:
            logger.warning(f"TOTP verification error for user {self.username}: {e}")
            return False

    def is_local_account(self):
        """Check if this account may only sign in from a trusted network"""
        return self.account_scope == ACCOUNT_SCOPE_LOCAL

    def is_admin(self):
        """Check if user is admin"""
        return self.role == ROLE_ADMIN

    def is_user(self):
        """Check if user is a regular user"""
        return self.role == ROLE_USER

    def is_read_only(self):
        """Check if user is read-only"""
        return self.role == ROLE_READ_ONLY

    def is_using_default_password(self):
        """Check if user is still using default password"""
        if self.username == DEFAULT_ADMIN_USERNAME:
            return check_password_hash(self.password_hash, DEFAULT_ADMIN_PASSWORD)
        return False


def _serialized_users_write(method):
    """Run a UserManager mutator under the users.json write lock.

    Every gunicorn worker keeps its own copy of the user table and saves it
    whole, so reload -> modify -> save must not interleave with another
    worker's save, or one of the two changes is silently reverted.
    """

    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._exclusive_write():
            return method(self, *args, **kwargs)

    return wrapper


class UserManager:
    """Manages user storage and operations"""

    def __init__(self):
        self.users = {}
        self._users_mtime = None
        self._write_mutex = threading.RLock()
        self._write_depth = 0
        self.load_users()

    @contextmanager
    def _exclusive_write(self):
        """Hold the users.json write lock across threads and gunicorn workers (reentrant)."""
        with self._write_mutex:
            outermost = self._write_depth == 0
            self._write_depth += 1
            try:
                if outermost:
                    with interprocess_lock(USERS_FILE + '.lock'):
                        yield
                else:
                    yield
            finally:
                self._write_depth -= 1

    def modify_user(self, user_id, mutate):
        """Apply ``mutate(user)`` to the freshest copy of one user and save, atomically across workers.

        For callers outside this class that change a user they looked up
        earlier: that object may predate another worker's save, and saving
        the table it belongs to would revert that save. Returns ``mutate``'s
        result, or None (without saving) when the user no longer exists.
        """
        with self._exclusive_write():
            self._reload_users_if_changed()
            user = self.users.get(user_id)
            if user is None:
                return None
            result = mutate(user)
            self.save_users()
            return result

    def load_users(self):
        """Load users from file"""
        if os.path.exists(USERS_FILE):
            try:
                with open(USERS_FILE, 'r') as f:
                    data = json.load(f)
                    is_valid, error_msg = self.validate_users_json_data(data)
                    if not is_valid:
                        raise ValueError(f"Invalid users data: {error_msg}")
                    self.users = {key: User.from_dict(user_data) for key, user_data in data.items()}
                self._users_mtime = os.path.getmtime(USERS_FILE)
                logger.debug(f"Loaded {len(self.users)} users from {USERS_FILE}")
            except Exception as e:
                logger.error(f"Error loading users: {e}")
                self.users = {}
                self._users_mtime = None
        else:
            logger.info("No users file found, starting fresh")
            self.users = {}
            self._users_mtime = None
            # Only create default admin if users file is missing
            self.ensure_default_admin()

    def _reload_users_if_changed(self):
        """Reload users from disk when file changed (multi-worker sync)."""
        try:
            if not os.path.exists(USERS_FILE):
                if self.users:
                    self.users = {}
                self._users_mtime = None
                return

            current_mtime = os.path.getmtime(USERS_FILE)
            if self._users_mtime is None or current_mtime != self._users_mtime:
                self.load_users()
        except Exception as e:
            logger.warning(f"Failed to check users file freshness: {e}")

    @_serialized_users_write
    def save_users(self):
        """Save users to file using atomic write and JSON validation."""
        temp_path = USERS_FILE + '.tmp'
        backup_path = USERS_FILE + '.backup'
        backup_created = False

        try:
            # Ensure data directory exists
            os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)

            data = {user_id: user.to_dict() for user_id, user in self.users.items()}

            # Keep a backup of current file before replacing it.
            if os.path.exists(USERS_FILE):
                shutil.copy2(USERS_FILE, backup_path)
                backup_created = True

            # Write to a temporary file first.
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            # Validate temporary JSON structure before replacing the live users file.
            is_valid, error_msg = self.validate_users_json_file(temp_path)
            if not is_valid:
                raise ValueError(f"users.json validation failed: {error_msg}")

            os.replace(temp_path, USERS_FILE)
            self._users_mtime = os.path.getmtime(USERS_FILE)

            if backup_created and os.path.exists(backup_path):
                os.remove(backup_path)

            logger.debug(f"Saved {len(self.users)} users to {USERS_FILE}")
        except Exception as e:
            logger.error(f"Error saving users: {e}")

            # Restore previous users file when possible.
            if backup_created and os.path.exists(backup_path):
                try:
                    os.replace(backup_path, USERS_FILE)
                    self._users_mtime = os.path.getmtime(USERS_FILE)
                except Exception as restore_error:
                    logger.error(f"Failed to restore users backup: {restore_error}")

            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception as cleanup_error:
                    logger.warning(f"Failed to remove users temp file: {cleanup_error}")

            if backup_created and os.path.exists(backup_path):
                try:
                    os.remove(backup_path)
                except Exception as cleanup_error:
                    logger.warning(f"Failed to remove users backup file: {cleanup_error}")

            raise

    @staticmethod
    def validate_users_json_data(data):
        """Validate in-memory users JSON structure."""
        if not isinstance(data, dict):
            return False, "JSON root must be a dictionary"

        for user_id, user_data in data.items():
            if not isinstance(user_id, str) or not user_id:
                return False, "Each user id key must be a non-empty string"

            if not isinstance(user_data, dict):
                return False, f"User {user_id} data must be a dictionary"

            required_fields = ['user_id', 'username', 'password_hash', 'role', 'created_at']
            missing_fields = [field for field in required_fields if field not in user_data]
            if missing_fields:
                return False, f"User {user_id} missing fields: {', '.join(missing_fields)}"

            if user_data.get('user_id') != user_id:
                return False, f"User {user_id} contains mismatched user_id"

            role = user_data.get('role')
            if role not in [ROLE_ADMIN, ROLE_USER, ROLE_READ_ONLY]:
                return False, f"User {user_id} has invalid role: {role}"

            preferences = user_data.get('preferences')
            if preferences is not None:
                if not isinstance(preferences, dict):
                    return False, f"User {user_id} preferences must be a dictionary"
                is_valid_prefs, prefs_error = UserManager.validate_user_preferences(preferences)
                if not is_valid_prefs:
                    return False, f"User {user_id} invalid preferences: {prefs_error}"

        return True, ""

    @classmethod
    def validate_users_json_file(cls, file_path):
        """Validate users JSON file content and structure."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return cls.validate_users_json_data(data)
        except json.JSONDecodeError as e:
            return False, f"Invalid JSON: {e}"
        except Exception as e:
            return False, f"Validation error: {e}"

    @staticmethod
    def validate_user_preferences(preferences):
        """Validate user preference payload for allowed keys and values."""
        if not isinstance(preferences, dict):
            return False, "Preferences must be a dictionary"

        # Unknown keys are silently ignored - forward-compat when new prefs are added
        # and old server code still runs for a moment before restart.

        startup_main_tab = preferences.get('startup_main_tab')
        if startup_main_tab is not None and startup_main_tab not in ALLOWED_STARTUP_MAIN_TABS:
            return False, f"Invalid startup_main_tab: {startup_main_tab}"

        startup_subtab = preferences.get('startup_subtab')
        if startup_subtab is not None and startup_subtab not in ALLOWED_STARTUP_SUBTABS:
            return False, f"Invalid startup_subtab: {startup_subtab}"

        time_format = preferences.get('time_format')
        if time_format is not None and time_format not in ALLOWED_TIME_FORMATS:
            return False, f"Invalid time_format: {time_format}"

        density = preferences.get('density')
        if density is not None and density not in ALLOWED_DENSITY_MODES:
            return False, f"Invalid density: {density}"

        theme_mode = preferences.get('theme_mode')
        if theme_mode is not None and theme_mode not in ALLOWED_THEME_MODES:
            return False, f"Invalid theme_mode: {theme_mode}"

        notifications = preferences.get('notifications')
        if notifications is not None:
            if not isinstance(notifications, dict):
                return False, "Invalid notifications: must be a dictionary"
            for trigger_id, trigger_prefs in notifications.items():
                if not isinstance(trigger_prefs, dict):
                    continue
                # Mirrors the fixed <select> option ranges backing #notif-lead-<id> (1 min to 7
                # days) and #notif-kp-threshold (Kp index, standardized 0-9) in templates/index.html.
                lead_minutes = trigger_prefs.get('lead_minutes')
                if lead_minutes is not None:
                    if not isinstance(lead_minutes, (int, float)) or isinstance(lead_minutes, bool):
                        return False, f"Invalid notifications.{trigger_id}.lead_minutes: must be a number"
                    if not (1 <= lead_minutes <= 10080):
                        return False, f"Invalid notifications.{trigger_id}.lead_minutes: must be between 1 and 10080"
                kp_threshold = trigger_prefs.get('kp_threshold')
                if kp_threshold is not None:
                    if not isinstance(kp_threshold, (int, float)) or isinstance(kp_threshold, bool):
                        return False, f"Invalid notifications.{trigger_id}.kp_threshold: must be a number"
                    if not (0 <= kp_threshold <= 9):
                        return False, f"Invalid notifications.{trigger_id}.kp_threshold: must be between 0 and 9"

        first_day_of_week = preferences.get('first_day_of_week')
        if first_day_of_week is not None and first_day_of_week not in ALLOWED_FIRST_DAY_OF_WEEK:
            return False, f"Invalid first_day_of_week: {first_day_of_week}"

        language = preferences.get('language')
        if language is not None and language not in ALLOWED_LANGUAGES:
            return False, f"Invalid language: {language}"

        experience_level = preferences.get('experience_level')
        if experience_level is not None and experience_level not in ALLOWED_EXPERIENCE_LEVELS:
            return False, f"Invalid experience_level: {experience_level}"

        beginner_catalog_enabled = preferences.get('beginner_catalog_enabled')
        if beginner_catalog_enabled is not None and not isinstance(beginner_catalog_enabled, bool):
            return False, "Invalid beginner_catalog_enabled: must be a boolean"

        recommendations_enabled = preferences.get('recommendations_enabled')
        if recommendations_enabled is not None and not isinstance(recommendations_enabled, bool):
            return False, "Invalid recommendations_enabled: must be a boolean"

        mqtt_publish_enabled = preferences.get('mqtt_publish_enabled')
        if mqtt_publish_enabled is not None and not isinstance(mqtt_publish_enabled, bool):
            return False, "Invalid mqtt_publish_enabled: must be a boolean"

        wizard = preferences.get('wizard')
        if wizard is not None:
            if not isinstance(wizard, dict):
                return False, "Invalid wizard: must be a dictionary"
            completed = wizard.get('completed')
            if completed is not None and not isinstance(completed, bool):
                return False, "Invalid wizard: completed must be a boolean"
            skipped = wizard.get('skipped')
            if skipped is not None and not isinstance(skipped, bool):
                return False, "Invalid wizard: skipped must be a boolean"

        location = preferences.get('location')
        if location is not None:
            if not isinstance(location, dict):
                return False, "Invalid location: must be a dictionary"
            for list_key in ('attributed_location_ids', 'order'):
                value = location.get(list_key)
                if value is not None:
                    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                        return False, f"Invalid location.{list_key}: must be a list of strings"
            for id_key in ('default_location_id', 'active_location_id'):
                value = location.get(id_key)
                if value is not None and not isinstance(value, str):
                    return False, f"Invalid location.{id_key}: must be a string or null"

        return True, ""

    @staticmethod
    def sanitize_user_preferences(preferences):
        """Merge a partial preferences payload into defaults.

        Deep-copies the defaults so nested blocks (notifications, wizard,
        location) are never shared by reference across users - a user missing
        a nested block must not receive a mutable alias of the module-level
        default dict.
        """
        import copy as _copy

        merged = _copy.deepcopy(DEFAULT_USER_PREFERENCES)
        if isinstance(preferences, dict):
            for key, value in preferences.items():
                if key in merged:
                    merged[key] = value
        return merged

    @_serialized_users_write
    def ensure_default_admin(self):
        """Ensure default admin user exists"""
        # Another worker may have created it while this one waited for the lock
        self._reload_users_if_changed()
        # Check by username, not by key
        if not self.get_user_by_username(DEFAULT_ADMIN_USERNAME):
            logger.info("Creating default admin user")
            self.create_user(DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_PASSWORD, ROLE_ADMIN)

    @staticmethod
    def _all_location_ids():
        """Every currently configured location id (lazy import: avoids a
        module-load-time cycle with repo_config.py, which itself lazily
        imports auth.user_manager in get_scheduler_locations et al)."""
        try:
            from utils.repo_config import load_config, get_all_locations

            return [loc["id"] for loc in get_all_locations(load_config()) if loc.get("id")]
        except Exception:
            return []

    @_serialized_users_write
    def create_user(self, username, password, role, account_scope=None):
        """Create a new user"""
        self._reload_users_if_changed()

        if self.get_user_by_username(username):
            raise ValueError(f"User {username} already exists")

        if role not in [ROLE_ADMIN, ROLE_USER, ROLE_READ_ONLY]:
            raise ValueError(f"Invalid role: {role}")

        if account_scope is not None and account_scope not in ALLOWED_ACCOUNT_SCOPES:
            raise ValueError(f"Invalid account scope: {account_scope}")

        user = User(
            username=username,
            password_hash=generate_password_hash(password),
            role=role,
            account_scope=account_scope,
        )

        # New users are attributed to every existing location by default - an
        # admin can manually exclude specific ones afterward. Saves having to
        # re-attribute each location by hand on larger installs.
        location_ids = self._all_location_ids()
        if location_ids:
            block = self._get_location_prefs_block(user)
            block['attributed_location_ids'] = location_ids
            user.preferences = self.sanitize_user_preferences(user.preferences)
            user.preferences['location'] = block

        self.users[user.user_id] = user
        self.save_users()
        logger.info(f"Created user {username} (ID: {user.user_id}) with role {role}")
        return user

    def get_user_by_username(self, username):
        """Get user by username"""
        self._reload_users_if_changed()
        for user in self.users.values():
            if user.username == username:
                return user
        return None

    def get_user_by_id(self, user_id):
        """Get user by UUID"""
        self._reload_users_if_changed()
        return self.users.get(user_id)

    def get_user(self, username):
        """Get user by username (for backwards compatibility)"""
        return self.get_user_by_username(username)

    @_serialized_users_write
    def update_user(self, user_id, username=None, password=None, role=None, account_scope=None):
        """Update user username, password, role and/or account scope"""
        self._reload_users_if_changed()
        user = self.get_user_by_id(user_id)
        if not user:
            raise ValueError(f"User with ID {user_id} not found")

        # If changing username, check for conflicts
        if username and username != user.username:
            existing_user = self.get_user_by_username(username)
            if existing_user and existing_user.user_id != user_id:
                raise ValueError(f"Username {username} already taken")
            logger.info(f"Changing username from {user.username} to {username}")
            user.username = username

        if password:
            user.password_hash = generate_password_hash(password)

        if role:
            if role not in [ROLE_ADMIN, ROLE_USER, ROLE_READ_ONLY]:
                raise ValueError(f"Invalid role: {role}")
            user.role = role

        if account_scope:
            if account_scope not in ALLOWED_ACCOUNT_SCOPES:
                raise ValueError(f"Invalid account scope: {account_scope}")
            user.account_scope = account_scope

        self.save_users()
        logger.info(f"Updated user {user.username} (ID: {user_id})")
        return user

    # ------------------------------------------------------------------
    # Two-factor authentication (TOTP) - per-user secret lifecycle
    # ------------------------------------------------------------------

    @_serialized_users_write
    def start_totp_setup(self, user_id):
        """Generate and persist a fresh, unconfirmed TOTP secret for a user.

        Restarting setup always regenerates the secret, so an abandoned enrollment
        never leaves a usable secret behind. The user stays without 2FA until
        confirm_totp_setup() succeeds.

        Raises ValueError when 2FA is already active: regenerating the secret would
        silently turn it off with no re-authentication, bypassing the password check
        disable_totp() requires. An already-enrolled user must disable first.
        """
        self._reload_users_if_changed()
        user = self.get_user_by_id(user_id)
        if not user:
            raise ValueError("User not found")

        if user.totp_enabled:
            raise ValueError("Two-factor authentication is already enabled")

        user.totp_secret = pyotp.random_base32()
        user.totp_enabled = False
        user.totp_confirmed_at = None
        self.save_users()
        logger.info(f"Started 2FA setup for user {user.username} (ID: {user_id})")
        return user

    @_serialized_users_write
    def confirm_totp_setup(self, user_id, code):
        """Activate 2FA for a user once they prove they can generate a valid code."""
        self._reload_users_if_changed()
        user = self.get_user_by_id(user_id)
        if not user:
            raise ValueError("User not found")

        if not user.totp_secret:
            raise ValueError("Two-factor setup has not been started")

        if not user.verify_totp(code):
            raise ValueError("Invalid two-factor code")

        user.totp_enabled = True
        user.totp_confirmed_at = datetime.now(timezone.utc).isoformat()
        self.save_users()
        logger.info(f"2FA confirmed and enabled for user {user.username} (ID: {user_id})")
        return user

    @_serialized_users_write
    def disable_totp(self, user_id, password=None):
        """Clear a user's 2FA state.

        *password* re-authenticates the self-service path. Admin-driven removal
        (a lost authenticator) passes None: admin authority is the check there.
        """
        self._reload_users_if_changed()
        user = self.get_user_by_id(user_id)
        if not user:
            raise ValueError("User not found")

        if password is not None and not user.check_password(password):
            raise ValueError("Current password is incorrect")

        user.totp_secret = None
        user.totp_enabled = False
        user.totp_confirmed_at = None
        self.save_users()
        logger.info(f"2FA disabled for user {user.username} (ID: {user_id})")
        return user

    @_serialized_users_write
    def change_own_password(self, user_id, current_password, new_password):
        """Change password for the authenticated user after verifying current password."""
        self._reload_users_if_changed()

        user = self.get_user_by_id(user_id)
        if not user:
            raise ValueError("User not found")

        if not user.check_password(current_password):
            raise ValueError("Current password is incorrect")

        if len(new_password) < 6:
            raise ValueError("New password must be at least 6 characters")

        if user.check_password(new_password):
            raise ValueError("New password must be different from current password")

        user.password_hash = generate_password_hash(new_password)
        self.save_users()
        logger.info(f"Password changed for user {user.username} (ID: {user_id})")
        return user

    @_serialized_users_write
    def get_user_preferences(self, user_id):
        """Return effective preferences for a given user."""
        self._reload_users_if_changed()
        user = self.get_user_by_id(user_id)
        if not user:
            raise ValueError("User not found")

        effective = self.sanitize_user_preferences(user.preferences)
        if effective != user.preferences:
            user.preferences = effective
            self.save_users()

        return effective.copy()

    @_serialized_users_write
    def update_user_preferences(self, user_id, preferences):
        """Update preferences for a given user with validation."""
        self._reload_users_if_changed()
        user = self.get_user_by_id(user_id)
        if not user:
            raise ValueError("User not found")

        if not isinstance(preferences, dict):
            raise ValueError("Preferences payload must be a dictionary")

        is_valid, error_msg = self.validate_user_preferences(preferences)
        if not is_valid:
            raise ValueError(error_msg)

        current_preferences = self.sanitize_user_preferences(user.preferences)
        current_preferences.update(preferences)

        # Validate merged preferences as well.
        is_valid_merged, merged_error = self.validate_user_preferences(current_preferences)
        if not is_valid_merged:
            raise ValueError(merged_error)

        user.preferences = current_preferences
        self.save_users()

        logger.info(f"Updated preferences for user {user.username} (ID: {user_id})")
        return user.preferences.copy()

    # ------------------------------------------------------------------
    # Multi-location profiles (v1.2) - per-user location preference helpers
    # ------------------------------------------------------------------

    def _get_location_prefs_block(self, user):
        """Return a normalized, mutable copy of a user's location prefs block."""
        import copy as _copy

        block = user.preferences.get('location')
        if not isinstance(block, dict):
            block = {}
        normalized = _copy.deepcopy(DEFAULT_USER_PREFERENCES['location'])
        for key in normalized:
            if key in block:
                normalized[key] = _copy.deepcopy(block[key])
        return normalized

    @_serialized_users_write
    def set_user_location_prefs(self, user_id, **updates):
        """Partially update a user's preferences.location block (validated keys only)."""
        self._reload_users_if_changed()
        user = self.get_user_by_id(user_id)
        if not user:
            raise ValueError("User not found")

        block = self._get_location_prefs_block(user)
        for key, value in updates.items():
            if key not in block:
                raise ValueError(f"Unknown location preference: {key}")
            block[key] = value

        is_valid, error_msg = self.validate_user_preferences({'location': block})
        if not is_valid:
            raise ValueError(error_msg)

        user.preferences = self.sanitize_user_preferences(user.preferences)
        user.preferences['location'] = block
        self.save_users()
        logger.info(f"Updated location preferences for user {user.username} (ID: {user_id})")
        return block

    @_serialized_users_write
    def set_location_attribution(self, location_id, user_ids):
        """Attach *location_id* to exactly the users in *user_ids* (detach from others).

        Admin-controlled many-to-many: a location can be attributed to several
        users and a user can hold several locations.
        """
        self._reload_users_if_changed()
        target_ids = {str(uid) for uid in user_ids}
        changed = False
        for uid, user in self.users.items():
            block = self._get_location_prefs_block(user)
            attributed = list(block['attributed_location_ids'])
            has_it = location_id in attributed
            if uid in target_ids and not has_it:
                attributed.append(location_id)
            elif uid not in target_ids and has_it:
                attributed.remove(location_id)
            else:
                continue
            block['attributed_location_ids'] = attributed
            # Keep order list consistent with attribution
            block['order'] = [lid for lid in block['order'] if lid in attributed]
            user.preferences = self.sanitize_user_preferences(user.preferences)
            user.preferences['location'] = block
            changed = True
        if changed:
            self.save_users()
            logger.info(f"Attribution updated for location {location_id}: {len(target_ids)} user(s)")
        return changed

    @_serialized_users_write
    def cleanup_location_references(self, location_id, fallback_location_id):
        """Eagerly remove a deleted preset from every user's location prefs.

        default/active pointers that referenced the deleted preset are reset to
        the install default (*fallback_location_id*) so users don't silently
        lose a preference without a consistent replacement.
        """
        self._reload_users_if_changed()
        changed = False
        for user in self.users.values():
            block = self._get_location_prefs_block(user)
            touched = False
            if location_id in block['attributed_location_ids']:
                block['attributed_location_ids'] = [
                    lid for lid in block['attributed_location_ids'] if lid != location_id
                ]
                touched = True
            if location_id in block['order']:
                block['order'] = [lid for lid in block['order'] if lid != location_id]
                touched = True
            for pointer in ('default_location_id', 'active_location_id'):
                if block[pointer] == location_id:
                    block[pointer] = fallback_location_id
                    touched = True
            if touched:
                user.preferences = self.sanitize_user_preferences(user.preferences)
                user.preferences['location'] = block
                changed = True
        if changed:
            self.save_users()
            logger.info(f"Cleaned location {location_id} references from user preferences")
        return changed

    @_serialized_users_write
    def reset_active_location_on_login(self, user_id):
        """On fresh login, reset active_location_id to default_location_id.

        This is the mechanism behind "the default location is what's shown when
        the user connects": a mid-session switch never outlives the session.
        """
        user = self.get_user_by_id(user_id)
        if not user:
            return
        block = self._get_location_prefs_block(user)
        if block['default_location_id'] and block['active_location_id'] != block['default_location_id']:
            block['active_location_id'] = block['default_location_id']
            user.preferences = self.sanitize_user_preferences(user.preferences)
            user.preferences['location'] = block
            self.save_users()
            logger.debug(f"Reset active location to default for user {user.username}")

    @_serialized_users_write
    def delete_user(self, user_id, current_user_id=None):
        """Delete a user and safely clean related astrodex data"""

        self._reload_users_if_changed()

        user_id = str(user_id)

        user = self.get_user_by_id(user_id)
        if not user:
            raise ValueError(f"User with ID {user_id} not found")

        # Prevent deleting your own account
        if current_user_id and str(current_user_id) == user_id:
            raise ValueError("Cannot delete your own account")

        username = user.username

        # Remove user from memory + persist
        del self.users[user_id]
        self.save_users()

        logger.info(f"Deleted user {username} (ID: {user_id})")

        # --- Cleanup astrodex files safely ---
        try:
            from observation.astrodex import ASTRODEX_DIR, ASTRODEX_IMAGES_DIR

            base_astrodex_dir = os.path.realpath(ASTRODEX_DIR)
            base_images_dir = os.path.realpath(ASTRODEX_IMAGES_DIR)

            astrodex_file = os.path.realpath(os.path.join(base_astrodex_dir, f"{user_id}_astrodex.json"))

            # Ensure confinement
            if not astrodex_file.startswith(base_astrodex_dir + os.sep):
                raise ValueError("Invalid astrodex file path")

            image_filenames = set()

            # Read astrodex file safely
            if os.path.exists(astrodex_file):
                try:
                    with open(astrodex_file, "r", encoding="utf-8") as f:
                        astrodex_data = json.load(f)

                    for item in astrodex_data.get("items", []):
                        for picture in item.get("pictures", []):
                            filename = picture.get("filename")
                            if filename and re.match(r"^[a-zA-Z0-9_.-]+$", filename):
                                image_filenames.add(filename)

                except Exception as read_error:
                    logger.warning(f"Failed to read astrodex file for cleanup: {read_error}")

            # Delete referenced images safely
            for filename in image_filenames:
                file_path = os.path.realpath(os.path.join(base_images_dir, filename))

                if not file_path.startswith(base_images_dir + os.sep):
                    continue

                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except Exception as remove_error:
                        logger.warning(f"Failed to delete astrodex image {filename}: {remove_error}")

            # Delete remaining images matching user_id prefix
            if os.path.exists(base_images_dir):
                for filename in os.listdir(base_images_dir):
                    if filename.startswith(f"{user_id}_") and re.match(r"^[a-zA-Z0-9_.-]+$", filename):
                        file_path = os.path.realpath(os.path.join(base_images_dir, filename))

                        if not file_path.startswith(base_images_dir + os.sep):
                            continue

                        try:
                            os.remove(file_path)
                        except Exception as remove_error:
                            logger.warning(f"Failed to delete astrodex image {filename}: {remove_error}")

            # Delete astrodex file itself
            if os.path.exists(astrodex_file):
                os.remove(astrodex_file)
                logger.info(f"Deleted astrodex file for {username}")

        except Exception as e:
            logger.warning(f"Failed to delete astrodex data for user {user_id}: {e}")

    def list_users(self):
        """List all users (without password hashes)"""
        self._reload_users_if_changed()
        return [
            {
                'user_id': user.user_id,
                'username': user.username,
                'role': user.role,
                'created_at': user.created_at,
                'last_login': user.last_login,
                'account_scope': user.account_scope,
                'totp_enabled': user.totp_enabled,
            }
            for user in self.users.values()
        ]

    @staticmethod
    def _stamp_last_login(user):
        user.last_login = datetime.now(timezone.utc).isoformat()
        return user

    def authenticate(self, username, password):
        """Authenticate user"""
        self._reload_users_if_changed()
        user = self.get_user_by_username(username)
        if user and user.check_password(password):
            # Update last login on the freshest copy; password hashing above stays outside the write lock
            user = self.modify_user(user.user_id, self._stamp_last_login) or user
            logger.info(f"Successful authentication for user {username}")
            return user
        # Log failure without revealing if username exists
        logger.warning(f"Failed authentication attempt for username: {username}")
        return None


# Global user manager instance
user_manager = UserManager()


# Authentication decorators
# Is read-only role, can only access GET endpoints (enforced in route handlers)
def login_required(f):
    """Decorator to require authentication"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            # Log failed authentication attempt via cookie
            client_ip = request.remote_addr
            logger.warning(f"Unauthorized access attempt to {request.path} from {client_ip} (no valid session cookie)")
            return jsonify({'error': 'Authentication required'}), 401
        return f(*args, **kwargs)

    return decorated_function


# If user role is user, can access non-admin endpoints (enforced in route handlers)
def user_required(f):
    """Decorator to require user or admin role"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            client_ip = request.remote_addr
            logger.warning(f"Unauthorized access attempt to {request.path} from {client_ip} (no valid session cookie)")
            return jsonify({'error': 'Authentication required'}), 401

        user = user_manager.get_user(session['username'])
        if not user or not (user.is_admin() or user.is_user()):
            client_ip = request.remote_addr
            logger.warning(
                f"User {session.get('username')} from {client_ip} attempted to access"
                f" {request.path} without sufficient permissions"
            )
            return jsonify({'error': 'User access required'}), 403

        return f(*args, **kwargs)

    return decorated_function


# Only admin role can access
def admin_required(f):
    """Decorator to require admin role"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            client_ip = request.remote_addr
            logger.warning(f"Unauthorized access attempt to {request.path} from {client_ip} (no valid session cookie)")
            return jsonify({'error': 'Authentication required'}), 401

        user = user_manager.get_user(session['username'])
        if not user or not user.is_admin():
            client_ip = request.remote_addr
            logger.warning(
                f"Non-admin user {session.get('username')} from {client_ip} attempted to access {request.path}"
            )
            return jsonify({'error': 'Admin access required'}), 403

        return f(*args, **kwargs)

    return decorated_function


def get_current_user():
    """Get current logged-in user"""
    if 'username' in session:
        return user_manager.get_user(session['username'])
    return None


def is_user_admin():
    """Check if current user is admin"""
    user = get_current_user()
    return user and user.is_admin()
