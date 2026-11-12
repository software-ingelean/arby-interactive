"""Persist the operating mode and schedule idle actions for Arby."""

import argparse
from concurrent.futures import Future
from contextlib import closing
from dataclasses import dataclass
import math
import os
from pathlib import Path
from random import Random
import sqlite3
import subprocess
import time
from typing import Callable


DEFAULT_DATABASE = Path(__file__).resolve().parents[2] / "config" / "arby_settings.sqlite3"
CLIP_DIRECTORY = DEFAULT_DATABASE.parents[1] / "assets" / "ambient"
MODES = ("oficina", "evento")


@dataclass(frozen=True)
class AmbientSettings:
    mode: str = "oficina"
    gesture_min_seconds: float = 60
    gesture_max_seconds: float = 120
    invitation_min_seconds: float = 300
    invitation_max_seconds: float = 420

    def __post_init__(self):
        if self.mode not in MODES:
            raise ValueError("El modo debe ser oficina o evento.")
        for low, high in (self.gesture_range, self.invitation_range):
            if not (math.isfinite(low) and math.isfinite(high) and 1 <= low <= high):
                raise ValueError("Cada intervalo requiere 1 <= mínimo <= máximo, en segundos finitos.")

    @property
    def gesture_range(self):
        return self.gesture_min_seconds, self.gesture_max_seconds

    @property
    def invitation_range(self):
        return self.invitation_min_seconds, self.invitation_max_seconds


def load_ambient_settings(database=DEFAULT_DATABASE):
    """Load one startup snapshot. A fresh installation starts in office mode."""
    path = Path(database).resolve()
    if not path.exists():
        return AmbientSettings()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
        row = connection.execute(
            """SELECT mode, gesture_min_seconds, gesture_max_seconds,
                      invitation_min_seconds, invitation_max_seconds
               FROM arby_ambient_settings WHERE id = 1"""
        ).fetchone()
    if row is None:
        raise ValueError("La base de datos no tiene configuración de Arby.")
    return AmbientSettings(*row)


def save_ambient_settings(settings: AmbientSettings, database=DEFAULT_DATABASE):
    """Create or atomically update the singleton configuration row."""
    path = Path(database)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS arby_ambient_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                mode TEXT NOT NULL CHECK (mode IN ('oficina', 'evento')),
                gesture_min_seconds REAL NOT NULL CHECK (gesture_min_seconds >= 1),
                gesture_max_seconds REAL NOT NULL CHECK (gesture_max_seconds >= gesture_min_seconds),
                invitation_min_seconds REAL NOT NULL CHECK (invitation_min_seconds >= 1),
                invitation_max_seconds REAL NOT NULL CHECK (invitation_max_seconds >= invitation_min_seconds)
            )"""
        )
        connection.execute(
            """INSERT INTO arby_ambient_settings
               (id, mode, gesture_min_seconds, gesture_max_seconds,
                invitation_min_seconds, invitation_max_seconds)
               VALUES (1, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   mode = excluded.mode,
                   gesture_min_seconds = excluded.gesture_min_seconds,
                   gesture_max_seconds = excluded.gesture_max_seconds,
                   invitation_min_seconds = excluded.invitation_min_seconds,
                   invitation_max_seconds = excluded.invitation_max_seconds""",
            (settings.mode, *settings.gesture_range, *settings.invitation_range),
        )


@dataclass(frozen=True)
class AmbientAction:
    kind: str
    matrix_state: str
    text: str = ""
    duration_seconds: float = 0


GESTURES = (
    AmbientAction("eyes", "guiño ojo", duration_seconds=1.8),
    AmbientAction("whistle", "alegres"),
    AmbientAction("hum", "alegres"),
    AmbientAction("eyes", "locos", duration_seconds=2),
)
INVITATIONS = (
    AmbientAction("phrase", "alegres", "¡Hola! Si quieres conversar, aquí estoy."),
    AmbientAction("phrase", "alegres", "¿Te cuento algo curioso sobre las plantas?"),
    AmbientAction("phrase", "alegres", "Si tienes curiosidad, pregúntame algo."),
)


class AmbientAudio:
    """Play local effects synchronously from the runtime's audio worker."""

    def __init__(self, *, ffplay=None, audio_driver=None, audio_device=None,
                 player_context=None):
        self.ffplay = ffplay or "ffplay"
        self.audio_driver = audio_driver
        self.audio_device = audio_device
        self.player_context = player_context

    def play(self, kind, cancel):
        filenames = {"whistle": "silbido.wav", "hum": "tarareo.wav"}
        clip = CLIP_DIRECTORY / filenames[kind]
        if not clip.is_file():
            raise FileNotFoundError(clip)
        if cancel.is_set():
            return
        if callable(self.player_context):
            env, options = self.player_context()
        else:
            env, options = os.environ.copy(), {}
            if os.name == "nt":
                options["creationflags"] = subprocess.CREATE_NO_WINDOW
        if self.audio_driver:
            env["SDL_AUDIODRIVER"] = self.audio_driver
        if self.audio_device:
            env["AUDIODEV"] = self.audio_device
        command = [self.ffplay, "-hide_banner", "-loglevel", "error", "-nodisp", "-autoexit",
                   "-af", "aformat=sample_rates=48000:channel_layouts=stereo", str(clip)]
        deadline = time.monotonic() + 10
        with subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL,
                              stderr=subprocess.PIPE, **options) as player:
            try:
                while not cancel.is_set():
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"El efecto {clip.name} tardó demasiado.")
                    try:
                        _, diagnostic = player.communicate(timeout=0.05)
                    except subprocess.TimeoutExpired:
                        continue
                    if player.returncode or diagnostic.strip():
                        message = diagnostic.decode(errors="replace").strip()
                        raise RuntimeError(message or f"ffplay terminó con código {player.returncode}.")
                    return
            finally:
                if player.poll() is None:
                    player.kill()
                    player.communicate()


class AmbientSequence:
    """Called from the render loop. The runtime owns every accepted action.

    visitor_active covers submitted conversation and touch work. The submit
    callback admits an action only when runtime and capture are available,
    returning its Future or None. Background VAD delays admission without
    restarting the timers. The runtime handles interruption of accepted work.
    """

    def __init__(self, settings: AmbientSettings, *, rng=None):
        self.settings = settings
        self._rng = rng if rng is not None else Random()
        self._gesture_at = None
        self._invitation_at = None
        self._future = None
        self._resume_at = 0.0
        self._gesture_index = 0
        self._invitation_index = 0

    def tick(self, now: float, *, visitor_active: bool,
             submit: Callable[[AmbientAction], Future | None]):
        """Advance the sequence without sleeping or generating a backlog."""
        if self.settings.mode != "evento":
            return
        if visitor_active:
            self._gesture_at = self._invitation_at = None
            return
        if self._future is not None:
            if not self._future.done():
                return
            self._future = None
            self._resume_at = now + 10
        if self._gesture_at is None:
            self._gesture_at = now + self._rng.uniform(*self.settings.gesture_range)
            self._invitation_at = now + self._rng.uniform(*self.settings.invitation_range)
        if now < self._resume_at:
            return

        invitation_due = now >= self._invitation_at
        if invitation_due:
            action = INVITATIONS[self._invitation_index]
        elif now >= self._gesture_at:
            action = GESTURES[self._gesture_index]
        else:
            return

        pending = submit(action)
        if pending is None:
            # Retry admission later, keeping the same action and due time.
            self._resume_at = now + 0.5
            return
        self._future = pending
        if invitation_due:
            self._invitation_index = (self._invitation_index + 1) % len(INVITATIONS)
            self._invitation_at = now + self._rng.uniform(*self.settings.invitation_range)
        else:
            self._gesture_index = (self._gesture_index + 1) % len(GESTURES)
            self._gesture_at = now + self._rng.uniform(*self.settings.gesture_range)


def main():
    parser = argparse.ArgumentParser(description="Configura el modo y los intervalos de Arby.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("mode", choices=(*MODES, "ver"))
    parser.add_argument("--gestos", nargs=2, type=float, metavar=("MIN", "MAX"))
    parser.add_argument("--invitaciones", nargs=2, type=float, metavar=("MIN", "MAX"))
    args = parser.parse_args()
    if args.mode == "ver" and (args.gestos or args.invitaciones):
        parser.error("Los intervalos se cambian seleccionando oficina o evento.")
    try:
        settings = load_ambient_settings(args.db)
        if args.mode != "ver":
            settings = AmbientSettings(
                args.mode, *(args.gestos or settings.gesture_range),
                *(args.invitaciones or settings.invitation_range),
            )
            save_ambient_settings(settings, args.db)
    except (ValueError, OSError, sqlite3.Error) as exc:
        parser.exit(1, f"No se pudo leer o guardar la configuración de Arby. {exc}\n")
    print(f"Modo {settings.mode} | gestos {settings.gesture_min_seconds:g}–"
          f"{settings.gesture_max_seconds:g} s | invitaciones "
          f"{settings.invitation_min_seconds:g}–{settings.invitation_max_seconds:g} s")


if __name__ == "__main__":
    main()
