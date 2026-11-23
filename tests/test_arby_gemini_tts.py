"""Keyboard -> existing ArbyBot -> Gemini TTS -> speakers, without LED drivers.

Place this file in the project root or its tests folder and run it in PyCharm.
Update the active test environment: uv pip install --upgrade "google-genai>=2.25.0"
The existing FAISS index and bot dependencies are still required.
TTS uses a cancellable worker with first-audio, idle and overall deadlines.
Progress is printed every five seconds; no audio files are generated.

Official TTS reference: https://aistudio.google.com/docs/speech-generation
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import importlib
import json
import os
from pathlib import Path
import queue
import shutil
import signal
import subprocess
import sys
import tempfile
from threading import Thread
from time import perf_counter


# ----------------------------- EDIT HERE ---------------------------------
GEMINI_API_KEY = "AIzaSyAjew2KoRtACHsG5naUUFCiEkPf1SmTf9g"
CHAT_MODEL = "gemini-3.5-flash-lite"
TTS_MODEL = "gemini-3.8-flash-tts"
TTS_VOICE = "Algenib"
FFPLAY_PATH = r"C:\ffmpeg\bin\ffplay.exe" if os.name == "nt" else "ffplay"
REQUEST_TIMEOUT_SECONDS = 30
TTS_FIRST_AUDIO_TIMEOUT_SECONDS = 30.0
TTS_IDLE_TIMEOUT_SECONDS = 15.0
TTS_TOTAL_TIMEOUT_SECONDS = 90.0

VOICE_STYLE = (
    "Speak in natural Colombian Spanish with a warm, friendly, conversational "
    "delivery. Use a slightly brisk pace, connected sentences and expressive "
    "intonation appropriate to the text. Avoid a robotic or announcer delivery."
)
# -------------------------------------------------------------------------

EMOTION_STYLES = {
    "triste": "Gentle and sympathetic, with restrained sadness.",
    "alegres": "Cheerful, smiling and welcoming, without shouting.",
    "sorprendidos": "Naturally surprised, with a lively change of intonation.",
    "pensativos": "Reflective and curious, without slowing down too much.",
    "locos": "Playful, amused and energetic.",
    "enojado": "Mildly exasperated in a playful way, never aggressive.",
    "duda": "Gently questioning and curious.",
    "guiño ojo": "Lighthearted and mischievous, with a smile in the voice.",
    "dormido": "Soft and sleepy, while remaining clear and audible.",
    "relato extenso": "Engaging storytelling, with varied natural intonation.",
}


@dataclass(frozen=True)
class SpeechStats:
    first_audio_seconds: float
    audio_seconds: float


def get_field(value, name, default=None):
    """Read a field from SDK objects or dictionaries."""
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def build_speech_content(reply):
    """Keep the original words; attach each emotion as separate style metadata."""
    if isinstance(reply, str):
        segments = [{"response": reply}]
    elif isinstance(reply, dict):
        segments = reply.get("segments") or [reply]
    else:
        raise TypeError("El bot debe devolver un diccionario o un texto.")

    content = []
    for segment in segments:
        text = str(segment.get("response", "")).strip()
        if not text:
            continue
        emotion = segment.get("matrix_state", "")
        style = " ".join((VOICE_STYLE, EMOTION_STYLES.get(emotion, ""))).strip()
        content.append({
            "type": "text",
            "text": text,
            "annotations": [{"type": "speech_metadata", "style": style}],
        })
    return content


def resolve_ffplay():
    configured = str(FFPLAY_PATH).strip()
    candidate = shutil.which(configured) if configured else None
    if not candidate and configured and Path(configured).is_file():
        candidate = str(Path(configured).resolve())
    candidate = candidate or shutil.which("ffplay")
    if not candidate:
        raise FileNotFoundError(
            "No se encontro ffplay. Ajusta FFPLAY_PATH al ejecutable de FFmpeg."
        )
    return candidate


def configure_project_imports():
    """Resolve the project from this file, independently of the working directory.

    Direct execution inside tests adds tests/ to sys.path rather than the
    project root. PyCharm may add the root automatically, but Python does not.
    """
    script_directory = Path(__file__).resolve().parent
    for candidate in (script_directory, *script_directory.parents):
        bot_files = (
            candidate / "libraries" / "bot" / "arby_bot.py",
            candidate / "libraries" / "arby_bot.py",
        )
        if any(path.is_file() for path in bot_files):
            project_path = str(candidate)
            if project_path not in sys.path:
                sys.path.insert(0, project_path)
            importlib.invalidate_caches()
            return candidate
    raise FileNotFoundError(
        "No se encontro la raiz del proyecto desde "
        f"{script_directory}. Coloca este archivo en la raiz o en tests/. "
        "Debe existir libraries/bot/arby_bot.py o libraries/arby_bot.py."
    )


def load_bot_class():
    """Support both bot layouts when launched from the root or tests/."""
    configure_project_imports()
    for module_name in ("libraries.bot.arby_bot", "libraries.arby_bot"):
        try:
            return importlib.import_module(module_name)
        except ModuleNotFoundError as error:
            # Do not hide a missing dependency imported by an existing bot.
            if not (error.name == module_name or module_name.startswith(error.name + ".")):
                raise
    raise ModuleNotFoundError(
        "Se encontro la raiz, pero no se pudo importar el bot. Comprueba que "
        "libraries no este siendo reemplazado por otro paquete instalado."
    )


def safe_error(error, api_key=None):
    """Display provider diagnostics without printing the locally configured key."""
    message = str(error)
    key = (GEMINI_API_KEY if api_key is None else api_key).strip()
    if key:
        message = message.replace(key, "[API_KEY]")
    return f"{type(error).__name__}: {message}"


def stream_speech(client, ffplay, content, progress=None):
    """Stream raw PCM to one player; no MP3 or WAV files are generated."""
    started = perf_counter()
    first_audio = None
    byte_count = 0
    stream = None
    player = None
    last_progress = 0.0

    def report(stage, **values):
        if progress:
            progress({"stage": stage, **values})

    # A temporary diagnostic file prevents stderr from blocking a full pipe.
    with tempfile.TemporaryFile() as player_log:
        try:
            report("request")
            stream = client.interactions.create(
                model=TTS_MODEL,
                input=[{"type": "user_input", "content": content}],
                response_format={
                    "type": "audio", "mime_type": "audio/l16", "sample_rate": 24000,
                },
                generation_config={"speech_config": [{"voice": TTS_VOICE}]},
                stream=True,
                timeout=REQUEST_TIMEOUT_SECONDS,
                automatic_continuation=False,
            )
            for event in stream:
                event_type = get_field(event, "event_type")
                if event_type in ("error", "interaction.failed"):
                    detail = get_field(event, "error", event)
                    raise RuntimeError(str(detail))
                if event_type != "step.delta":
                    continue
                delta = get_field(event, "delta")
                if get_field(delta, "type") != "audio":
                    continue
                encoded = get_field(delta, "data")
                if not encoded:
                    continue
                audio = base64.b64decode(encoded, validate=True)
                if not audio:
                    continue
                if first_audio is None:
                    first_audio = perf_counter() - started
                    report("first_audio", elapsed=first_audio)
                    player = subprocess.Popen(
                        [ffplay, "-hide_banner", "-loglevel", "error",
                         "-nodisp", "-autoexit", "-probesize", "32", "-analyzeduration", "0",
                         "-f", "s16le", "-ar", "24000",
                         "-ch_layout", "mono", "-i", "pipe:0"],
                        stdin=subprocess.PIPE,
                        stdout=subprocess.DEVNULL,
                        stderr=player_log,
                    )
                    report("player", pid=player.pid)
                now = perf_counter()
                if now - last_progress >= 0.5:
                    report("audio", write_seconds=len(audio) / (24000 * 2))
                    last_progress = now
                try:
                    player.stdin.write(audio)
                    player.stdin.flush()
                except (BrokenPipeError, OSError) as error:
                    raise RuntimeError("ffplay interrumpio la reproduccion.") from error
                byte_count += len(audio)

            if not byte_count:
                raise RuntimeError(
                    "Gemini no devolvio audio. Comprueba el modelo, acceso y cuotas "
                    "del proyecto en Google AI Studio."
                )
            if byte_count % 2:
                raise RuntimeError("El flujo PCM termino con una muestra incompleta.")
            player.stdin.close()
            audio_seconds = byte_count / (24000 * 2)
            report("playing", audio_seconds=audio_seconds)
            exit_code = player.wait(timeout=audio_seconds + 15)
            if exit_code:
                raise RuntimeError(f"ffplay termino con codigo {exit_code}.")
            return SpeechStats(first_audio, audio_seconds)
        except Exception as error:
            if player is not None and player.poll() is not None:
                player_log.seek(0)
                detail = player_log.read(2000).decode("utf-8", errors="replace").strip()
                if detail:
                    raise RuntimeError(f"{error}\nffplay: {detail}") from error
            raise
        finally:
            if player is not None:
                if player.poll() is None:
                    player.kill()
                player.wait()
                if player.stdin and not player.stdin.closed:
                    try:
                        player.stdin.close()
                    except OSError:
                        pass
            close_stream = getattr(stream, "close", None)
            if close_stream:
                close_stream()


def stop_tts_process(process):
    """Stop a stalled worker and its ffplay child, including on Windows."""
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=5, check=False,
            )
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except (OSError, subprocess.TimeoutExpired):
        pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=5)


def tts_worker_main():
    """Run SDK/network/playback in a cancellable child, never loading FAISS."""
    def emit(payload):
        print(json.dumps(payload, ensure_ascii=True), flush=True)

    payload = {}
    try:
        payload = json.loads(sys.stdin.readline())
        from google import genai
        from google.genai import types

        with genai.Client(
            api_key=payload["key"],
            http_options=types.HttpOptions(
                api_version="v1beta", timeout=REQUEST_TIMEOUT_SECONDS * 1000,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        ) as client:
            if not hasattr(client, "interactions"):
                raise RuntimeError(
                    'Actualiza el SDK: uv pip install --upgrade "google-genai>=2.25.0"'
                )
            stats = stream_speech(client, payload["ffplay"], payload["content"], emit)
            emit({"stage": "result", "first_audio_seconds": stats.first_audio_seconds,
                  "audio_seconds": stats.audio_seconds})
        return 0
    except Exception as error:
        emit({"stage": "error", "message": safe_error(error, payload.get("key", ""))})
        return 1


def speak(ffplay, content):
    """Supervise the whole TTS operation, including blocked network/pipe writes.

    SDK/socket timeouts alone cannot cancel a blocked ffplay stdin write.
    This independent process deadline also works with silent SSE heartbeats.
    The key travels through stdin, never as a command-line argument.
    """
    limits = (TTS_FIRST_AUDIO_TIMEOUT_SECONDS, TTS_IDLE_TIMEOUT_SECONDS,
              TTS_TOTAL_TIMEOUT_SECONDS)
    if any(not 0 < value < float("inf") for value in limits):
        raise ValueError("Los limites de espera TTS deben ser positivos y finitos.")
    started = perf_counter()
    first_audio = False
    stage = "inicio del proceso de voz"
    idle_deadline = started + TTS_FIRST_AUDIO_TIMEOUT_SECONDS
    next_notice = started + 5
    messages = queue.Queue()
    with tempfile.TemporaryFile() as worker_log:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--tts-worker"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=worker_log,
            text=True, encoding="utf-8",
            start_new_session=os.name != "nt",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

        def read_messages():
            try:
                for line in process.stdout:
                    try:
                        message = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(message, dict):
                        messages.put(message)
            finally:
                messages.put({"stage": "eof"})

        reader = Thread(target=read_messages, daemon=True)
        reader.start()
        try:
            process.stdin.write(json.dumps({
                "key": GEMINI_API_KEY.strip(), "ffplay": ffplay, "content": content,
            }, ensure_ascii=True) + "\n")
            process.stdin.close()
            print("[TTS] Iniciando solicitud de voz...", flush=True)
            while True:
                now = perf_counter()
                elapsed = now - started
                if elapsed >= TTS_TOTAL_TIMEOUT_SECONDS:
                    raise TimeoutError(
                        f"TTS supero el limite total de {TTS_TOTAL_TIMEOUT_SECONDS:g} s. "
                        f"Ultima etapa: {stage}. Se cancelo la prueba de voz.")
                if not first_audio and elapsed >= TTS_FIRST_AUDIO_TIMEOUT_SECONDS:
                    raise TimeoutError(
                        f"No llego el primer audio en {TTS_FIRST_AUDIO_TIMEOUT_SECONDS:g} s. "
                        f"Ultima etapa: {stage}. No se inicia otra solicitud automaticamente.")
                if first_audio and now >= idle_deadline:
                    raise TimeoutError(
                        f"El TTS dejo de avanzar. Ultima etapa: {stage}. "
                        "Se detuvo el proceso de voz y ffplay.")
                if now >= next_notice:
                    print(f"[TTS] {elapsed:.0f} s | {stage}...", flush=True)
                    next_notice = now + 5
                try:
                    message = messages.get(timeout=0.1)
                except queue.Empty:
                    continue
                status = message.get("stage")
                if status == "request":
                    stage = "esperando audio de Gemini"
                    print("[TTS] Esperando audio de Gemini...", flush=True)
                elif status == "first_audio":
                    first_audio = True
                    idle_deadline = perf_counter() + TTS_IDLE_TIMEOUT_SECONDS
                    stage = "primer audio recibido; iniciando ffplay"
                    print(f"[TTS] Primer audio recibido en {message['elapsed']:.2f} s.", flush=True)
                elif status == "player":
                    stage = "reproduciendo audio con ffplay"
                    print("[TTS] Reproduciendo audio...", flush=True)
                elif status == "audio":
                    idle_deadline = perf_counter() + max(
                        TTS_IDLE_TIMEOUT_SECONDS, message.get("write_seconds", 0) + 5)
                elif status == "playing":
                    stage = "finalizando reproduccion en ffplay"
                    idle_deadline = perf_counter() + max(
                        TTS_IDLE_TIMEOUT_SECONDS, message.get("audio_seconds", 0) + 5)
                elif status == "result":
                    return SpeechStats(message["first_audio_seconds"], message["audio_seconds"])
                elif status == "error":
                    raise RuntimeError(message.get("message", "Fallo el proceso TTS."))
                elif status == "eof":
                    worker_log.seek(0)
                    detail = worker_log.read(3000).decode("utf-8", errors="replace").strip()
                    raise RuntimeError(
                        "El proceso TTS termino sin devolver un resultado. " + detail)
        finally:
            stop_tts_process(process)
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
            reader.join(timeout=1)
            if not reader.is_alive():
                process.stdout.close()


def main():
    key = GEMINI_API_KEY.strip()
    if not key or key == "PASTE_YOUR_GEMINI_API_KEY_HERE":
        raise ValueError("Pega tu clave en GEMINI_API_KEY al inicio de este archivo.")

    ffplay = resolve_ffplay()
    bot_module = load_bot_class()
    bot_options = {"api_key": key}
    if CHAT_MODEL.strip():
        bot_options["config"] = bot_module.BotConfig(model=CHAT_MODEL.strip())

    bot = bot_module.ArbyBot(**bot_options)
    try:
        print(f"Chat: {getattr(getattr(bot, 'config', None), 'model', 'predeterminado')}")
        print(f"TTS: {TTS_MODEL} | Voz: {TTS_VOICE}")
        print("Comandos: salir, reiniciar, /voz TEXTO (prueba solo TTS).\n")
        while True:
            try:
                text = input("Tu: ").strip()
            except EOFError:
                break
            if not text:
                continue
            if text.lower() in ("salir", "exit", "quit"):
                break
            if text.lower() == "reiniciar":
                bot.reset_session()
                print("Conversacion reiniciada.\n")
                continue
            try:
                chat_started = perf_counter()
                if text.lower().startswith("/voz "):
                    reply = text[5:].strip()
                    chat_seconds = 0.0
                else:
                    reply = bot.respond(text)
                    chat_seconds = perf_counter() - chat_started
                    if getattr(bot, "last_error", None):
                        print(f"Aviso del chat: {bot.last_error}")
                content = build_speech_content(reply)
                if not content:
                    print("El bot no devolvio texto para reproducir.\n")
                    continue
                print("Arby: " + " ".join(part["text"] for part in content), flush=True)
                stats = speak(ffplay, content)
                print(
                    f"[Chat: {chat_seconds:.2f} s | "
                    f"TTS hasta primer bloque: {stats.first_audio_seconds:.2f} s | "
                    f"Audio generado: {stats.audio_seconds:.2f} s]\n"
                )
            except Exception as error:
                print(f"Error: {safe_error(error)}\n", file=sys.stderr)
    finally:
        bot.close()


if __name__ == "__main__":
    if sys.argv[1:] == ["--tts-worker"]:
        raise SystemExit(tts_worker_main())
    try:
        main()
    except KeyboardInterrupt:
        print("\nPrueba finalizada.")
    except Exception as error:
        print(f"No se pudo iniciar: {safe_error(error)}", file=sys.stderr)
        raise SystemExit(1)
