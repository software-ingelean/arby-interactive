"""Django test client bound to an isolated portal URL configuration."""
import json as json_module
from django.test import Client


class PortalClient(Client):
    def __init__(self, application):
        super().__init__(enforce_csrf_checks=True)
        self.handler.get_response = application.get_response

    def open(self, url, method='POST', json=None, headers=None):
        return self.generic(method, url, data=json_module.dumps(json),
                            content_type='application/json', headers=headers)

    def post(self, url, json=None, headers=None):
        return self.open(url, json=json, headers=headers)

    def set_cookie(self, key, value):
        self.cookies[key] = value
