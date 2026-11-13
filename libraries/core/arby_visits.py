"""Anonymous event conversation metrics; never stores speech or names."""
from contextlib import closing
from datetime import date, datetime, time as day_time, timedelta, timezone
from pathlib import Path
import logging
import sqlite3
import time
import uuid
from zoneinfo import ZoneInfo

from libraries.core.arby_ambient import DEFAULT_DATABASE

BOGOTA = ZoneInfo('America/Bogota')


def connect(database):
    db = sqlite3.connect(database, timeout=0.1)
    db.row_factory = sqlite3.Row
    return db


def initialize(database=DEFAULT_DATABASE):
    Path(database).parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(database)) as db, db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS visits (
                id TEXT PRIMARY KEY, started_at REAL NOT NULL,
                last_activity_at REAL NOT NULL, ended_at REAL,
                close_reason TEXT, messages INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS visits_started ON visits(started_at);
            CREATE TABLE IF NOT EXISTS visit_health (
                id INTEGER PRIMARY KEY CHECK(id=1), incomplete INTEGER NOT NULL);
            INSERT OR IGNORE INTO visit_health VALUES(1,0);
        ''')


class VisitRecorder:
    """Used exclusively by the runtime worker. A failure stays visible across restarts."""
    def __init__(self, database=DEFAULT_DATABASE):
        self.database = database
        self.current = None
        self.error = None
        self.incomplete = False

    def _write(self, action):
        try:
            initialize(self.database)
            with closing(connect(self.database)) as db, db:
                action(db)
                if self.incomplete:
                    db.execute('UPDATE visit_health SET incomplete=1 WHERE id=1')
                self.incomplete = bool(db.execute('SELECT incomplete FROM visit_health WHERE id=1').fetchone()[0])
            self.error = None
        except (OSError, sqlite3.Error):
            self.incomplete = True
            logging.getLogger(__name__).warning('Registro de visitas: fallo de almacenamiento; conteo incompleto.')
            self.error = 'No se pudo guardar el registro de visitas. El conteo está incompleto.'

    def recover(self):
        self._write(lambda db: db.execute(
            "UPDATE visits SET close_reason='interrupted' WHERE close_reason IS NULL"))

    def begin(self):
        self.current = uuid.uuid4().hex
        now = time.time()
        self._write(lambda db: db.execute(
            'INSERT INTO visits(id,started_at,last_activity_at) VALUES(?,?,?)',
            (self.current, now, now)))

    def message(self):
        if self.current:
            def update(db):
                result = db.execute('UPDATE visits SET messages=messages+1,last_activity_at=? WHERE id=?',
                                    (time.time(), self.current))
                if not result.rowcount:
                    raise sqlite3.DatabaseError('Missing visit')
            self._write(update)

    def end(self, reason='timeout'):
        if self.current:
            self._write(lambda db: db.execute(
                'UPDATE visits SET ended_at=?,close_reason=? WHERE id=?',
                (time.time(), reason, self.current)))
            self.current = None

    @property
    def status(self):
        return {'incomplete': self.incomplete, 'error': self.error}


def report(database, start=None, end=None):
    def boundary(value, following=False):
        try:
            parsed = date.fromisoformat(value)
            if following:
                parsed += timedelta(days=1)
            return datetime.combine(parsed, day_time(), BOGOTA).timestamp()
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError('Usa fechas válidas con formato AAAA-MM-DD.') from exc
    lower = boundary(start) if start else None
    upper = boundary(end, True) if end else None
    if lower is not None and upper is not None and lower >= upper:
        raise ValueError('La fecha inicial debe ser anterior o igual a la final.')
    clauses, values = [], []
    for clause, value in [('started_at>=?', lower), ('started_at<?', upper)]:
        if value is not None:
            clauses.append(clause)
            values.append(value)
    with closing(connect(database)) as db:
        rows = db.execute('SELECT * FROM visits' + (' WHERE ' + ' AND '.join(clauses) if clauses else '') +
                          ' ORDER BY started_at DESC,id', values).fetchall()
        incomplete = bool(db.execute('SELECT incomplete FROM visit_health WHERE id=1').fetchone()[0])
    visits = [dict(row) for row in rows]
    for visit in visits:
        for key in ('started_at', 'last_activity_at', 'ended_at'):
            if visit[key] is not None:
                visit[key] = datetime.fromtimestamp(visit[key], timezone.utc).isoformat()
    return {'visits': visits, 'total': len(visits), 'messages': sum(v['messages'] for v in visits),
            'incomplete': incomplete, 'timezone': 'America/Bogota'}
