"""Discover ALSA hardware without opening it; persist identity instead of card indexes."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess

from libraries.core.arby_ambient import DEFAULT_DATABASE

IDENTITY_FIELDS = {'driver', 'name', 'vendor', 'product', 'serial', 'port', 'pcm'}
EMPTY_SELECTION = {'input': None, 'output': None}


def read_text(path):
    try:
        return path.read_text().strip()
    except (OSError, UnicodeError):
        return ''


def validate_selection(value):
    if not isinstance(value, dict) or set(value) != set(EMPTY_SELECTION):
        raise ValueError('Selecciona entrada y salida de audio.')
    for preference in value.values():
        if preference is None:
            continue
        if not isinstance(preference, dict) or set(preference) != IDENTITY_FIELDS:
            raise ValueError('Identidad de audio inválida.')
        if type(preference['pcm']) is not int or not 0 <= preference['pcm'] <= 255:
            raise ValueError('Canal de audio inválido.')
        for key in IDENTITY_FIELDS - {'pcm'}:
            field = preference[key]
            if not isinstance(field, str) or len(field) > 256 or any(ord(c) < 32 for c in field):
                raise ValueError('Identidad de audio inválida.')
        if not preference['name'] or not preference['driver']:
            raise ValueError('El dispositivo necesita nombre y controlador.')
    return value


def load_selection(database=DEFAULT_DATABASE):
    if not Path(database).exists():
        return dict(EMPTY_SELECTION)
    with closing(sqlite3.connect(database, timeout=0.05)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='support_audio_settings'").fetchone():
            return dict(EMPTY_SELECTION)
        row = db.execute('SELECT value FROM support_audio_settings WHERE id=1').fetchone()
    return validate_selection(json.loads(row[0])) if row else dict(EMPTY_SELECTION)


def device_key(identity):
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]


def discover_devices(proc=Path('/proc/asound'), sound=Path('/sys/class/sound')):
    """Read the same physical inventory for the unprivileged portal and root runtime.

    PortAudio/ALSA plugin devices are intentionally excluded: a playback-only
    Headphones card can never become a microphone just because indexes move.
    """
    devices = []
    for line in read_text(proc / 'pcm').splitlines():
        match = re.match(r'\s*(\d+)-(\d+):\s*([^:]+)', line)
        if not match:
            continue
        card, pcm = int(match[1]), int(match[2])
        node = (sound / f'card{card}' / 'device').resolve()
        driver_link = node / 'driver'
        driver = driver_link.resolve().name if driver_link.exists() else 'alsa'
        usb = next((p for p in (node, *node.parents) if (p / 'idVendor').is_file()), None)
        identity = {
            'driver': driver,
            'name': (read_text(usb / 'product') if usb else '') or match[3].strip(),
            'vendor': read_text(usb / 'idVendor') if usb else '',
            'product': read_text(usb / 'idProduct') if usb else '',
            'serial': read_text(usb / 'serial') if usb else '',
            'port': usb.name if usb else str(node),
            'pcm': pcm,
        }
        for role, token in (('input', 'capture'), ('output', 'playback')):
            count = re.search(rf'\b{token}\s+(\d+)', line)
            if count and int(count[1]) > 0:
                devices.append({'id': f'{role}-{device_key(identity)}', 'role': role,
                                'name': identity['name'], 'identity': identity, 'card': card,
                                'detail': f"{driver} · {identity['port']} · PCM {pcm}"})
    if proc == Path('/proc/asound') and sound == Path('/sys/class/sound'):
        devices.extend(discover_bluetooth_outputs())
    return devices


def command_output(argv):
    try:
        return subprocess.run(argv, capture_output=True, text=True, check=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return ''


def bluetooth_output(driver, name, address, endpoint):
    identity = {'driver': driver, 'name': name, 'vendor': '', 'product': '',
                'serial': address.upper(), 'port': endpoint, 'pcm': 0}
    return {'id': f'output-{device_key(identity)}', 'role': 'output', 'name': name,
            'identity': identity, 'detail': f'Bluetooth · {driver} · {address}'}


def discover_bluetooth_outputs():
    """List playback endpoints exposed to this service, without opening audio."""
    devices = []
    try:
        sinks = json.loads(command_output(['pactl', '--format=json', 'list', 'sinks']) or '[]')
    except (ValueError, TypeError):
        sinks = []
    for sink in sinks if isinstance(sinks, list) else []:
        if not isinstance(sink, dict):
            continue
        endpoint = sink.get('name', '')
        if not isinstance(endpoint, str) or not endpoint.startswith(('bluez_output.', 'bluez_sink.')):
            continue
        match = re.search(r'((?:[0-9A-Fa-f]{2}_){5}[0-9A-Fa-f]{2})', endpoint)
        if match:
            devices.append(bluetooth_output('pulse-bluetooth', sink.get('description') or endpoint,
                                            match[1].replace('_', ':'), endpoint))
    rows = command_output(['bluealsa-aplay', '-L']).splitlines()
    for index, row in enumerate(rows):
        match = re.fullmatch(r'bluealsa:DEV=((?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}),PROFILE=(a2dp|sco),SRV=([A-Za-z0-9_.-]+)', row)
        if not match or index + 1 >= len(rows):
            continue
        description = rows[index + 1].strip()
        if not description.endswith(', playback'):
            continue
        address = match[1]
        devices.append(bluetooth_output('bluealsa', description.split(',')[0], address, row))
    return devices


def find_preferred(preference, role, devices):
    """Prefer serial, then physical port, then an unambiguous model match."""
    if preference['driver'] == 'pulse-bluetooth':
        keys = ('driver', 'serial', 'pcm')
    elif preference['driver'] == 'bluealsa':
        keys = ('driver', 'serial', 'port', 'pcm')
    else:
        keys = ('driver', 'name', 'vendor', 'product', 'pcm')
    candidates = [d for d in devices if d['role'] == role and
                  all(d['identity'][key] == preference[key] for key in keys)]
    if preference['serial']:
        candidates = [d for d in candidates if d['identity']['serial'] == preference['serial']]
    else:
        same_port = [d for d in candidates if d['identity']['port'] == preference['port']]
        if same_port:
            candidates = same_port
    if not candidates:
        raise ValueError('El dispositivo de audio predeterminado no está conectado. Conéctalo o elige otro en Audio.')
    if len(candidates) != 1:
        raise ValueError('Hay varios dispositivos de audio iguales. Selecciona el puerto correcto en Audio.')
    return candidates[0]


def portaudio_input(device, sounddevice):
    """Resolve the current ALSA hardware to an input-capable PortAudio index."""
    card, pcm = device['card'], device['identity']['pcm']
    matches = []
    for index, info in enumerate(sounddevice.query_devices()):
        if info['max_input_channels'] < 1:
            continue
        hardware = re.search(r'\(hw:(\d+),(\d+)\)', info['name'])
        if hardware and (int(hardware[1]), int(hardware[2])) == (card, pcm):
            matches.append(index)
    if len(matches) != 1:
        raise ValueError('El micrófono preferido no está disponible como entrada de captura. Revisa Audio.')
    return matches[0]


def apply_selection(config, selection, *, devices=None, sounddevice=None):
    """Resolve once per startup; never silently switch to an unrelated device."""
    devices = discover_devices() if devices is None else devices
    active = {}
    if selection['input'] is not None and config.input_mode == 'voice':
        device = find_preferred(selection['input'], 'input', devices)
        if sounddevice is None:
            import sounddevice
        config.microphone.device_identity = dict(selection['input'])
        config.microphone.device = portaudio_input(device, sounddevice)
        config.mic_device = str(config.microphone.device)
        active['input'] = {'name': device['name'], 'detail': device['detail']}
    if selection['output'] is not None and not config.mute:
        device = find_preferred(selection['output'], 'output', devices)
        card_id = read_text(Path('/proc/asound') / f"card{device['card']}" / 'id') if 'card' in device else ''
        # Use the current ALSA identifier where available, matching existing recovery rules.
        if device['identity']['driver'] in ('bluealsa', 'pulse-bluetooth'):
            config.audio_device = device['identity']['port']
        elif card_id and re.fullmatch(r'[A-Za-z0-9_]+', card_id):
            config.audio_device = f"plughw:CARD={card_id},DEV={device['identity']['pcm']}"
        else:
            config.audio_device = f"plughw:{device['card']},{device['identity']['pcm']}"
        config.audio_driver = 'pulseaudio' if device['identity']['driver'] == 'pulse-bluetooth' else 'alsa'
        active['output'] = {'name': device['name'], 'detail': device['detail']}
    if selection['output'] is not None and selection['output']['driver'] in ('bluealsa', 'pulse-bluetooth'):
        # Jack recovery applies only to the physical Headphones output.
        config.audio_recover_on_exit = False
    if config.audio_recover_on_exit and (config.audio_driver != 'alsa' or config.audio_device != 'plughw:CARD=Headphones,DEV=0'):
        raise ValueError('La recuperación del jack requiere seleccionar Headphones o desactivar ARBY_AUDIO_RECOVER_ON_EXIT.')
    return active


def inventory(selection, devices=None):
    devices = discover_devices() if devices is None else devices
    preferred = {}
    for role, preference in selection.items():
        if preference is None:
            preferred[role] = {'state': 'environment', 'message': 'Se usa la configuración de .env.'}
            continue
        try:
            device = find_preferred(preference, role, devices)
            preferred[role] = {'state': 'available', 'id': device['id'], 'message': 'Predeterminado conectado.'}
        except ValueError as exc:
            preferred[role] = {'state': 'unavailable', 'message': str(exc)}
    return {'devices': devices, 'preferred': preferred,
            'message': 'Audio de la Raspberry, incluidas salidas Bluetooth conectadas y disponibles para este servicio. Si falta una, conéctala en Conexión y comprueba BlueALSA o PulseAudio/PipeWire.' if devices else
                       'No se detectaron dispositivos de audio. Para Bluetooth, conecta el altavoz en Conexión y comprueba que BlueALSA o PulseAudio/PipeWire esté disponible para el servicio de Arby.'}
