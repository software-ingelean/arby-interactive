"""Authenticated LAN portal. Run with python -m libraries.support.server."""
from contextlib import closing
from datetime import timedelta
import csv
import io
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
                                capture_output=True, text=True, timeout=55 if action == 'bluetooth_connect' else 38, check=False)
        if result.returncode:
            raise ValueError('No se pudo completar la acción. Revisa permisos, conexión o servicio por SSH.')
        payload = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        raise ValueError('Acción no disponible. Revisa la instalación y la conexión por SSH.') from exc
    messages = {
        'bluetooth_missing': 'Bluetooth no está instalado. Instala BlueZ en la Raspberry y actualiza el helper por SSH.',
        'bluetooth_scan_failed': 'No se pudo consultar o buscar dispositivos Bluetooth. Revisa el servicio bluetooth por SSH y vuelve a intentar.',
        'bluetooth_timeout': 'Bluetooth tardó demasiado. Acerca el dispositivo, activa el modo de emparejamiento y vuelve a intentar.',
        'bluetooth_unavailable': 'El adaptador Bluetooth no está disponible o no está encendido.',
        'bluetooth_not_found': 'El dispositivo ya no está disponible. Activa su modo de emparejamiento y pulsa Buscar dispositivos.',
        'bluetooth_auth_failed': 'El dispositivo rechazó el emparejamiento. Desconéctalo del celular y activa su modo de emparejamiento. Si requiere PIN o confirmación, este portal todavía no admite ese paso.',
        'bluetooth_pair_failed': 'No se pudo emparejar. Activa el modo de emparejamiento del dispositivo y vuelve a intentar.',
        'bluetooth_connect_failed': 'No se pudo conectar. Comprueba que el dispositivo esté cerca y desconectado de otros equipos.',
        'bluetooth_disconnect_failed': 'No se pudo desconectar el dispositivo. Actualiza su estado y vuelve a intentar.',
        'bluetooth_audio_unavailable': 'El dispositivo se detectó, pero el sistema no tiene disponible su perfil de audio Bluetooth.',
        'wifi_timeout': 'La conexión tardó demasiado. Comprueba la señal e intenta de nuevo.',
        'wifi_not_found': 'La red ya no está disponible. Pulsa Buscar redes y vuelve a seleccionarla.',
        'wifi_credentials': 'No se pudieron validar las credenciales. Revisa la contraseña y el tipo de seguridad de la red.',
        'wifi_failed': 'No se pudo activar la conexión Wi-Fi. Revisa la contraseña, la señal y la configuración del router.',
    }
    if payload.get('error_code') in messages:
        raise ValueError(messages[payload['error_code']])
    return payload


def create_app(database=DEFAULT_DATABASE, password_hash=None, system=system_action):
    database = Path(database)
    initialize(database)
    from libraries.core.arby_visits import initialize as initialize_visits, report, BOGOTA
    initialize_visits(database)
    app = Flask(__name__)
    app.config.update(SECRET_KEY=secrets.token_hex(32), MAX_CONTENT_LENGTH=8192,
                      SESSION_COOKIE_NAME='arby_portal_session',
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
                    return jsonify(error='No se pudo validar la sesión. Intenta de nuevo.', code='csrf_mismatch'), 403
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

    def visits_report():
        result = report(database, request.args.get('start'), request.args.get('end'))
        status = runtime_status(database)
        health = status.get('visits', {})
        result['incomplete'] = result['incomplete'] or bool(health.get('incomplete'))
        result['error'] = health.get('error')
        return result

    @app.get('/api/visits')
    def visits():
        return jsonify(visits_report())

    @app.get('/api/visits/export.csv')
    def export_visits():
        from datetime import datetime
        result = visits_report()
        output = io.StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow(['id', 'inicio_America_Bogota', 'ultima_actividad_America_Bogota',
                         'cierre_America_Bogota', 'motivo_cierre', 'mensajes', 'conteo_incompleto'])
        for visit in result['visits']:
            dates = [datetime.fromisoformat(visit[key]).astimezone(BOGOTA).isoformat()
                     if visit[key] else '' for key in ('started_at', 'last_activity_at', 'ended_at')]
            writer.writerow([visit['id'], *dates, visit['close_reason'] or 'active',
                             visit['messages'], result['incomplete']])
        return app.response_class(output.getvalue(), mimetype='text/csv', headers={
            'Content-Disposition': 'attachment; filename="arby-visitas.csv"'})

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
        defaults = {'trill': os.getenv('ARBY_TRILL', '').lower() in ('1', 'true', 'yes', 'on'),
                    'mute': os.getenv('ARBY_MUTE', '').lower() in ('1', 'true', 'yes', 'on'),
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

    @app.get('/api/bluetooth')
    def bluetooth_status():
        return jsonify(system('bluetooth'))

    @app.post('/api/bluetooth/<operation>')
    def bluetooth_action(operation):
        if operation not in ('scan', 'connect', 'disconnect'):
            raise ValueError('Acción Bluetooth no permitida.')
        if operation == 'scan':
            return jsonify(system('bluetooth_scan'))
        import re
        address = body().get('address')
        if not isinstance(address, str) or not re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}', address):
            raise ValueError('Dirección Bluetooth inválida.')
        return jsonify(system('bluetooth_' + operation, address=address))

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
