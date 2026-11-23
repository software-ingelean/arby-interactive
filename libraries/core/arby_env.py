"""Load local settings without replacing the process environment."""
from pathlib import Path

from dotenv import load_dotenv


def load_environment():
    """Find .env relative to the project, independent of the working directory."""
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
    # Only explicit portal preferences override the installed environment.
    import os
    from libraries.core.arby_configuration import load_extra
    os.environ.update(load_extra())
