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

import argparse
import collections
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


def log(*args):
    print(*args, file=sys.stderr, flush=True)


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
    ):
        super().__init__(daemon=True)
        self.jobs = jobs
        self.stop_event = stop_event
        self.language = language
        self.followup_seconds = followup_seconds
        self.on_question = on_question
        self.on_unrecognized = on_unrecognized
        self.repeat_prompt = None
        self.is_paused = is_paused or (lambda: False)
        self.generation = generation or (lambda: 0)

        self.recognizer = sr.Recognizer()
        self.recognizer.operation_timeout = request_timeout
        self.mode = "WAKE"
        self.deadline = None

    def run(self):
        last_generation = self.generation()
        while not self.stop_event.is_set():
            current_generation = self.generation()
            if current_generation != last_generation:
                self.mode, self.deadline = "WAKE", None
                last_generation = current_generation
            self._resume_followup()
            try:
                pcm = self.jobs.get(timeout=0.2)
            except queue.Empty:
                if (
                    self.mode == "COMMAND"
                    and self.deadline
                    and time.monotonic() > self.deadline
                ):
                    self.mode = "WAKE"
                    self.deadline = None
                    log("[TIMEOUT] No llegó una pregunta. Esperando 'Arby'.")
                continue

            try:
                self._recognize(pcm)
            finally:
                self.jobs.task_done()

    def _resume_followup(self):
        # Wait for playback and the microphone's speaker-tail pause to end.
        prompt = self.repeat_prompt
        if prompt is not None and prompt.done() and not self.is_paused():
            self._listen_for_command()
            self.repeat_prompt = None

    def _listen_for_command(self):
        self.mode = "COMMAND"
        self.deadline = time.monotonic() + self.followup_seconds
        log("[ARBY] Escuchando tu pregunta...")

    def _recognize(self, pcm):
        if self.stop_event.is_set() or self.is_paused():
            return
        self._resume_followup()
        if self.repeat_prompt is not None:
            return
        if self.deadline is not None and time.monotonic() > self.deadline:
            self.mode, self.deadline = "WAKE", None
        audio = sr.AudioData(pcm, FS_OUT, 2)
        generation = self.generation()
        start = time.perf_counter()

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
            log(f"[GOOGLE] (no reconocido) | {elapsed:.2f}s")
            if (self.mode == "COMMAND" and self.on_unrecognized is not None
                    and not self.stop_event.is_set() and not self.is_paused()
                    and generation == self.generation()):
                try:
                    self.repeat_prompt = self.on_unrecognized()
                except (ValueError, RuntimeError) as exc:
                    log(f"[ARBY] {exc}")
                if self.repeat_prompt is not None:
                    self.mode, self.deadline = "WAKE", None
            return

        except sr.RequestError as exc:
            elapsed = time.perf_counter() - start
            log(f"[GOOGLE] Error de servicio/red: {exc} | {elapsed:.2f}s")
            return

        except Exception as exc:
            log(f"[GOOGLE] Error: {exc}")
            return

        if (self.stop_event.is_set() or self.is_paused()
                or generation != self.generation()):
            return
        if self.mode == "WAKE":
            matched, remainder = wake_match(text)

            if matched:
                log("[ARBY] ACTIVADO")

                if remainder:
                    # Si el usuario dijo la activación y la pregunta
                    # en la misma frase, se conserva la pregunta.
                    log(f"[PREGUNTA] {remainder}")
                    self.mode = "WAKE"
                    self.deadline = None
                    self.deliver(remainder)
                else:
                    self._listen_for_command()

        else:
            log(f"[PREGUNTA] {text}")
            self.mode = "WAKE"
            self.deadline = None
            self.deliver(text)
            log("[READY] Esperando 'Arby'.")

    def deliver(self, text):
        if self.on_question is not None and not self.stop_event.is_set():
            try:
                self.on_question(text)
            except (ValueError, RuntimeError) as exc:
                log(f"[ARBY] {exc}")


class ArbyPipeline:
    def __init__(self, args, *, on_question=None, is_paused=None, on_voice_start=None,
                 on_unrecognized=None):
        self.args = args
        self.is_paused = is_paused or (lambda: False)
        self.max_utterance_seconds = getattr(args, "max_utterance_seconds", 15.0)
        self.stop_event = threading.Event()
        self.generation = 0
        self._activity_lock = threading.RLock()
        self._capturing_voice = False
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
            on_unrecognized=on_unrecognized,
            is_paused=self.is_paused,
            request_timeout=getattr(args, "request_timeout", 10.0),
            generation=lambda: self.generation,
        )

    @property
    def visitor_active(self):
        """Cover VAD, queued/in-flight recognition and the wake follow-up."""
        with self._activity_lock:
            if (not self._ready.is_set() or self._capturing_voice
                    or self.google_worker.repeat_prompt is not None):
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
            return
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
                        self.google_q.put_nowait(utterance)
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

        device_info, channels, channel = input_layout(sd, self.args.device, self.args.channel)
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
