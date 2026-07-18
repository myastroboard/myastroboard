"""Authentication + user management Blueprint.

Routes: /api/auth/*, /api/users/*
"""

from flask import Blueprint, request, jsonify, session

from utils.auth import user_manager, login_required, admin_required, get_current_user
from utils.logging_config import get_logger

logger = get_logger(__name__)

auth_bp = Blueprint('auth', __name__)


# ============================================================
# Authentication API
# ============================================================


@auth_bp.route('/api/auth/login', methods=['POST'])
def login():
    """Login endpoint"""
    try:
        data = request.json
        username = data.get('username')
        password = data.get('password')
        remember_me = data.get('remember_me', False)

        if not username or not password:
            logger.warning("Login attempt with missing credentials")
            return (
                jsonify({'error': 'Username and password required', 'error_key': 'auth.enter_username_password'}),
                400,
            )

        user = user_manager.authenticate(username, password)
        if user:
            # Set session to permanent BEFORE setting session data
            # This ensures the cookie is created with the correct expiration
            session.permanent = remember_me

            session['user_id'] = user.user_id
            session['username'] = user.username
            session['role'] = user.role

            # Fresh login: the user's default location becomes the active one
            # (a mid-session switch from a previous session never survives login)
            try:
                user_manager.reset_active_location_on_login(user.user_id)
            except Exception as loc_reset_error:
                logger.warning(f"Could not reset active location on login: {loc_reset_error}")

            # Check if using default password
            using_default_password = user.is_using_default_password()

            # Log successful login with remember_me status
            logger.info(
                f"Successful login for user {username} "
                + f"(remember_me: {remember_me}, permanent_session: {session.permanent})"
            )

            return jsonify(
                {
                    'status': 'success',
                    'user_id': user.user_id,
                    'username': user.username,
                    'role': user.role,
                    'using_default_password': using_default_password,
                }
            )
        else:
            logger.warning(f"Failed login attempt for username: {username}")
            return jsonify({'error': 'Invalid credentials', 'error_key': 'auth.invalid_credentials'}), 401
    except Exception as e:
        logger.error(f"Login error: {e}")
        return jsonify({'error': 'Internal server error', 'error_key': 'auth.internal_server_error'}), 500


@auth_bp.route('/api/auth/logout', methods=['POST'])
@login_required
def logout():
    """Logout endpoint"""
    username = session.get('username')
    was_permanent = session.permanent
    session.clear()

    logger.info(f"User {username} logged out (was_permanent: {was_permanent})")

    # session.clear() handles cookie removal properly
    return jsonify({'status': 'success'})


@auth_bp.route('/api/auth/status', methods=['GET'])
def auth_status():
    """Get authentication status"""
    if 'username' in session:
        user = get_current_user()
        if user:
            return jsonify(
                {
                    'authenticated': True,
                    'user_id': user.user_id,
                    'username': user.username,
                    'role': user.role,
                    'using_default_password': user.is_using_default_password(),
                }
            )
    return jsonify({'authenticated': False})


@auth_bp.route('/api/auth/change-password', methods=['POST'])
@login_required
def change_own_password():
    """Change password for currently authenticated user only."""
    try:
        data = request.json or {}
        current_password = data.get('current_password')
        new_password = data.get('new_password')

        if not current_password or not new_password:
            return (
                jsonify(
                    {
                        'error': 'Current password and new password are required',
                        'error_key': 'users.password_change_missing_fields',
                    }
                ),
                400,
            )

        current_user = get_current_user()
        if not current_user:  # pragma: no cover
            return jsonify({'error': 'Authentication required', 'error_key': 'auth.authentication_required'}), 401

        user_manager.change_own_password(current_user.user_id, current_password, new_password)

        return jsonify({'status': 'success'})
    except ValueError as e:
        error_text = str(e)
        error_key = 'users.error_update_password'

        if error_text == 'Current password is incorrect':
            error_key = 'users.current_password_incorrect'
        elif error_text == 'New password must be at least 6 characters':
            error_key = 'users.password_too_short'
        elif error_text == 'New password must be different from current password':
            error_key = 'users.password_must_be_different'

        logger.warning(f"Password change rejected for user {session.get('username')}: {e}")
        return jsonify({'error': 'Invalid request', 'error_key': error_key}), 400
    except Exception as e:
        logger.error(f"Error changing password for user {session.get('username')}: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@auth_bp.route('/api/auth/preferences', methods=['GET'])
@login_required
def get_own_preferences():
    """Get UI customization preferences for the currently authenticated user."""
    try:
        current_user = get_current_user()
        if not current_user:  # pragma: no cover
            return jsonify({'error': 'Authentication required', 'error_key': 'auth.authentication_required'}), 401

        preferences = user_manager.get_user_preferences(current_user.user_id)
        return jsonify({'preferences': preferences})
    except ValueError as e:
        logger.warning(f"Preference fetch rejected for user {session.get('username')}: {e}")
        return jsonify({'error': 'Invalid request', 'error_key': 'settings.pref_save_error'}), 400
    except Exception as e:
        logger.error(f"Error reading preferences for user {session.get('username')}: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@auth_bp.route('/api/auth/preferences', methods=['PUT'])
@login_required
def update_own_preferences():
    """Update UI customization preferences for the currently authenticated user."""
    try:
        current_user = get_current_user()
        if not current_user:  # pragma: no cover
            return jsonify({'error': 'Authentication required', 'error_key': 'auth.authentication_required'}), 401

        data = request.json or {}
        preferences = data.get('preferences')
        if preferences is None:
            return jsonify({'error': 'Preferences are required', 'error_key': 'settings.pref_save_error'}), 400

        updated = user_manager.update_user_preferences(current_user.user_id, preferences)
        return jsonify({'status': 'success', 'preferences': updated})
    except ValueError as e:
        error_text = str(e)
        error_key = 'settings.pref_save_error'

        if error_text.startswith('Invalid startup_main_tab'):
            error_key = 'settings.pref_invalid_startup_main_tab'
        elif error_text.startswith('Invalid startup_subtab'):
            error_key = 'settings.pref_invalid_startup_subtab'
        elif error_text.startswith('Invalid time_format'):
            error_key = 'settings.pref_invalid_time_format'
        elif error_text.startswith('Invalid density'):
            error_key = 'settings.pref_invalid_density'
        elif error_text.startswith('Invalid theme_mode'):
            error_key = 'settings.pref_invalid_theme'
        elif error_text.startswith('Invalid experience_level'):
            error_key = 'settings.pref_invalid_experience_level'
        elif error_text.startswith('Invalid wizard'):
            error_key = 'settings.pref_invalid_wizard'

        logger.warning(f"Preference update rejected for user {session.get('username')}: {e}")
        return jsonify({'error': 'Invalid request', 'error_key': error_key}), 400
    except Exception as e:
        logger.error(f"Error updating preferences for user {session.get('username')}: {e}")
        return jsonify({'error': 'Internal server error'}), 500


# ============================================================
# User Management API (Admin only)
# ============================================================


@auth_bp.route('/api/users', methods=['GET'])
@admin_required
def list_users():
    """List all users (admin only)"""
    users = user_manager.list_users()
    return jsonify(users)


@auth_bp.route('/api/users', methods=['POST'])
@admin_required
def create_user():
    """Create a new user (admin only)"""
    try:
        data = request.json
        username = data.get('username')
        password = data.get('password')
        role = data.get('role')

        if not username or not password or not role:
            return (
                jsonify(
                    {
                        'error': 'Username, password, and role required',
                        'error_key': 'users.required_username_password_role',
                    }
                ),
                400,
            )

        user = user_manager.create_user(username, password, role)
        return jsonify(
            {'status': 'success', 'user': {'username': user.username, 'role': user.role, 'created_at': user.created_at}}
        )
    except ValueError as e:
        error_text = str(e)
        error_key = 'users.invalid_input'

        if error_text.startswith('User ') and error_text.endswith('already exists'):
            error_key = 'users.username_already_exists'
        elif error_text.startswith('Invalid role'):
            error_key = 'users.invalid_role'

        logger.warning(f"User creation failed: {e}")
        return jsonify({'error': 'Invalid request', 'error_key': error_key}), 400
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@auth_bp.route('/api/users/<user_id>', methods=['PUT'])
@admin_required
def update_user(user_id):
    """Update a user (admin only)"""
    try:
        data = request.json
        username = data.get('username')
        password = data.get('password')
        role = data.get('role')

        if not username and not password and not role:
            return (
                jsonify({'error': 'Username, password or role required', 'error_key': 'users.required_update_payload'}),
                400,
            )

        logger.info(f"Updating user {user_id}, available users: {list(user_manager.users.keys())}")
        user = user_manager.update_user(user_id, username, password, role)
        return jsonify(
            {'status': 'success', 'user': {'user_id': user.user_id, 'username': user.username, 'role': user.role}}
        )
    except ValueError as e:
        error_text = str(e)
        error_key = 'users.invalid_input'

        if error_text.startswith('User with ID ') and error_text.endswith(' not found'):
            error_key = 'users.user_not_found'
        elif error_text.startswith('Username ') and error_text.endswith(' already taken'):
            error_key = 'users.username_already_taken'
        elif error_text.startswith('Invalid role'):
            error_key = 'users.invalid_role'

        logger.warning(f"User update failed for user_id {user_id}: {e}")
        return jsonify({'error': 'Invalid request', 'error_key': error_key}), 400
    except Exception as e:
        logger.error(f"Error updating user: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@auth_bp.route('/api/users/<user_id>', methods=['DELETE'])
@admin_required
def delete_user(user_id):
    """Delete a user (admin only)"""
    try:
        current_user_id = session.get('user_id')
        user_manager.delete_user(user_id, current_user_id)
        return jsonify({'status': 'success'})
    except ValueError as e:
        error_text = str(e)
        error_key = 'users.invalid_input'

        if error_text.startswith('User with ID ') and error_text.endswith(' not found'):
            error_key = 'users.user_not_found'
        elif error_text == 'Cannot delete your own account':
            error_key = 'users.cannot_delete_own_account'

        logger.warning(f"User deletion failed for user_id {user_id}: {e}")
        return jsonify({'error': 'Invalid request', 'error_key': error_key}), 400
    except Exception as e:
        logger.error(f"Error deleting user: {e}")
        return jsonify({'error': 'Internal server error'}), 500
