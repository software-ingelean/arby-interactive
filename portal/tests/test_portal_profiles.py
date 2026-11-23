"""Role boundaries, administrator preferences and reserved physical PTT flag."""
from contextlib import closing
from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from werkzeug.security import generate_password_hash
from portal.tests.portal_client import PortalClient
from portal.server import create_app
from libraries.core.arby_ambient import AmbientSettings
from libraries.core.arby_config import FIELDS, parse_config
from libraries.core.arby_configuration import EXTRA_FIELDS, environment_file, load_extra
from libraries.core.arby_support import connect, load_overrides, settings, configuration_revision
from libraries.audio.arby_devices import apply_selection


class PortalProfilesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin_hash = generate_password_hash('admin-test')
        cls.commercial_hash = generate_password_hash('commercial-test')

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.database = Path(temp.name) / 'settings.sqlite3'
        self.system = Mock(return_value={'ok': True})
        self.app = create_app(self.database, self.admin_hash, self.system, self.commercial_hash)
        self.client = PortalClient(self.app)
        self.csrf = self.client.get('/api/session').json()['csrf']

    def request(self, url, data=None, method='POST'):
        return self.client.open(url, method=method, json=data or {}, headers={'X-CSRF-Token': self.csrf})

    def login(self, role='admin'):
        result = self.request('/api/login', {'role': role, 'password': 'admin-test' if role == 'admin' else 'commercial-test'})
        self.assertEqual(result.status_code, 200)
        self.csrf = result.json()['csrf']

    def publish(self, **controls):
        payload = {'state': 'ready', 'debug': {'threads': ['private']},
                   'effective': {**settings(self.database), 'controls': controls, 'configuration_revision': configuration_revision(self.database)}, 'components': {}}
        with closing(connect(self.database)) as db, db:
            db.execute('INSERT OR REPLACE INTO support_runtime VALUES(1,?,?)', (time.time(), json.dumps(payload)))

    def test_commercial_cannot_call_administrator_actions_directly(self):
        self.login('comercial')
        for url in ('/api/admin/configuration', '/api/network', '/api/bluetooth', '/api/audio/devices'):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        for url, payload in [('/api/power', {'target': 'shutdown'}),
                             ('/api/restart', {'target': 'raspberry'}),
                             ('/api/network/connect', {'ssid': 'example'}),
                             ('/api/admin/configuration', {'values': {'push_to_talk': True}})]:
            self.assertEqual(self.request(url, payload, 'PUT' if 'configuration' in url else 'POST').status_code, 403, url)
        self.system.assert_not_called()
        self.assertEqual(self.request('/api/restart', {'target': 'arby'}).status_code, 200)
        self.system.assert_called_once_with('arby')

    def test_profile_selection_never_grants_access_with_other_password(self):
        result = self.request('/api/login', {'role': 'admin', 'password': 'commercial-test'})
        self.assertEqual(result.status_code, 401)
        for role in ('unknown', {}, []):
            self.assertEqual(self.request('/api/login', {'role': role, 'password': 'admin-test'}).status_code, 401)

    def test_commercial_basic_saves_preserve_administrator_settings(self):
        self.login()
        self.assertEqual(self.request('/api/admin/configuration', {'values': {'push_to_talk': True, 'voice': 'es-MX-JorgeNeural'}}, 'PUT').status_code, 200)
        self.request('/api/logout')
        self.csrf = self.client.get('/api/session').json()['csrf']
        self.login('comercial')
        payload = {'ambient': asdict(AmbientSettings()), 'controls': {'mute': True}}
        self.assertEqual(self.request('/api/settings', payload, 'PUT').status_code, 200)
        self.assertTrue(load_overrides(self.database)['push_to_talk'])
        for controls in ({'push_to_talk': False}, {'microphone_enabled': False}, {'strip_gpio': 18}):
            payload['controls'] = controls
            self.assertEqual(self.request('/api/settings', payload, 'PUT').status_code, 403)
        self.system.assert_not_called()

    def test_advanced_status_is_hidden_from_commercial(self):
        self.publish(strip_gpio=12, mic_gain_db=6, voice='test', mute=False)
        self.login('comercial')
        data = self.client.get('/api/status').json()
        self.assertNotIn('debug', data['runtime'])
        self.assertEqual(data['runtime']['effective']['controls'], {'mute': False})
        self.assertNotIn('voice', data['saved']['controls'])

    def test_admin_settings_persist_without_system_action_and_ptt_is_reserved(self):
        self.login()
        values = {'push_to_talk': True, 'microphone_enabled': False, 'trill': False,
                  'eyes': 'none', 'strip': False, 'mute': True, 'mic_threshold': 0.65}
        result = self.request('/api/admin/configuration', {'values': values}, 'PUT')
        self.assertEqual(result.status_code, 200, result.content)
        self.assertFalse(result.json()['push_to_talk_implemented'])
        self.assertEqual(load_overrides(self.database), values)
        config = parse_config(load_overrides(self.database), {'ARBY_INPUT_MODE': 'voice'})
        self.assertTrue(config.push_to_talk)
        self.assertFalse(config.microphone_enabled)
        self.system.assert_not_called()
        second = PortalClient(create_app(self.database, self.admin_hash, self.system, self.commercial_hash))
        self.assertEqual(second.get('/api/status').status_code, 401)
        self.assertTrue(load_overrides(self.database)['push_to_talk'])

    def test_reset_and_secret_edits_are_pending_until_runtime_restarts(self):
        self.login()
        self.publish()
        self.assertFalse(self.client.get('/api/status').json()['runtime']['pending_changes'])
        self.request('/api/admin/configuration', {'values': {'GEMINI_API_KEY': 'test-secret', 'voice': None}}, 'PUT')
        self.assertTrue(self.client.get('/api/status').json()['runtime']['pending_changes'])
        self.publish(voice=None)
        self.assertFalse(self.client.get('/api/status').json()['runtime']['pending_changes'])
        self.request('/api/admin/configuration', {'reset': ['voice', 'GEMINI_API_KEY']}, 'PUT')
        self.assertTrue(self.client.get('/api/status').json()['runtime']['pending_changes'])
        self.publish()
        self.assertFalse(self.client.get('/api/status').json()['runtime']['pending_changes'])

    def test_secrets_are_private_redacted_and_preserved(self):
        self.login()
        url = '/api/admin/configuration'
        self.assertEqual(self.request(url, {'values': {'GEMINI_API_KEY': 'provider-test-secret', 'ARBY_SUPPORT': True}}, 'PUT').status_code, 200)
        self.assertEqual(environment_file(self.database).stat().st_mode & 0o777, 0o600)
        self.assertEqual(load_extra(self.database)['GEMINI_API_KEY'], 'provider-test-secret')
        self.assertNotIn('provider-test-secret', self.client.get(url).content.decode())
        self.assertNotIn('provider-test-secret', self.client.get('/api/status').content.decode())
        self.assertNotIn('GEMINI_API_KEY', load_overrides(self.database))
        self.request(url, {'values': {'push_to_talk': True}}, 'PUT')
        self.assertEqual(load_extra(self.database)['GEMINI_API_KEY'], 'provider-test-secret')
        self.request(url, {'reset': ['GEMINI_API_KEY', 'push_to_talk']}, 'PUT')
        self.assertNotIn('GEMINI_API_KEY', load_extra(self.database))
        self.assertNotIn('push_to_talk', load_overrides(self.database))

    def test_invalid_configuration_never_changes_saved_values(self):
        self.login()
        for values in ({'unknown': 'x'}, {'mic_threshold': 2}, {'push_to_talk': 'true'},
                       {'strip_gpio': -1}, {'GEMINI_API_KEY': 'bad\nkey'}, {'ARBY_SUPPORT': 'false'}):
            response = self.request('/api/admin/configuration', {'values': values}, 'PUT')
            self.assertEqual(response.status_code, 400, values)
            self.assertEqual(load_overrides(self.database), {})
            self.assertFalse(environment_file(self.database).exists())

    def test_csrf_and_origin_checks_protect_advanced_configuration(self):
        self.login()
        url = '/api/admin/configuration'
        self.assertEqual(self.client.open(url, method='PUT', json={'values': {'push_to_talk': True}}).status_code, 403)
        response = self.client.open(url, method='PUT', json={'values': {'push_to_talk': True}},
                                    headers={'X-CSRF-Token': self.csrf, 'Origin': 'https://untrusted.example'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(load_overrides(self.database), {})

    def test_logout_invalidates_previously_copied_session(self):
        self.login()
        stolen = PortalClient(self.app)
        stolen.cookies = self.client.cookies.copy()
        self.request('/api/logout')
        self.assertEqual(stolen.get('/api/status').status_code, 401)

    def test_all_documented_environment_options_are_available(self):
        import re
        keys = set(re.findall(r'^#?\s*([A-Z][A-Z0-9_]+)=', Path('.env.example').read_text(), re.M))
        configured = {'GEMINI_MODEL' if key == 'model' else f'ARBY_{key.upper()}' for key in FIELDS} | set(EXTRA_FIELDS)
        self.assertFalse(keys - configured)

    def test_disabled_microphone_does_not_resolve_missing_audio_preference(self):
        config = parse_config({'microphone_enabled': False, 'mute': True}, {'ARBY_INPUT_MODE': 'voice'})
        self.assertEqual(apply_selection(config, {'input': {'missing': True}, 'output': None}, devices=[]), {})

    def test_extra_preferences_are_loaded_for_runtime_only(self):
        self.login()
        self.request('/api/admin/configuration', {'values': {'GEMINI_API_KEY': 'provider-test-secret'}}, 'PUT')
        from libraries.core.arby_env import load_environment
        with patch.dict(os.environ, {}, clear=True), patch('libraries.core.arby_env.load_dotenv'), patch('libraries.core.arby_configuration.environment_file', return_value=environment_file(self.database)):
            load_environment()
            self.assertEqual(os.environ['GEMINI_API_KEY'], 'provider-test-secret')
