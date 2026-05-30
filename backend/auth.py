"""
Authentication and User Management Module
Handles user authentication, authorization, and session management
"""
import json
import os
import uuid
import re
import shutil
from datetime import datetime
from functools import wraps
from flask import session, jsonify, request
from werkzeug.security import generate_password_hash, check_password_hash
from logging_config import get_logger

logger = get_logger(__name__)

# User roles
ROLE_ADMIN = 'admin'
ROLE_USER = 'user'
ROLE_READ_ONLY = 'read-only'

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
    'parameters'
}
ALLOWED_STARTUP_SUBTABS = {
    'astro-weather', 'window', 'moon', 'sun', 'aurora', 'calendar',
    'weather', 'seeing', 'trend',
    'launches', 'astronauts', 'space-events', 'iss',
    'astrodex', 'plan-my-night',
    'combinations', 'fov', 'telescopes', 'cameras', 'mounts', 'filters', 'accessories',
    'customize', 'security',
    'configuration', 'advanced', 'logs', 'users', 'metrics'
}
ALLOWED_TIME_FORMATS = {'auto', '12h', '24h'}
ALLOWED_DENSITY_MODES = {'comfortable', 'compact'}
ALLOWED_THEME_MODES = {'auto', 'light', 'dark', 'red'}
ALLOWED_FIRST_DAY_OF_WEEK = {'monday', 'sunday'}

DEFAULT_USER_PREFERENCES = {
    'startup_main_tab': 'forecast-astro',
    'startup_subtab': 'astro-weather',
    'time_format': 'auto',
    'density': 'comfortable',
    'theme_mode': 'auto',
    'first_day_of_week': 'monday',
    'notifications': {
        'enabled': True,
        'permission_asked': False,
        'triggers': {
            'N1': {'enabled': True, 'lead_minutes': 15},
            'N2': {'enabled': True, 'lead_minutes': 5},
            'N3': {'enabled': True, 'lead_minutes': 10},
            'N4': {'enabled': True, 'lead_minutes': 30},
            'N5': {'enabled': True, 'lead_minutes': 30},
            'N6': {'enabled': True, 'lead_minutes': 20},
            'N7': {'enabled': True, 'kp_threshold': 5},
        }
    }
}

# Users storage file
USERS_FILE = os.path.join(os.environ.get('DATA_DIR', '/app/data'), 'users.json')


class User:
    """User model"""
    def __init__(self, username, password_hash, role, user_id=None, created_at=None, last_login=None, preferences=None, push_subscriptions=None):
        self.user_id = user_id or str(uuid.uuid4())
        self.username = username
        self.password_hash = password_hash
        self.role = role
        self.created_at = created_at or datetime.now().isoformat()
        self.last_login = last_login
        self.preferences = preferences.copy() if isinstance(preferences, dict) else DEFAULT_USER_PREFERENCES.copy()
        self.push_subscriptions = push_subscriptions if isinstance(push_subscriptions, list) else []

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
        }
    
    @staticmethod
    def from_dict(data):
        """Create user from dictionary"""
        return User(
            user_id=data.get('user_id'),
            username=data['username'],
            password_hash=data['password_hash'],
            role=data['role'],
            created_at=data.get('created_at'),
            last_login=data.get('last_login'),
            preferences=data.get('preferences'),
            push_subscriptions=data.get('push_subscriptions'),
        )
    
    def check_password(self, password):
        """Check if password matches"""
        return check_password_hash(self.password_hash, password)
    
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


class UserManager:
    """Manages user storage and operations"""
    
    def __init__(self):
        self.users = {}
        self._users_mtime = None
        self.load_users()
    
    def load_users(self):
        """Load users from file"""
        if os.path.exists(USERS_FILE):
            try:
                with open(USERS_FILE, 'r') as f:
                    data = json.load(f)
                    is_valid, error_msg = self.validate_users_json_data(data)
                    if not is_valid:
                        raise ValueError(f"Invalid users data: {error_msg}")
                    self.users = {
                        key: User.from_dict(user_data)
                        for key, user_data in data.items()
                    }
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
    
    def save_users(self):
        """Save users to file using atomic write and JSON validation."""
        temp_path = USERS_FILE + '.tmp'
        backup_path = USERS_FILE + '.backup'
        backup_created = False

        try:
            # Ensure data directory exists
            os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)

            data = {
                user_id: user.to_dict()
                for user_id, user in self.users.items()
            }

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

        # Unknown keys are silently ignored — forward-compat when new prefs are added
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
        if notifications is not None and not isinstance(notifications, dict):
            return False, "Invalid notifications: must be a dictionary"

        first_day_of_week = preferences.get('first_day_of_week')
        if first_day_of_week is not None and first_day_of_week not in ALLOWED_FIRST_DAY_OF_WEEK:
            return False, f"Invalid first_day_of_week: {first_day_of_week}"

        return True, ""

    @staticmethod
    def sanitize_user_preferences(preferences):
        """Merge a partial preferences payload into defaults."""
        merged = DEFAULT_USER_PREFERENCES.copy()
        if isinstance(preferences, dict):
            for key, value in preferences.items():
                if key in merged:
                    merged[key] = value
        return merged
    
    def ensure_default_admin(self):
        """Ensure default admin user exists"""
        # Check by username, not by key
        if not self.get_user_by_username(DEFAULT_ADMIN_USERNAME):
            logger.info("Creating default admin user")
            self.create_user(
                DEFAULT_ADMIN_USERNAME,
                DEFAULT_ADMIN_PASSWORD,
                ROLE_ADMIN
            )
    
    def create_user(self, username, password, role):
        """Create a new user"""
        self._reload_users_if_changed()

        if self.get_user_by_username(username):
            raise ValueError(f"User {username} already exists")
        
        if role not in [ROLE_ADMIN, ROLE_USER, ROLE_READ_ONLY]:
            raise ValueError(f"Invalid role: {role}")
        
        user = User(
            username=username,
            password_hash=generate_password_hash(password),
            role=role
        )
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
    
    def update_user(self, user_id, username=None, password=None, role=None):
        """Update user username, password and/or role"""
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
        
        self.save_users()
        logger.info(f"Updated user {user.username} (ID: {user_id})")
        return user

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
            from astrodex import ASTRODEX_DIR, ASTRODEX_IMAGES_DIR

            base_astrodex_dir = os.path.abspath(ASTRODEX_DIR)
            base_images_dir = os.path.abspath(ASTRODEX_IMAGES_DIR)

            astrodex_file = os.path.normpath(
                os.path.join(base_astrodex_dir, f"{user_id}_astrodex.json")
            )

            # Ensure confinement
            if not astrodex_file.startswith(base_astrodex_dir):
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
                file_path = os.path.normpath(
                    os.path.join(base_images_dir, filename)
                )

                if not file_path.startswith(base_images_dir):
                    continue

                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except Exception as remove_error:
                        logger.warning(
                            f"Failed to delete astrodex image {filename}: {remove_error}"
                        )

            # Delete remaining images matching user_id prefix
            if os.path.exists(base_images_dir):
                for filename in os.listdir(base_images_dir):
                    if filename.startswith(f"{user_id}_") and re.match(
                        r"^[a-zA-Z0-9_.-]+$", filename
                    ):
                        file_path = os.path.normpath(
                            os.path.join(base_images_dir, filename)
                        )

                        if file_path.startswith(base_images_dir):
                            try:
                                os.remove(file_path)
                            except Exception as remove_error:
                                logger.warning(
                                    f"Failed to delete astrodex image {filename}: {remove_error}"
                                )

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
                'last_login': user.last_login
            }
            for user in self.users.values()
        ]
    
    def authenticate(self, username, password):
        """Authenticate user"""
        self._reload_users_if_changed()
        user = self.get_user_by_username(username)
        if user and user.check_password(password):
            # Update last login
            user.last_login = datetime.now().isoformat()
            self.save_users()
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
            logger.warning(f"User {session.get('username')} from {client_ip} attempted to access {request.path} without sufficient permissions")
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
            logger.warning(f"Non-admin user {session.get('username')} from {client_ip} attempted to access {request.path}")
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