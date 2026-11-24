"""Persistent operational logs, also visible through stderr/systemd journal."""
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path


def configure_logging():
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, '_arby_handler', False):
            root.removeHandler(handler)
            handler.close()
    requested = os.environ.get('ARBY_LOG_LEVEL', 'INFO').strip().upper()
    levels = {'DEBUG': logging.DEBUG, 'INFO': logging.INFO,
              'WARNING': logging.WARNING, 'ERROR': logging.ERROR,
              'CRITICAL': logging.CRITICAL, 'OFF': logging.CRITICAL + 1}
    level = levels.get(requested, logging.INFO)
    formatter = logging.Formatter('%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s')
    console = logging.StreamHandler()
    console._arby_handler = True
    console.setFormatter(formatter)
    console.setLevel(level)
    root.addHandler(console)
    root.setLevel(logging.WARNING)
    logging.getLogger('libraries').setLevel(level)
    logging.getLogger('arby').setLevel(level)
    if requested == 'OFF':
        return
    path = Path(os.environ.get('ARBY_LOG_FILE') or Path(__file__).resolve().parents[2] / 'logs' / 'arby.log')
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(path, maxBytes=5_000_000, backupCount=3, encoding='utf-8')
        handler._arby_handler = True
        handler.setFormatter(formatter)
        handler.setLevel(level)
        root.addHandler(handler)
    except OSError:
        logging.getLogger('arby').exception('No se pudo abrir el archivo de logs %s; continúa el registro en consola', path)
    else:
        logging.getLogger('arby').info('Registro operativo: %s', path)
