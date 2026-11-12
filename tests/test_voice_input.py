"""Offline voice contracts: activation, runtime bridge and playback exclusion."""
import collections
from concurrent.futures import Future
import os
import queue
import sys
import io
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import run_arby
from libraries.voice_input.arby_microphone import MicrophoneInput

# Optional voice packages are needed, but PortAudio/hardware are not.
try:
    from libraries.voice_input.arby_google_vad_iir import (
        ArbyPipeline, GoogleWorker, SpeechSegment, wake_match, sr,
    )
except ImportError as exc:
    raise unittest.SkipTest(f"Instala el extra voice: {exc}")


class VoiceTests(unittest.TestCase):
    def recognize(self, phrases, *, followup=8, generation=None):
        jobs, stop, delivered = queue.Queue(), threading.Event(), []
        worker = GoogleWorker(jobs, stop, "es-CO", followup,
                              on_question=delivered.append, generation=generation)
        phrases = iter(phrases)
        def recognize(*args, **kwargs):
            try:
                return next(phrases)
            except StopIteration:
                stop.set()
                return ""
        worker.recognizer.recognize_google = recognize
        for _ in range(6):
            jobs.put(b'\0' * 1024)
        worker.start()
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        return delivered

    def test_activation_preserves_question(self):
        self.assertEqual(wake_match("¡Arbi! ¿Cuánto es 12 + 3?"),
                         (True, "Cuánto es 12 + 3?"))
        self.assertEqual(self.recognize(["ruido", "Arby, cuánto es 12 + 3?",
                                         "otra pregunta"]), ["cuánto es 12 + 3?", "otra pregunta"])

    def test_activation_matches_whole_name(self):
        self.assertEqual(wake_match("ARBY"), (True, ""))
        self.assertEqual(wake_match("Arby, ¿qué hora es?"), (True, "qué hora es?"))
        self.assertEqual(wake_match("arbyte"), (False, ""))
        self.assertEqual(wake_match("hola"), (False, ""))

    def test_separate_questions_continue_without_repeating_wake_word(self):
        self.assertEqual(self.recognize(["Arby", "¿Cómo estás?", "cuéntame más"]),
                         ["¿Cómo estás?", "cuéntame más"])

    def test_active_question_can_mention_arby_without_becoming_a_wake_command(self):
        self.assertEqual(self.recognize(['Arby', '¿Por qué te llamas Arby?', 'Arby, dime algo']),
                         ['¿Por qué te llamas Arby?', 'dime algo'])

    def test_unrecognized_voice_requests_repetition_only_after_activation(self):
        for failure in (sr.UnknownValueError(), sr.RequestError('offline'), TimeoutError(), ConnectionError()):
            with self.subTest(failure=type(failure).__name__):
                prompt = Future()
                feedback, deliver = Mock(return_value=prompt), Mock()
                worker = GoogleWorker(queue.Queue(), threading.Event(), 'es-CO', 8,
                                      on_question=deliver, on_unrecognized=feedback)
                recognize = worker.recognizer.recognize_google = Mock(side_effect=[failure, 'Arby', failure, '¿Cómo estás?'])
                worker._recognize(bytes(1024))
                feedback.assert_not_called()
                worker._recognize(bytes(1024))
                worker._recognize(bytes(1024))
                feedback.assert_called_once_with()
                worker._recognize(bytes(1024))
                self.assertEqual(recognize.call_count, 3)
                prompt.set_result(None)
                worker._recognize(bytes(1024))
                deliver.assert_called_once_with('¿Cómo estás?')

    def test_empty_transcription_asks_to_repeat(self):
        feedback = Mock(return_value=Future())
        worker = GoogleWorker(queue.Queue(), threading.Event(), 'es-CO', 8, on_unrecognized=feedback)
        worker.recognizer.recognize_google = Mock(side_effect=['Arby', '   '])
        worker._recognize(bytes(1024))
        worker._recognize(bytes(1024))
        feedback.assert_called_once_with()

    def test_model_failure_reopens_only_after_audio_and_echo_tail(self):
        future = Future()
        deliver = Mock(return_value=future)
        paused = [False]
        generation = [0]
        worker = GoogleWorker(queue.Queue(), threading.Event(), 'es-CO', 8, on_question=deliver,
                              is_paused=lambda: paused[0], generation=lambda: generation[0])
        worker.recognizer.recognize_google = Mock(side_effect=['Arby, pregunta', 'pregunta repetida'])
        worker._recognize(bytes(1024))
        future.retry_requested = True
        future.set_result(None)
        paused[0] = True
        generation[0] += 1
        worker._resume_followup()
        self.assertIsNone(worker.deadline)
        paused[0] = False
        worker._recognize(bytes(1024))
        self.assertEqual(deliver.call_args_list, [unittest.mock.call('pregunta'), unittest.mock.call('pregunta repetida')])

    def test_silence_expires_after_one_minute_without_announcements(self):
        feedback = Mock(return_value=Future())
        worker = GoogleWorker(queue.Queue(), threading.Event(), 'es-CO', 8, on_unrecognized=feedback)
        with patch('libraries.voice_input.arby_google_vad_iir.time.monotonic', return_value=100):
            worker._listen_for_command()
        self.assertEqual(worker.deadline, 160)
        with patch('libraries.voice_input.arby_google_vad_iir.time.monotonic', return_value=159):
            worker._expire_followup()
        self.assertEqual(worker.mode, 'COMMAND')
        with patch('libraries.voice_input.arby_google_vad_iir.time.monotonic', return_value=160):
            worker._expire_followup()
        feedback.assert_not_called()
        self.assertEqual(worker.mode, 'WAKE')

    def test_repeat_cooldown_does_not_permanently_disable_prompts(self):
        prompts = []
        def feedback():
            prompt = Future()
            prompts.append(prompt)
            return prompt
        worker = GoogleWorker(queue.Queue(), threading.Event(), 'es-CO', 8, on_unrecognized=feedback)
        worker.recognizer.recognize_google = Mock(side_effect=['Arby'] + [sr.UnknownValueError()] * 4)
        clock = [100]
        with patch('libraries.voice_input.arby_google_vad_iir.time.monotonic', side_effect=lambda: clock[0]):
            worker._recognize(bytes(1024))
            clock[0] = 101
            worker._recognize(bytes(1024))
            self.assertEqual(len(prompts), 1)
            clock[0] = 102
            prompts[-1].set_result(None)
            worker._resume_followup()
            clock[0] = 105
            with patch('libraries.voice_input.arby_google_vad_iir.log') as log:
                worker._recognize(bytes(1024))
            self.assertTrue(any('pausa breve entre avisos' in call.args[0] for call in log.call_args_list))
            self.assertEqual(len(prompts), 1)
            clock[0] = 111
            worker._recognize(bytes(1024))
            self.assertEqual(len(prompts), 2)
            clock[0] = 112
            prompts[-1].set_result(None)
            worker._resume_followup()
            clock[0] = 121
            worker._recognize(bytes(1024))
            self.assertEqual(len(prompts), 3)
            # Noise does not renew a full minute after every repetition request.
            self.assertEqual(worker.deadline, 160)

    def test_minute_starts_after_each_answer_and_echo_tail(self):
        first, second = Future(), Future()
        deliver = Mock(side_effect=[first, second])
        paused = [False]
        worker = GoogleWorker(queue.Queue(), threading.Event(), 'es-CO', 8, on_question=deliver,
                              is_paused=lambda: paused[0])
        worker.recognizer.recognize_google = Mock(side_effect=['Arby, pregunta', 'otra pregunta', 'fuera de tiempo'])
        clock = [100]
        with patch('libraries.voice_input.arby_google_vad_iir.time.monotonic', side_effect=lambda: clock[0]):
            worker._recognize(bytes(1024))
            self.assertIsNone(worker.deadline)
            clock[0] = 200
            first.set_result(None)
            paused[0] = True
            worker._resume_followup()
            self.assertIsNone(worker.deadline)
            paused[0] = False
            clock[0] = 201
            worker._resume_followup()
            self.assertEqual(worker.deadline, 261)
            clock[0] = 260
            worker._recognize(bytes(1024))
            self.assertIsNone(worker.deadline)
            clock[0] = 300
            second.set_result(None)
            worker._resume_followup()
            self.assertEqual(worker.deadline, 360)
            clock[0] = 360
            worker._recognize(bytes(1024))
        self.assertEqual(deliver.call_args_list, [unittest.mock.call('pregunta'), unittest.mock.call('otra pregunta')])
        self.assertEqual(worker.mode, 'WAKE')

    def test_capture_generation_changes_do_not_reset_the_conversation(self):
        jobs, stop = queue.Queue(), threading.Event()
        generation, questions = [0], []
        def deliver(text):
            questions.append(text)
            generation[0] += 1  # A playback pause flushes the capture pipeline.
            future = Future()
            future.set_result(None)
            return future
        worker = GoogleWorker(jobs, stop, 'es-CO', 8, on_question=deliver, generation=lambda: generation[0])
        phrases = iter(['Arby, hola', 'seguimos'])
        def recognize(*args, **kwargs):
            try:
                return next(phrases)
            except StopIteration:
                stop.set()
                return ''
        worker.recognizer.recognize_google = recognize
        for _ in range(3):
            jobs.put(bytes(1024))
        worker.start()
        worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(questions, ['hola', 'seguimos'])

    def test_cancelled_prompt_does_not_renew_the_minute(self):
        worker = GoogleWorker(queue.Queue(), threading.Event(), 'es-CO', 8)
        with patch('libraries.voice_input.arby_google_vad_iir.time.monotonic', return_value=100):
            worker._listen_for_command()
        cancelled = Future()
        cancelled.cancel()
        worker.repeat_prompt = cancelled
        with patch('libraries.voice_input.arby_google_vad_iir.time.monotonic', return_value=130):
            worker._resume_followup()
        self.assertEqual(worker.mode, 'COMMAND')
        self.assertEqual(worker.deadline, 160)

    def test_repeat_playback_failure_is_logged_and_listening_continues(self):
        prompt = Future()
        feedback = Mock(return_value=prompt)
        worker = GoogleWorker(queue.Queue(), threading.Event(), 'es-CO', 8, on_unrecognized=feedback)
        worker._listen_for_command()
        worker._request_repeat(0)
        prompt.set_exception(RuntimeError('voice unavailable'))
        with patch('libraries.voice_input.arby_google_vad_iir.log') as log:
            worker._resume_followup()
        self.assertTrue(any('No se pudo reproducir' in call.args[0] for call in log.call_args_list))
        self.assertEqual(worker.mode, 'COMMAND')

    def test_inactive_unknown_audio_logs_why_no_prompt_is_spoken(self):
        feedback = Mock(return_value=Future())
        worker = GoogleWorker(queue.Queue(), threading.Event(), 'es-CO', 8, on_unrecognized=feedback)
        worker.recognizer.recognize_google = Mock(side_effect=sr.UnknownValueError())
        with patch('libraries.voice_input.arby_google_vad_iir.log') as log:
            worker._recognize(bytes(1024))
        self.assertTrue(any('no hay conversación activa' in call.args[0] for call in log.call_args_list))
        feedback.assert_not_called()

    def test_failed_stale_or_paused_recognition_never_speaks(self):
        for reason in ('stale', 'paused', 'stopped'):
            generation, paused = [0], [False]
            stop = threading.Event()
            feedback = Mock(return_value=Future())
            worker = GoogleWorker(queue.Queue(), stop, 'es-CO', 8, on_unrecognized=feedback,
                                  generation=lambda: generation[0], is_paused=lambda: paused[0])
            worker._listen_for_command()
            def recognize(*args, **kwargs):
                if reason == 'stale': generation[0] += 1
                elif reason == 'paused': paused[0] = True
                else: stop.set()
                raise sr.UnknownValueError()
            worker.recognizer.recognize_google = recognize
            worker._recognize(bytes(1024))
            feedback.assert_not_called()

    def test_speech_starting_inside_the_minute_finishes_after_deadline(self):
        delivered = []
        worker = GoogleWorker(queue.Queue(), threading.Event(), 'es-CO', 8, on_question=delivered.append)
        worker.recognizer.recognize_google = Mock(return_value='pregunta al final')
        with patch('libraries.voice_input.arby_google_vad_iir.time.monotonic', return_value=100):
            worker._listen_for_command()
        with patch('libraries.voice_input.arby_google_vad_iir.time.monotonic', return_value=164):
            worker._recognize(SpeechSegment(bytes(1024), 159, 0))
        self.assertEqual(delivered, ['pregunta al final'])

    def test_expired_activation_does_not_deliver(self):
        deliver = Mock()
        worker = GoogleWorker(queue.Queue(), threading.Event(), 'es-CO', 8, on_question=deliver)
        worker.recognizer.recognize_google = Mock(return_value='demasiado tarde')
        with patch('libraries.voice_input.arby_google_vad_iir.time.monotonic', return_value=100):
            worker._listen_for_command()
        with patch('libraries.voice_input.arby_google_vad_iir.time.monotonic', return_value=161):
            worker._recognize(SpeechSegment(bytes(1024), 161, 0))
        deliver.assert_not_called()
        self.assertEqual(worker.mode, 'WAKE')

    def test_queued_speech_from_before_pause_is_discarded_without_stt(self):
        worker = GoogleWorker(queue.Queue(), threading.Event(), 'es-CO', 8, generation=lambda: 2)
        recognize = worker.recognizer.recognize_google = Mock()
        worker._recognize(SpeechSegment(bytes(1024), 100, 1))
        recognize.assert_not_called()

    def test_inflight_recognition_is_discarded_on_pause(self):
        jobs, stop = queue.Queue(), threading.Event()
        generation = [0]
        delivered = []
        worker = GoogleWorker(jobs, stop, "es-CO", 8, on_question=delivered.append,
                              generation=lambda: generation[0])
        def recognize(*args, **kwargs):
            if generation[0]:
                stop.set()
                return ""
            generation[0] += 1
            return "Arby pregunta vieja"
        worker.recognizer.recognize_google = recognize
        jobs.put(b'\0' * 1024)
        jobs.put(b"\0" * 1024)
        worker.start()
        worker.join(1)
        self.assertEqual(delivered, [])

    def test_bridge_suppresses_busy_audio_and_resumes_after_tail(self):
        runtime = SimpleNamespace(pending_count=1, capture_blocked=True, interrupt_ambient=Mock(),
                                  events=queue.Queue(), submit_text=Mock(),
                                  submit_fixed_phrase=Mock())
        with patch.dict(os.environ, {}, clear=True):
            config = run_arby.load_config().microphone
        mic = MicrophoneInput(runtime, config, threading.Event(), threading.Event())
        with patch('libraries.voice_input.arby_microphone.time.monotonic', return_value=10):
            mic.submit("eco")
            mic.request_repetition()
        runtime.submit_fixed_phrase.assert_not_called()
        runtime.submit_text.assert_not_called()
        runtime.pending_count = 0
        runtime.capture_blocked = False
        with patch('libraries.voice_input.arby_microphone.time.monotonic', return_value=10.2):
            self.assertTrue(mic.is_paused())
        with patch('libraries.voice_input.arby_microphone.time.monotonic', return_value=10.4):
            mic.submit("pregunta")
            mic.request_repetition()
        runtime.submit_fixed_phrase.assert_called_once_with(
            "Perdón, no te escuché bien. ¿Me lo repites?", state="duda",
        )
        runtime.submit_text.assert_called_once_with("pregunta")

    def test_support_meter_normalizes_int32_and_uses_selected_channel(self):
        with patch.dict(os.environ, {}, clear=True):
            config = run_arby.load_config().microphone
        pipeline = ArbyPipeline(config)
        pipeline._capture_channel = 1
        samples = np.array([[0, 1073741824], [0, -1073741824]], dtype=np.int32)
        pipeline.callback(samples, 2, None, None)
        self.assertAlmostEqual(pipeline.input_level, 0.5)
        pipeline.is_paused = lambda: True
        pipeline.callback(samples, 2, None, None)
        self.assertEqual(pipeline.input_level, 0)
        pipeline.close()

    def test_continuous_speech_has_bounded_segment(self):
        with patch.dict(os.environ, {}, clear=True):
            config = run_arby.load_config().microphone
        pipeline = ArbyPipeline(config)
        pipeline.max_utterance_seconds = 0.224
        pipeline.vad = Mock(side_effect=[{"start": 0}] + [None] * 6)
        state = {"active": False, "parts": []}
        pipeline.process_vad_audio(bytes(7168), bytearray(), collections.deque(maxlen=10), state)
        self.assertEqual(len(pipeline.google_q.get_nowait().pcm), 7168)
        self.assertFalse(state['active'])

    def test_real_onnx_and_resampler_accept_frames(self):
        with patch.dict(os.environ, {}, clear=True):
            config = run_arby.load_config().microphone
        pipeline = ArbyPipeline(config)
        from silero_onnx import load_silero_vad, VADIterator
        vad = VADIterator(load_silero_vad(), sampling_rate=16000)
        self.assertIsNone(vad(np.zeros(512, dtype=np.float32)))
        pipeline.resampler.clear()

    def test_microphone_failure_returns_error_and_stops_workers(self):
        audio = Mock()
        audio.InputStream.side_effect = RuntimeError("entrada no disponible")
        with patch.dict(os.environ, {"ARBY_INPUT_MODE": "voice", "ARBY_DEMO": "true",
                                    "ARBY_MUTE": "true", "ARBY_EYES": "none"}, clear=True), \
                patch.object(run_arby, "load_environment"), \
                patch.object(sys, "argv", ["run_arby.py"]), \
                patch.dict(sys.modules, {"sounddevice": audio}), \
                patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(run_arby.main(), 1)
        self.assertFalse(any(t.name == "arby-microphone" for t in threading.enumerate()))

    def test_invalid_microphone_settings_fail_before_hardware(self):
        for name, value in [('THRESHOLD','nan'), ('QUEUE_BLOCKS','0'),
                            ('BLOCK_MS','15'), ('MAX_UTTERANCE_SECONDS','inf')]:
            with self.subTest(name=name), patch.dict(os.environ, {f'ARBY_MIC_{name}':value}, clear=True):
                with self.assertRaises(ValueError):
                    run_arby.load_config()


if __name__ == '__main__':
    unittest.main()
