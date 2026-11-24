"""Portal configuration and one-time import of legacy environment settings."""
from contextlib import closing
import json
import os
from pathlib import Path
import tempfile
import uuid

from libraries.core.arby_ambient import DEFAULT_DATABASE
from libraries.core.arby_config import FIELDS, parse_config

PROJECT_ENVIRONMENT = Path(__file__).resolve().parents[2] / '.env'
EXTRA_FIELDS = {'GEMINI_API_KEY': True, 'GOOGLE_API_KEY': True,
                'GEMINI_FALLBACK_MODELS': False, 'ARBY_SUPPORT': False,
                'ARBY_LOG_LEVEL': False, 'ARBY_LOG_FILE': False}
EXTRA_DEFAULTS = {'GEMINI_API_KEY': '', 'GOOGLE_API_KEY': '',
                  'GEMINI_FALLBACK_MODELS': 'gemini-flash-lite-latest',
                  'ARBY_SUPPORT': 'true', 'ARBY_LOG_LEVEL': 'INFO', 'ARBY_LOG_FILE': ''}
LOG_LEVELS = ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL', 'OFF')


def variable_for(key):
    return 'GEMINI_MODEL' if key == 'model' else f'ARBY_{key.upper()}'


def environment_file(database=DEFAULT_DATABASE):
    return Path(database).parent / 'portal_environment.json'


def load_extra(database=DEFAULT_DATABASE):
    target = environment_file(database)
    if not target.exists():
        return {}
    values = json.loads(target.read_text())
    if (not isinstance(values, dict) or set(values) - EXTRA_FIELDS.keys()
            or any(not isinstance(value, str) for value in values.values())):
        raise ValueError('Configuración avanzada no válida.')
    return values


def write_extra(values, database=DEFAULT_DATABASE):
    target = environment_file(database)
    fd, name = tempfile.mkstemp(prefix='.portal-environment-', dir=target.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(values, stream)
            stream.flush()
            os.fsync(stream.fileno())
        # The runtime runs as root; the portal must still own its private file.
        if os.geteuid() == 0:
            import pwd
            try:
                account = pwd.getpwnam('arby-portal')
            except KeyError:
                pass
            else:
                os.chown(name, account.pw_uid, account.pw_gid)
        os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_legacy_environment(path=PROJECT_ENVIRONMENT, system=None):
    from dotenv import dotenv_values
    import io
    try:
        with Path(path).open(encoding='utf-8') as stream:
            content = stream.read(65537)
        found = True
    except FileNotFoundError:
        return {}, {'available': True, 'found': False, 'error': None}
    except PermissionError:
        if system is None:
            raise ValueError('No se pudo leer .env para migrar la configuración.') from None
        result = system('environment')
        content, found = result['content'], result['found']
    if not isinstance(content, str) or len(content) > 65536:
        raise ValueError('El archivo .env no es válido o supera 64 KB.')
    return dotenv_values(stream=io.StringIO(content), interpolate=False), {
        'available': True, 'found': found, 'error': None}


def ensure_configuration(database=DEFAULT_DATABASE, environment_path=PROJECT_ENVIRONMENT,
                         system=None, process_environment=None):
    """Import once, preserving portal edits. Never read .env after the marker commits."""
    from libraries.core.arby_support import initialize, connect, validate_controls
    initialize(database)
    with closing(connect(database)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS portal_configuration (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)')
        row = db.execute('SELECT value FROM portal_configuration WHERE id=1').fetchone()
        if row:
            return json.loads(row['value'])
    environment, status = read_legacy_environment(environment_path, system)
    environment = {**environment, **(process_environment or {})}
    # Serialize migration with portal saves and other startup processes.
    with closing(connect(database)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT value FROM portal_configuration WHERE id=1').fetchone()
        if row:
            return json.loads(row['value'])
        row = db.execute('SELECT value FROM support_settings WHERE id=1').fetchone()
        existing = json.loads(row['value']) if row else {}
        parsed = parse_config(existing, {key: value for key, value in environment.items() if value is not None})
        controls = {key: getattr(parsed, key) for key in FIELDS if variable_for(key) in environment}
        controls.update(existing)
        validate_controls(controls)
        extra = {key: environment[key] for key in EXTRA_FIELDS if environment.get(key) is not None}
        saved_extra = load_extra(database)
        extra.update(saved_extra)
        if 'ARBY_LOG_LEVEL' in extra:
            extra['ARBY_LOG_LEVEL'] = extra['ARBY_LOG_LEVEL'].strip().upper()
        if extra.get('ARBY_LOG_LEVEL', 'INFO') not in LOG_LEVELS:
            raise ValueError('Nivel de logging inválido; usa DEBUG, INFO, WARNING, ERROR, CRITICAL u OFF.')
        if extra:
            write_extra(extra, database)
        result = {'managed_by': 'portal', 'imported_environment': status['found']}
        db.execute('INSERT OR REPLACE INTO support_settings VALUES(1, ?)', (json.dumps(controls),))
        if controls != existing or extra != saved_extra:
            db.execute('INSERT OR REPLACE INTO support_configuration_revision VALUES(1, ?)', (uuid.uuid4().hex,))
        db.execute('INSERT INTO portal_configuration VALUES(1, ?)', (json.dumps(result),))
    return result
