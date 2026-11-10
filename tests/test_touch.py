"""Sensor behavior without I2C, audio, pygame or API calls."""
from concurrent.futures import Future
from copy import deepcopy
from types import SimpleNamespace
from queue import Queue
import unittest
from unittest.mock import Mock

from libraries.core.arby_touch import DEFAULTS, TouchDetector, TouchReactions, load_touch_config


class TouchTests(unittest.TestCase):
    def setUp(self):
        self.cfg = deepcopy(DEFAULTS)
        self.detector = TouchDetector(self.cfg)
        self.values = [0.0] * 30

    def test_debounce_release_and_hold(self):
        self.values[0] = .1
        self.assertEqual(self.detector.update(self.values, 0), [])
        self.assertEqual(self.detector.update(self.values, .05), [("cabeza", 0)])
        self.assertEqual(self.detector.update(self.values, 1), [])
        self.assertEqual(self.detector.update(self.values, 3), [("sostenido", 0)])
        self.assertEqual(self.detector.update(self.values, 4), [])
        self.values[0] = 0
        self.detector.update(self.values, 5)
        self.assertIsNone(self.detector.active)

    def test_unassigned_channel_does_not_hide_touch(self):
        self.values[29], self.values[8] = .8, .1
        self.detector.update(self.values, 0)
        self.assertEqual(self.detector.update(self.values, .1), [("mano", 8)])

    def test_repeated_touch(self):
        for i in range(4):
            self.values[4] = .1
            self.detector.update(self.values, i)
            events = self.detector.update(self.values, i + .1)
            self.values[4] = 0
            self.detector.update(self.values, i + .2)
        self.assertEqual(events, [("repetido", 4)])

    def test_busy_touches_are_discarded_and_cooldown_applies(self):
        reader = SimpleNamespace(read=lambda: self.values)
        future = Future()
        runtime = SimpleNamespace(pending_count=0, events=Queue(),
                                  submit_fixed_phrase=Mock(return_value=future))
        reactions = TouchReactions(reader, self.cfg)
        self.values[0] = .1
        reactions.update(runtime, 0)
        reactions.update(runtime, .1)
        runtime.submit_fixed_phrase.assert_called_once()
        self.values[0] = 0
        reactions.update(runtime, .2)
        self.values[0] = .1
        reactions.update(runtime, .3)
        reactions.update(runtime, .4)
        runtime.submit_fixed_phrase.assert_called_once()
        future.set_result(None)
        reactions.update(runtime, .5)
        self.values[0] = 0
        reactions.update(runtime, .6)
        self.values[0] = .1
        reactions.update(runtime, .7)
        reactions.update(runtime, .8)
        runtime.submit_fixed_phrase.assert_called_once()
        self.values[0] = 0
        reactions.update(runtime, 2)
        self.values[0] = .1
        reactions.update(runtime, 2.1)
        reactions.update(runtime, 2.2)
        self.assertEqual(runtime.submit_fixed_phrase.call_count, 2)

    def test_project_config(self):
        self.assertEqual(load_touch_config()["i2c_address"], "0x30")


if __name__ == "__main__":
    unittest.main()
