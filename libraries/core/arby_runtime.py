"""Serialize text and fixed phrases while exposing thread-safe visual state."""
from concurrent.futures import Future, CancelledError
from dataclasses import dataclass
import logging
from queue import Queue, Empty, Full
import threading
import time

from libraries.eyes.arby_eyes import EMOTION_STATES, normalize_state
from libraries.audio.arby_recordings import BOT_ERROR, BOT_TRY_LATER, REPEAT_QUESTION
from libraries.core.arby_response import normalize_reply, validate_color, make_segment
from libraries.core.arby_ambient import AmbientAction

LOGGER = logging.getLogger(__name__)
IDLE_COLOR = (40, 215, 255)


def validate_reply(reply):
    return normalize_reply(reply)


class ConversationFuture(Future):
    """A completed answer can ask the microphone to reopen its follow-up window."""
    retry_requested = False


@dataclass(frozen=True)
class VisualState:
    revision: int = 0
    matrix_state: str = "default"
    color: tuple = IDLE_COLOR
    phase: str = "idle"


@dataclass
class _Request:
    kind: str
    payload: object
    future: Future
    cancel: threading.Event | None = None


class ArbyRuntime:
    """Own bot and TTS clients after start(); hardware remains in the main thread.

    All future STT/sensor callbacks may submit work. Only one worker calls the
    bot, speaks, or resets the session. Fixed text bypasses Gemini and history.
    """

    def __init__(self, bot, tts, *, emotion_colors, queue_size=8, minimum_display=0.5,
                 play_ambient_clip=None, visit_recorder=None):
        if queue_size < 1 or minimum_display < 0:
            raise ValueError("Invalid runtime limits")
        self.bot, self.tts = bot, tts
        self.emotion_colors = dict(emotion_colors)
        self.minimum_display = minimum_display
        self._queue_capacity = queue_size
        self._queue = Queue(maxsize=queue_size + 1)
        self.events = Queue()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._visual = VisualState()
        self._thread = None
        self._closed = False
        self._ambient = None
        self._play_ambient_clip = play_ambient_clip
        self._activity_revision = 0
        self.visit_recorder = visit_recorder

    @property
    def visual(self):
        with self._lock:
            return self._visual

    @property
    def pending_count(self):
        with self._queue.mutex:
            return self._queue.unfinished_tasks

    @property
    def visitor_activity(self):
        """Return whether user work is pending and its submission counter."""
        with self._lock:
            pending = self.pending_count - int(self._ambient is not None)
            return pending > 0, self._activity_revision

    @property
    def capture_blocked(self):
        """Silent eye gestures can run while the microphone listens."""
        with self._lock:
            count = self.pending_count
            if not count or self._ambient is None or count > 1:
                return count > 0
            kind = self._ambient.payload.kind
            return kind == "phrase" or (kind not in ("eyes", "lights") and self._play_ambient_clip is not None)

    def try_submit_ambient(self, action: AmbientAction):
        """Admit at most one ambient action and only into an idle runtime."""
        with self._lock:
            if self._closed or self._thread is None or self.pending_count:
                return None
            request = _Request("ambient", action, Future(), threading.Event())
            self._ambient = request
            self._queue.put_nowait(request)
            return request.future

    def cancel_ambient(self, future):
        """Cancel only the support action that owns this Future, never a visitor."""
        with self._lock:
            if self._ambient is not None and self._ambient.future is future:
                self._ambient.cancel.set()
                return True
            return False

    def interrupt_ambient(self):
        with self._lock:
            if self._ambient is not None:
                self._ambient.cancel.set()

    def _set_visual(self, state, color, phase):
        with self._lock:
            self._visual = VisualState(self._visual.revision + 1, state, color, phase)

    def start(self):
        with self._lock:
            if self._closed:
                raise RuntimeError("Runtime is closed")
            if self._thread is None:
                self._thread = threading.Thread(target=self._work, name="arby-conversation", daemon=True)
                self._thread.start()
        return self

    def _submit(self, kind, payload):
        with self._lock:
            if self._closed or self._thread is None:
                raise RuntimeError("Runtime must be started and open")
            future = ConversationFuture()
            try:
                # Keep a separate slot for the single idle action, so even a
                # queue_size of one admits a visitor while the action is queued.
                with self._queue.mutex:
                    queued_visitors = sum(item.kind != "ambient" for item in self._queue.queue)
                if queued_visitors >= self._queue_capacity:
                    raise Full
                self._queue.put_nowait(_Request(kind, payload, future))
            except Full as exc:
                raise RuntimeError("La cola está llena; espera a que Arby termine.") from exc
            self._activity_revision += 1
            self.interrupt_ambient()
            return future

    def submit_text(self, text):
        """Console now; STT calls this same nonblocking method later."""
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Input text must be a nonempty string")
        return self._submit("text", text.strip())

    def visit_event(self, event):
        return self._submit('visit_' + event, None)

    def submit_voice_text(self, text):
        if not isinstance(text, str) or not text.strip():
            raise ValueError('Input text must be a nonempty string')
        return self._submit('voice_text', text.strip())

    def submit_fixed_phrase(self, text, *, state="alegres", color=None):
        """Future sensor hook. Speak supplied text without a Gemini request."""
        return self._submit("fixed", self._fixed_reply(text, state, color))

    def _fixed_reply(self, text, state, color=None):
        state = normalize_state(state)
        if state not in EMOTION_STATES:
            raise ValueError("Fixed phrases require an emotion")
        color = validate_color(self.emotion_colors[state] if color is None else color)
        r, g, b = color
        return validate_reply({"matrix_state": state,
            "strip_led": {"color": {"r": r, "g": g, "b": b}, "mood": state},
            "response": text})

    def reset_session(self):
        return self._submit("reset", None)

    def _speak(self, reply, cancel=None):
        started = time.monotonic()
        color = validate_color(reply["strip_led"]["color"])
        self._set_visual(reply["matrix_state"], color, "speaking")
        with self._lock:
            if self._stop.is_set() or (cancel is not None and cancel.is_set()):
                raise CancelledError()
            accepted = self.tts.speak(reply["response"])
        if not accepted:
            raise RuntimeError("TTS rejected the utterance")
        while not self.tts.wait(0.05):
            if self._stop.is_set():
                raise CancelledError()
            if cancel is not None and cancel.is_set():
                if self.tts.stop() is False:
                    raise RuntimeError("No se pudo detener la invitación.")
                raise CancelledError()
        if self.tts.last_error:
            self.events.put(("error", f"TTS: {self.tts.last_error}"))
            raise RuntimeError('No se pudo reproducir la voz de Arby.')
        wait_for = cancel if cancel is not None else self._stop
        wait_for.wait(max(0, self.minimum_display - (time.monotonic() - started)))
        if self._stop.is_set() or wait_for.is_set():
            raise CancelledError()

    def _run_ambient(self, request):
        action, cancel = request.payload, request.cancel
        if cancel.is_set():
            raise CancelledError()
        if action.kind == "phrase":
            reply = self._fixed_reply(action.text, action.matrix_state)
            self.events.put(("response", reply["response"]))
            for segment in reply["segments"]:
                self._speak(segment, cancel)
            return reply
        state = normalize_state(action.matrix_state)
        color = validate_color(action.color if action.color is not None else self.emotion_colors[state])
        if action.kind in ("eyes", "lights") or self._play_ambient_clip is None:
            self._set_visual(state, color, "speaking" if action.kind == "lights" else "idle")
            cancel.wait(action.duration_seconds or 1.5)
        else:
            self._set_visual(state, color, "speaking")
            self._play_ambient_clip(action.kind, cancel)
        if cancel.is_set() or self._stop.is_set():
            raise CancelledError()
        return None

    def _speak_reply(self, reply):
        segments = reply["segments"]
        speak_segments = getattr(self.tts, "speak_segments", None)
        if not callable(speak_segments):
            # Compatibility with older TTS adapters and the muted preview.
            for segment in segments:
                if self._stop.is_set():
                    raise CancelledError()
                self._speak(segment)
            return

        def on_segment(index):
            if self._stop.is_set():
                return
            segment = segments[index]
            self._set_visual(segment["matrix_state"],
                             validate_color(segment["strip_led"]["color"]), "speaking")

        with self._lock:
            if self._stop.is_set():
                raise CancelledError()
            accepted = speak_segments([s["response"] for s in segments], on_segment=on_segment)
        if not accepted:
            raise RuntimeError("TTS rejected the sequence")
        while not self.tts.wait(0.05):
            if self._stop.is_set():
                raise CancelledError()
        if self._stop.is_set():
            raise CancelledError()
        if self.tts.last_error:
            self.events.put(("error", f"TTS: {self.tts.last_error}"))
            raise RuntimeError('No se pudo reproducir la voz de Arby.')

    def _model_reply(self, text):
        """Speak one bounded fallback for query/validation failures, not TTS failures."""
        try:
            reply = self.bot.respond(text)
            if self._stop.is_set():
                raise CancelledError()
            reply = validate_reply(reply)
            if not reply['segments']:
                raise ValueError('Empty assistant response')
            error = getattr(self.bot, 'last_error', None)
            retry = isinstance(error, str) and bool(error)
            if retry:
                self.events.put(('error', 'No se pudo completar la consulta al asistente.'))
            asks_to_repeat = reply['response'] == REPEAT_QUESTION
            if asks_to_repeat:
                # The model may split this known prompt into two sentences. Keep
                # the catalog phrase intact so its local recording can be reused.
                reply = normalize_reply(make_segment(REPEAT_QUESTION, 'duda'))
            return reply, retry or asks_to_repeat
        except CancelledError:
            raise
        except Exception as exc:
            if self._stop.is_set():
                raise CancelledError() from exc
            # Never echo provider details or the user's question into the fallback.
            self.events.put(('error', f'Consulta al asistente: {type(exc).__name__}'))
            LOGGER.warning('Assistant query failed: %s', type(exc).__name__)
            return normalize_reply({'segments': [
                make_segment(BOT_ERROR, 'pensativos'),
                make_segment(BOT_TRY_LATER, 'duda'),
            ]}), True

    def _work(self):
        try:
            if self.visit_recorder:
                self.visit_recorder.recover()
            while not self._stop.is_set():
                try:
                    request = self._queue.get(timeout=0.05)
                except Empty:
                    continue
                try:
                    if not request.future.set_running_or_notify_cancel():
                        continue
                    if self._stop.is_set():
                        raise CancelledError()
                    if request.kind == "ambient":
                        reply = self._run_ambient(request)
                    elif request.kind.startswith('visit_'):
                        if request.kind == 'visit_start':
                            self.bot.reset_session()
                            self.visit_recorder.begin()
                        else:
                            self.visit_recorder.end()
                        reply = None
                    elif request.kind == "reset":
                        self.bot.reset_session()
                        reply = None
                        self.events.put(("info", "Conversación reiniciada."))
                    else:
                        if request.kind in ("text", "voice_text"):
                            if request.kind == "voice_text" and self.visit_recorder:
                                self.visit_recorder.message()
                            self._set_visual("cargando", IDLE_COLOR, "loading")
                            reply, request.future.retry_requested = self._model_reply(request.payload)
                        else:
                            reply = request.payload
                        self.events.put(("response", reply["response"]))
                        self._speak_reply(reply)
                    request.future.set_result(reply)
                except CancelledError as exc:
                    request.future.set_exception(exc)
                except Exception as exc:
                    try:
                        self.tts.stop()
                    except Exception:
                        LOGGER.warning("Playback cleanup failed")
                    if request.kind == "ambient":
                        self.events.put(("error", f"Acción de evento ({request.payload.kind}): {exc}"))
                    else:
                        self.events.put(("error", f"No se completó la solicitud: {type(exc).__name__}"))
                    request.future.set_exception(exc)
                    LOGGER.debug("Request failed", exc_info=True)
                finally:
                    with self._lock:
                        self._set_visual("default", IDLE_COLOR, "idle")
                        if request is self._ambient:
                            self._ambient = None
                        self._queue.task_done()
        finally:
            if self.visit_recorder:
                self.visit_recorder.end('shutdown')
            self._cancel_pending()
            for client in (self.tts, self.bot):
                try:
                    client.close()
                except Exception:
                    LOGGER.warning("Client cleanup failed: %s", type(client).__name__)

    def _cancel_pending(self):
        while True:
            try:
                request = self._queue.get_nowait()
            except Empty:
                return
            request.future.cancel()
            with self._lock:
                if request is self._ambient:
                    self._ambient = None
                self._queue.task_done()

    def close(self, timeout=5.0):
        """Stop playback and pending work; an in-flight network call may finish later."""
        with self._lock:
            self._closed = True
            self._stop.set()
            self.interrupt_ambient()
        self._cancel_pending()
        try:
            self.tts.stop()
        except Exception:
            LOGGER.warning("TTS stop failed")
        if self._thread is None:
            for client in (self.tts, self.bot):
                client.close()
            return True
        if self._thread is threading.current_thread():
            return False
        self._thread.join(timeout)
        return not self._thread.is_alive()
