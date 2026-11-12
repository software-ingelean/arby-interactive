"""Small local support contract. SQLite never contains credentials or conversations."""
from contextlib import closing
from dataclasses import asdict
import json
import math
import os
import re
import logging
from pathlib import Path
import sqlite3
import time
import uuid

from libraries.audio.arby_recordings import SOUND_TEST
from libraries.core.arby_ambient import (
    DEFAULT_DATABASE, AmbientSettings, load_ambient_settings, save_ambient_settings,
)

# Explicit allowlist: hardware wiring and provider credentials stay in .env.
CONTROLS = {
    'mute': (bool, None, None),
    'rate': (str, None, None),
    'mic_gain_db': (float, -30, 36),
    'matrix_brightness': (int, 1, 100),
    'strip_brightness': (int, 0, 100),
}


def connect(database=DEFAULT_DATABASE):
    db = sqlite3.connect(database, timeout=0.05)
    db.row_factory = sqlite3.Row
    return db


def initialize(database=DEFAULT_DATABASE):
    # Also initializes the ambient table before creating any other table in this DB.
    database = Path(database)
    if not database.exists():
        save_ambient_settings(AmbientSettings(), database)
    else:
        load_ambient_settings(database)
    with closing(connect(database)) as db, db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS support_settings (
                id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS support_runtime (
                id INTEGER PRIMARY KEY CHECK(id=1), updated REAL NOT NULL, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS support_commands (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, created REAL NOT NULL,
                state TEXT NOT NULL, message TEXT NOT NULL);
        ''')


def load_overrides(database=DEFAULT_DATABASE):
    database = Path(database)
    if not database.exists():
        return {}
    with closing(connect(database)) as db:
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='support_settings'").fetchone()
        row = db.execute('SELECT value FROM support_settings WHERE id=1').fetchone() if exists else None
    return validate_controls(json.loads(row['value'])) if row else {}


def validate_controls(values):
    if not isinstance(values, dict) or set(values) - CONTROLS.keys():
        raise ValueError('Configuración no permitida.')
    result = {}
    for key, value in values.items():
        kind, low, high = CONTROLS[key]
        if kind is bool:
            valid = type(value) is bool
        elif kind is str:
            valid = isinstance(value, str) and re.fullmatch(r'[+-]\d{1,3}%', value) and -50 <= int(value[:-1]) <= 100
        else:
            valid = type(value) in (int, float) and math.isfinite(value) and low <= value <= high
            if kind is int:
                valid = valid and int(value) == value
        if not valid:
            raise ValueError(f'Valor inválido: {key}.')
        result[key] = kind(value)
    return result


def save_settings(payload, database=DEFAULT_DATABASE):
    if not isinstance(payload, dict) or set(payload) != {'ambient', 'controls'}:
        raise ValueError('Se requieren ambiente y controles.')
    raw = payload['ambient']
    if not isinstance(raw, dict) or set(raw) != set(asdict(AmbientSettings())):
        raise ValueError('Configuración de ambiente incompleta.')
    if any(type(value) not in (int, float) for key, value in raw.items() if key != 'mode'):
        raise ValueError('Los intervalos deben ser números.')
    ambient = AmbientSettings(**raw)
    controls = validate_controls(payload['controls'])
    # One transaction for both the existing ambient singleton and new overrides.
    with closing(connect(database)) as db, db:
        db.execute('''UPDATE arby_ambient_settings SET mode=?, gesture_min_seconds=?,
            gesture_max_seconds=?, invitation_min_seconds=?, invitation_max_seconds=? WHERE id=1''',
            (ambient.mode, *ambient.gesture_range, *ambient.invitation_range))
        db.execute('INSERT OR REPLACE INTO support_settings VALUES(1, ?)', (json.dumps(controls),))


def settings(database=DEFAULT_DATABASE):
    return {'ambient': asdict(load_ambient_settings(database)), 'controls': load_overrides(database)}


def runtime_status(database=DEFAULT_DATABASE):
    with closing(connect(database)) as db:
        row = db.execute('SELECT * FROM support_runtime WHERE id=1').fetchone()
    if not row:
        return {'state': 'unknown', 'fresh': False, 'components': {}}
    data = json.loads(row['value'])
    data['fresh'] = 0 <= time.time() - row['updated'] < 8
    return data


def enqueue(kind, database=DEFAULT_DATABASE):
    if kind not in ('speaker', 'eyes'):
        raise ValueError('Prueba desconocida.')
    status = runtime_status(database)
    if not status['fresh'] or status.get('state') != 'ready':
        raise ValueError('Arby no está disponible para pruebas.')
    identifier = uuid.uuid4().hex
    with closing(connect(database)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute("SELECT 1 FROM support_commands WHERE state IN ('pending','running') AND created>?",
                      (time.time() - 30,)).fetchone():
            raise ValueError('Ya hay una prueba en curso.')
        db.execute('INSERT INTO support_commands VALUES(?,?,?,?,?)',
                   (identifier, kind, time.time(), 'pending', 'Esperando a Arby.'))
        db.execute('DELETE FROM support_commands WHERE created<?', (time.time() - 86400,))
    return identifier


class SupportBridge:
    """Called from the render thread; bounded database waits and no hardware ownership."""
    def __init__(self, database=DEFAULT_DATABASE):
        self.database = database
        self.next_poll = 0
        self.pending = None
        self.snapshot = {'state': 'starting', 'components': {}, 'effective': {}}
        self.enabled = os.getenv('ARBY_SUPPORT', '').lower() in ('1', 'true', 'yes', 'on')
        if self.enabled:
            try:
                initialize(database)
                self.publish()
            except (OSError, sqlite3.Error, ValueError):
                self.enabled = False
                logging.getLogger(__name__).warning('Portal: no se pudo iniciar la telemetría.')

    def publish(self):
        if not self.enabled:
            return
        self.snapshot['pid'] = os.getpid()
        with closing(connect(self.database)) as db, db:
            db.execute('INSERT OR REPLACE INTO support_runtime VALUES(1,?,?)',
                       (time.time(), json.dumps(self.snapshot)))

    def finish(self, state):
        self.snapshot['state'] = state
        try:
            self.publish()
        except (OSError, sqlite3.Error):
            pass

    def tick(self, runtime, microphone, tts, touch, submit):
        if not self.enabled or time.monotonic() < self.next_poll:
            return
        self.next_poll = time.monotonic() + 1
        try:
            with closing(connect(self.database)) as db, db:
                if self.pending:
                    identifier, future, kind = self.pending
                    if future.done():
                        failed = future.cancelled() or future.exception() is not None or (kind == 'speaker' and bool(getattr(tts, 'last_error', None)))
                        db.execute("UPDATE support_commands SET state=?,message=? WHERE id=? AND state='running'",
                                   ('error' if failed else 'done',
                                    'La prueba se interrumpió o falló. Comprueba el componente e intenta nuevamente.' if failed else 'Prueba terminada. Confirma el resultado físicamente.', identifier))
                        self.pending = None
                db.execute("UPDATE support_commands SET state='error',message='La solicitud caducó o Arby se reinició.' WHERE state IN ('pending','running') AND created<?",
                           (time.time() - 30,))
                row = db.execute("SELECT * FROM support_commands WHERE state='pending' ORDER BY created LIMIT 1").fetchone()
                if row and self.pending is None:
                    from libraries.core.arby_ambient import AmbientAction
                    component = 'speaker' if row['kind'] == 'speaker' else 'eyes'
                    enabled = self.snapshot['components'].get(component, {}).get('state') != 'disabled'
                    action = (AmbientAction('phrase', 'alegres', SOUND_TEST)
                              if row['kind'] == 'speaker' else AmbientAction('eyes', 'guiño ojo', duration_seconds=2))
                    future = submit(action) if enabled else None
                    message = 'Prueba en curso.' if future else 'No disponible: componente desactivado o Arby ocupado. Intenta de nuevo.'
                    db.execute('UPDATE support_commands SET state=?,message=? WHERE id=?',
                               ('running' if future else 'error', message, row['id']))
                    if future:
                        self.pending = row['id'], future, row['kind']
            self.snapshot['busy'] = runtime.pending_count > 0
            self.snapshot['phase'] = runtime.visual.phase
            if microphone:
                self.snapshot['microphone_activity'] = microphone.pipeline.visitor_active
            if touch:
                self.snapshot['last_touch'] = getattr(touch, 'last_touch', None)
            if getattr(tts, 'last_error', None):
                self.snapshot['components']['speaker'] = {'state': 'error', 'detail': 'Falló la última reproducción. Prueba nuevamente o reinicia Arby.'}
            elif self.snapshot['components'].get('speaker', {}).get('state') != 'disabled':
                checked = getattr(tts, 'last_status', '') == 'completed'
                self.snapshot['components']['speaker'] = {'state': 'ready' if checked else 'unknown', 'detail': 'Reproducción completada; confirma que se escucha.' if checked else 'Voz inicializada. Usa Probar sonido para comprobar la salida.'}
            self.publish()
        except (OSError, sqlite3.Error):
            # Support must never take down the conversation or steal its event queue.
            self.next_poll = time.monotonic() + 5
