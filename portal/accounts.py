"""Django accounts stored alongside the portal's local settings."""
import hashlib
from pathlib import Path

from django.core.management import call_command
from django.db import connections, transaction
from django.contrib.auth.models import User
from django.contrib.auth.hashers import check_password
from werkzeug.security import check_password_hash


def initialize_accounts(database, admin_hash=None, commercial_hash=None):
    alias = 'portal_' + hashlib.sha256(str(Path(database).resolve()).encode()).hexdigest()[:16]
    if alias not in connections.databases:
        connections.databases[alias] = {**connections.databases['default'], 'NAME': str(database)}
    call_command('migrate', database=alias, interactive=False, verbosity=0)
    # Seed only an empty account table. Restarting never resets credentials.
    with transaction.atomic(using=alias):
        if not User.objects.using(alias).exists():
            call_command('loaddata', str(Path(__file__).parent / 'fixtures' / 'initial_users.json'), database=alias, verbosity=0)
            for username, encoded in [('admin', admin_hash), ('comercial', commercial_hash)]:
                if encoded:
                    User.objects.using(alias).filter(username=username).update(password=encoded)
    return alias


def role_for(user, alias):
    if not user or not user.is_active:
        return None
    groups = set(user.groups.using(alias).values_list('name', flat=True))
    return 'admin' if 'Admin' in groups else 'comercial' if 'Comercial' in groups else None


def verify_password(user, password):
    if user.password.startswith(('scrypt:', 'pbkdf2:')):
        return check_password_hash(user.password, password)
    return check_password(password, user.password)
