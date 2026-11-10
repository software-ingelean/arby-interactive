"""Edge TTS with complete MP3 playback and owned-player cleanup."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import threading
from tempfile import TemporaryDirectory
import time
from typing import Callable

LOGGER = logging.getLogger(__name__)


class _SpeechFailure(RuntimeError):
    """Local diagnostic without request URLs or spoken text."""


def _connection_detail(error):
    """Report exception classes and OS errors, never request URLs or tokens."""
    parts, seen = [], set()
    while error is not None and id(error) not in seen and len(parts) < 5:
        seen.add(id(error))
        detail = type(error).__name__
        number = getattr(error, "errno", None)
        if isinstance(number, int):
            detail += f" errno={number} ({os.strerror(number)})"
        parts.append(detail)
        error = error.__cause__ or error.__context__
    return " -> ".join(parts)


def _certificate_error(error):
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, ssl.SSLCertVerificationError):
            return True
        error = error.__cause__ or error.__context__
    return False


@dataclass(frozen=True)
class TTSConfig:
    voice: str = "es-CO-SalomeNeural"
    rate: str = "+12%"
    pitch: str = "+0Hz"
    volume: str = "+0%"
    ffplay_path: str = "ffplay"
    timeout_seconds: float = 120.0
    max_text_chars: int = 4000
    prefetch_segments: bool = True
    max_prefetch_bytes: int = 4 * 1024 * 1024
    # SDL2 output settings; leave unset on Windows for the default device.
    audio_driver: str | None = None
    audio_device: str | None = None

    def __post_init__(self):
        if self.timeout_seconds <= 0 or self.max_text_chars < 1 or self.max_prefetch_bytes < 1:
            raise ValueError("Invalid timeout or text limit.")


@dataclass
class _Job:
    done: threading.Event = field(default_factory=threading.Event)
    cancelled: threading.Event = field(default_factory=threading.Event)
    loop: asyncio.AbstractEventLoop | None = None
    task: asyncio.Task | None = None
    thread: threading.Thread | None = None
    error: str | None = None
    status: str = "starting"
    first_chunk_seconds: float | None = None
    total_seconds: float | None = None
    segments: tuple[str, ...] | None = None
    on_segment: Callable[[int], None] | None = None
    process: asyncio.subprocess.Process | None = None


class ArbyTTS:
    """One utterance at a time; speak() returns immediately, without a queue.

    True means accepted, not completed. Inspect last_status/last_error after
    wait(). is_speaking includes connection, buffering, and playback.
    The injectable stream_factory is intended for offline tests.
    """
    def __init__(self, config: TTSConfig | None = None, *, stream_factory: Callable | None = None):
        self.config = config or TTSConfig()
        player = shutil.which(self.config.ffplay_path)
        if player is None:
            candidate = Path(self.config.ffplay_path)
            if not candidate.is_file():
                raise FileNotFoundError("No se encontró ffplay. Instala FFmpeg con ffplay o configura ffplay_path.")
            player = str(candidate.resolve())
        self._player = player
        if stream_factory is None:
            import edge_tts
            def stream_factory(text):
                return edge_tts.Communicate(text, self.config.voice,
                    rate=self.config.rate, pitch=self.config.pitch,
                    volume=self.config.volume).stream()
        self._stream_factory = stream_factory
        self._control = threading.RLock()
        self._state = threading.Lock()
        self._job: _Job | None = None
        self._closed = False

    @property
    def is_speaking(self) -> bool:
        with self._state:
            return bool(self._job and not self._job.done.is_set())

    @property
    def last_error(self) -> str | None:
        with self._state:
            return self._job.error if self._job else None

    @property
    def last_status(self) -> str:
        with self._state:
            return self._job.status if self._job else "idle"

    @property
    def first_chunk_seconds(self) -> float | None:
        with self._state:
            return self._job.first_chunk_seconds if self._job else None

    @property
    def total_seconds(self) -> float | None:
        with self._state:
            return self._job.total_seconds if self._job else None

    def speak(self, text: str, *, interrupt: bool = False) -> bool:
        if not isinstance(text, str):
            raise TypeError("text must be a str.")
        text = text.strip()
        return self._start_job(text, interrupt=interrupt)

    def speak_segments(self, texts, *, on_segment=None, interrupt=False):
        """Synthesize each phrase and prefetch one next phrase in RAM.

        on_segment(index) runs on the TTS worker when its player starts
        for that phrase; callbacks must be short and thread-safe, never draw UI.
        wait/stop/is_speaking cover the whole sequence, not an individual phrase.
        """
        if isinstance(texts, (str, bytes)):
            raise TypeError("texts must be a sequence of strings")
        texts = tuple(texts)
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("Each segment must contain nonempty speech text")
        if on_segment is not None and not callable(on_segment):
            raise TypeError("on_segment must be callable")
        texts = tuple(text.strip() for text in texts)
        return self._start_job(" ".join(texts), interrupt=interrupt,
                               segments=texts, on_segment=on_segment)

    def _start_job(self, text, *, interrupt, segments=None, on_segment=None):
        with self._control:
            if self._closed:
                raise RuntimeError("ArbyTTS is closed.")
            if not text:
                return False
            if len(text) > self.config.max_text_chars:
                raise ValueError("text exceeds max_text_chars.")
            if self.is_speaking:
                if not interrupt:
                    return False
                if not self.stop():
                    raise TimeoutError("Previous speech did not stop; replacement was rejected.")
            job = _Job(segments=segments, on_segment=on_segment)
            with self._state:
                self._job = job
            job.thread = threading.Thread(target=self._worker, args=(job, text),
                                          name="arby-tts", daemon=True)
            job.thread.start()
            return True

    def wait(self, timeout: float | None = None) -> bool:
        """Wait for the current utterance to end (success, cancellation or failure)."""
        with self._state:
            job = self._job
        return True if job is None else job.done.wait(timeout)

    def stop(self, timeout: float = 5.0) -> bool:
        """Cancel network streaming and terminate ffplay; True when fully stopped."""
        with self._control:
            with self._state:
                job = self._job
                if job is None or job.done.is_set():
                    return True
                first_cancel = not job.cancelled.is_set()
                job.cancelled.set()
                loop, task = job.loop, job.task
            # Repeated close/stop calls must not cancel the cleanup itself.
            if first_cancel and loop and task:
                try:
                    loop.call_soon_threadsafe(task.cancel)
                except RuntimeError:
                    pass  # The worker has already closed its event loop.
            if job.done.wait(timeout):
                return True
            # A stuck network stream must not leave an owned player sounding.
            with self._state:
                process = job.process
            if process and process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            return job.done.wait(1.0)

    def close(self):
        with self._control:
            self._closed = True
            if not self.stop():
                raise TimeoutError("Speech cleanup did not finish within 5 seconds.")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _worker(self, job, text):
        started = time.monotonic()
        try:
            asyncio.run(self._run_job(job, text, started))
            job.status = "cancelled" if job.cancelled.is_set() else "completed"
        except asyncio.CancelledError:
            job.status = "cancelled"
        except Exception as error:
            if job.cancelled.is_set():
                job.status = "cancelled"
            else:
                job.status = "failed"
                # Never include the input text or a raw request URL in the log.
                detail = (str(error) if isinstance(error, _SpeechFailure) else
                          "tiempo de espera de voz agotado" if isinstance(error, TimeoutError) else
                          f"falló la conexión de síntesis: {_connection_detail(error)}" if isinstance(error, OSError) else
                          "síntesis o reproducción no completada")
                job.error = f"{type(error).__name__}: {detail}"
                LOGGER.warning("Arby TTS failed: %s", job.error)
                LOGGER.debug("Arby TTS diagnostic", exc_info=True)
        finally:
            with self._state:
                job.loop = None
                job.task = None
                job.total_seconds = time.monotonic() - started
            job.done.set()

    async def _run_job(self, job, text, started):
        with self._state:
            job.loop = asyncio.get_running_loop()
            job.task = asyncio.current_task()
        if job.cancelled.is_set():
            raise asyncio.CancelledError
        operation = (self._play_segments(job, started) if job.segments is not None
                     else self._play_stream(job, text, started))
        async def watch_cancel():
            # Also observe the event locally, without relying solely on the
            # cross-thread event-loop wakeup to interrupt a network wait.
            while not job.cancelled.is_set():
                await asyncio.sleep(0.05)
            if not job.task.cancelling():
                job.task.cancel()
        watcher = asyncio.create_task(watch_cancel())
        try:
            await asyncio.wait_for(operation, timeout=self.config.timeout_seconds)
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)

    async def _collect_audio(self, text):
        """Retry synthesis only, before any of this phrase has been played."""
        for attempt in range(3):
            try:
                return await self._collect_audio_once(text)
            except (OSError, TimeoutError) as exc:
                if _certificate_error(exc) or attempt == 2:
                    raise
                LOGGER.warning("Conexión Edge TTS interrumpida (%s); reintento %s/2.",
                               _connection_detail(exc), attempt + 1)
                await asyncio.sleep(0.5 * (attempt + 1))

    async def _collect_audio_once(self, text):
        """Collect a complete phrase, with a hard RAM limit."""
        stream = self._stream_factory(text)
        data = bytearray()
        try:
            async for chunk in stream:
                if chunk.get("type") != "audio":
                    continue
                packet = chunk.get("data", b"")
                if len(data) + len(packet) > self.config.max_prefetch_bytes:
                    raise MemoryError("Phrase audio exceeds max_prefetch_bytes")
                data.extend(packet)
            if not data:
                raise _SpeechFailure("Edge TTS no devolvió audio")
            return data
        finally:
            if hasattr(stream, "aclose"):
                await stream.aclose()

    @staticmethod
    async def _buffer_stream(data):
        for offset in range(0, len(data), 16384):
            yield {"type": "audio", "data": data[offset:offset + 16384]}

    async def _play_segments(self, job, started):
        pending = None
        try:
            for index, text in enumerate(job.segments):
                if job.cancelled.is_set():
                    raise asyncio.CancelledError
                stream = None
                if pending is not None:
                    data = await pending
                    pending = None
                    stream = self._buffer_stream(data)
                    del data
                if self.config.prefetch_segments and index + 1 < len(job.segments):
                    pending = asyncio.create_task(self._collect_audio(job.segments[index + 1]))
                callback = (lambda i=index: job.on_segment(i)) if job.on_segment else None
                await self._play_stream(job, text, started,
                                        stream_override=stream, on_audio_start=callback)
        finally:
            if pending is not None:
                if not pending.done():
                    pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)

    async def _play_stream(self, job, text, started, *, stream_override=None, on_audio_start=None):
        # Match the working standalone path: complete the MP3 before opening
        # the player. This avoids probing an unfinished network-fed pipe.
        job.status = "synthesizing"
        if stream_override is None:
            data = await self._collect_audio(text)
        else:
            data = bytearray()
            try:
                async for chunk in stream_override:
                    if chunk.get("type") == "audio":
                        packet = chunk.get("data", b"")
                        if len(data) + len(packet) > self.config.max_prefetch_bytes:
                            raise MemoryError("Phrase audio exceeds max_prefetch_bytes")
                        data.extend(packet)
            finally:
                if hasattr(stream_override, "aclose"):
                    await stream_override.aclose()
        if not data:
            raise _SpeechFailure("Edge TTS no devolvió audio")
        if job.cancelled.is_set():
            raise asyncio.CancelledError
        env = os.environ.copy()
        if self.config.audio_driver:
            env["SDL_AUDIODRIVER"] = self.config.audio_driver
        if self.config.audio_device:
            env["AUDIODEV"] = self.config.audio_device
        options = ({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt"
                   else {"start_new_session": True})
        # The directory is private and removed after playback, including errors
        # and cancellation. Close the file before spawning for Windows support.
        with TemporaryDirectory(prefix="arby-tts-") as folder:
            audio_path = Path(folder) / "speech.mp3"
            audio_path.write_bytes(data)
            del data
            command = [self._player, "-hide_banner", "-loglevel", "error", "-nodisp",
                       "-autoexit", "-af", "aformat=sample_rates=48000:channel_layouts=stereo",
                       str(audio_path)]
            process = None
            stderr_task = None
            diagnostics = bytearray()

            async def drain_stderr():
                while True:
                    chunk = await process.stderr.read(1024)
                    if not chunk:
                        return
                    diagnostics.extend(chunk)
                    del diagnostics[:-4096]

            try:
                startup = asyncio.create_task(asyncio.create_subprocess_exec(
                    *command, stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
                    env=env, **options))
                try:
                    process = await asyncio.shield(startup)
                except asyncio.CancelledError:
                    process = await startup
                    raise
                with self._state:
                    job.process = process
                stderr_task = asyncio.create_task(drain_stderr())
                job.status = "playing"
                if job.first_chunk_seconds is None:
                    job.first_chunk_seconds = time.monotonic() - started
                if on_audio_start is not None:
                    on_audio_start()
                result = await process.wait()
                await stderr_task
                if result != 0:
                    detail = diagnostics.decode(errors="replace").strip()
                    selection = (f"driver={env.get('SDL_AUDIODRIVER', 'default')}, "
                                 f"device={env.get('AUDIODEV', 'default')}")
                    # The temporary path is not useful after this method exits.
                    detail = detail.replace(str(audio_path), "[audio temporal]")
                    raise _SpeechFailure(f"ffplay terminó con código {result} ({selection})"
                                         + (f": {detail}" if detail else ""))
            finally:
                if process and process.returncode is None:
                    try:
                        process.terminate()
                    except ProcessLookupError:
                        pass
                    try:
                        await asyncio.wait_for(process.wait(), 1.0)
                    except asyncio.TimeoutError:
                        try:
                            process.kill()
                        except ProcessLookupError:
                            pass
                        await process.wait()
                with self._state:
                    job.process = None
                if stderr_task:
                    if not stderr_task.done():
                        stderr_task.cancel()
                    await asyncio.gather(stderr_task, return_exceptions=True)
