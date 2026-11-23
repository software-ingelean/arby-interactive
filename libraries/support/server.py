"""Compatibility entry point. The portal implementation lives in portal.server."""
from portal.server import configure_django, create_app, main, system_action

__all__ = ['configure_django', 'create_app', 'main', 'system_action']

if __name__ == '__main__':
    main()
