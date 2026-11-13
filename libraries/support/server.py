"""Authenticated LAN portal. Run with python -m libraries.support.server."""
from contextlib import closing
from datetime import timedelta
import hmac
import os
import secrets
import sqlite3
import subprocess
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, render_template, request, session, send_file
from werkzeug.security import check_password_hash

from libraries.core.arby_ambient import DEFAULT_DATABASE
from libraries.audio.arby_devices import inventory, load_selection
from libraries.core.arby_support import TESTS, initialize, settings, save_settings, runtime_status, enqueue, connect

SYSTEM_HELPER = ['/usr/bin/sudo', '-n', '/usr/bin/python3', '-I', '/usr/local/libexec/arby-system.py']


def system_action(action, **values):
    import json
    try:
        result = subprocess.run(SYSTEM_HELPER, input=json.dumps({'action': action, **values}),
                                capture_output=True, text=True, timeout=35, check=False)
        if result.returncode:
            raise ValueError('No se pudo completar la acción. Revisa permisos, conexión o servicio por SSH.')
        return json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        raise ValueError('Acción no disponible. Revisa la instalación y la conexión por SSH.') from exc


def create_app(database=DEFAULT_DATABASE, password_hash=None, system=system_action):
    database = Path(database)
    initialize(database)
    app = Flask(__name__)
    app.config.update(SECRET_KEY=secrets.token_hex(32), MAX_CONTENT_LENGTH=8192,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict',
                      PERMANENT_SESSION_LIFETIME=timedelta(hours=4))
    password_hash = password_hash or os.getenv('ARBY_PORTAL_PASSWORD_HASH')
    if not password_hash:
        raise ValueError('Configura ARBY_PORTAL_PASSWORD_HASH antes de iniciar el portal.')
    attempts, login_lock = {}, threading.Lock()

    def body():
        value = request.get_json()
        if not isinstance(value, dict):
            raise ValueError('Se esperaba un objeto de configuración.')
        return value

    @app.before_request
    def protect():
        if request.path.startswith('/api/'):
            if request.method != 'GET':
                if not session.get('csrf') or not hmac.compare_digest(request.headers.get('X-CSRF-Token', ''), session['csrf']):
                    return jsonify(error='Sesión caducada. Recarga la página.'), 403
            if request.path not in ('/api/session', '/api/login') and not session.get('authenticated'):
                return jsonify(error='Introduce la clave de soporte.'), 401

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    @app.errorhandler(ValueError)
    @app.errorhandler(TypeError)
    def invalid(error):
        return jsonify(error=str(error) if isinstance(error, ValueError) else 'Datos inválidos.'), 400

    @app.errorhandler(sqlite3.Error)
    @app.errorhandler(OSError)
    def unavailable(error):
        return jsonify(error='No se pudo acceder al estado local. Intenta de nuevo o revisa por SSH.'), 503

    @app.get('/')
    def index():
        return render_template('index.html')

    @app.get('/assets/arby.webp')
    def brand_asset():
        return send_file(Path(__file__).resolve().parents[2] / 'assets' / 'arby.webp', mimetype='image/webp')

    @app.get('/api/session')
    def session_info():
        session.setdefault('csrf', secrets.token_hex(32))
        return jsonify(authenticated=bool(session.get('authenticated')), csrf=session['csrf'])

    @app.post('/api/login')
    def login():
        key = request.remote_addr or 'local'
        now = time.monotonic()
        with login_lock:
            for address in list(attempts):
                attempts[address] = [stamp for stamp in attempts[address] if now - stamp < 60]
                if not attempts[address]:
                    del attempts[address]
            if len(attempts.get(key, [])) >= 5 or sum(map(len, attempts.values())) >= 30:
                return jsonify(error='Demasiados intentos. Espera un minuto.'), 429
            attempts.setdefault(key, []).append(now)
        password = body().get('password', '')
        if not isinstance(password, str) or not check_password_hash(password_hash, password):
            return jsonify(error='Clave incorrecta.'), 401
        session.clear()
        session.update(authenticated=True, csrf=secrets.token_hex(32))
        session.permanent = True
        return jsonify(csrf=session['csrf'])

    @app.post('/api/logout')
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.get('/api/status')
    def status():
        live = runtime_status(database)
        saved = settings(database)
        effective = live.get('effective', {})
        live['pending_changes'] = bool(effective) and (saved['ambient'] != effective.get('ambient') or any(effective.get('controls', {}).get(key) != value for key, value in saved['controls'].items()) or saved['audio'] != effective.get('audio', {'input': None, 'output': None}))
        with closing(connect(database)) as db:
            commands = [dict(row) for row in db.execute('SELECT * FROM support_commands ORDER BY created DESC LIMIT 5')]
        for command in commands:
            if command['state'] in ('pending', 'running') and time.time() - command['created'] > 30:
                command.update(state='error', message='Prueba caducada. Comprueba que Arby siga funcionando.')
        defaults = {'mute': os.getenv('ARBY_MUTE', '').lower() in ('1', 'true', 'yes', 'on'),
                    'rate': os.getenv('ARBY_RATE') or '+12%',
                    'mic_gain_db': os.getenv('ARBY_MIC_GAIN_DB') or 6,
                    'mic_channel': os.getenv('ARBY_MIC_CHANNEL') or 'left',
                    'matrix_brightness': os.getenv('ARBY_MATRIX_BRIGHTNESS') or 25,
                    'strip_brightness': os.getenv('ARBY_STRIP_BRIGHTNESS') or 20}
        return jsonify(runtime=live, saved=saved, defaults=defaults, commands=commands,
                       tests=[{'id': key, 'label': item['label'], 'requires': item['requires']} for key, item in TESTS.items()])

    @app.put('/api/settings')
    def update_settings():
        save_settings(body(), database)
        return jsonify(ok=True)

    @app.post('/api/tests')
    def tests():
        return jsonify(id=enqueue(body().get('kind'), database)), 202

    @app.get('/api/audio/devices')
    def audio_devices():
        return jsonify(inventory(load_selection(database)))

    @app.post('/api/tests/cancel')
    def cancel_test():
        return jsonify(id=enqueue('cancel', database)), 202

    @app.post('/api/power')
    def power():
        if body().get('target') != 'shutdown':
            raise ValueError('Acción de energía no permitida.')
        return jsonify(system('shutdown'))

    @app.get('/api/network')
    def network():
        return jsonify(system('network'))

    @app.post('/api/network/connect')
    def network_connect():
        data = body()
        return jsonify(system('wifi', ssid=data.get('ssid'), password=data.get('password', '')))

    @app.post('/api/restart')
    def restart():
        target = body().get('target')
        if target not in ('arby', 'raspberry'):
            raise ValueError('Reinicio no permitido.')
        return jsonify(system(target))

    return app


def main():
    from waitress import serve
    serve(create_app(), host=os.getenv('ARBY_PORTAL_HOST', '0.0.0.0'),
          port=int(os.getenv('ARBY_PORTAL_PORT', '8080')), threads=4)


if __name__ == '__main__':
    main()
