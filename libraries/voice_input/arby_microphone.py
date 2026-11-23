"""Bridge microphone recognition to the shared conversation runtime."""
import socket
import threading
import time

from libraries.audio.arby_recordings import REPEAT_PHRASES


class MicrophoneInput:
    def __init__(self, runtime, config, stop, input_done):
        # Optional audio dependencies are only imported in voice mode.
        from libraries.voice_input.arby_google_vad_iir import ArbyPipeline
        self.runtime = runtime
        self.stop = stop
        self.input_done = input_done
        self.resume_at = 0.0
        self.error = None
        self.push_to_talk = getattr(config, "push_to_talk", False)
        self.udp_socket = None
        self.udp_thread = None
        self._repeat_index = 0
        self.track_visits = getattr(runtime, "visit_recorder", None) is not None
        self.pipeline = ArbyPipeline(config, on_question=self.submit,
                                     on_unrecognized=self.request_repetition,
                                     is_paused=self.is_paused,
                                     on_voice_start=self.voice_started,
                                     on_conversation_start=(lambda: runtime.visit_event('start')) if self.track_visits else None,
                                     on_conversation_end=(lambda: runtime.visit_event('end')) if self.track_visits else None)
        self.pipeline.google_worker.debug = getattr(runtime, "debug", None)
        self.thread = threading.Thread(target=self.run, name="arby-microphone", daemon=True)

    def trace(self, message, **details):
        debug = getattr(self.runtime, 'debug', None)
        if debug:
            debug.event('microfono', message, **details)

    def voice_started(self):
        self.trace('Inicio de voz detectado')
        self.runtime.interrupt_ambient()

    def is_paused(self):
        if self.runtime.capture_blocked:
            # Also discard the tail of speaker audio after playback ends.
            self.resume_at = time.monotonic() + 0.35
            return True
        return self.stop.is_set() or time.monotonic() < self.resume_at

    def try_submit_ambient(self, action):
        return self.pipeline.when_idle(lambda: self.runtime.try_submit_ambient(action))

    def submit(self, text):
        # The pipeline already excludes playback before delivering recognized text.
        # A queued visit-start reset must not discard its accompanying question.
        if self.track_visits or not self.is_paused():
            self.trace("Reconocimiento completado", characters=len(text))
            return (self.runtime.submit_voice_text(text) if self.track_visits
                    else self.runtime.submit_text(text))

    def request_repetition(self):
        self.trace("Voz no reconocida; solicitando repetición")
        if self.is_paused():
            return None
        phrase = REPEAT_PHRASES[self._repeat_index]
        pending = self.runtime.submit_fixed_phrase(phrase, state="duda")
        if pending is not None:
            self._repeat_index = (self._repeat_index + 1) % len(REPEAT_PHRASES)
        return pending

    def start(self):
        if self.push_to_talk:
            self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                self.udp_socket.bind(("0.0.0.0", 5005))
                self.udp_socket.settimeout(0.2)
            except Exception:
                self.udp_socket.close()
                self.udp_socket = None
                raise
            self.udp_thread = threading.Thread(target=self.listen_button, name="arby-push-to-talk", daemon=True)
            self.udp_thread.start()
        self.thread.start()
        return self

    def listen_button(self):
        try:
            while not self.stop.is_set() and not self.pipeline.stop_event.is_set():
                try:
                    payload, _ = self.udp_socket.recvfrom(1024)
                except socket.timeout:
                    continue
                if payload.strip() in (b"1", b"\x01"):
                    self.runtime.interrupt_ambient()
                    self.pipeline.google_worker.activation_requested.set()
                    self.trace("Botón UDP recibido", port=5005)
        except OSError as exc:
            if not self.stop.is_set() and not self.pipeline.stop_event.is_set():
                self.error = exc
                self.runtime.events.put(("error", f"Push to talk UDP: {exc}"))
                self.stop.set()

    def run(self):
        try:
            self.pipeline.run()
        except Exception as exc:
            self.error = exc
            self.trace("Entrada de audio fallida", error=type(exc).__name__)
            self.runtime.events.put(("error", f"Micrófono: {type(exc).__name__}: {exc}"))
            self.stop.set()
        finally:
            self.input_done.set()

    def close(self):
        self.pipeline.close()
        if self.udp_thread is not None:
            self.udp_thread.join(timeout=1.0)
        if self.udp_socket is not None:
            self.udp_socket.close()
        if self.thread.ident is not None:
            self.thread.join(timeout=2.0)
