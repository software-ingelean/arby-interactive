"""Edge TTS streaming to ffplay stdin. No temporary audio files."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
from typing import Callable

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class TTSConfig:
    voice: str = "es-MX-JorgeNeural"
    rate: str = "+10%"
    pitch: str = "-8Hz"
    volume: str = "+0%"
    ffplay_path: str = "ffplay"
    timeout_seconds: float = 120.0
    max_text_chars: int = 4000
    # SDL2 output settings; leave unset on Windows for the default device.
    audio_driver: str | None = None
    audio_device: str | None = None

    def __post_init__(self):
        if self.timeout_seconds <= 0 or self.max_text_chars < 1:
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
            job = _Job()
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
                job.cancelled.set()
                loop, task = job.loop, job.task
            if loop and task:
                try:
                    loop.call_soon_threadsafe(task.cancel)
                except RuntimeError:
                    pass  # The worker has already closed its event loop.
            return job.done.wait(timeout)

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
                job.error = f"{type(error).__name__}: síntesis o reproducción no completada"
                LOGGER.warning("Arby TTS failed: %s", type(error).__name__)
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
        await asyncio.wait_for(self._play_stream(job, text, started),
                               timeout=self.config.timeout_seconds)

    async def _play_stream(self, job, text, started):
        env = os.environ.copy()
        if self.config.audio_driver:
            env["SDL_AUDIODRIVER"] = self.config.audio_driver
        if self.config.audio_device:
            env["AUDIODEV"] = self.config.audio_device
        command = [self._player, "-hide_banner", "-loglevel", "error", "-nodisp",
                   "-autoexit", "-probesize", "4096", "-analyzeduration", "0",
                   "-f", "mp3", "-i", "pipe:0"]
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        process = None
        stderr_task = None
        stream = None
        diagnostics = bytearray()
        async def drain_stderr():
            while True:
                chunk = await process.stderr.read(1024)
                if not chunk:
                    return
                diagnostics.extend(chunk)
                del diagnostics[:-4096]
        try:
            # Shield process startup so cancellation cannot orphan a new player.
            startup = asyncio.create_task(asyncio.create_subprocess_exec(
                *command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE, env=env, **options))
            try:
                process = await asyncio.shield(startup)
            except asyncio.CancelledError:
                process = await startup
                raise
            stderr_task = asyncio.create_task(drain_stderr())
            stream = self._stream_factory(text)
            received = False
            job.status = "streaming"
            async for chunk in stream:
                if chunk.get("type") != "audio":
                    continue
                data = chunk.get("data", b"")
                if not data:
                    continue
                if process.returncode is not None:
                    raise RuntimeError("ffplay exited before the stream ended.")
                if not received:
                    job.first_chunk_seconds = time.monotonic() - started
                received = True
                process.stdin.write(data)
                await process.stdin.drain()
            if not received:
                raise RuntimeError("No audio received.")
            process.stdin.close()
            await process.stdin.wait_closed()
            job.status = "finishing"
            result = await process.wait()
            await stderr_task
            if result != 0:
                LOGGER.debug("ffplay stderr: %s", diagnostics.decode(errors="replace"))
                raise RuntimeError(f"ffplay exit code: {result}")
        finally:
            # Kill playback first; then close the stream and diagnostic reader.
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
            if stream is not None and hasattr(stream, "aclose"):
                await stream.aclose()
            if stderr_task:
                if not stderr_task.done():
                    stderr_task.cancel()
                await asyncio.gather(stderr_task, return_exceptions=True)
