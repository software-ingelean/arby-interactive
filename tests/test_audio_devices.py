"""Physical audio identity must survive ALSA/PortAudio reordering and fail closed."""
from contextlib import closing
from copy import deepcopy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from libraries.audio.arby_devices import (
    apply_selection, discover_devices, find_preferred, inventory,
    load_selection, portaudio_input, validate_selection, discover_bluetooth_outputs, bluetooth_output,
)
from libraries.core.arby_support import initialize, save_settings, settings


def identity(**updates):
    result = {'driver': 'snd-usb-audio', 'name': 'USB Audio CODEC', 'vendor': '08bb',
              'product': '2902', 'serial': '', 'port': '1-1.2', 'pcm': 0}
    return {**result, **updates}


def device(role='input', card=1, **updates):
    return {'id': f'{role}-{card}', 'role': role, 'card': card, 'name': 'USB Audio CODEC',
            'identity': identity(**updates), 'detail': 'USB audio'}


class AudioIdentityTests(unittest.TestCase):
    def test_bluetooth_outputs_are_discovered_with_stable_identity(self):
        import json
        outputs = {
            'pactl': json.dumps([{'name': 'bluez_output.AA_BB_CC_DD_EE_FF.1', 'description': 'Altavoz'}]),
            'bluealsa-aplay': 'bluealsa:DEV=11:22:33:44:55:66,PROFILE=a2dp,SRV=org.bluealsa\n    Audífonos, trusted audio-headset, playback\n    A2DP (SBC)\nbluealsa:DEV=11:22:33:44:55:66,PROFILE=sco,SRV=org.bluealsa\n    Audífonos, trusted audio-headset, capture\n',
        }
        with patch('libraries.audio.arby_devices.command_output', side_effect=lambda argv: outputs[argv[0]]):
            devices = discover_bluetooth_outputs()
        self.assertEqual(len(devices), 2)
        self.assertEqual({d['role'] for d in devices}, {'output'})
        self.assertEqual(devices[0]['identity']['serial'], 'AA:BB:CC:DD:EE:FF')
        validate_selection({'input': None, 'output': devices[1]['identity']})

    def test_bluetooth_selection_uses_endpoint_after_rename(self):
        for driver, endpoint, audio_driver in [
                ('bluealsa', 'bluealsa:DEV=AA:BB:CC:DD:EE:FF,PROFILE=a2dp,SRV=org.bluealsa', 'alsa'),
                ('pulse-bluetooth', 'bluez_output.AA_BB_CC_DD_EE_FF.1', 'pulseaudio')]:
            with self.subTest(driver=driver):
                original = bluetooth_output(driver, 'Nombre anterior', 'AA:BB:CC:DD:EE:FF', endpoint)
                current = bluetooth_output(driver, 'Nombre nuevo', 'AA:BB:CC:DD:EE:FF', endpoint)
                config = SimpleNamespace(input_mode='text', mute=False, audio_recover_on_exit=True)
                apply_selection(config, {'input': None, 'output': original['identity']}, devices=[current])
                self.assertEqual(config.audio_device, endpoint)
                self.assertEqual(config.audio_driver, audio_driver)
                self.assertFalse(config.audio_recover_on_exit)
                with self.assertRaises(ValueError):
                    apply_selection(config, {'input': None, 'output': original['identity']}, devices=[])

    def test_missing_bluetooth_audio_services_leave_inventory_usable(self):
        with patch('libraries.audio.arby_devices.command_output', return_value=''):
            self.assertEqual(discover_bluetooth_outputs(), [])

    def test_reordered_card_resolves_current_portaudio_input(self):
        preferred = identity()
        current = device(card=4)
        sd = SimpleNamespace(query_devices=lambda: [
            {'name': 'Headphones (hw:1,0)', 'max_input_channels': 0},
            {'name': 'USB Audio CODEC (hw:4,0)', 'max_input_channels': 2},
        ])
        config = SimpleNamespace(input_mode='voice', mute=True, microphone=SimpleNamespace(device=0),
                                 audio_recover_on_exit=False)
        result = apply_selection(config, {'input': preferred, 'output': None}, devices=[current], sounddevice=sd)
        self.assertEqual(config.microphone.device, 1)
        self.assertEqual(result['input']['name'], 'USB Audio CODEC')
        self.assertNotIn('card', preferred)

    def test_playback_only_card_can_never_be_selected_for_capture(self):
        with self.assertRaises(ValueError):
            find_preferred(identity(), 'input', [device(role='output')])
        sd = SimpleNamespace(query_devices=lambda: [{'name': 'Headphones (hw:1,0)', 'max_input_channels': 0}])
        with self.assertRaises(ValueError):
            portaudio_input(device(), sd)

    def test_serial_survives_port_change(self):
        selected = find_preferred(identity(serial='one'), 'input',
                                  [device(serial='two'), device(card=5, serial='one', port='1-1.5')])
        self.assertEqual(selected['card'], 5)

    def test_missing_serial_does_not_switch_to_another_unit(self):
        with self.assertRaises(ValueError):
            find_preferred(identity(serial='missing'), 'input', [device(serial='other')])

    def test_without_serial_prefers_port_then_unique_model(self):
        candidates = [device(port='1-1.3'), device(card=2)]
        self.assertEqual(find_preferred(identity(), 'input', candidates)['card'], 2)
        self.assertEqual(find_preferred(identity(), 'input', candidates[:1])['card'], 1)

    def test_same_driver_is_not_enough_and_ambiguity_is_reported(self):
        with self.assertRaises(ValueError):
            find_preferred(identity(), 'input', [device(product='different')])
        with self.assertRaisesRegex(ValueError, 'varios'):
            find_preferred(identity(port='gone'), 'input', [device(port='one'), device(card=2, port='two')])

    def test_absent_preference_is_visible_in_portal(self):
        result = inventory({'input': identity(), 'output': None}, [])
        self.assertEqual(result['preferred']['input']['state'], 'unavailable')
        self.assertEqual(result['preferred']['output']['state'], 'environment')

    def test_output_is_resolved_independently_from_microphone(self):
        config = SimpleNamespace(input_mode='text', mute=False, audio_recover_on_exit=False)
        with patch('libraries.audio.arby_devices.read_text', return_value='Device_1'):
            apply_selection(config, {'input': None, 'output': identity()}, devices=[device(role='output', card=5)])
        self.assertEqual(config.audio_driver, 'alsa')
        self.assertEqual(config.audio_device, 'plughw:CARD=Device_1,DEV=0')

    def test_output_recovery_cannot_be_redirected_to_usb(self):
        config = SimpleNamespace(input_mode='text', mute=False, audio_recover_on_exit=True)
        with patch('libraries.audio.arby_devices.read_text', return_value='Device'), self.assertRaises(ValueError):
            apply_selection(config, {'input': None, 'output': identity()}, devices=[device(role='output')])

    def test_muted_output_and_text_input_do_not_require_absent_devices(self):
        config = SimpleNamespace(input_mode='text', mute=True, audio_recover_on_exit=False)
        result = apply_selection(config, {'input': identity(), 'output': identity()}, devices=[])
        self.assertEqual(result, {})

    def test_invalid_descriptors_and_old_numeric_ids_are_rejected(self):
        for invalid in (1, {'card': 1}, identity(pcm=-1), identity(serial='bad\nvalue')):
            with self.assertRaises(ValueError):
                validate_selection({'input': invalid, 'output': None})

    def test_selection_persists_without_changing_existing_controls(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / 'settings.sqlite3'
            initialize(database)
            payload = settings(database)
            payload['audio']['input'] = identity()
            save_settings(payload, database)
            self.assertEqual(load_selection(database)['input'], identity())
            # Simulate closing the portal and loading settings on the next boot.
            initialize(database)
            self.assertEqual(load_selection(database)['input'], identity())
            bluetooth = bluetooth_output('bluealsa', 'Altavoz', 'AA:BB:CC:DD:EE:FF',
                                         'bluealsa:DEV=AA:BB:CC:DD:EE:FF,PROFILE=a2dp,SRV=org.bluealsa')
            payload['audio']['output'] = bluetooth['identity']
            save_settings(payload, database)
            initialize(database)
            self.assertEqual(load_selection(database)['output'], bluetooth['identity'])
            # Old clients may omit audio; the saved device must not be cleared.
            del payload['audio']
            save_settings(payload, database)
            self.assertEqual(load_selection(database)['input'], identity())
            with closing(__import__('sqlite3').connect(database)) as db:
                saved = db.execute('SELECT value FROM support_audio_settings').fetchone()[0]
            self.assertNotIn('"card"', saved)

    def test_discovery_reads_capture_and_playback_without_opening_devices(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            proc, sound = root / 'proc', root / 'sound'
            proc.mkdir()
            sound.mkdir()
            usb = root / 'devices' / '1-1.2'
            interface = usb / '1-1.2:1.0'
            interface.mkdir(parents=True)
            driver = root / 'drivers' / 'snd-usb-audio'
            driver.mkdir(parents=True)
            (interface / 'driver').symlink_to(driver)
            for key, value in {'idVendor': '08bb', 'idProduct': '2902', 'product': 'USB Audio CODEC', 'serial': 'ABC'}.items():
                (usb / key).write_text(value)
            (sound / 'card7').mkdir()
            (sound / 'card7' / 'device').symlink_to(interface)
            (proc / 'pcm').write_text('07-00: USB Audio : USB Audio : playback 1 : capture 1\n')
            result = discover_devices(proc, sound)
            self.assertEqual({item['role'] for item in result}, {'input', 'output'})
            self.assertEqual(result[0]['identity']['serial'], 'ABC')
            self.assertEqual(result[0]['card'], 7)
            first_key = result[0]['id']
            (sound / 'card3').mkdir()
            (sound / 'card3' / 'device').symlink_to(interface)
            (proc / 'pcm').write_text('03-00: USB Audio : USB Audio : playback 1 : capture 1\n')
            self.assertEqual(discover_devices(proc, sound)[0]['id'], first_key)
