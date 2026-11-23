"""Bind runner tests to temporary preferences instead of the installed configuration."""
from functools import partial
from pathlib import Path
import tempfile
from unittest.mock import patch

import run_arby
from libraries.core import arby_touch
from libraries.audio.arby_devices import apply_selection, load_selection
from libraries.core.arby_ambient import load_ambient_settings
from libraries.core.arby_support import (
    SupportBridge, initialize, load_overrides,
)


def isolate_runtime(test_case, database=None):
    """Exercise real persistence in a test DB without accessing installed audio devices."""
    if database is None:
        temporary = tempfile.TemporaryDirectory(prefix='arby-test-')
        test_case.addCleanup(temporary.cleanup)
        database = Path(temporary.name) / 'settings.sqlite3'
    initialize(database)
    bindings = {
        'load_overrides': partial(load_overrides, database=database),
        'load_selection': partial(load_selection, database=database),
        'load_ambient_settings': partial(load_ambient_settings, database=database),
        'SupportBridge': partial(SupportBridge, database=database),
        'apply_selection': partial(apply_selection, devices=[]),
    }
    for name, bound in bindings.items():
        replacement = patch.object(run_arby, name, bound)
        replacement.start()
        test_case.addCleanup(replacement.stop)
    touch_loader = patch.object(arby_touch, 'load_touch_config',
                                partial(arby_touch.load_touch_config, path=Path(database).parent / 'triki_config.json'))
    touch_loader.start()
    test_case.addCleanup(touch_loader.stop)
    return database
