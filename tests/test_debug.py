"""Operational trace retention, elapsed waits and safe publication."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from libraries.core.arby_debug import DebugTrace
from libraries.core.arby_support import SupportBridge, runtime_status


class DebugTests(unittest.TestCase):
    def test_bounded_trace_and_normal_idle(self):
        trace = DebugTrace(limit=3)
        trace.stage('worker', 'Esperando', 'Queue.get')
        for index in range(5):
            trace.event('trill', 'Toque', channel=index)
        snapshot = trace.snapshot()
        self.assertEqual([event['id'] for event in snapshot['events']], [4, 5, 6])
        self.assertFalse(snapshot['stages']['worker']['slow'])
        self.assertTrue(snapshot['threads'])
        json.dumps(snapshot)

    def test_slow_stage_and_recovery(self):
        trace = DebugTrace()
        with patch('libraries.core.arby_debug.time.monotonic', return_value=100):
            trace.stage('worker', 'Modelo', 'bot.respond', 30)
        with patch('libraries.core.arby_debug.time.monotonic', return_value=131):
            self.assertTrue(trace.snapshot()['stages']['worker']['slow'])
            trace.stage('worker', 'Espera', 'Queue.get')
            self.assertFalse(trace.snapshot()['stages']['worker']['slow'])

    def test_bridge_publishes_trace_and_stale_status(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, ARBY_SUPPORT='true'):
            bridge = SupportBridge(Path(directory) / 'support.sqlite3')
            bridge.debug.event('trill', 'Toque', channel=3)
            bridge.publish()
            status = runtime_status(bridge.database)
            self.assertTrue(status['fresh'])
            self.assertEqual(status['debug']['events'][-1]['details']['channel'], 3)
            with patch('libraries.core.arby_support.time.time', return_value=status['updated_at'] + 9):
                self.assertFalse(runtime_status(bridge.database)['fresh'])
