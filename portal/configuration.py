"""Administrator settings editor for the portal."""
from contextlib import closing
import json
import os
import tempfile
import uuid

from libraries.core.arby_config import FIELDS, parse_config
from libraries.core.arby_configuration import EXTRA_FIELDS, environment_file, load_extra
from libraries.core.arby_support import connect, load_overrides, runtime_status, validate_controls


def describe(database):
    overrides = load_overrides(database)
    active = runtime_status(database).get('effective', {}).get('controls', {})
    fields = []
    for key, (kind, default, choices) in FIELDS.items():
        variable = 'GEMINI_MODEL' if key == 'model' else f'ARBY_{key.upper()}'
        fields.append({'key': key, 'variable': variable, 'type': kind.__name__,
                       'choices': choices, 'default': default,
                       'value': overrides.get(key, active.get(key, default)),
                       'overridden': key in overrides, 'secret': False})
    extra = load_extra(database)
    for key, secret in EXTRA_FIELDS.items():
        fields.append({'key': key, 'variable': key, 'type': 'bool' if key == 'ARBY_SUPPORT' else 'str',
                       'value': None if secret else (extra.get(key) == 'true' if key == 'ARBY_SUPPORT' else extra.get(key)), 'secret': secret,
                       'overridden': key in extra, 'configured': bool(extra.get(key)) if secret else None,
                       'choices': None, 'default': None})
    return {'fields': fields, 'push_to_talk_implemented': False}


def save_configuration(payload, database):
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
    parse_config({**active, **controls}, {})
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
