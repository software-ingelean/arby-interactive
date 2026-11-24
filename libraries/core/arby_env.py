"""Expose the portal startup snapshot to provider libraries that use environment APIs."""
import os

from libraries.core.arby_ambient import DEFAULT_DATABASE
from libraries.core.arby_configuration import (
    EXTRA_DEFAULTS, PROJECT_ENVIRONMENT, ensure_configuration, load_extra, variable_for,
)
from libraries.core.arby_config import FIELDS, parse_config
from libraries.core.arby_support import load_overrides


def load_environment(database=DEFAULT_DATABASE, environment_path=PROJECT_ENVIRONMENT):
    ensure_configuration(database, environment_path, process_environment=os.environ)
    config = parse_config(load_overrides(database), {})
    for key in FIELDS:
        value = getattr(config, key)
        os.environ[variable_for(key)] = '' if value is None else str(value)
    os.environ.update({**EXTRA_DEFAULTS, **load_extra(database)})
