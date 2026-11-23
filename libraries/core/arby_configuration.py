"""Read private portal preferences shared with the Arby runtime; no web dependencies."""
import json
from pathlib import Path

from libraries.core.arby_ambient import DEFAULT_DATABASE

EXTRA_FIELDS = {'GEMINI_API_KEY': True, 'GOOGLE_API_KEY': True,
                'GEMINI_FALLBACK_MODELS': False, 'ARBY_SUPPORT': False}


def environment_file(database=DEFAULT_DATABASE):
    return Path(database).parent / 'portal_environment.json'


def load_extra(database=DEFAULT_DATABASE):
    target = environment_file(database)
    if not target.exists():
        return {}
    values = json.loads(target.read_text())
    if (not isinstance(values, dict) or set(values) - EXTRA_FIELDS.keys()
            or any(not isinstance(value, str) for value in values.values())):
        raise ValueError('Configuración avanzada no válida.')
    return values

