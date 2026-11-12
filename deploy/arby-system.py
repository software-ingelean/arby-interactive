#!/usr/bin/python3
"""Root-owned, stdlib-only helper. Install as /usr/local/libexec/arby-system.py.

Only fixed operations, no shell, no caller-selected devices or service names.
"""
import json
import os
import subprocess
import sys
import tempfile


def run(args, timeout=25):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=True,
                          env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C'})


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


def execute(data):
    action = data.get('action')
    if action == 'arby':
        run(['/usr/bin/systemctl', '--no-block', 'restart', 'arby.service'])
        return {'ok': True, 'message': 'Reinicio de Arby solicitado.'}
    if action == 'raspberry':
        # A short delay allows the HTTP response to reach the browser.
        run(['/usr/bin/systemd-run', '--on-active=3s', '/usr/bin/systemctl', 'reboot'])
        return {'ok': True, 'message': 'La Raspberry se reiniciará en unos segundos.'}
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
    if action == 'wifi':
        ssid, password = data.get('ssid'), data.get('password')
        if (not isinstance(ssid, str) or not 1 <= len(ssid.encode()) <= 32 or ssid.startswith('-')
                or not isinstance(password, str) or len(password) > 128
                or any(c in ssid + password for c in '\r\n\x00')):
            raise ValueError('Invalid Wi-Fi parameters')
        # The password is never a process argument or a log entry.
        with tempfile.NamedTemporaryFile(mode='w', prefix='arby-wifi-') as credentials:
            credentials.write('802-11-wireless-security.psk:' + password + '\n')
            credentials.flush()
            run(['/usr/bin/nmcli', '--wait', '20', '--passwd-file', credentials.name,
                 'device', 'wifi', 'connect', ssid, 'ifname', 'wlan0'])
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
