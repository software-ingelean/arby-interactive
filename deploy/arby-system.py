#!/usr/bin/python3
"""Root-owned, stdlib-only helper. Install as /usr/local/libexec/arby-system.py.

Only fixed operations, no shell, no caller-selected devices or service names.
"""
import json
import os
import re
import subprocess
import sys
import time


def run(args, timeout=25, input=None):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=True,
                          input=input, env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C'})


def split_fields(line):
    fields, current, escaped = [], '', False
    for char in line:
        if escaped:
            current += char
            escaped = False
        elif char == '\\':
            escaped = True
        elif char == ':':
            fields.append(current)
            current = ''
        else:
            current += char
    return fields + [current]


class BluetoothFailure(ValueError):
    pass


def bluetooth(command, *args, seconds=4):
    try:
        # --timeout keeps BlueZ alive even after a command succeeds.
        # Discovery needs this window; other commands exit on completion.
        options = ['--timeout', str(seconds)] if command == 'scan' else []
        result = run(['/usr/bin/bluetoothctl', *options, command, *args], timeout=seconds + 2)
    except subprocess.CalledProcessError as exc:
        raise BluetoothFailure((exc.stdout or '') + '\n' + (exc.stderr or '')) from exc
    if any(error in result.stdout for error in ('Failed', 'not available', 'No default controller')):
        raise BluetoothFailure(result.stdout)
    return result.stdout


def bluetooth_properties(output):
    return dict(line.strip().split(': ', 1) for line in output.splitlines() if ': ' in line)


def bluetooth_name(value, address):
    value = value.strip()
    if not value or value.lower().replace('-', ':') == address.lower():
        return None
    return value


def bluetooth_status():
    controller = bluetooth_properties(bluetooth('show'))
    rows = bluetooth('devices')
    connected = bluetooth('devices', 'Connected')
    paired = bluetooth('devices', 'Paired')
    devices = []
    name_deadline = time.monotonic() + 8
    for line in rows.splitlines():
        match = re.fullmatch(r'Device ((?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}) (.+)', line)
        if match:
            address, name = match.groups()
            name = bluetooth_name(name, address)
            if not name and time.monotonic() < name_deadline:
                try:
                    properties = bluetooth_properties(bluetooth('info', address, seconds=1))
                    name = (bluetooth_name(properties.get('Name', ''), address)
                            or bluetooth_name(properties.get('Alias', ''), address))
                except (ValueError, OSError, subprocess.SubprocessError):
                    pass
            name = name or 'Dispositivo sin nombre'
            devices.append({'address': address, 'name': name,
                            'connected': f'Device {address} ' in connected,
                            'paired': f'Device {address} ' in paired})
    return {'powered': controller.get('Powered') == 'yes', 'devices': devices}


def execute(data):
    try:
        return execute_action(data)
    except subprocess.TimeoutExpired:
        if data.get('action') in ('bluetooth', 'bluetooth_scan'):
            return {'error_code': 'bluetooth_timeout'}
        raise
    except BluetoothFailure as exc:
        if data.get('action') in ('bluetooth', 'bluetooth_scan'):
            detail = str(exc).lower()
            unavailable = any(value in detail for value in ('no default controller', 'notready', 'blocked'))
            return {'error_code': 'bluetooth_unavailable' if unavailable else 'bluetooth_scan_failed'}
        raise
    except FileNotFoundError:
        if data.get('action') in ('bluetooth', 'bluetooth_scan', 'bluetooth_connect', 'bluetooth_disconnect'):
            return {'error_code': 'bluetooth_missing'}
        raise


def execute_action(data):
    action = data.get('action')
    if action == 'arby':
        run(['/usr/bin/systemctl', '--no-block', 'restart', 'arby.service'])
        return {'ok': True, 'message': 'Reinicio de Arby solicitado.'}
    if action in ('raspberry', 'shutdown'):
        # A short delay allows the HTTP response to reach the browser.
        operation = 'poweroff' if action == 'shutdown' else 'reboot'
        run(['/usr/bin/systemd-run', '--on-active=3s', '/usr/bin/systemctl', operation])
        return {'ok': True, 'message': 'La Raspberry se apagará en unos segundos. Espera antes de retirar la alimentación.' if action == 'shutdown' else 'La Raspberry se reiniciará en unos segundos.'}
    if action == 'network':
        devices = run(['/usr/bin/nmcli', '-t', '-f', 'DEVICE,TYPE,STATE,CONNECTION', 'device']).stdout
        addresses = run(['/usr/bin/hostname', '-I']).stdout.strip().split()
        connectivity = run(['/usr/bin/nmcli', '-t', '-f', 'CONNECTIVITY', 'general']).stdout.strip()
        rows = run(['/usr/bin/nmcli', '-t', '-f', 'SSID,SIGNAL,SECURITY', 'device', 'wifi', 'list', 'ifname', 'wlan0', '--rescan', 'auto']).stdout
        networks = []
        for line in rows.splitlines():
            fields = split_fields(line)
            if len(fields) == 3 and fields[0] and fields[0] not in [item['ssid'] for item in networks]:
                networks.append(dict(zip(('ssid', 'signal', 'security'), fields)))
        return {'devices': [split_fields(line) for line in devices.splitlines()],
                'addresses': addresses, 'connectivity': connectivity, 'networks': networks}
    if action == 'bluetooth':
        return bluetooth_status()
    if action == 'bluetooth_scan':
        bluetooth('power', 'on')
        # Give classic discovery its own window for headphones, then include
        # LE devices as well. Names are resolved by BlueZ during discovery.
        try:
            bluetooth('scan', 'bredr', seconds=8)
        except (ValueError, subprocess.CalledProcessError):
            # Some controllers only support LE; retain general discovery.
            pass
        bluetooth('scan', 'on', seconds=8)
        return bluetooth_status()
    if action in ('bluetooth_connect', 'bluetooth_disconnect'):
        address = data.get('address')
        if not isinstance(address, str) or not re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}', address):
            raise ValueError('Invalid Bluetooth address')
        stage = 'disconnect' if action == 'bluetooth_disconnect' else 'connect'
        try:
            if action == 'bluetooth_disconnect':
                bluetooth('disconnect', address, seconds=10)
                return {'ok': True, 'message': 'Dispositivo desconectado.'}
            bluetooth('power', 'on')
            try:
                info = bluetooth_properties(bluetooth('info', address))
            except BluetoothFailure as exc:
                detail = str(exc).lower()
                if 'no default controller' in detail or not any(
                        marker in detail for marker in ('not available', 'doesnotexist')):
                    raise
                # An unpaired discovery result can expire while the portal is
                # open. Rediscover once before trying to pair this exact address.
                bluetooth('scan', 'on', seconds=5)
                info = bluetooth_properties(bluetooth('info', address))
            if info.get('Paired') != 'yes':
                stage = 'pair'
                try:
                    result = run(['/usr/bin/bluetoothctl', '--agent', 'NoInputNoOutput', 'pair', address], timeout=17)
                except subprocess.CalledProcessError as exc:
                    raise BluetoothFailure((exc.stdout or '') + '\n' + (exc.stderr or '')) from exc
                if 'Pairing successful' not in result.stdout:
                    raise BluetoothFailure(result.stdout)
            stage = 'connect'
            bluetooth('trust', address)
            bluetooth('connect', address, seconds=10)
            if bluetooth_properties(bluetooth('info', address)).get('Connected') != 'yes':
                return {'error_code': 'bluetooth_connect_failed'}
        except subprocess.TimeoutExpired:
            return {'error_code': 'bluetooth_timeout'}
        except BluetoothFailure as exc:
            detail = str(exc).lower()
            if 'no default controller' in detail or 'notready' in detail:
                code = 'bluetooth_unavailable'
            elif 'not available' in detail or 'doesnotexist' in detail:
                code = 'bluetooth_not_found'
            elif 'authentication' in detail or 'rejected' in detail:
                code = 'bluetooth_auth_failed'
            elif 'br-connection-profile-unavailable' in detail:
                code = 'bluetooth_audio_unavailable'
            else:
                code = 'bluetooth_' + stage + '_failed'
            return {'error_code': code}
        return {'ok': True, 'message': 'Dispositivo conectado.'}
    if action == 'wifi':
        ssid, password = data.get('ssid'), data.get('password')
        if (not isinstance(ssid, str) or not 1 <= len(ssid.encode()) <= 32 or ssid.startswith('-')
                or not isinstance(password, str) or len(password) > 128
                or any(c in ssid + password for c in '\r\n\x00')):
            raise ValueError('Invalid Wi-Fi parameters')
        # Answer nmcli's secret prompt through stdin, never argv or logs.
        # passwd-file belongs to `connection up`, not `device wifi connect`.
        try:
            run(['/usr/bin/nmcli', '--wait', '20', '--ask',
                 'device', 'wifi', 'connect', ssid, 'ifname', 'wlan0'],
                input=password + '\n')
        except subprocess.TimeoutExpired:
            return {'error_code': 'wifi_timeout'}
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or '').lower()
            if 'no network with ssid' in detail:
                return {'error_code': 'wifi_not_found'}
            if 'secrets' in detail or 'password' in detail:
                return {'error_code': 'wifi_credentials'}
            return {'error_code': 'wifi_failed'}
        return {'ok': True, 'message': 'Conexión solicitada. Busca la nueva IP si el panel se desconecta.'}
    raise ValueError('Unsupported action')


if __name__ == '__main__':
    try:
        raw = sys.stdin.read(8193)
        if len(raw) > 8192:
            raise ValueError('Too much input')
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError('Invalid input')
        print(json.dumps(execute(data)))
    except Exception:
        # Deliberately omit subprocess diagnostics: these can contain network details.
        print(json.dumps({'error': 'Action failed'}))
        sys.exit(1)
