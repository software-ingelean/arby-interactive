"""UDP button lifecycle without audio hardware or optional voice dependencies."""
import queue
import socket
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from libraries.voice_input.arby_microphone import MicrophoneInput


class PushToTalkTests(unittest.TestCase):
    def test_udp_button_filters_packets_and_stops_listener(self):
        pipeline = Mock()
        pipeline.stop_event = threading.Event()
        pipeline.google_worker.activation_requested = threading.Event()
        pipeline.run.side_effect = lambda: pipeline.stop_event.wait(3)
        pipeline.close.side_effect = pipeline.stop_event.set
        runtime = SimpleNamespace(events=queue.Queue(), interrupt_ambient=Mock())
        udp = Mock()
        packets = iter([b'0', b'other', b'1\n', b'\x01'])

        def receive(_):
            try:
                payload = next(packets)
            except StopIteration:
                pipeline.stop_event.set()
                raise socket.timeout()
            return payload, ('192.168.1.10', 1234)

        udp.recvfrom.side_effect = receive
        module = SimpleNamespace(ArbyPipeline=Mock(return_value=pipeline))
        with patch.dict(sys.modules, {'libraries.voice_input.arby_google_vad_iir': module}), \
                patch('libraries.voice_input.arby_microphone.socket.socket', return_value=udp):
            mic = MicrophoneInput(runtime, SimpleNamespace(push_to_talk=True),
                                  threading.Event(), threading.Event())
            try:
                mic.start()
                mic.udp_thread.join(2)
                self.assertFalse(mic.udp_thread.is_alive())
                udp.bind.assert_called_once_with(('0.0.0.0', 5005))
                self.assertEqual(runtime.interrupt_ambient.call_count, 2)
                self.assertTrue(pipeline.google_worker.activation_requested.is_set())
            finally:
                mic.close()
            udp.close.assert_called_once()
            self.assertFalse(mic.thread.is_alive())

    def test_disabled_mode_does_not_open_udp(self):
        pipeline = Mock()
        module = SimpleNamespace(ArbyPipeline=Mock(return_value=pipeline))
        with patch.dict(sys.modules, {'libraries.voice_input.arby_google_vad_iir': module}), \
                patch('libraries.voice_input.arby_microphone.socket.socket') as socket_factory:
            mic = MicrophoneInput(SimpleNamespace(), SimpleNamespace(),
                                  threading.Event(), threading.Event())
            mic.start()
            mic.close()
            socket_factory.assert_not_called()
