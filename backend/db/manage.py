"""Operator command line for the database - recovery tasks that used to mean editing users.json.

Run inside the container, as the application user:

    docker exec -u appuser myastroboard python backend/db/manage.py status
    docker exec -u appuser myastroboard python backend/db/manage.py list-users
    docker exec -u appuser myastroboard python backend/db/manage.py reset-password admin
    docker exec -u appuser myastroboard python backend/db/manage.py disable-2fa admin

``reset-password`` prints a generated password unless ``--password`` is given.
"""

import argparse
import os
import secrets
import sys
from typing import List, Optional

_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _BACKEND_DIR not in sys.path:  # pragma: no cover - only when started as a script
    sys.path.insert(0, _BACKEND_DIR)


def _out(text: str) -> None:
    """Command output for the operator's terminal (this is a CLI, not application logging)."""
    sys.stdout.write(f'{text}\n')


def _ready() -> None:
    """Bring the schema (and any pending legacy import) up to date, like the app does at start."""
    from db import bootstrap

    if not bootstrap.ensure_database_ready():
        raise SystemExit(f'The database is in maintenance mode: {bootstrap.maintenance_reason()}')


def _find_user(username: str):
    from utils.auth import user_manager

    user = user_manager.get_user_by_username(username)
    if user is None:
        raise SystemExit(f'No account named {username!r}')
    return user_manager, user


def cmd_status(_args) -> int:
    from sqlalchemy import func, select

    from db import migrate, schema
    from db.engine import database_path, read

    _out(f'Database: {database_path()}')
    _out(f'Schema revision: {migrate.current_revision()} (application expects {migrate.head_revision()})')
    with read() as conn:
        users = conn.execute(select(func.count()).select_from(schema.users)).scalar_one()
        docs = conn.execute(select(func.count()).select_from(schema.user_documents)).scalar_one()
        imports = conn.execute(
            select(schema.legacy_import.c.status, func.count()).group_by(schema.legacy_import.c.status)
        ).all()
    _out(f'Accounts: {users}, per-user documents: {docs}')
    if imports:
        _out('Legacy JSON import: ' + ', '.join(f'{count} {status}' for status, count in imports))
    return 0


def cmd_list_users(_args) -> int:
    from utils.auth import user_manager

    for user in sorted(user_manager.list_users(), key=lambda entry: entry['username']):
        two_factor = '2FA' if user['totp_enabled'] else '   '
        _out(f"{user['username']:<24} {user['role']:<10} {two_factor} last login: {user['last_login'] or '-'}")
    return 0


def cmd_reset_password(args) -> int:
    manager, user = _find_user(args.username)
    password = args.password or secrets.token_urlsafe(12)
    if len(password) < 6:
        raise SystemExit('The password must be at least 6 characters')
    manager.update_user(user.user_id, password=password)
    if args.password:
        _out(f'Password of {user.username} changed.')
    else:
        _out(f'New password of {user.username}: {password}')
    return 0


def cmd_disable_2fa(args) -> int:
    manager, user = _find_user(args.username)
    manager.disable_totp(user.user_id)
    _out(f'Two-factor authentication disabled for {user.username}.')
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='manage.py', description='MyAstroBoard database maintenance')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status', help='schema revision, counts, legacy import state').set_defaults(func=cmd_status)
    commands.add_parser('list-users', help='list the accounts').set_defaults(func=cmd_list_users)
    reset = commands.add_parser('reset-password', help="set an account's password (generated when omitted)")
    reset.add_argument('username')
    reset.add_argument('--password', help='the new password (at least 6 characters)')
    reset.set_defaults(func=cmd_reset_password)
    disable = commands.add_parser('disable-2fa', help='turn two-factor authentication off for an account')
    disable.add_argument('username')
    disable.set_defaults(func=cmd_disable_2fa)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    _ready()
    return args.func(args)


if __name__ == '__main__':  # pragma: no cover
    sys.exit(main())
