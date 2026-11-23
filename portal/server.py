"""Authenticated LAN portal. Run with python -m portal."""
from contextlib import closing
import csv
import io
import os
import secrets
import sqlite3
import subprocess
import threading
import time
from pathlib import Path

import json
from functools import wraps
from types import ModuleType

from werkzeug.security import check_password_hash

from libraries.core.arby_ambient import DEFAULT_DATABASE
from libraries.audio.arby_devices import inventory, load_selection
from libraries.core.arby_support import TESTS, initialize, settings, save_settings, runtime_status, enqueue, connect

from django.core.handlers.wsgi import WSGIHandler
from django.http import JsonResponse, HttpResponse, FileResponse
from django.middleware.csrf import get_token, rotate_token
from django.shortcuts import render
from django.urls import path
from django.views.decorators.http import require_http_methods
from django.contrib.auth.hashers import check_password


def jsonify(*args, **kwargs):
    return JsonResponse(args[0] if args else kwargs)


def csrf_failure(request, reason=''):
    return JsonResponse({'error': 'No se pudo validar la sesión. Intenta de nuevo.', 'code': 'csrf_mismatch'}, status=403)


class PortalHeaders:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response['Cache-Control'] = 'no-store'
        response['X-Content-Type-Options'] = 'nosniff'
        response['X-Frame-Options'] = 'DENY'
        response['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response


def configure_django():
    from django.conf import settings as django_settings
    if not django_settings.configured:
        django_settings.configure(
            SECRET_KEY=secrets.token_hex(32), DEBUG=False, ALLOWED_HOSTS=['*'],
            ROOT_URLCONF=__name__,
            INSTALLED_APPS=[],
            MIDDLEWARE=['portal.server.PortalHeaders',
                        'django.contrib.sessions.middleware.SessionMiddleware',
                        'django.middleware.csrf.CsrfViewMiddleware'],
            SESSION_ENGINE='django.contrib.sessions.backends.cache',
            SESSION_COOKIE_NAME='arby_portal_session', SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SAMESITE='Strict', SESSION_COOKIE_AGE=14400,
            SESSION_SAVE_EVERY_REQUEST=True, CSRF_USE_SESSIONS=True,
            CSRF_HEADER_NAME='HTTP_X_CSRF_TOKEN',
            CSRF_FAILURE_VIEW='portal.server.csrf_failure',
            DATA_UPLOAD_MAX_MEMORY_SIZE=32768,
            CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                                'OPTIONS': {'MAX_ENTRIES': 4096}}},
            TEMPLATES=[{'BACKEND': 'django.template.backends.django.DjangoTemplates',
                        'DIRS': [str(Path(__file__).parent / 'templates')]}],
        )
        import django
        django.setup()


class PortalHandler(WSGIHandler):
    def __init__(self, patterns):
        self.urlconf = ModuleType('arby_portal_urls')
        self.urlconf.urlpatterns = patterns
        super().__init__()

    def get_response(self, request):
        request.urlconf = self.urlconf
        return super().get_response(request)


urlpatterns = []

COMMERCIAL_CONTROLS = {'mute', 'rate', 'matrix_brightness', 'strip_brightness'}

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
        'wifi_profile_missing': 'La configuración guardada de esa red ya no está disponible. Pulsa Buscar redes y vuelve a seleccionarla.',
        'wifi_timeout': 'La conexión tardó demasiado. Comprueba la señal e intenta de nuevo.',
        'wifi_not_found': 'La red ya no está disponible. Pulsa Buscar redes y vuelve a seleccionarla.',
        'wifi_credentials': 'No se pudieron validar las credenciales. Revisa la contraseña y el tipo de seguridad de la red.',
        'wifi_failed': 'No se pudo activar la conexión Wi-Fi. Revisa la contraseña, la señal y la configuración del router.',
    }
    if payload.get('error_code') in messages:
        raise ValueError(messages[payload['error_code']])
    return payload


def create_app(database=DEFAULT_DATABASE, password_hash=None, system=system_action, commercial_password_hash=None):
    database = Path(database)
    initialize(database)
    from libraries.core.arby_visits import initialize as initialize_visits, report, BOGOTA
    initialize_visits(database)
    configure_django()
    patterns = []
    password_hash = password_hash or os.getenv('ARBY_PORTAL_PASSWORD_HASH')
    if not password_hash:
        raise ValueError('Configura ARBY_PORTAL_PASSWORD_HASH antes de iniciar el portal.')
    commercial_password_hash = commercial_password_hash or os.getenv('ARBY_PORTAL_COMMERCIAL_PASSWORD_HASH')
    attempts, login_lock = {}, threading.Lock()

    def route(url, methods):
        def decorate(view):
            @wraps(view)
            def dispatch(request, **kwargs):
                if url.startswith('/api/') and url not in ('/api/session', '/api/login'):
                    role = request.session.get('role')
                    if role not in ('admin', 'comercial'):
                        return JsonResponse({'error': 'Introduce la clave de soporte.'}, status=401)
                    if role == 'comercial':
                        allowed = url in ('/api/status', '/api/logout', '/api/visits', '/api/visits/export.csv',
                                          '/api/settings', '/api/tests', '/api/tests/cancel', '/api/restart')
                        if not allowed:
                            return JsonResponse({'error': 'Esta opción requiere el perfil admin.'}, status=403)
                try:
                    response = view(request, **kwargs)
                except (ValueError, TypeError) as exc:
                    response = JsonResponse({'error': str(exc) if isinstance(exc, ValueError) else 'Datos inválidos.'}, status=400)
                except (sqlite3.Error, OSError):
                    response = JsonResponse({'error': 'No se pudo acceder al estado local. Intenta de nuevo o revisa por SSH.'}, status=503)
                if isinstance(response, tuple):
                    response, status_code = response
                    response.status_code = status_code
                return response
            patterns.append(path(url.lstrip('/'), require_http_methods(methods)(dispatch)))
            return view
        return decorate


    def body(request):
        if request.content_type != 'application/json':
            raise ValueError('Se esperaba contenido JSON.')
        try:
            value = json.loads(request.body)
        except (ValueError, UnicodeDecodeError):
            raise ValueError('JSON inválido.') from None
        if not isinstance(value, dict):
            raise ValueError('Se esperaba un objeto de configuración.')
        return value

    @route('/', ['GET'])
    def index(request):
        return render(request, 'index.html')

    @route('/assets/arby.webp', ['GET'])
    def brand_asset(request):
        return FileResponse((Path(__file__).resolve().parents[1] / 'assets' / 'arby.webp').open('rb'), content_type='image/webp')

    def visits_report(request):
        result = report(database, request.GET.get('start'), request.GET.get('end'))
        status = runtime_status(database)
        health = status.get('visits', {})
        result['incomplete'] = result['incomplete'] or bool(health.get('incomplete'))
        result['error'] = health.get('error')
        return result

    @route('/api/visits', ['GET'])
    def visits(request):
        return jsonify(visits_report(request))

    @route('/api/visits/export.csv', ['GET'])
    def export_visits(request):
        from datetime import datetime
        result = visits_report(request)
        output = io.StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow(['id', 'inicio_America_Bogota', 'ultima_actividad_America_Bogota',
                         'cierre_America_Bogota', 'motivo_cierre', 'mensajes', 'conteo_incompleto'])
        for visit in result['visits']:
            dates = [datetime.fromisoformat(visit[key]).astimezone(BOGOTA).isoformat()
                     if visit[key] else '' for key in ('started_at', 'last_activity_at', 'ended_at')]
            writer.writerow([visit['id'], *dates, visit['close_reason'] or 'active',
                             visit['messages'], result['incomplete']])
        return HttpResponse(output.getvalue(), content_type='text/csv', headers={
            'Content-Disposition': 'attachment; filename="arby-visitas.csv"'})

    @route('/api/session', ['GET'])
    def session_info(request):
        return jsonify(authenticated=bool(request.session.get('role')), role=request.session.get('role'), csrf=get_token(request))

    @route('/api/login', ['POST'])
    def login(request):
        key = request.META.get('REMOTE_ADDR') or 'local'
        now = time.monotonic()
        with login_lock:
            for address in list(attempts):
                attempts[address] = [stamp for stamp in attempts[address] if now - stamp < 60]
                if not attempts[address]:
                    del attempts[address]
            if len(attempts.get(key, [])) >= 5 or sum(map(len, attempts.values())) >= 30:
                return jsonify(error='Demasiados intentos. Espera un minuto.'), 429
            attempts.setdefault(key, []).append(now)
        data = body(request)
        password, role = data.get('password', ''), data.get('role', 'admin')
        chosen_hash = {'admin': password_hash, 'comercial': commercial_password_hash}.get(role) if isinstance(role, str) else None
        valid = False
        if chosen_hash and isinstance(password, str):
            valid = (check_password_hash(chosen_hash, password) if chosen_hash.startswith(('scrypt:', 'pbkdf2:'))
                     else check_password(password, chosen_hash))
        if not valid:
            return jsonify(error='Clave incorrecta.'), 401
        request.session.flush()
        request.session['role'] = role
        rotate_token(request)
        return jsonify(role=role, csrf=get_token(request))

    @route('/api/logout', ['POST'])
    def logout(request):
        request.session.flush()
        return jsonify(ok=True)

    @route('/api/status', ['GET'])
    def status(request):
        live = runtime_status(database)
        saved = settings(database)
        effective = live.get('effective', {})
        from libraries.core.arby_support import configuration_revision
        revision = configuration_revision(database)
        if 'configuration_revision' in effective:
            live['pending_changes'] = effective['configuration_revision'] != revision
        else:
            # Old runtime snapshots remain readable during the transition.
            live['pending_changes'] = bool(effective) and (revision != '0' or saved['ambient'] != effective.get('ambient') or any(effective.get('controls', {}).get(key) != value for key, value in saved['controls'].items()) or saved['audio'] != effective.get('audio', {'input': None, 'output': None}))
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
        if request.session.get('role') == 'comercial':
            live.pop('debug', None)
            live.pop('configuration', None)
            saved['controls'] = {key: value for key, value in saved['controls'].items() if key in COMMERCIAL_CONTROLS}
            if 'effective' in live:
                live['effective'] = {**live['effective'], 'controls': {key: value for key, value in live['effective'].get('controls', {}).items() if key in COMMERCIAL_CONTROLS}}
        return jsonify(role=request.session.get('role'), runtime=live, saved=saved, defaults=defaults, commands=commands,
                       tests=[{'id': key, 'label': item['label'], 'requires': item['requires']} for key, item in TESTS.items()])

    @route('/api/settings', ['PUT'])
    def update_settings(request):
        payload = body(request)
        if request.session.get('role') == 'comercial':
            if set(payload.get('controls', {})) - COMMERCIAL_CONTROLS or 'audio' in payload:
                return jsonify(error='Estos ajustes requieren el perfil admin.'), 403
        save_settings(payload, database)
        return jsonify(ok=True)

    @route('/api/tests', ['POST'])
    def tests(request):
        return jsonify(id=enqueue(body(request).get('kind'), database)), 202

    @route('/api/audio/devices', ['GET'])
    def audio_devices(request):
        return jsonify(inventory(load_selection(database)))

    @route('/api/tests/cancel', ['POST'])
    def cancel_test(request):
        return jsonify(id=enqueue('cancel', database)), 202

    @route('/api/power', ['POST'])
    def power(request):
        if body(request).get('target') != 'shutdown':
            raise ValueError('Acción de energía no permitida.')
        return jsonify(system('shutdown'))

    @route('/api/network', ['GET'])
    def network(request):
        return jsonify(system('network'))

    @route('/api/network/connect', ['POST'])
    def network_connect(request):
        data = body(request)
        values = {'ssid': data.get('ssid'), 'password': data.get('password', '')}
        if 'use_saved' in data:
            if type(data['use_saved']) is not bool:
                raise ValueError('La opción de red guardada debe ser booleana.')
            values['use_saved'] = data['use_saved']
        return jsonify(system('wifi', **values))

    @route('/api/bluetooth', ['GET'])
    def bluetooth_status(request):
        return jsonify(system('bluetooth'))

    @route('/api/bluetooth/<str:operation>', ['POST'])
    def bluetooth_action(request, operation):
        if operation not in ('scan', 'connect', 'disconnect'):
            raise ValueError('Acción Bluetooth no permitida.')
        if operation == 'scan':
            return jsonify(system('bluetooth_scan'))
        import re
        address = body(request).get('address')
        if not isinstance(address, str) or not re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}', address):
            raise ValueError('Dirección Bluetooth inválida.')
        return jsonify(system('bluetooth_' + operation, address=address))

    @route('/api/restart', ['POST'])
    def restart(request):
        target = body(request).get('target')
        if request.session.get('role') == 'comercial' and target != 'arby':
            return jsonify(error='Esta opción requiere el perfil admin.'), 403
        if target not in ('arby', 'raspberry'):
            raise ValueError('Reinicio no permitido.')
        return jsonify(system(target))

    @route('/static/<str:filename>', ['GET'])
    def static_file(request, filename):
        if filename not in ('portal.css', 'portal.js'):
            return HttpResponse(status=404)
        content_type = 'text/css' if filename.endswith('.css') else 'text/javascript'
        return FileResponse((Path(__file__).parent / 'static' / filename).open('rb'), content_type=content_type)

    @route('/api/admin/configuration', ['GET', 'PUT'])
    def configuration(request):
        from portal.configuration import describe, save_configuration
        if request.method == 'PUT':
            save_configuration(body(request), database)
        return jsonify(describe(database))

    return PortalHandler(patterns)


def main():
    from waitress import serve
    serve(create_app(), host=os.getenv('ARBY_PORTAL_HOST', '0.0.0.0'),
          port=int(os.getenv('ARBY_PORTAL_PORT', '8080')), threads=4)


if __name__ == '__main__':
    main()
