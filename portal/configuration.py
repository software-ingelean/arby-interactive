"""Administrator settings editor: portal storage is the only runtime source."""
from contextlib import closing
import json
import uuid

from libraries.core.arby_config import FIELDS, parse_config
from libraries.core.arby_configuration import (
    EXTRA_FIELDS, EXTRA_DEFAULTS, LOG_LEVELS, PROJECT_ENVIRONMENT,
    ensure_configuration, load_extra, variable_for, write_extra,
)
from libraries.core.arby_support import connect, load_overrides, validate_controls
from portal.configuration_help import CATEGORIES, field_help


def describe(database, environment_path=PROJECT_ENVIRONMENT, system=None):
    migration = ensure_configuration(database, environment_path, system)
    controls = load_overrides(database)
    config = parse_config(controls, {})
    fields = []
    for key, (kind, default, choices) in FIELDS.items():
        fields.append({'key': key, 'variable': variable_for(key), 'type': kind.__name__,
                       'choices': (10, 20, 40) if key == 'mic_block_ms' else choices,
                       'default': default, 'value': getattr(config, key),
                       'source': 'portal' if key in controls else 'default',
                       'overridden': key in controls, 'secret': False, **field_help(key)})
    extra = load_extra(database)
    for key, secret in EXTRA_FIELDS.items():
        default = EXTRA_DEFAULTS[key]
        value = extra.get(key, default)
        kind = bool if key == 'ARBY_SUPPORT' else str
        if kind is bool:
            value = value.lower() in ('true', '1', 'yes', 'on')
            default = default == 'true'
        fields.append({'key': key, 'variable': key, 'type': kind.__name__,
                       'value': None if secret else value,
                       'source': 'portal' if key in extra else 'default',
                       'secret': secret, 'overridden': key in extra,
                       'configured': bool(value) if secret else None,
                       'choices': LOG_LEVELS if key == 'ARBY_LOG_LEVEL' else None,
                       'default': None if secret else default, **field_help(key)})
    return {'fields': fields, 'categories': CATEGORIES, 'storage': migration,
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
    ensure_configuration(database, environment_path, system)
    with closing(connect(database)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        # Read under the same lock to preserve simultaneous administrator edits.
        row = db.execute('SELECT value FROM support_settings WHERE id=1').fetchone()
        controls = json.loads(row['value']) if row else {}
        extra = load_extra(database)
        for key in reset:
            (controls if key in FIELDS else extra).pop(key, None)
        for key, value in values.items():
            if key in FIELDS:
                controls[key] = value
            elif key == 'ARBY_SUPPORT':
                if type(value) is not bool:
                    raise ValueError('Publicar estado requiere verdadero o falso.')
                extra[key] = 'true' if value else 'false'
            elif not isinstance(value, str) or len(value) > 4096 or any(c in value for c in '\r\n\x00'):
                raise ValueError(f'Valor inválido: {key}.')
            elif key == 'ARBY_LOG_LEVEL' and value not in LOG_LEVELS:
                raise ValueError('Nivel de registro no permitido.')
            else:
                extra[key] = value
        controls = validate_controls(controls)
        parse_config(controls, {})
        if any(key in EXTRA_FIELDS for key in set(values) | set(reset)):
            write_extra(extra, database)
        db.execute('INSERT OR REPLACE INTO support_settings VALUES(1, ?)', (json.dumps(controls),))
        db.execute('INSERT OR REPLACE INTO support_configuration_revision VALUES(1, ?)', (uuid.uuid4().hex,))
