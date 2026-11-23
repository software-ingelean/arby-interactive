"""Administrator settings editor for the portal."""
from contextlib import closing
import json
import io
import math
from pathlib import Path

from dotenv import dotenv_values
import os
import tempfile
import uuid

from libraries.core.arby_config import FIELDS, parse_config
from libraries.core.arby_configuration import EXTRA_FIELDS, environment_file, load_extra
from libraries.core.arby_support import connect, load_overrides, runtime_status, validate_controls


PROJECT_ENVIRONMENT = Path(__file__).resolve().parents[1] / '.env'
CATEGORIES = [
    {'id': 'matrix', 'label': 'Matriz LED y ojos',
     'description': 'Salida visual, brillo, colores y configuración de los paneles.'},
    {'id': 'strip', 'label': 'Tira LED',
     'description': 'Activación, conexión, número de LED y efectos.'},
    {'id': 'microphone', 'label': 'Micrófono y reconocimiento',
     'description': 'Dispositivo, canal, filtros, sensibilidad y tiempos de captura.'},
    {'id': 'audio', 'label': 'Voz y salida de audio',
     'description': 'Voz, velocidad, tono, reproducción y recuperación del audio.'},
    {'id': 'input', 'label': 'Sensores y push to talk',
     'description': 'Entrada de Arby, sensores Trill y preferencia del botón físico.'},
    {'id': 'bot', 'label': 'Modelos e IA',
     'description': 'Modelos, respuestas, tiempos de espera y claves del proveedor.'},
    {'id': 'portal', 'label': 'Portal y soporte',
     'description': 'Publicación de estado y comunicación con el portal.'},
]


def category_for(key):
    if key == 'eyes' or key == 'swap_eyes' or key.startswith('matrix_') or key in ('multiplexing', 'row_address_type', 'slowdown'):
        return 'matrix'
    if key == 'strip' or key.startswith('strip_'):
        return 'strip'
    if key == 'microphone_enabled' or key.startswith('mic_'):
        return 'microphone'
    if key in ('input_mode', 'trill', 'push_to_talk'):
        return 'input'
    if key == 'ARBY_SUPPORT':
        return 'portal'
    if key in ('model', 'model_cooldown_seconds', 'bot_timeout', 'demo') or key.startswith(('GEMINI_', 'GOOGLE_')):
        return 'bot'
    return 'audio'


def read_environment(environment_path, system=None):
    """Read the installed file without changing filesystem permissions or returning secrets."""
    try:
        with Path(environment_path).open(encoding='utf-8') as stream:
            content = stream.read(65537)
        found = True
    except FileNotFoundError:
        return {}, {'available': True, 'found': False, 'error': None}
    except PermissionError:
        # The privileged helper chooses the path from the fixed arby.service unit.
        if system is None:
            return {}, {'available': False, 'found': None, 'error': 'No se pudo leer .env.'}
        try:
            result = system('environment')
            content, found = result['content'], result['found']
        except (OSError, ValueError, KeyError, TypeError):
            return {}, {'available': False, 'found': None,
                        'error': 'No se pudo leer .env. Actualiza el ayudante del portal y comprueba arby.service.'}
    except (OSError, UnicodeError):
        return {}, {'available': False, 'found': None, 'error': 'No se pudo leer .env.'}
    if not isinstance(content, str) or len(content) > 65536:
        return {}, {'available': False, 'found': None, 'error': 'No se pudo leer .env: archivo inválido o demasiado grande.'}
    values = dotenv_values(stream=io.StringIO(content), interpolate=False)
    return values, {'available': True, 'found': found, 'error': None}


def typed_environment_value(kind, value, default):
    if value is None or value == '':
        return default
    if kind is bool:
        if value.lower() in ('true', '1', 'yes', 'on'):
            return True
        if value.lower() in ('false', '0', 'no', 'off'):
            return False
        return value
    try:
        converted = kind(value)
        return value if isinstance(converted, float) and not math.isfinite(converted) else converted
    except (ValueError, TypeError):
        return value


def describe(database, environment_path=PROJECT_ENVIRONMENT, system=None):
    overrides = load_overrides(database)
    active = runtime_status(database).get('effective', {}).get('controls', {})
    environment, environment_status = read_environment(environment_path, system)
    fields = []
    for key, (kind, default, choices) in FIELDS.items():
        variable = 'GEMINI_MODEL' if key == 'model' else f'ARBY_{key.upper()}'
        raw = environment.get(variable)
        installed = typed_environment_value(kind, raw, default)
        if key in overrides:
            value, source = overrides[key], 'portal'
        elif environment_status['available']:
            value, source = installed, 'env' if variable in environment else 'default'
        else:
            value, source = active.get(key, default), 'runtime' if key in active else 'default'
        fields.append({'key': key, 'variable': variable, 'type': kind.__name__,
                       'choices': choices, 'default': default, 'category': category_for(key),
                       'value': value, 'source': source, 'env_value': raw,
                       'env_present': variable in environment, 'overridden': key in overrides, 'secret': False})
    extra = load_extra(database)
    for key, secret in EXTRA_FIELDS.items():
        kind = bool if key == 'ARBY_SUPPORT' else str
        raw = environment.get(key)
        # An explicitly empty fallback list disables the pool, rather than restoring a default.
        default = 'gemini-flash-lite-latest' if key == 'GEMINI_FALLBACK_MODELS' else False if kind is bool else None
        installed = (raw if key == 'GEMINI_FALLBACK_MODELS' and raw is not None
                     else typed_environment_value(kind, raw, default))
        value = typed_environment_value(kind, extra[key], default) if key in extra else installed
        if key == 'GEMINI_FALLBACK_MODELS' and key in extra:
            value = extra[key]
        fields.append({'key': key, 'variable': key, 'type': kind.__name__,
                       'category': category_for(key), 'value': None if secret else value,
                       'source': 'portal' if key in extra else 'env' if key in environment else 'default',
                       'env_value': None if secret else raw, 'env_present': key in environment,
                       'env_configured': bool(raw) if secret else None,
                       'secret': secret, 'overridden': key in extra,
                       'configured': bool(extra.get(key, raw)) if secret else None,
                       'choices': None, 'default': default})
    return {'fields': fields, 'categories': CATEGORIES, 'environment': environment_status,
            'push_to_talk_implemented': True}


def save_configuration(payload, database, environment_path=PROJECT_ENVIRONMENT, system=None):
    if not isinstance(payload, dict) or set(payload) - {'values', 'reset'}:
        raise ValueError('Configuración avanzada no permitida.')
    values, reset = payload.get('values', {}), payload.get('reset', [])
    if not isinstance(values, dict) or not isinstance(reset, list) or any(not isinstance(k, str) for k in reset):
        raise ValueError('Configuración avanzada no válida.')
    known = set(FIELDS) | set(EXTRA_FIELDS)
    if set(values) - known or set(reset) - known or set(values) & set(reset):
        raise ValueError('Opción avanzada no permitida.')
    controls = load_overrides(database)
    extra = load_extra(database)
    for key in reset:
        (controls if key in FIELDS else extra).pop(key, None)
    for key, value in values.items():
        if key in FIELDS:
            controls[key] = value
        else:
            if key == 'ARBY_SUPPORT':
                if type(value) is not bool:
                    raise ValueError('ARBY_SUPPORT requiere verdadero o falso.')
                extra[key] = 'true' if value else 'false'
            elif not isinstance(value, str) or len(value) > 4096 or any(c in value for c in '\r\n\x00'):
                raise ValueError(f'Valor inválido: {key}.')
            else:
                extra[key] = value
    controls = validate_controls(controls)
    active = runtime_status(database).get('effective', {}).get('controls', {})
    environment, status = read_environment(environment_path, system)
    parse_config(controls if status['available'] else {**active, **controls}, environment)
    # Write secrets atomically with owner-only permissions; the root runtime can read them.
    target = environment_file(database)
    with closing(connect(database)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('INSERT OR REPLACE INTO support_settings VALUES(1, ?)', (json.dumps(controls),))
        db.execute('INSERT OR REPLACE INTO support_configuration_revision VALUES(1, ?)', (uuid.uuid4().hex,))
        if any(key in EXTRA_FIELDS for key in set(values) | set(reset)):
            fd, name = tempfile.mkstemp(prefix='.portal-environment-', dir=target.parent)
            try:
                with os.fdopen(fd, 'w') as stream:
                    json.dump(extra, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(name, target)
            finally:
                if os.path.exists(name):
                    os.unlink(name)
