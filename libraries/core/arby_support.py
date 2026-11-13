"""Small local support contract. SQLite never contains credentials or conversation content."""
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

from libraries.audio.arby_devices import load_selection, validate_selection
from libraries.audio.arby_recordings import SOUND_TEST
from libraries.core.arby_ambient import (
    DEFAULT_DATABASE, AmbientSettings, AmbientAction, load_ambient_settings, save_ambient_settings,
)

# Explicit allowlist: hardware wiring and provider credentials stay in .env.
CONTROLS = {
    'mute': (bool, None, None),
    'rate': (str, None, None),
    'mic_gain_db': (float, -30, 36),
    'mic_channel': (str, None, None),
    'matrix_brightness': (int, 1, 100),
    'strip_brightness': (int, 0, 100),
}


TESTS = {
    'speaker': {'label': 'Probar sonido', 'requires': ('speaker',),
                'action': AmbientAction('phrase', 'alegres', 'Hola, soy Arby. Esta es una prueba de sonido.')},
    'greeting': {'label': 'Saludo de Arby', 'requires': ('speaker',),
                 'action': AmbientAction('phrase', 'alegres', '¡Hola! Soy Arby, tu plantita de compañía. Acércate y conversemos un ratito.')},
    'invitation': {'label': 'Invitar a conversar', 'requires': ('speaker',),
                   'action': AmbientAction('phrase', 'sorprendidos', '¿Sabías que las plantas tienen muchas historias que contar? Pregúntame algo y lo descubrimos juntos.')},
    'eyes': {'label': 'Guiño', 'requires': ('eyes',),
             'action': AmbientAction('eyes', 'guiño ojo', duration_seconds=3)},
    'happy': {'label': 'Ojos alegres', 'requires': ('eyes',),
              'action': AmbientAction('eyes', 'alegres', duration_seconds=3)},
    'surprise': {'label': 'Sorpresa', 'requires': ('eyes',),
                 'action': AmbientAction('eyes', 'sorprendidos', duration_seconds=3)},
    'sleep': {'label': 'Ojos dormidos', 'requires': ('eyes',),
              'action': AmbientAction('eyes', 'dormido', duration_seconds=3)},
    **{f'light_{key}': {'label': f'Luz {label}', 'requires': ('strip',),
                        'action': AmbientAction('lights', 'default', duration_seconds=3, color=color)}
       for key, label, color in (('red', 'roja', (255, 0, 0)), ('green', 'verde', (0, 255, 0)),
                                 ('blue', 'azul', (0, 0, 255)))},
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
        columns = {row[1] for row in db.execute('PRAGMA table_info(arby_ambient_settings)')}
        if 'phrases_enabled' not in columns:
            db.execute('ALTER TABLE arby_ambient_settings ADD COLUMN phrases_enabled INTEGER NOT NULL DEFAULT 1 CHECK(phrases_enabled IN (0,1))')
        db.executescript('''
            CREATE TABLE IF NOT EXISTS support_settings (
                id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS support_audio_settings (
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
            valid = value in ('left', 'right') if key == 'mic_channel' else (isinstance(value, str) and re.fullmatch(r'[+-]\d{1,3}%', value) and -50 <= int(value[:-1]) <= 100)
        else:
            valid = type(value) in (int, float) and math.isfinite(value) and low <= value <= high
            if kind is int:
                valid = valid and int(value) == value
        if not valid:
            raise ValueError(f'Valor inválido: {key}.')
        result[key] = kind(value)
    return result


def save_settings(payload, database=DEFAULT_DATABASE):
    if not isinstance(payload, dict) or set(payload) not in ({'ambient', 'controls'}, {'ambient', 'controls', 'audio'}):
        raise ValueError('Se requieren ambiente y controles.')
    raw = payload['ambient']
    if isinstance(raw, dict):
        raw = {'phrases_enabled': load_ambient_settings(database).phrases_enabled, **raw}
    if not isinstance(raw, dict) or set(raw) != set(asdict(AmbientSettings())):
        raise ValueError('Configuración de ambiente incompleta.')
    if any(type(value) not in (int, float) for key, value in raw.items() if key not in ('mode', 'phrases_enabled')):
        raise ValueError('Los intervalos deben ser números.')
    ambient = AmbientSettings(**raw)
    controls = validate_controls(payload['controls'])
    audio = validate_selection(payload['audio']) if 'audio' in payload else None
    # One transaction for both the existing ambient singleton and new overrides.
    with closing(connect(database)) as db, db:
        db.execute('''UPDATE arby_ambient_settings SET mode=?, gesture_min_seconds=?,
            gesture_max_seconds=?, invitation_min_seconds=?, invitation_max_seconds=?, phrases_enabled=? WHERE id=1''',
            (ambient.mode, *ambient.gesture_range, *ambient.invitation_range, ambient.phrases_enabled))
        db.execute('INSERT OR REPLACE INTO support_settings VALUES(1, ?)', (json.dumps(controls),))
        if audio is not None:
            db.execute('INSERT OR REPLACE INTO support_audio_settings VALUES(1, ?)', (json.dumps(audio),))


def settings(database=DEFAULT_DATABASE):
    return {'ambient': asdict(load_ambient_settings(database)), 'controls': load_overrides(database),
            'audio': load_selection(database)}


def runtime_status(database=DEFAULT_DATABASE):
    with closing(connect(database)) as db:
        row = db.execute('SELECT * FROM support_runtime WHERE id=1').fetchone()
    if not row:
        return {'state': 'unknown', 'fresh': False, 'components': {}}
    data = json.loads(row['value'])
    data['fresh'] = 0 <= time.time() - row['updated'] < 8
    return data


def enqueue(kind, database=DEFAULT_DATABASE):
    if kind not in TESTS and kind != 'cancel':
        raise ValueError('Prueba desconocida.')
    status = runtime_status(database)
    if not status['fresh'] or status.get('state') != 'ready':
        raise ValueError('Arby no está disponible para pruebas.')
    identifier = uuid.uuid4().hex
    with closing(connect(database)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        if kind != 'cancel' and db.execute("SELECT 1 FROM support_commands WHERE state IN ('pending','running') AND created>?",
                      (time.time() - 30,)).fetchone():
            raise ValueError('Ya hay una prueba en curso.')
        db.execute('INSERT INTO support_commands VALUES(?,?,?,?,?)',
                   (identifier, kind, time.time(), 'pending', 'Esperando a Arby.'))
        db.execute('DELETE FROM support_commands WHERE created<?', (time.time() - 86400,))
    return identifier


class SupportBridge:
    """Called from the render thread; bounded database waits and no hardware ownership."""
    def __init__(self, database=DEFAULT_DATABASE):
        from libraries.core.arby_debug import DebugTrace
        self.debug = DebugTrace()
        self.debug.stage("proceso", "Iniciando Arby", "run_arby.py · main", 60)
        self._debug_observed = {}
        self.database = database
        self.next_poll = 0
        self.pending = None
        self.waiting = False
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
        self.snapshot['debug'] = self.debug.snapshot()
        self.snapshot['debug']['pending'] = self.snapshot.get('pending', 0)
        self.snapshot['updated_at'] = time.time()
        with closing(connect(self.database)) as db, db:
            db.execute('INSERT OR REPLACE INTO support_runtime VALUES(1,?,?)',
                       (time.time(), json.dumps(self.snapshot)))

    def checkpoint(self, name, location, expected_seconds=60):
        self.debug.stage('proceso', name, location, expected_seconds)
        try:
            self.publish()
        except (OSError, sqlite3.Error):
            pass

    def finish(self, state):
        self.debug.stage('proceso', 'Arby finalizado: ' + state, 'run_arby.py · main')
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
                        failed = future.cancelled() or future.exception() is not None or ('speaker' in TESTS[kind]['requires'] and bool(getattr(tts, 'last_error', None)))
                        db.execute("UPDATE support_commands SET state=?,message=? WHERE id=? AND state='running'",
                                   ('error' if failed else 'done',
                                    'La prueba se interrumpió o falló. Comprueba el componente e intenta nuevamente.' if failed else 'Prueba terminada. Confirma el resultado físicamente.', identifier))
                        self.pending = None
                db.execute("UPDATE support_commands SET state='error',message='La solicitud caducó o Arby se reinició.' WHERE state IN ('pending','running') AND created<?",
                           (time.time() - 30,))
                row = db.execute("SELECT * FROM support_commands WHERE state='pending' ORDER BY CASE WHEN kind='cancel' THEN 0 ELSE 1 END, created LIMIT 1").fetchone()
                self.waiting = row is not None
                if row and row['kind'] == 'cancel':
                    cancelled = db.execute("UPDATE support_commands SET state='error',message='Prueba cancelada antes de iniciar.' WHERE state='pending' AND kind!='cancel'").rowcount
                    self.waiting = False
                    stopped = self.pending is not None and runtime.cancel_ambient(self.pending[1])
                    db.execute('UPDATE support_commands SET state=?,message=? WHERE id=?',
                               ('done', 'Demostración interrumpida.' if stopped else 'Prueba pendiente cancelada.' if cancelled else 'No hay una demostración en curso.', row['id']))
                elif row and self.pending is None:
                    definition = TESTS[row['kind']]
                    enabled = all(self.snapshot['components'].get(component, {}).get('state') != 'disabled'
                                  for component in definition['requires'])
                    future = submit(definition['action']) if enabled else None
                    message = 'Prueba en curso.' if future else ('Esperando a que Arby esté libre.' if enabled else 'No disponible: componente desactivado.')
                    db.execute('UPDATE support_commands SET state=?,message=? WHERE id=?',
                               ('running' if future else 'pending' if enabled else 'error', message, row['id']))
                    if future:
                        self.pending = row['id'], future, row['kind']
            if getattr(runtime, 'visit_recorder', None):
                self.snapshot['visits'] = runtime.visit_recorder.status
            self.snapshot['pending'] = runtime.pending_count
            self.snapshot['busy'] = runtime.pending_count > 0
            self.snapshot['visitor_busy'] = runtime.visitor_activity[0] if hasattr(runtime, 'visitor_activity') else runtime.pending_count > 0
            self.snapshot['phase'] = runtime.visual.phase
            if microphone:
                self.snapshot['microphone_activity'] = microphone.pipeline.visitor_active
                recent = time.monotonic() - getattr(microphone.pipeline, 'last_audio_at', 0) < 2
                self.snapshot['microphone_level'] = getattr(microphone.pipeline, 'input_level', 0) if recent else 0
            if touch:
                self.snapshot['last_touch'] = getattr(touch, 'last_touch', None)
            if getattr(tts, 'last_error', None):
                self.snapshot['components']['speaker'] = {'state': 'error', 'detail': 'Falló la última reproducción. Prueba nuevamente o reinicia Arby.'}
            elif self.snapshot['components'].get('speaker', {}).get('state') != 'disabled':
                checked = getattr(tts, 'last_status', '') == 'completed'
                self.snapshot['components']['speaker'] = {'state': 'ready' if checked else 'unknown', 'detail': 'Reproducción completada; confirma que se escucha.' if checked else 'Voz inicializada. Usa Probar sonido para comprobar la salida.'}
            observed = {'microphone_activity': self.snapshot.get('microphone_activity'),
                        'capture_blocked': getattr(runtime, 'capture_blocked', runtime.pending_count > 0),
                        'pending': runtime.pending_count}
            if microphone:
                pipeline = microphone.pipeline
                observed.update(listen_mode=getattr(getattr(pipeline, 'google_worker', None), 'mode', 'unknown'),
                                dropped_capture=getattr(pipeline, 'drop_capture', 0),
                                dropped_recognition=getattr(pipeline, 'drop_google', 0))
            for key, value in observed.items():
                if self._debug_observed.get(key) != value:
                    self.debug.event('entrada', 'Cambio de actividad', field=key, value=value)
            self._debug_observed = observed
            self.snapshot['capture_blocked'] = getattr(runtime, 'capture_blocked', runtime.pending_count > 0)
            self.publish()
        except (OSError, sqlite3.Error):
            # Support must never take down the conversation or steal its event queue.
            self.next_poll = time.monotonic() + 5
