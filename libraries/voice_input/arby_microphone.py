"""Bridge microphone recognition to the shared conversation runtime."""
import threading
import time

from libraries.audio.arby_recordings import REPEAT_QUESTION


class MicrophoneInput:
    def __init__(self, runtime, config, stop, input_done):
        # Optional audio dependencies are only imported in voice mode.
        from libraries.voice_input.arby_google_vad_iir import ArbyPipeline
        self.runtime = runtime
        self.stop = stop
        self.input_done = input_done
        self.resume_at = 0.0
        self.error = None
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
        if not self.is_paused():
            return self.runtime.submit_fixed_phrase(
                REPEAT_QUESTION, state="duda",
            )
        return None

    def start(self):
        self.thread.start()
        return self

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
        if self.thread.ident is not None:
            self.thread.join(timeout=2.0)
