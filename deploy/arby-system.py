#!/usr/bin/python3
"""Root-owned, stdlib-only helper. Install as /usr/local/libexec/arby-system.py.

Only fixed operations, no shell, no caller-selected devices or service names.
"""
import json
import os
import re
import subprocess
import sys


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


def bluetooth(command, *args, seconds=4):
    result = run(['/usr/bin/bluetoothctl', '--timeout', str(seconds), command, *args], timeout=seconds + 2)
    if any(error in result.stdout for error in ('Failed', 'not available', 'No default controller')):
        raise ValueError('Bluetooth no disponible')
    return result.stdout


def bluetooth_properties(output):
    return dict(line.strip().split(': ', 1) for line in output.splitlines() if ': ' in line)


def bluetooth_status():
    controller = bluetooth_properties(bluetooth('show'))
    rows = bluetooth('devices')
    connected = bluetooth('devices', 'Connected')
    paired = bluetooth('devices', 'Paired')
    devices = []
    for line in rows.splitlines():
        match = re.fullmatch(r'Device ((?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}) (.+)', line)
        if match:
            address, name = match.groups()
            devices.append({'address': address, 'name': name,
                            'connected': f'Device {address} ' in connected,
                            'paired': f'Device {address} ' in paired})
    return {'powered': controller.get('Powered') == 'yes', 'devices': devices}


def execute(data):
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
        bluetooth('scan', 'on', seconds=8)
        return bluetooth_status()
    if action in ('bluetooth_connect', 'bluetooth_disconnect'):
        address = data.get('address')
        if not isinstance(address, str) or not re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}', address):
            raise ValueError('Invalid Bluetooth address')
        if action == 'bluetooth_disconnect':
            bluetooth('disconnect', address, seconds=10)
            return {'ok': True, 'message': 'Dispositivo desconectado.'}
        info = bluetooth_properties(bluetooth('info', address))
        if info.get('Paired') != 'yes':
            result = run(['/usr/bin/bluetoothctl', '--agent', 'NoInputNoOutput', '--timeout', '15', 'pair', address], timeout=17)
            if 'Pairing successful' not in result.stdout:
                raise ValueError('Pairing failed')
        bluetooth('connect', address, seconds=10)
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
