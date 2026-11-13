"""Offline visit persistence, lifecycle and portal contracts."""
from contextlib import closing
import csv
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from libraries.core.arby_visits import VisitRecorder, initialize, report, connect


class VisitsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'settings.sqlite3'
        from libraries.core.arby_support import initialize as initialize_support
        initialize_support(self.db)
        self.recorder = VisitRecorder(self.db)
        self.recorder.recover()

    def test_lifecycle_and_recovery_do_not_invent_end_time(self):
        self.recorder.begin()
        self.recorder.message()
        self.recorder.message()
        self.recorder.end()
        self.recorder.begin()
        VisitRecorder(self.db).recover()
        result = report(self.db)
        self.assertEqual((result['total'], result['messages']), (2, 2))
        interrupted = next(v for v in result['visits'] if v['close_reason'] == 'interrupted')
        self.assertIsNone(interrupted['ended_at'])
        self.assertFalse(result['incomplete'])
        self.assertEqual(set(interrupted), {'id', 'started_at', 'last_activity_at', 'ended_at', 'close_reason', 'messages'})

    def test_storage_failure_is_sticky_and_does_not_raise(self):
        with patch('libraries.core.arby_visits.connect', side_effect=OSError):
            self.recorder.begin()
        self.assertTrue(self.recorder.status['incomplete'])
        self.assertIsNotNone(self.recorder.status['error'])
        self.recorder.message()
        self.recorder.end()
        self.recorder.recover()
        self.assertTrue(report(self.db)['incomplete'])

    def test_bogota_date_boundaries(self):
        from datetime import datetime
        self.recorder.begin()
        identifier = self.recorder.current
        with closing(connect(self.db)) as db, db:
            db.execute('UPDATE visits SET started_at=? WHERE id=?',
                       (datetime.fromisoformat('2026-11-14T04:59:59+00:00').timestamp(), identifier))
        self.assertEqual(report(self.db, '2026-11-13', '2026-11-13')['total'], 1)
        self.assertEqual(report(self.db, '2026-11-14', '2026-11-14')['total'], 0)
        with self.assertRaises(ValueError):
            report(self.db, 'bad')
        with self.assertRaises(ValueError):
            report(self.db, '2026-11-15', '2026-11-13')

    def test_authenticated_portal_and_csv_agree(self):
        from libraries.support.server import create_app
        from werkzeug.security import generate_password_hash
        self.recorder.begin()
        self.recorder.message()
        client = create_app(self.db, password_hash=generate_password_hash('test')).test_client()
        for route in ('/api/visits', '/api/visits/export.csv'):
            self.assertEqual(client.get(route).status_code, 401)
        csrf = client.get('/api/session').json['csrf']
        self.assertEqual(client.post('/api/login', json={'password': 'test'}, headers={'X-CSRF-Token': csrf}).status_code, 200)
        data = client.get('/api/visits').json
        rows = list(csv.DictReader(io.StringIO(client.get('/api/visits/export.csv').text)))
        self.assertEqual(len(rows), data['total'])
        self.assertEqual(int(rows[0]['mensajes']), data['messages'])
        self.assertIn('-05:00', rows[0]['inicio_America_Bogota'])
        self.assertEqual(client.get('/api/visits?start=bad').status_code, 400)

    def test_voice_callbacks_only_mark_state_transitions(self):
        try:
            from libraries.voice_input.arby_google_vad_iir import GoogleWorker
        except ImportError as exc:
            self.skipTest(str(exc))
        import queue
        import threading
        events = []
        worker = GoogleWorker(queue.Queue(), threading.Event(), 'es-CO', 8,
                              on_conversation_start=lambda: events.append('start'),
                              on_conversation_end=lambda: events.append('end'))
        worker._listen_for_command()
        worker._listen_for_command()
        worker._expire_followup(at=worker.deadline)
        worker._expire_followup(at=1e20)
        worker._listen_for_command()
        self.assertEqual(events, ['start', 'end', 'start'])

    def test_runtime_resets_before_first_question_and_excludes_fixed_phrases(self):
        from libraries.core.arby_runtime import ArbyRuntime
        from libraries.core.arby_response import make_reply
        from libraries.simulation.arby_muted_tts import MutedTTS
        from libraries.eyes.arby_eyes import EMOTION_STATES
        from unittest.mock import Mock
        bot = Mock()
        bot.last_error = None
        bot.respond.return_value = make_reply('Hola', 'alegres')
        runtime = ArbyRuntime(bot, MutedTTS(), emotion_colors={s: (1, 2, 3) for s in EMOTION_STATES},
                              minimum_display=0, visit_recorder=self.recorder).start()
        try:
            runtime.visit_event('start').result(2)
            runtime.submit_voice_text('Pregunta').result(2)
            runtime.submit_fixed_phrase('Prueba').result(2)
            runtime.visit_event('end').result(2)
            runtime.visit_event('start').result(2)
            runtime.submit_voice_text('Otra pregunta').result(2)
        finally:
            runtime.close()
        self.assertEqual([c[0] for c in bot.method_calls if c[0] in ('reset_session', 'respond')],
                         ['reset_session', 'respond', 'reset_session', 'respond'])
        self.assertEqual((report(self.db)['total'], report(self.db)['messages']), (2, 2))
