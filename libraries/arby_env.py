"""Load local settings without replacing the process environment."""
from pathlib import Path

from dotenv import load_dotenv


def load_environment():
    """Find .env relative to the project, independent of the working directory."""
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
