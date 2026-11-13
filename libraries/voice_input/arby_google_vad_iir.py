#!/usr/bin/env python3
"""
ARBY: INMP441 -> filtro IIR de voz -> ganancia fija -> limitador
-> remuestreo 16 kHz -> Silero VAD -> Google Speech Recognition.

Filtro IIR:
- Pasaaltos Butterworth de 2º orden (80 Hz por defecto).
- Pasabajos Butterworth de 2º orden (8000 Hz por defecto).
- Estado SOS conservado entre bloques.
- Ganancia fija configurable.
- Limitador de pico por bloque a -1 dBFS.

No utiliza DeepFilterNet, Vosk ni reducción espectral.
"""

from __future__ import annotations

import logging
import argparse
import collections
from concurrent.futures import Future
from dataclasses import dataclass
import queue
import re
import signal
import sys
import threading
import time
import unicodedata

import numpy as np
import soxr
import speech_recognition as sr
from scipy import signal as scipy_signal
from silero_onnx import load_silero_vad, VADIterator


FS_IN = 48_000
FS_OUT = 16_000
S32_SCALE = 2_147_483_648.0

VAD_FRAME = 512
VAD_FRAME_BYTES = VAD_FRAME * 2
CONVERSATION_IDLE_SECONDS = 30.0
REPEAT_COOLDOWN_SECONDS = 8.0


def log(*args):
    message = ' '.join(str(arg) for arg in args)
    logger = logging.getLogger(__name__)
    if any(marker in message for marker in ('[WARN]', '[ALSA]', 'Error:', 'Error de servicio/red:', 'No se pudo')):
        logger.warning('%s', message)
    else:
        logger.debug('%s', message)


def input_layout(sd, device, channel):
    """Keep I2S stereo selection while accepting mono capture devices."""
    info = sd.query_devices(device, kind="input")
    maximum = int(info["max_input_channels"])
    if maximum < 1:
        raise ValueError(
            f"ARBY_MIC_DEVICE={device}: {info['name']} no tiene canales de entrada. "
            "Lista los dispositivos con: .venv/bin/python -m sounddevice"
        )
    channels = min(2, maximum)
    selected = 0 if channels == 1 or channel == "left" else 1
    return info, channels, selected


class FiltroVoz:
    """Entrada/salida float32 mono [-1, 1], con estado entre fragmentos."""

    def __init__(
        self,
        frecuencia=48_000,
        graves=80.0,
        agudos=8_000.0,
        ganancia_db=6.0,
    ):
        values = (frecuencia, graves, agudos, ganancia_db)
        if not all(np.isfinite(v) for v in values):
            raise ValueError("Parámetros del filtro no finitos.")

        if (
            frecuencia <= 0
            or not 0 < graves < agudos < frecuencia / 2
            or not -30 <= ganancia_db <= 36
        ):
            raise ValueError(
                "Requiere 0 < graves < agudos < fs/2 "
                "y ganancia entre -30 y 36 dB."
            )

        sos_hp = scipy_signal.butter(
            2, graves, "highpass", fs=frecuencia, output="sos"
        )
        sos_lp = scipy_signal.butter(
            2, agudos, "lowpass", fs=frecuencia, output="sos"
        )

        self.sos = np.concatenate((sos_hp, sos_lp))
        self.zi = np.zeros((len(self.sos), 2), dtype=np.float64)

        self.ganancia = 10.0 ** (ganancia_db / 20.0)
        self.techo = 10.0 ** (-1.0 / 20.0)

        self.limitados = 0
        self.clipping_entrada = 0
        self.bloques = 0

    def procesar(self, audio):
        x = np.asarray(audio, dtype=np.float32)

        if x.ndim != 1 or not np.isfinite(x).all():
            raise ValueError(
                "Se espera audio mono, normalizado y con valores finitos."
            )

        if not len(x):
            return x.copy()

        self.clipping_entrada += int(np.count_nonzero(np.abs(x) >= 0.999))

        y, self.zi = scipy_signal.sosfilt(self.sos, x, zi=self.zi)

        # Ganancia fija. Si el pico supera -1 dBFS, se reduce
        # la ganancia de ese bloque para evitar saturación.
        pico = float(np.max(np.abs(y)))
        factor = min(self.ganancia, self.techo / max(pico, 1e-12))

        self.limitados += int(factor < self.ganancia)
        self.bloques += 1

        return (y * factor).astype(np.float32)


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(
        c for c in text if not unicodedata.combining(c)
    )
    return re.sub(
        r"\s+", " ", re.sub(r"[^a-zñ\s]", " ", text)
    ).strip()


def wake_match(text: str):
    """Devuelve (coincide, texto posterior a la palabra de activación)."""
    # Keep original offsets: questions must retain numbers, accents and punctuation.
    characters, offsets = [], []
    for index, char in enumerate(text):
        for folded in unicodedata.normalize("NFKD", char.lower()):
            if not unicodedata.combining(folded):
                characters.append(folded if folded.isalpha() else " ")
                offsets.append(index)
    normalized = "".join(characters)

    # Preserve the transcription variants already accepted for the name.
    patterns = (r"\b(?:arby|arbi|barbie|army|aby|abby|David|Harry)\b",)

    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            return True, text[offsets[match.end() - 1] + 1:].lstrip(" ,.!?¿¡:;")
    return False, ""


@dataclass(frozen=True)
class SpeechSegment:
    pcm: bytes
    started_at: float
    generation: int


class GoogleWorker(threading.Thread):
    """Realiza las consultas de Google fuera del hilo de captura."""

    def __init__(
        self,
        jobs,
        stop_event,
        language,
        followup_seconds,
        on_question=None,
        is_paused=None,
        request_timeout=10.0,
        generation=None,
        on_unrecognized=None,
        capture_started_at=None,
        on_conversation_start=None,
        on_conversation_end=None,
    ):
        super().__init__(daemon=True, name="arby-recognition")
        self.debug = None
        self.jobs = jobs
        self.stop_event = stop_event
        self.language = language
        self.followup_seconds = followup_seconds
        self.on_conversation_start = on_conversation_start
        self.on_conversation_end = on_conversation_end
        self.on_question = on_question
        self.on_unrecognized = on_unrecognized
        self.repeat_prompt = None
        self.answer_future = None
        self.last_repeat_at = float('-inf')
        self.is_paused = is_paused or (lambda: False)
        self.generation = generation or (lambda: 0)
        self.capture_started_at = capture_started_at or (lambda: None)

        self.recognizer = sr.Recognizer()
        self.recognizer.operation_timeout = request_timeout
        self.mode = "WAKE"
        self.deadline = None

    def run(self):
        while not self.stop_event.is_set():
            # Capture generations invalidate old audio, not an active conversation.
            self._resume_followup()
            self._expire_followup()
            try:
                pcm = self.jobs.get(timeout=0.2)
            except queue.Empty:
                continue

            try:
                self._recognize(pcm)
            finally:
                if self.debug:
                    self.debug.stage("reconocimiento", "Esperando audio", "arby_google_vad_iir.py · GoogleWorker.run → Queue.get")
                self.jobs.task_done()

    def _resume_followup(self):
        # Reopen only after playback AND the speaker-tail pause. Slow model calls
        # and speech do not consume the visitor's minute to ask another question.
        if self.stop_event.is_set() or self.is_paused():
            return
        prompt = self.repeat_prompt
        if prompt is not None:
            if prompt.done():
                self.repeat_prompt = None
                self.last_repeat_at = time.monotonic()
                if prompt.cancelled():
                    log('[REPETIR] Aviso cancelado.')
                else:
                    error = prompt.exception()
                    if error is not None:
                        log(f'[REPETIR] No se pudo reproducir el aviso ({type(error).__name__}); revisa audio y grabaciones locales.')
                    else:
                        log('[REPETIR] Aviso terminado; vuelve a escuchar.')
                    # Give time to repeat if a long STT/TTS operation crossed the
                    # deadline, but noise reminders never renew the full minute.
                    grace = min(CONVERSATION_IDLE_SECONDS, max(0, self.followup_seconds))
                    self.deadline = max(self.deadline or 0, time.monotonic() + grace)
                    self.mode = 'COMMAND'
            return
        answer = self.answer_future
        if answer is not None and answer.done():
            self.answer_future = None
            if not answer.cancelled():
                if answer.exception() is not None:
                    log('[CONVERSACION] La respuesta terminó con error; la escucha continúa.')
                self._listen_for_command()

    def _request_repeat(self, generation):
        """Keep the session alive; throttle prompts instead of permanently capping them."""
        if self.stop_event.is_set():
            log('[REPETIR] Omitido: el micrófono se está cerrando.')
            return
        if generation != self.generation():
            log('[REPETIR] Omitido: audio anterior a una pausa.')
            return
        if self.is_paused():
            log('[REPETIR] Omitido: Arby está ocupado o evitando eco del altavoz.')
            return
        if self.mode != 'COMMAND':
            log("[REPETIR] Omitido: esperando 'Arby'; no hay conversación activa.")
            return
        if self.on_unrecognized is None:
            log('[REPETIR] Omitido: no hay salida de avisos configurada.')
            return
        if self.repeat_prompt is not None:
            log('[REPETIR] Omitido: ya hay un aviso en curso.')
            return
        if time.monotonic() - self.last_repeat_at < REPEAT_COOLDOWN_SECONDS:
            log('[REPETIR] Omitido: pausa breve entre avisos; la conversación sigue activa.')
            return
        try:
            prompt = self.on_unrecognized()
        except (ValueError, RuntimeError) as exc:
            log(f'[REPETIR] No se pudo solicitar el aviso ({type(exc).__name__}).')
            return
        if isinstance(prompt, Future):
            self.last_repeat_at = time.monotonic()
            self.repeat_prompt = prompt
            log('[REPETIR] Aviso solicitado: Perdón, no te escuché bien. ¿Me lo repites?')
        else:
            log('[REPETIR] No se pudo encolar el aviso; revisa si Arby está ocupado.')

    def _expire_followup(self, at=None):
        if at is None:
            # Finish an utterance that began inside the minute even if STT runs
            # after the boundary. Waiting segments carry their own start time.
            started = self.capture_started_at()
            if (self.jobs.unfinished_tasks or (started is not None and self.deadline is not None
                                               and started < self.deadline)):
                return
        if (self.mode == 'COMMAND' and self.deadline is not None
                and self.repeat_prompt is None and self.answer_future is None
                and (time.monotonic() if at is None else at) >= self.deadline):
            self.mode, self.deadline = 'WAKE', None
            if self.on_conversation_end:
                self.on_conversation_end()
            log("[CONVERSACION] Terminó la ventana de escucha. Esperando 'Arby'.")

    def _listen_for_command(self):
        if self.mode == 'WAKE' and self.on_conversation_start:
            self.on_conversation_start()
        self.mode = 'COMMAND'
        self.deadline = time.monotonic() + CONVERSATION_IDLE_SECONDS
        self.last_repeat_at = float('-inf')
        log('[CONVERSACION] Activa durante 60 s; puedes preguntar sin decir Arby.')

    def _recognize(self, pcm):
        if self.stop_event.is_set() or self.is_paused():
            return
        self._resume_followup()
        segment = pcm if isinstance(pcm, SpeechSegment) else None
        if segment is not None and segment.generation != self.generation():
            log('[GOOGLE] Segmento descartado: audio anterior a una pausa.')
            return
        self._expire_followup(at=segment.started_at if segment else time.monotonic())
        if segment is not None:
            pcm = segment.pcm
        if self.repeat_prompt is not None or self.answer_future is not None:
            return
        audio = sr.AudioData(pcm, FS_OUT, 2)
        generation = self.generation()
        start = time.perf_counter()
        if self.debug:
            self.debug.stage("reconocimiento", "Reconociendo audio con Google", "arby_google_vad_iir.py · _recognize → recognize_google", self.recognizer.operation_timeout + 5)

        try:
            text = self.recognizer.recognize_google(
                audio,
                language=self.language,
                show_all=False,
            )
            if not text.strip():
                raise sr.UnknownValueError()
            elapsed = time.perf_counter() - start
            log(f"[GOOGLE] {text} | {elapsed:.2f}s")

        except sr.UnknownValueError:
            elapsed = time.perf_counter() - start
            log(f"[GOOGLE] (no reconocido) | {elapsed:.2f}s | estado={self.mode}")
            self._request_repeat(generation)
            return

        except sr.RequestError as exc:
            elapsed = time.perf_counter() - start
            if self.debug:
                self.debug.event("reconocimiento", "Error del servicio de reconocimiento", "error", error=type(exc).__name__)
            log(f"[GOOGLE] Error de servicio/red: {type(exc).__name__} | {elapsed:.2f}s")
            self._request_repeat(generation)
            return

        except Exception as exc:
            log(f"[GOOGLE] Error: {type(exc).__name__}")
            self._request_repeat(generation)
            return

        if (self.stop_event.is_set() or self.is_paused()
                or generation != self.generation()):
            return
        matched, remainder = wake_match(text)
        # During an active conversation, mentioning Arby inside a question is
        # ordinary speech. Strip the name only when it starts the utterance.
        leading_wake = bool(re.match(r'^\W*(?:arby|arbi|barbie|army|aby|abby)\b', text, re.IGNORECASE))
        if matched and (self.mode == 'WAKE' or leading_wake):
            log('[ARBY] ACTIVADO')
            self._listen_for_command()
            if remainder:
                log(f'[PREGUNTA] {remainder}')
                self.deliver(remainder)
        elif self.mode == 'COMMAND':
            log(f'[PREGUNTA] {text}')
            self.deliver(text)

    def deliver(self, text):
        if self.on_question is not None and not self.stop_event.is_set():
            try:
                future = self.on_question(text)
                if isinstance(future, Future):
                    self.answer_future = future
                    self.deadline = None
                    log('[CONVERSACION] Esperando respuesta; el minuto comienza al terminar el audio.')
                else:
                    # Synchronous consumers (including the standalone diagnostic).
                    self._listen_for_command()
            except (ValueError, RuntimeError) as exc:
                log(f'[ARBY] No se pudo enviar la pregunta: {type(exc).__name__}')


class ArbyPipeline:
    def __init__(self, args, *, on_question=None, is_paused=None, on_voice_start=None,
                 on_unrecognized=None, on_conversation_start=None, on_conversation_end=None):
        self.args = args
        self.is_paused = is_paused or (lambda: False)
        self.max_utterance_seconds = getattr(args, "max_utterance_seconds", 15.0)
        self.stop_event = threading.Event()
        self.generation = 0
        self._activity_lock = threading.RLock()
        self._capturing_voice = False
        self._voice_started_at = None
        self.input_level = 0.0
        self._capture_channel = 0
        self.last_audio_at = 0.0
        self._ready = threading.Event()
        self._on_voice_start = on_voice_start

        self.capture_q = queue.Queue(maxsize=args.queue_blocks)
        self.google_q = queue.Queue(maxsize=1)

        self.drop_capture = 0
        self.drop_google = 0

        self.block_samples = int(FS_IN * args.block_ms / 1000)
        self.block_ms = args.block_ms

        self.filtro = FiltroVoz(
            frecuencia=FS_IN,
            graves=args.graves,
            agudos=args.agudos,
            ganancia_db=args.gain_db,
        )

        self.resampler = soxr.ResampleStream(
            FS_IN,
            FS_OUT,
            1,
            dtype="float32",
        )

        self.vad_model = None
        self.vad = None

        self.google_worker = GoogleWorker(
            self.google_q,
            self.stop_event,
            args.language,
            args.followup_seconds,
            on_question=on_question,
            on_conversation_start=on_conversation_start,
            on_conversation_end=on_conversation_end,
            on_unrecognized=on_unrecognized,
            is_paused=self.is_paused,
            request_timeout=getattr(args, "request_timeout", 10.0),
            generation=lambda: self.generation,
            capture_started_at=lambda: self._voice_started_at if self._capturing_voice else None,
        )

    @property
    def visitor_active(self):
        """Cover VAD, queued/in-flight recognition and the wake follow-up."""
        with self._activity_lock:
            if (not self._ready.is_set() or self._capturing_voice
                    or self.google_worker.repeat_prompt is not None
                    or self.google_worker.answer_future is not None):
                return True
            with self.google_q.mutex:
                if self.google_q.unfinished_tasks:
                    return True
            deadline = self.google_worker.deadline
            return deadline is not None and time.monotonic() < deadline

    def when_idle(self, callback):
        """Check capture and reserve the runtime under the same lock as VAD."""
        with self._activity_lock:
            if self.visitor_active or self.is_paused():
                return None
            return callback()

    def callback(self, indata, frames, time_info, status):
        if self.stop_event.is_set() or self.is_paused():
            self.input_level = 0.0
            return
        self.last_audio_at = time.monotonic()
        samples = indata[:, self._capture_channel].astype(np.float64) / S32_SCALE
        self.input_level = min(1.0, float(np.sqrt(np.mean(samples * samples)))) if samples.size else 0.0
        if status:
            log(f"[ALSA] {status}")

        block = indata.copy()

        try:
            self.capture_q.put_nowait(block)
        except queue.Full:
            self.drop_capture += 1

            # Se descarta el bloque más antiguo para mantener
            # acotada la latencia, nunca se bloquea el callback.
            try:
                self.capture_q.get_nowait()
            except queue.Empty:
                pass

            try:
                self.capture_q.put_nowait(block)
            except queue.Full:
                self.drop_capture += 1

    def process_vad_audio(
        self,
        pcm16,
        vad_buffer,
        preroll,
        utterance_state,
    ):
        vad_buffer.extend(pcm16)

        while len(vad_buffer) >= VAD_FRAME_BYTES:
            frame_bytes = bytes(vad_buffer[:VAD_FRAME_BYTES])
            del vad_buffer[:VAD_FRAME_BYTES]

            frame_i16 = np.frombuffer(frame_bytes, dtype="<i2")
            frame_f32 = frame_i16.astype(np.float32) / 32768.0

            event = self.vad(frame_f32)
            in_speech = utterance_state["active"]

            if not in_speech and event is not None and "start" in event:
                utterance_state["active"] = True
                self._voice_started_at = time.monotonic()
                self._capturing_voice = True
                if self._on_voice_start is not None:
                    self._on_voice_start()
                utterance_state["parts"] = list(preroll)
                utterance_state["parts"].append(frame_bytes)
                log("[VAD] Inicio de voz")

            elif in_speech:
                utterance_state["parts"].append(frame_bytes)

            if (
                utterance_state["active"]
                and ((event is not None and "end" in event)
                     or len(utterance_state["parts"]) * VAD_FRAME / FS_OUT
                     >= self.max_utterance_seconds)
            ):
                utterance_state["active"] = False

                utterance = b"".join(utterance_state["parts"])
                utterance_state["parts"] = []

                duration = len(utterance) / (2 * FS_OUT)

                if duration >= 0.20:
                    try:
                        self.google_q.put_nowait(SpeechSegment(utterance, self._voice_started_at, self.generation))
                        log(
                            "[VAD] Fin de voz; enviado a Google "
                            f"({duration:.2f}s)"
                        )
                    except queue.Full:
                        self.drop_google += 1
                        log("[WARN] Cola Google llena; segmento descartado")

                self.vad.reset_states()
                self._capturing_voice = False

            preroll.append(frame_bytes)

    def _discard_audio(self):
        for pending in (self.capture_q, self.google_q):
            while True:
                try:
                    pending.get_nowait()
                    if pending is self.google_q:
                        pending.task_done()
                except queue.Empty:
                    break

    def close(self):
        self.stop_event.set()

    def run(self):
        log("[FILTER] Configurando filtro IIR de voz...")
        import sounddevice as sd

        preference = getattr(self.args, 'device_identity', None)
        if preference is not None:
            from libraries.audio.arby_devices import discover_devices, find_preferred, portaudio_input
            # Hardware may have been renumbered while bot/matrices initialized.
            self.args.device = portaudio_input(find_preferred(preference, 'input', discover_devices()), sd)
        device_info, channels, channel = input_layout(sd, self.args.device, self.args.channel)
        self._capture_channel = channel
        self.vad_model = load_silero_vad()
        self.vad = VADIterator(
            self.vad_model,
            threshold=self.args.threshold,
            sampling_rate=FS_OUT,
            min_silence_duration_ms=self.args.silence_ms,
            speech_pad_ms=30,
        )

        self.google_worker.start()

        preroll = collections.deque(
            maxlen=max(1, round(self.args.preroll_ms / 32))
        )
        vad_buffer = bytearray()
        utterance_state = {
            "active": False,
            "parts": [],
        }

        log(
            f"[AUDIO] device={self.args.device} ({device_info['name']}), "
            f"48 kHz, {channels} canal(es) S32; canal={channel}"
        )
        log(
            f"[FILTER] HPF={self.args.graves:g} Hz; "
            f"LPF={self.args.agudos:g} Hz; "
            f"ganancia={self.args.gain_db:+.1f} dB; "
            f"limitador=-1 dBFS"
        )
        log(
            f"[AUDIO] Bloques={self.args.block_ms} ms; "
            f"salida={FS_OUT} Hz mono"
        )
        log(
            f"[VAD] threshold={self.args.threshold}; "
            f"silence={self.args.silence_ms} ms; "
            f"preroll={self.args.preroll_ms} ms"
        )

        block_count = 0
        total_proc = 0.0
        max_proc = 0.0
        last_report = time.perf_counter()

        try:
            with sd.InputStream(
                device=self.args.device,
                samplerate=FS_IN,
                channels=channels,
                dtype="int32",
                blocksize=self.block_samples,
                latency="low",
                callback=self.callback,
            ):
                self._ready.set()
                log("[READY] Di 'Arby'.")
                paused = False
                while not self.stop_event.is_set():
                    if self.is_paused():
                        if not paused:
                            self.generation += 1
                        paused = True
                        self._discard_audio()
                        vad_buffer.clear()
                        preroll.clear()
                        utterance_state.update(active=False, parts=[])
                        with self._activity_lock:
                            self._capturing_voice = False
                        self.stop_event.wait(0.03)
                        continue
                    if paused:
                        self._discard_audio()
                        self.vad.reset_states()
                        self.filtro.zi.fill(0)
                        self.resampler.clear()
                        paused = False
                    try:
                        raw = self.capture_q.get(timeout=0.2)
                    except queue.Empty:
                        continue

                    t0 = time.perf_counter()

                    # Conversión de S32_LE a float32 normalizado.
                    mono = (
                        raw[:, channel].astype(np.float32) / S32_SCALE
                    )

                    # Filtro IIR de voz, ganancia fija y limitador.
                    filtered = self.filtro.procesar(mono)

                    # Remuestreo streaming de 48 kHz a 16 kHz.
                    output = self.resampler.resample_chunk(
                        np.ascontiguousarray(filtered, dtype=np.float32),
                        last=False,
                    )

                    if output.size:
                        pcm16 = (
                            np.clip(output, -1.0, 0.999969) * 32768.0
                        ).astype("<i2").tobytes()

                        with self._activity_lock:
                            if not self.is_paused():
                                self.process_vad_audio(
                                    pcm16, vad_buffer, preroll, utterance_state,
                                )

                    elapsed = time.perf_counter() - t0
                    total_proc += elapsed
                    max_proc = max(max_proc, elapsed)
                    block_count += 1

                    now = time.perf_counter()

                    if now - last_report >= 5.0:
                        avg_ms = (
                            total_proc * 1000 / max(block_count, 1)
                        )
                        rtf = (
                            total_proc / max(block_count, 1)
                        ) / (self.block_ms / 1000)

                        log(
                            f"[PERF] media={avg_ms:.2f} ms/bloque "
                            f"({self.block_ms} ms audio), "
                            f"RTF={rtf:.3f}, "
                            f"max={max_proc * 1000:.2f} ms, "
                            f"drop_capture={self.drop_capture}, "
                            f"drop_google={self.drop_google}"
                        )

                        total_proc = 0.0
                        max_proc = 0.0
                        block_count = 0
                        last_report = now

        finally:
            self._ready.clear()
            self.stop_event.set()

            if self.google_worker.is_alive():
                self.google_worker.join(timeout=1.0)

            log(
                f"[FILTER] Bloques limitados={self.filtro.limitados}; "
                f"muestras de entrada próximas a clipping="
                f"{self.filtro.clipping_entrada}"
            )

            if self.filtro.limitados:
                log(
                    "[FILTER] Aviso: algunos bloques necesitaron reducir "
                    "la ganancia para respetar -1 dBFS."
                )

            if self.filtro.clipping_entrada:
                log(
                    "[FILTER] Aviso: hubo muestras de entrada próximas "
                    "a saturación; el filtro no puede reparar clipping "
                    "de origen."
                )


def main():
    parser = argparse.ArgumentParser(
        description="ARBY: filtro IIR de voz + Silero VAD + Google STT."
    )

    parser.add_argument("--device", default="0")
    parser.add_argument(
        "--channel",
        choices=("left", "right"),
        default="left",
    )
    parser.add_argument("--language", default="es-CO")

    parser.add_argument("--gain-db", type=float, default=6.0)
    parser.add_argument("--graves", type=float, default=80.0)
    parser.add_argument("--agudos", type=float, default=8000.0)

    parser.add_argument(
        "--block-ms",
        type=int,
        choices=(10, 20, 40),
        default=20,
    )
    parser.add_argument("--queue-blocks", type=int, default=8)

    parser.add_argument("--threshold", type=float, default=0.50)
    parser.add_argument("--silence-ms", type=int, default=450)
    parser.add_argument("--preroll-ms", type=int, default=320)
    parser.add_argument("--followup-seconds", type=float, default=8.0)

    args = parser.parse_args()

    if str(args.device).isdigit():
        args.device = int(args.device)

    # Validar los parámetros del filtro antes de abrir el micrófono.
    FiltroVoz(
        frecuencia=FS_IN,
        graves=args.graves,
        agudos=args.agudos,
        ganancia_db=args.gain_db,
    )

    pipeline = ArbyPipeline(args)

    def stop(*_):
        pipeline.stop_event.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    try:
        pipeline.run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
