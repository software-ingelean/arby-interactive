"""Persistence, fixtures and account lifecycle through the portal API."""
from pathlib import Path
import tempfile
import unittest
from portal.server import create_app
from portal.tests.portal_client import PortalClient


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / 'settings.sqlite3'
        self.app = create_app(self.database, environment_path=Path(self.temp.name) / '.env')
        self.client = PortalClient(self.app)
        self.csrf = self.client.get('/api/session').json()['csrf']

    def request(self, url, data, method='POST', client=None):
        return (client or self.client).open(url, method=method, json=data, headers={'X-CSRF-Token': self.csrf})

    def login(self, username='admin', password='1234'):
        response = self.request('/api/login', {'username': username, 'password': password})
        if response.status_code == 200:
            self.csrf = response.json()['csrf']
        return response

    def test_fixtures_and_permissions(self):
        self.assertEqual(self.login('comercial').status_code, 200)
        self.assertEqual(self.client.get('/api/admin/users').status_code, 403)
        self.assertEqual(self.login().status_code, 200)
        users = self.client.get('/api/admin/users').json()['users']
        self.assertEqual({u['username'] for u in users}, {'admin', 'comercial'})
        self.assertNotIn('password', users[0])

    def test_create_change_password_and_restart_preserves_credentials(self):
        self.login()
        payload = {'username': 'ana', 'role': 'comercial', 'password': 'personal'}
        self.assertEqual(self.request('/api/admin/users', payload).status_code, 200)
        payload = {'username': 'admin', 'role': 'admin', 'password': 'nueva'}
        self.assertEqual(self.request('/api/admin/users', payload, 'PUT').status_code, 200)
        self.assertEqual(self.client.get('/api/admin/users').status_code, 200)
        self.client = PortalClient(create_app(self.database))
        self.csrf = self.client.get('/api/session').json()['csrf']
        self.assertEqual(self.login(password='1234').status_code, 401)
        self.assertEqual(self.login(password='nueva').status_code, 200)
        self.assertEqual(self.login('ana', 'personal').status_code, 200)

    def test_deactivation_and_password_changes_revoke_other_sessions(self):
        self.login('comercial')
        commercial = self.client
        self.client = PortalClient(self.app)
        self.csrf = self.client.get('/api/session').json()['csrf']
        self.login()
        payload = {'username': 'comercial', 'role': 'comercial', 'password': 'changed'}
        self.assertEqual(self.request('/api/admin/users', payload, 'PUT').status_code, 200)
        self.assertEqual(commercial.get('/api/status').status_code, 401)
        self.login('comercial', 'changed')
        commercial = self.client
        self.client = PortalClient(self.app)
        self.csrf = self.client.get('/api/session').json()['csrf']
        self.login()
        payload.update(active=False, password='')
        self.assertEqual(self.request('/api/admin/users', payload, 'PUT').status_code, 200)
        self.assertEqual(commercial.get('/api/status').status_code, 401)
        self.assertEqual(self.login('comercial', 'changed').status_code, 401)

    def test_last_administrator_cannot_be_disabled_or_demoted(self):
        self.login()
        for values in [{'active': False, 'role': 'admin'}, {'active': True, 'role': 'comercial'}]:
            self.assertEqual(self.request('/api/admin/users', {'username': 'admin', **values}, 'PUT').status_code, 400)
