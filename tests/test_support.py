"""Offline support contracts: auth, persistence, stale state and shared runtime admission."""
from concurrent.futures import Future
from contextlib import closing
from dataclasses import asdict
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from werkzeug.security import generate_password_hash
from libraries.core.arby_ambient import AmbientSettings, load_ambient_settings, save_ambient_settings
from libraries.core.arby_support import (SupportBridge, connect, initialize, settings,
                                        save_settings, runtime_status, enqueue, validate_controls)
from libraries.support.server import create_app, system_action
import run_arby


class SupportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password_hash = generate_password_hash('support-test')

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.database = Path(temp.name) / 'settings.sqlite3'
        self.system = Mock(return_value={'ok': True})
        self.app = create_app(self.database, self.password_hash, self.system)
        self.app.testing = True
        self.client = self.app.test_client()
        self.csrf = self.client.get('/api/session').json['csrf']

    def request(self, url, data=None, method='POST'):
        return self.client.open(url, method=method, json=data or {}, headers={'X-CSRF-Token': self.csrf})

    def login(self):
        response = self.request('/api/login', {'password': 'support-test'})
        self.assertEqual(response.status_code, 200)
        self.csrf = response.json['csrf']

    def publish(self, **updates):
        snapshot = {'state': 'ready', 'components': {'speaker': {'state': 'unknown'}, 'eyes': {'state': 'ready'}},
                    'effective': settings(self.database)}
        snapshot.update(updates)
        with closing(connect(self.database)) as db, db:
            db.execute('INSERT OR REPLACE INTO support_runtime VALUES(1,?,?)', (time.time(), json.dumps(snapshot)))

    def payload(self):
        return {'ambient': asdict(AmbientSettings('evento')), 'controls': {'mute': True, 'mic_gain_db': 10, 'rate': '+8%'}}

    def test_authentication_and_csrf_are_required(self):
        self.assertEqual(self.client.get('/api/status').status_code, 401)
        self.assertEqual(self.client.post('/api/login', json={'password': 'support-test'}).status_code, 403)
        self.login()
        self.assertEqual(self.client.get('/api/status').status_code, 200)
        self.assertEqual(self.client.post('/api/restart', json={'target': 'arby'}).status_code, 403)
        self.system.assert_not_called()

    def test_stale_csrf_can_recover_without_repeating_system_action(self):
        self.login()
        response = self.client.post('/api/network/connect', json={'ssid': 'Fair', 'password': 'secret'},
                                    headers={'X-CSRF-Token': 'stale-token'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json['code'], 'csrf_mismatch')
        self.system.assert_not_called()
        info = self.client.get('/api/session').json
        self.assertTrue(info['authenticated'])
        self.csrf = info['csrf']
        self.assertEqual(self.request('/api/network/connect', {'ssid': 'Fair', 'password': 'secret'}).status_code, 200)
        self.system.assert_called_once_with('wifi', ssid='Fair', password='secret')

    def test_portal_cookie_does_not_collide_with_generic_session_cookie(self):
        self.client.set_cookie('session', 'another-application')
        self.login()
        self.client.set_cookie('session', 'changed-by-another-application')
        self.assertEqual(self.client.get('/api/status').status_code, 200)

    def test_login_throttle_and_logout(self):
        for _ in range(5):
            self.assertEqual(self.request('/api/login', {'password': 'wrong'}).status_code, 401)
        self.assertEqual(self.request('/api/login', {'password': 'wrong'}).status_code, 429)

    def test_logout_invalidates_access(self):
        self.login()
        self.assertEqual(self.request('/api/logout').status_code, 200)
        self.assertEqual(self.client.get('/api/status').status_code, 401)

    def test_settings_save_without_restarting_and_pending_changes(self):
        self.login()
        self.publish()
        self.assertFalse(self.client.get('/api/status').json['runtime']['pending_changes'])
        self.assertEqual(self.request('/api/settings', self.payload(), 'PUT').status_code, 200)
        self.system.assert_not_called()
        self.assertEqual(load_ambient_settings(self.database).mode, 'evento')
        self.assertTrue(self.client.get('/api/status').json['runtime']['pending_changes'])
        self.publish()
        self.assertFalse(self.client.get('/api/status').json['runtime']['pending_changes'])

    def test_invalid_update_is_atomic(self):
        before = settings(self.database)
        invalid = self.payload()
        invalid['controls']['mic_gain_db'] = 100
        with self.assertRaises(ValueError):
            save_settings(invalid, self.database)
        self.assertEqual(settings(self.database), before)
        for value in (float('inf'), float('nan'), True, 'ten'):
            invalid = self.payload()
            invalid['ambient']['gesture_min_seconds'] = value
            with self.assertRaises((ValueError, TypeError)):
                save_settings(invalid, self.database)
        self.assertEqual(settings(self.database), before)

    def test_credentials_and_hardware_keys_cannot_be_saved(self):
        for key in ('GEMINI_API_KEY', 'strip_gpio', 'voice', '__class__'):
            with self.assertRaises(ValueError):
                validate_controls({key: 'secret'})

    def test_stale_state_and_stopped_runtime_reject_tests(self):
        self.publish()
        with closing(connect(self.database)) as db, db:
            db.execute('UPDATE support_runtime SET updated=?', (time.time() - 20,))
        self.assertFalse(runtime_status(self.database)['fresh'])
        with self.assertRaises(ValueError):
            enqueue('speaker', self.database)
        self.publish(state='stopped')
        with self.assertRaises(ValueError):
            enqueue('speaker', self.database)

    def test_tests_wait_for_existing_runtime_when_busy(self):
        with patch.dict(os.environ, {'ARBY_SUPPORT': 'true'}):
            bridge = SupportBridge(self.database)
        bridge.snapshot.update(state='ready', components={'speaker': {'state': 'unknown'}})
        bridge.publish()
        identifier = enqueue('speaker', self.database)
        submit = Mock(return_value=None)
        runtime = SimpleNamespace(pending_count=1, visual=SimpleNamespace(phase='speaking'))
        tts = SimpleNamespace(last_error=None)
        bridge.tick(runtime, None, tts, None, submit)
        with closing(connect(self.database)) as db:
            row = db.execute('SELECT * FROM support_commands WHERE id=?', (identifier,)).fetchone()
        self.assertEqual(row['state'], 'pending')
        submit.assert_called_once()
        self.assertEqual(submit.call_args.args[0].kind, 'phrase')
        self.assertIn('libre', row['message'])
        future = Future()
        bridge.next_poll = 0
        bridge.tick(runtime, None, tts, None, lambda action: future)
        with closing(connect(self.database)) as db:
            self.assertEqual(db.execute('SELECT state FROM support_commands WHERE id=?', (identifier,)).fetchone()[0], 'running')

    def test_test_completion_and_failure(self):
        with patch.dict(os.environ, {'ARBY_SUPPORT': 'true'}):
            bridge = SupportBridge(self.database)
        bridge.snapshot.update(state='ready', components={'speaker': {'state': 'unknown'}})
        bridge.publish()
        identifier = enqueue('eyes', self.database)
        future = Future()
        runtime = SimpleNamespace(pending_count=0, visual=SimpleNamespace(phase='idle'))
        tts = SimpleNamespace(last_error=None)
        bridge.tick(runtime, None, tts, None, lambda action: future)
        future.set_result(None)
        bridge.next_poll = 0
        bridge.tick(runtime, None, tts, None, lambda action: None)
        with closing(connect(self.database)) as db:
            row = db.execute('SELECT * FROM support_commands WHERE id=?', (identifier,)).fetchone()
        self.assertEqual(row['state'], 'done')

    def test_failed_future_is_reported_without_exception_details(self):
        with patch.dict(os.environ, {'ARBY_SUPPORT': 'true'}):
            bridge = SupportBridge(self.database)
        bridge.snapshot.update(state='ready', components={'eyes': {'state': 'ready'}})
        bridge.publish()
        identifier = enqueue('eyes', self.database)
        future = Future()
        runtime = SimpleNamespace(pending_count=0, visual=SimpleNamespace(phase='idle'))
        bridge.tick(runtime, None, SimpleNamespace(last_error=None), None, lambda action: future)
        future.set_exception(RuntimeError('private provider details'))
        bridge.next_poll = 0
        bridge.tick(runtime, None, SimpleNamespace(last_error=None), None, lambda action: None)
        with closing(connect(self.database)) as db:
            row = db.execute('SELECT * FROM support_commands WHERE id=?', (identifier,)).fetchone()
        self.assertEqual(row['state'], 'error')
        self.assertNotIn('private', row['message'])

    def test_invalid_request_object_is_rejected(self):
        self.login()
        response = self.client.post('/api/restart', json=['arby'], headers={'X-CSRF-Token': self.csrf})
        self.assertEqual(response.status_code, 400)
        self.system.assert_not_called()

    def test_database_failure_does_not_stop_arby(self):
        with patch.dict(os.environ, {'ARBY_SUPPORT': 'true'}):
            bridge = SupportBridge(self.database)
        with patch('libraries.core.arby_support.connect', side_effect=__import__('sqlite3').OperationalError('locked')):
            bridge.tick(Mock(), None, Mock(), None, Mock())
            bridge.finish('error')

    def test_existing_ambient_database_is_preserved(self):
        save_ambient_settings(AmbientSettings('evento', 10, 20, 30, 40), self.database)
        initialize(self.database)
        self.assertEqual(load_ambient_settings(self.database).gesture_range, (10, 20))

    def test_overrides_win_over_environment(self):
        with patch.dict(os.environ, {'ARBY_MIC_GAIN_DB': 'invalid', 'ARBY_MUTE': 'false'}, clear=True), patch.object(run_arby, 'load_overrides', return_value={'mic_gain_db': 9, 'mute': True}):
            config = run_arby.load_config()
        self.assertEqual(config.microphone.gain_db, 9)
        self.assertTrue(config.mute)

    def test_bluetooth_auth_validation_and_actions(self):
        self.assertEqual(self.client.get('/api/bluetooth').status_code, 401)
        self.assertEqual(self.request('/api/bluetooth/scan').status_code, 401)
        self.login()
        self.assertEqual(self.client.post('/api/bluetooth/scan', json={}).status_code, 403)
        for operation, data in [('shell', {}), ('connect', {'address': '--help'}), ('disconnect', {'address': []})]:
            self.assertEqual(self.request('/api/bluetooth/' + operation, data).status_code, 400)
        self.system.assert_not_called()
        self.assertEqual(self.client.get('/api/bluetooth').status_code, 200)
        self.system.assert_called_with('bluetooth')
        self.assertEqual(self.request('/api/bluetooth/scan').status_code, 200)
        self.system.assert_called_with('bluetooth_scan')
        for operation in ('connect', 'disconnect'):
            self.assertEqual(self.request('/api/bluetooth/' + operation, {'address': 'AA:BB:CC:DD:EE:FF'}).status_code, 200)
            self.system.assert_called_with('bluetooth_' + operation, address='AA:BB:CC:DD:EE:FF')

    def test_restart_allowlist(self):
        self.login()
        self.assertEqual(self.request('/api/restart', {'target': 'anything'}).status_code, 400)
        self.system.assert_not_called()
        self.assertEqual(self.request('/api/restart', {'target': 'arby'}).status_code, 200)
        self.system.assert_called_once_with('arby')

    def test_page_and_local_assets(self):
        for path in ('/', '/static/portal.js', '/static/portal.css'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
            response.close()

    def test_audio_catalog_requires_auth_and_reports_missing_preference(self):
        self.assertEqual(self.client.get('/api/audio/devices').status_code, 401)
        self.login()
        with patch('libraries.audio.arby_devices.discover_devices', return_value=[]):
            response = self.client.get('/api/audio/devices')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['devices'], [])

    def test_shutdown_is_authenticated_and_is_not_an_arbitrary_command(self):
        self.assertEqual(self.request('/api/power', {'target': 'shutdown'}).status_code, 401)
        self.login()
        self.assertEqual(self.request('/api/power', {'target': 'shell'}).status_code, 400)
        self.system.assert_not_called()
        self.assertEqual(self.request('/api/power', {'target': 'shutdown'}).status_code, 200)
        self.system.assert_called_once_with('shutdown')

    def test_demo_catalog_and_cancel_endpoint(self):
        self.login()
        self.publish()
        result = self.client.get('/api/status').json
        self.assertIn('light_red', [item['id'] for item in result['tests']])
        enqueue('greeting', self.database)
        self.assertEqual(self.request('/api/tests/cancel').status_code, 202)
        with closing(connect(self.database)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM support_commands WHERE kind='cancel'").fetchone()[0], 1)

    def test_stop_only_cancels_the_owned_demo(self):
        with patch.dict(os.environ, {'ARBY_SUPPORT': 'true'}):
            bridge = SupportBridge(self.database)
        bridge.snapshot.update(state='ready', components={'eyes': {'state': 'ready'}})
        bridge.publish()
        future = Future()
        runtime = SimpleNamespace(pending_count=0, visual=SimpleNamespace(phase='idle'), cancel_ambient=Mock(return_value=True))
        bridge.tick(runtime, None, SimpleNamespace(last_error=None), None, lambda action: future)
        enqueue('eyes', self.database)
        bridge.next_poll = 0
        bridge.tick(runtime, None, SimpleNamespace(last_error=None), None, lambda action: future)
        enqueue('cancel', self.database)
        bridge.next_poll = 0
        bridge.tick(runtime, None, SimpleNamespace(last_error=None), None, lambda action: None)
        runtime.cancel_ambient.assert_called_once_with(future)

    def test_cancel_removes_waiting_demo_without_interrupting_conversation(self):
        with patch.dict(os.environ, {'ARBY_SUPPORT': 'true'}):
            bridge = SupportBridge(self.database)
        bridge.snapshot.update(state='ready', components={'eyes': {'state': 'ready'}})
        bridge.publish()
        identifier = enqueue('eyes', self.database)
        runtime = SimpleNamespace(pending_count=1, visual=SimpleNamespace(phase='speaking'),
                                  cancel_ambient=Mock())
        submit = Mock(return_value=None)
        bridge.tick(runtime, None, SimpleNamespace(last_error=None), None, submit)
        self.assertTrue(bridge.waiting)
        enqueue('cancel', self.database)
        bridge.next_poll = 0
        bridge.tick(runtime, None, SimpleNamespace(last_error=None), None, submit)
        self.assertFalse(bridge.waiting)
        runtime.cancel_ambient.assert_not_called()
        self.assertEqual(submit.call_count, 1)
        with closing(connect(self.database)) as db:
            row = db.execute('SELECT * FROM support_commands WHERE id=?', (identifier,)).fetchone()
        self.assertEqual(row['state'], 'error')
        self.assertIn('cancelada', row['message'])

    def test_system_failure_has_no_subprocess_output_or_password(self):
        with patch('libraries.support.server.subprocess.run', return_value=SimpleNamespace(returncode=1, stdout='secret', stderr='password')):
            with self.assertRaises(ValueError) as caught:
                system_action('wifi', ssid='fair', password='password')
        self.assertNotIn('password', str(caught.exception))


class HelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('arby_system', Path(__file__).resolve().parents[1] / 'deploy' / 'arby-system.py')
        cls.helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.helper)

    def test_helper_rejects_arbitrary_actions_and_invalid_wifi(self):
        for payload in ({'action': 'shell'}, {'action': 'wifi', 'ssid': '--help', 'password': ''}, {'action': 'wifi', 'ssid': 'fair', 'password': 'bad\nvalue'}):
            with self.assertRaises(ValueError), patch.object(self.helper, 'run') as run:
                self.helper.execute(payload)
            run.assert_not_called()

    def test_bluetooth_scan_includes_classic_and_general_discovery(self):
        with patch.object(self.helper, 'bluetooth') as command, patch.object(self.helper, 'bluetooth_status', return_value={'devices': []}):
            self.helper.execute({'action': 'bluetooth_scan'})
        self.assertEqual(command.call_args_list, [
            unittest.mock.call('power', 'on'),
            unittest.mock.call('scan', 'bredr', seconds=8),
            unittest.mock.call('scan', 'on', seconds=8),
        ])

    def test_bluetooth_scan_falls_back_when_classic_is_unavailable(self):
        with patch.object(self.helper, 'bluetooth', side_effect=[None, ValueError('Unsupported'), None]) as command, patch.object(self.helper, 'bluetooth_status', return_value={'devices': []}):
            self.helper.execute({'action': 'bluetooth_scan'})
        self.assertEqual(command.call_args, unittest.mock.call('scan', 'on', seconds=8))

    def test_bluetooth_rejects_invalid_addresses_before_running(self):
        for address in ('--help', 'AA:BB:CC:DD:EE:FF\n', None, ['AA']):
            with patch.object(self.helper, 'run') as run, self.assertRaises(ValueError):
                self.helper.execute({'action': 'bluetooth_connect', 'address': address})
            run.assert_not_called()

    def test_bluetooth_does_not_repair_existing_pairing(self):
        with patch.object(self.helper, 'bluetooth', return_value='Paired: yes') as command:
            self.helper.execute({'action': 'bluetooth_connect', 'address': 'AA:BB:CC:DD:EE:FF'})
        self.assertEqual(command.call_args.args, ('connect', 'AA:BB:CC:DD:EE:FF'))
        self.assertEqual(command.call_count, 2)

    def test_bluetooth_status_parses_names_and_states(self):
        with patch.object(self.helper, 'bluetooth', side_effect=[
            'Controller AA:BB:CC:DD:EE:00 Raspberry\n\tPowered: yes',
            'Device AA:BB:CC:DD:EE:FF Altavoz de Arby',
            'Device AA:BB:CC:DD:EE:FF Altavoz de Arby', '',
        ]):
            result = self.helper.bluetooth_status()
        self.assertTrue(result['powered'])
        self.assertEqual(result['devices'][0], {'address': 'AA:BB:CC:DD:EE:FF', 'name': 'Altavoz de Arby', 'connected': True, 'paired': False})

    def test_bluetooth_resolves_mac_placeholder_to_device_name(self):
        for placeholder in ('AA:BB:CC:DD:EE:FF', 'AA-BB-CC-DD-EE-FF'):
            with self.subTest(placeholder=placeholder), patch.object(self.helper, 'bluetooth', side_effect=[
                'Powered: yes', f'Device AA:BB:CC:DD:EE:FF {placeholder}', '', '',
                'Name: JBL Flip\nAlias: AA-BB-CC-DD-EE-FF',
            ]):
                self.assertEqual(self.helper.bluetooth_status()['devices'][0]['name'], 'JBL Flip')

    def test_bluetooth_missing_name_does_not_hide_device(self):
        with patch.object(self.helper, 'bluetooth', side_effect=[
            'Powered: yes', 'Device AA:BB:CC:DD:EE:FF AA-BB-CC-DD-EE-FF', '', '',
            ValueError('Device unavailable'),
        ]):
            device = self.helper.bluetooth_status()['devices'][0]
        self.assertEqual(device['name'], 'Dispositivo sin nombre')
        self.assertEqual(device['address'], 'AA:BB:CC:DD:EE:FF')

    def test_bluetooth_uses_readable_alias_when_name_missing(self):
        with patch.object(self.helper, 'bluetooth', side_effect=[
            'Powered: yes', 'Device AA:BB:CC:DD:EE:FF AA-BB-CC-DD-EE-FF', '', '',
            'Alias: Altavoz de sala',
        ]):
            self.assertEqual(self.helper.bluetooth_status()['devices'][0]['name'], 'Altavoz de sala')

    def test_password_is_not_a_process_argument(self):
        with patch.object(self.helper, 'run') as run:
            self.helper.execute({'action': 'wifi', 'ssid': 'Fair', 'password': 'secret-123'})
        args = run.call_args.args[0]
        self.assertNotIn('secret-123', args)
        self.assertIn('--ask', args)
        self.assertNotIn('--passwd-file', args)
        self.assertEqual(run.call_args.kwargs['input'], 'secret-123\n')

    def test_wifi_failure_returns_safe_code_without_credentials(self):
        import subprocess
        failure = subprocess.CalledProcessError(4, ['nmcli'], stderr='password secret-123 missing')
        with patch.object(self.helper, 'run', side_effect=failure):
            result = self.helper.execute({'action': 'wifi', 'ssid': 'Fair', 'password': 'secret-123'})
        self.assertEqual(result, {'error_code': 'wifi_credentials'})

    def test_wifi_timeout_returns_safe_code(self):
        import subprocess
        with patch.object(self.helper, 'run', side_effect=subprocess.TimeoutExpired(['nmcli'], 25)):
            result = self.helper.execute({'action': 'wifi', 'ssid': 'Fair', 'password': 'secret-123'})
        self.assertEqual(result, {'error_code': 'wifi_timeout'})

    def test_nmcli_escaped_ssid_fields(self):
        self.assertEqual(self.helper.split_fields(r'Fair\: Booth:80:WPA2'), ['Fair: Booth', '80', 'WPA2'])

    def test_shutdown_schedules_fixed_poweroff(self):
        with patch.object(self.helper, 'run') as run:
            result = self.helper.execute({'action': 'shutdown'})
        self.assertTrue(result['ok'])
        self.assertEqual(run.call_args.args[0], ['/usr/bin/systemd-run', '--on-active=3s', '/usr/bin/systemctl', 'poweroff'])
