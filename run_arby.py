# sudo "$(pwd)/.venv/bin/python" "$(pwd)/run_arby.py"
"""Compose text/microphone input, bot, TTS, eyes and NeoPixel strip."""
import sys
from types import SimpleNamespace
from queue import Empty
from contextlib import ExitStack
import logging
import math
import os
import signal
import threading
import time

from libraries.core.arby_env import load_environment
from libraries.audio.arby_audio_recovery import close_strip_and_recover_audio
from libraries.simulation.arby_demo_bot import DemoBot
from libraries.simulation.arby_memory_pixels import MemoryPixels
from libraries.simulation.arby_muted_tts import MutedTTS
from libraries.preview.arby_preview import Preview
from libraries.eyes.arby_eyes import EyeAnimator
from libraries.core.arby_runtime import ArbyRuntime
from libraries.leds.arby_strip_led import LedStripController, StripConfig


_console_output_lock = threading.Lock()


def load_config():
    """Read typed settings from the process environment (including loaded .env)."""
    fields = {
        "input_mode": (str, "text", ("text", "voice")),
        "mic_device": (str, "0", None),
        "mic_channel": (str, "left", ("left", "right")),
        "mic_language": (str, "es-CO", None),
        "mic_gain_db": (float, 6.0, None),
        "mic_graves": (float, 80.0, None),
        "mic_agudos": (float, 8000.0, None),
        "mic_block_ms": (int, 20, None),
        "mic_queue_blocks": (int, 8, None),
        "mic_threshold": (float, 0.5, None),
        "mic_silence_ms": (int, 450, None),
        "mic_preroll_ms": (int, 320, None),
        "mic_followup_seconds": (float, 8.0, None),
        "mic_request_timeout": (float, 10.0, None),
        "mic_max_utterance_seconds": (float, 15.0, None),
        "eyes": (str, "preview", ("preview", "none", "matrix")),
        "strip": (bool, False, None),
        "strip_gpio": (int, 12, None),
        "strip_leds": (int, 55, None),
        "strip_brightness": (int, 20, None),
        "strip_effect": (str, "solid", ("solid", "breathing", "bounce", "center_out", "ripple")),
        "multiplexing": (int, None, None),
        "row_address_type": (int, 0, None),
        "matrix_brightness": (int, 25, None),
        "matrix_mapping": (str, "regular", ("regular", "regular-oe5")),
        "matrix_rgb_sequence": (str, "RGB", ("RGB", "RBG", "GRB", "GBR", "BRG", "BGR")),
        "slowdown": (int, 2, None),
        "swap_eyes": (bool, False, None),
        "model": (str, None, None),
        "bot_timeout": (float, 30.0, None),
        "voice": (str, None, None),
        "rate": (str, None, None),
        "pitch": (str, None, None),
        "ffplay": (str, None, None),
        "audio_driver": (str, None, None),
        "audio_device": (str, None, None),
        "audio_recover_on_exit": (bool, False, None),
        "mute": (bool, False, None),
        "demo": (bool, False, None),
        "trill": (bool, False, None),
    }
    settings = {}
    for name, (convert, default, choices) in fields.items():
        variable = "GEMINI_MODEL" if name == "model" else f"ARBY_{name.upper()}"
        raw = os.getenv(variable, "").strip()
        value = default
        if raw:
            try:
                if convert is bool:
                    if raw.casefold() not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
                        raise ValueError("usa true/false, 1/0, yes/no u on/off")
                    value = raw.casefold() in {"true", "1", "yes", "on"}
                else:
                    value = convert(raw)
                if choices is not None and value not in choices:
                    raise ValueError(f"opciones: {', '.join(choices)}")
            except ValueError as exc:
                raise ValueError(f"{variable}: valor inválido ({exc})") from exc
        settings[name] = value
    config = SimpleNamespace(**settings)
    mic_values = {name[4:]: value for name, value in settings.items() if name.startswith("mic_")}
    if not all(math.isfinite(v) for v in mic_values.values() if isinstance(v, (int, float))):
        raise ValueError("Los parámetros ARBY_MIC deben ser finitos.")
    if (not 0 < config.mic_graves < config.mic_agudos < 24000
            or not -30 <= config.mic_gain_db <= 36
            or config.mic_block_ms not in (10, 20, 40)
            or not 1 <= config.mic_queue_blocks <= 100
            or not 0 < config.mic_threshold < 1
            or not 0 < config.mic_silence_ms <= 5000
            or not 0 <= config.mic_preroll_ms <= 2000
            or not 0 < config.mic_followup_seconds <= 120
            or not 0 < config.mic_request_timeout <= 120
            or not 1 <= config.mic_max_utterance_seconds <= 60):
        raise ValueError("Revisa los límites de ARBY_MIC en .env.example.")
    if str(mic_values["device"]).isdigit():
        mic_values["device"] = int(mic_values["device"])
    config.microphone = SimpleNamespace(**mic_values)
    if config.audio_recover_on_exit and (
        config.audio_driver != "alsa" or
        config.audio_device != "plughw:CARD=Headphones,DEV=0"
    ):
        raise ValueError("ARBY_AUDIO_RECOVER_ON_EXIT requiere ARBY_AUDIO_DRIVER=alsa y "
                         "ARBY_AUDIO_DEVICE=plughw:CARD=Headphones,DEV=0.")
    if not 0 < config.bot_timeout < float("inf"):
        raise ValueError("ARBY_BOT_TIMEOUT debe ser positivo y finito.")
    if config.eyes == "matrix" and config.multiplexing is None:
        raise ValueError("ARBY_MULTIPLEXING es obligatorio en modo matrix; valida el valor sobre tus paneles.")
    matrix_pins = {4, 7, 8, 9, 10, 11, 17, 18, 22, 23, 24, 25, 27}
    if config.matrix_mapping == "regular-oe5":
        matrix_pins = (matrix_pins - {18}) | {5}
    if config.eyes == "matrix" and config.strip and config.strip_gpio in matrix_pins:
        raise ValueError("ARBY_STRIP_GPIO coincide con el cableado de las matrices seleccionado.")
    if config.strip_gpio < 0 or config.strip_leds < 1 or not 0 <= config.strip_brightness <= 100:
        raise ValueError("Revisa ARBY_STRIP_GPIO (>=0), ARBY_STRIP_LEDS (>0) y ARBY_STRIP_BRIGHTNESS (0–100).")
    if not 1 <= config.matrix_brightness <= 100:
        raise ValueError("ARBY_MATRIX_BRIGHTNESS debe estar entre 1 y 100.")
    return config


def _console(runtime, stop, input_done):
    print("Escribe para conversar. Comandos: salir, reiniciar, /frase TEXTO.")
    try:
        while not stop.is_set():
            try:
                text = input("Tú: ").strip()
            except EOFError:
                return
            if text.casefold() in {"salir", "/salir", "exit"}:
                stop.set()
                return
            if not text:
                continue
            try:
                if text.casefold() in {"reiniciar", "/reiniciar"}:
                    pending = runtime.reset_session()
                elif text.startswith("/frase "):
                    pending = runtime.submit_fixed_phrase(text[7:])
                else:
                    pending = runtime.submit_text(text)
                # Keep rendering and playback on their own threads, but do not
                # offer another console turn until this request has finished.
                while not pending.done():
                    if stop.wait(0.03):
                        return
                _print_events(runtime)
            except (ValueError, RuntimeError) as exc:
                print(f"\n{exc}")
    finally:
        input_done.set()


def _print_events(runtime):
    # The main loop and console may drain events concurrently. Holding this
    # through printing ensures a drained reply is visible before the next input.
    with _console_output_lock:
        _drain_events(runtime)


def _drain_events(runtime):
    while True:
        try:
            kind, message = runtime.events.get_nowait()
        except Empty:
            return
        prefix = "Arby" if kind == "response" else "Estado" if kind == "info" else "Error"
        print(f"\n{prefix}: {message}", flush=True)


def main():
    if len(sys.argv) > 1:
        print("Arby se configura desde .env; ejecuta sin argumentos. Consulta .env.example.")
        return 2
    load_environment()
    try:
        args = load_config()
        strip_config = StripConfig(args.strip_gpio, args.strip_leds,
                                   args.strip_brightness / 100, args.strip_effect)
    except ValueError as exc:
        print(f"Configuración inválida: {exc}")
        return 2
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    stop, input_done = threading.Event(), threading.Event()
    try:
        with ExitStack() as stack:
            touch = None
            if args.trill:
                from libraries.core.arby_touch import TrillReader, TouchReactions, load_touch_config
                touch_config = load_touch_config()
                sensor = TrillReader(touch_config)
                stack.callback(sensor.close)
                touch = TouchReactions(sensor, touch_config)
            # Terminal closure and service stop use the same cleanup as salir.
            if threading.current_thread() is threading.main_thread():
                for name in ("SIGTERM", "SIGHUP", "SIGINT"):
                    sig = getattr(signal, name, None)
                    if sig is not None:
                        previous = signal.signal(sig, lambda *_: stop.set())
                        stack.callback(signal.signal, sig, previous)
            # GPIO initialization comes before MatrixOutput can drop privileges.
            pixels = None if args.strip else MemoryPixels(args.strip_leds)
            strip = LedStripController(strip_config, pixels=pixels)
            stack.callback(close_strip_and_recover_audio, strip,
                           recover=args.strip and args.audio_recover_on_exit)
            matrix = preview = None
            if args.eyes == "matrix":
                from libraries.eyes.matrix_output import MatrixOutput
                matrix = MatrixOutput(multiplexing=args.multiplexing,
                    row_address_type=args.row_address_type, slowdown=args.slowdown,
                    brightness=args.matrix_brightness, swap_eyes=args.swap_eyes,
                    hardware_mapping=args.matrix_mapping,
                    rgb_sequence=args.matrix_rgb_sequence,
                    disable_hardware_pulsing=args.strip)
                stack.callback(matrix.close)
            elif args.eyes == "preview":
                preview = Preview(args.strip_leds)
                stack.callback(preview.close)
            if args.demo:
                bot = DemoBot()
                palette = bot.colors
            else:
                if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
                    raise ValueError("Configura GEMINI_API_KEY antes de ejecutar.")
                from libraries.bot.arby_bot import ArbyBot, BotConfig, EMOTION_COLORS
                bot = ArbyBot(config=BotConfig(
                    model=args.model or BotConfig().model,
                    timeout_seconds=args.bot_timeout))
                palette = EMOTION_COLORS
            # Until runtime starts, protect client cleanup during partial startup.
            with ExitStack() as clients:
                clients.callback(bot.close)
                if args.mute:
                    tts = MutedTTS()
                    print("Estado: voz desactivada (ARBY_MUTE=true).", flush=True)
                else:
                    from libraries.audio.arby_tts import ArbyTTS, TTSConfig
                    overrides = {name: value for name, value in {
                        "voice": args.voice, "rate": args.rate, "pitch": args.pitch,
                        "ffplay_path": args.ffplay, "audio_driver": args.audio_driver,
                        "audio_device": args.audio_device}.items() if value is not None}
                    tts = ArbyTTS(TTSConfig(**overrides))
                    print(f"Estado: voz activa / driver={args.audio_driver or os.getenv('SDL_AUDIODRIVER') or 'default'}"
                          f" / device={args.audio_device or os.getenv('AUDIODEV') or 'default'}"
                          " / salida estéreo 48000 Hz", flush=True)
                clients.callback(tts.close)
                runtime = ArbyRuntime(bot, tts, emotion_colors=palette).start()
                clients.pop_all()  # Ownership is now held by the runtime worker.
            stack.callback(runtime.close)
            eyes = EyeAnimator()
            if touch:
                print("Estado: Trill activo junto a la conversación; toques con respuestas automáticas.", flush=True)
            if args.input_mode == "voice":
                from libraries.voice_input.arby_microphone import MicrophoneInput
                microphone = MicrophoneInput(runtime, args.microphone, stop, input_done)
                stack.callback(microphone.close)
                microphone.start()
            else:
                reader = threading.Thread(target=_console, args=(runtime, stop, input_done),
                                          name="arby-console", daemon=True)
                reader.start()
            revision = -1
            while not stop.is_set():
                started = time.monotonic()
                if touch:
                    touch.update(runtime, started)
                if preview and preview.requested_stop():
                    stop.set()
                    break
                visual = runtime.visual
                if visual.revision != revision:
                    eyes.set_state(visual.matrix_state, color=visual.color, now=started)
                    strip.set_visual(visual.color, visual.phase, now=started)
                    revision = visual.revision
                strip.update(started)
                if preview or matrix:
                    frame = eyes.render(started)
                    if matrix:
                        matrix.show(frame)
                    if preview:
                        preview.show(frame, visual, strip.pixels, physical_strip=args.strip)
                _print_events(runtime)
                if not touch and input_done.is_set() and runtime.pending_count == 0:
                    break
                stop.wait(max(0, 1/30 - (time.monotonic() - started)))
            _print_events(runtime)
            if args.input_mode == "voice" and microphone.error is not None:
                raise RuntimeError("Falló la entrada de micrófono; revisa el error anterior.")
    except KeyboardInterrupt:
        stop.set()
    except Exception as exc:
        print(f"No se pudo ejecutar Arby: {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
