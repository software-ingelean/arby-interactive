# sudo "$(pwd)/.venv/bin/python" "$(pwd)/run_arby.py"
"""Compose text/microphone input, bot, TTS, eyes and NeoPixel strip."""
import sys
from queue import Empty
from contextlib import ExitStack
import logging
import os
import signal
import sqlite3
import threading
import time

from libraries.audio.arby_devices import load_selection, apply_selection
from libraries.core.arby_support import SupportBridge, load_overrides, CONTROLS
from dataclasses import asdict
from libraries.core.arby_logging import configure_logging
from libraries.core.arby_env import load_environment
from libraries.core.arby_config import parse_config
from libraries.core.arby_support import configuration_revision
from libraries.audio.arby_audio_recovery import close_strip_and_recover_audio
from libraries.simulation.arby_demo_bot import DemoBot
from libraries.simulation.arby_memory_pixels import MemoryPixels
from libraries.simulation.arby_muted_tts import MutedTTS
from libraries.preview.arby_preview import Preview
from libraries.eyes.arby_eyes import EyeAnimator
from libraries.core.arby_runtime import ArbyRuntime
from libraries.core.arby_ambient import AmbientAudio, AmbientSequence, load_ambient_settings
from libraries.leds.arby_strip_led import LedStripController, StripConfig


_console_output_lock = threading.Lock()


def load_config():
    """Read typed settings exclusively from saved portal preferences."""
    config = parse_config(load_overrides(), {})
    config.audio_selection = load_selection()
    config.audio_active = apply_selection(config, config.audio_selection)
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
        if kind == "info":
            continue
        prefix = "Arby" if kind == "response" else "Error"
        print(f"\n{prefix}: {message}", flush=True)


def main():
    if len(sys.argv) > 1:
        print("Arby se configura desde el portal; ejecuta sin argumentos.")
        return 2
    try:
        load_environment()
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(f"No se pudo cargar o migrar la configuración del portal: {type(exc).__name__}: {exc}", flush=True)
        return 2
    configure_logging()
    support = SupportBridge()
    try:
        applied_revision = configuration_revision(support.database)
        args = load_config()
        strip_config = StripConfig(args.strip_gpio, args.strip_leds,
                                   args.strip_brightness / 100, args.strip_effect)
    except (ValueError, OSError, sqlite3.Error) as exc:
        support.finish("error")
        logging.getLogger("arby").exception("Configuración inválida")
        print(f"Configuración inválida: {exc}")
        return 2
    logging.getLogger("arby").info("Configuración: entrada=%s, micrófono=%s, push_to_talk=%s", args.input_mode, args.microphone_enabled, args.push_to_talk)
    if args.push_to_talk and (args.input_mode != "voice" or not args.microphone_enabled):
        logging.getLogger("arby").warning("Push to talk requiere ARBY_INPUT_MODE=voice y ARBY_MICROPHONE_ENABLED=true")
    stop, input_done = threading.Event(), threading.Event()
    try:
        with ExitStack() as stack:
            ambient_settings = load_ambient_settings()
            support.snapshot['effective'] = {
                'ambient': asdict(ambient_settings),
                'audio': args.audio_selection,
                'push_to_talk': args.push_to_talk,
                'configuration_revision': applied_revision,
                'controls': {key: (getattr(args, key) if key != 'rate' else args.rate or '+12%') for key in CONTROLS},
            }
            support.snapshot['audio_active'] = args.audio_active
            support.snapshot['capabilities'] = {'eyes': args.eyes != 'none', 'strip': args.strip,
                                                'microphone': args.input_mode == 'voice' and args.microphone_enabled, 'speaker': not args.mute}
            support.snapshot['components'] = {
                'trill': {'state': 'disabled' if not args.trill else 'unknown', 'detail': 'Desactivado.' if not args.trill else 'Pendiente de inicializar.'},
                'microphone': {'state': 'disabled' if (args.input_mode != 'voice' or not args.microphone_enabled) else 'unknown', 'detail': 'Captura desactivada.' if not args.microphone_enabled else 'Entrada por consola.' if args.input_mode != 'voice' else 'Pendiente de inicializar.'},
                'speaker': {'state': 'disabled' if args.mute else 'unknown', 'detail': 'Voz desactivada.' if args.mute else 'Sin comprobar.'},
                'eyes': {'state': 'disabled' if args.eyes == 'none' else 'unknown', 'detail': 'Desactivados.' if args.eyes == 'none' else 'Pendientes de inicializar.'},
                'strip': {'state': 'disabled' if not args.strip else 'unknown', 'detail': 'Simulada.' if not args.strip else 'Pendiente de inicializar.'},
            }
            event_mode = ambient_settings.mode == "evento"
            ambient = AmbientSequence(ambient_settings, speak=not args.mute)
            support.debug.event("inicio", "Modo seleccionado", mode=ambient_settings.mode)
            touch = None
            if args.trill:
                from libraries.core.arby_touch import TrillReader, TouchReactions, load_touch_config
                touch_config = load_touch_config()
                support.checkpoint("Inicializando TrillReader", "run_arby.py · main → TrillReader")
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
            support.checkpoint("Inicializando LedStripController", "run_arby.py · main → LedStripController")
            strip = LedStripController(strip_config, pixels=pixels)
            stack.callback(close_strip_and_recover_audio, strip,
                           recover=args.strip and args.audio_recover_on_exit)
            matrix = preview = None
            if args.eyes == "matrix":
                from libraries.eyes.matrix_output import MatrixOutput
                support.checkpoint("Inicializando MatrixOutput", "run_arby.py · main → MatrixOutput")
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
                    raise ValueError("Configura GEMINI_API_KEY en Administración del portal antes de ejecutar.")
                from libraries.bot.arby_bot import ArbyBot, BotConfig, EMOTION_COLORS
                support.checkpoint("Inicializando ArbyBot", "run_arby.py · main → ArbyBot")
                bot = ArbyBot(config=BotConfig(
                    model=args.model or BotConfig().model,
                    timeout_seconds=args.bot_timeout,
                    event_mode=event_mode,
                    fallback_models=tuple(model.strip() for model in os.getenv(
                        "GEMINI_FALLBACK_MODELS", "gemini-flash-lite-latest").split(",") if model.strip()),
                    model_cooldown_seconds=args.model_cooldown_seconds))
                palette = EMOTION_COLORS
            # Until runtime starts, protect client cleanup during partial startup.
            with ExitStack() as clients:
                clients.callback(bot.close)
                if args.mute:
                    tts = MutedTTS()
                    support.debug.event("inicio", "Voz desactivada")
                else:
                    from libraries.audio.arby_tts import ArbyTTS, TTSConfig
                    overrides = {name: value for name, value in {
                        "voice": args.voice, "rate": args.rate, "pitch": args.pitch,
                        "ffplay_path": args.ffplay, "audio_driver": args.audio_driver,
                        "audio_device": args.audio_device}.items() if value is not None}
                    support.checkpoint("Inicializando ArbyTTS", "run_arby.py · main → ArbyTTS")
                    tts = ArbyTTS(TTSConfig(**overrides))
                    support.debug.event("inicio", "Voz inicializada", driver=args.audio_driver or "default")
                clients.callback(tts.close)
                ambient_audio = None
                if event_mode and not args.mute:
                    ambient_audio = AmbientAudio(
                        ffplay=args.ffplay, audio_driver=args.audio_driver,
                        audio_device=args.audio_device,
                        player_context=getattr(tts, "_player_context", None),
                    )
                from libraries.core.arby_visits import VisitRecorder
                runtime = ArbyRuntime(
                    bot, tts, emotion_colors=palette, debug=support.debug,
                    visit_recorder=VisitRecorder(support.database) if event_mode and args.input_mode == "voice" and args.microphone_enabled and not args.demo else None,
                    play_ambient_clip=ambient_audio.play if ambient_audio else None,
                ).start()
                clients.pop_all()  # Ownership is now held by the runtime worker.
            stack.callback(runtime.close)
            eyes = EyeAnimator()
            if touch:
                support.debug.event("inicio", "Trill activo con respuestas automáticas")
            microphone = None
            if args.input_mode == "voice" and args.microphone_enabled:
                from libraries.voice_input.arby_microphone import MicrophoneInput
                args.microphone.push_to_talk = args.push_to_talk
                microphone = MicrophoneInput(runtime, args.microphone, stop, input_done)
                stack.callback(microphone.close)
                microphone.start()
            elif args.input_mode == "text":
                reader = threading.Thread(target=_console, args=(runtime, stop, input_done),
                                          name="arby-console", daemon=True)
                reader.start()
            support.debug.stage('proceso', 'Atendiendo sensores y actualizando salidas', 'run_arby.py · main → bucle de renderizado')
            support.snapshot['state'] = 'ready'
            for name in ('trill', 'microphone', 'eyes', 'strip'):
                component = support.snapshot['components'][name]
                if component['state'] != 'disabled':
                    component.update(state='ready', detail='Inicializado; confirma la respuesta físicamente.' if name in ('eyes', 'strip') else 'Inicializado y atendiendo lecturas.')
            revision = -1
            activity_revision = 0
            submit_ambient = (microphone.try_submit_ambient if microphone is not None
                              else runtime.try_submit_ambient)
            while not stop.is_set():
                started = time.monotonic()
                touch_active = touch is not None and touch.update(runtime, started)
                if touch_active:
                    runtime.interrupt_ambient()
                if preview and preview.requested_stop():
                    stop.set()
                    break
                support.tick(runtime, microphone, tts, touch, submit_ambient)
                if (touch is not None or not input_done.is_set()) and not support.waiting and support.pending is None:
                    busy, current_revision = runtime.visitor_activity
                    visitor_active = touch_active or busy or current_revision != activity_revision
                    activity_revision = current_revision
                    ambient.tick(started, visitor_active=visitor_active, submit=submit_ambient)
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
            if microphone is not None and microphone.error is not None:
                raise RuntimeError("Falló la entrada de micrófono; revisa el error anterior.")
    except KeyboardInterrupt:
        stop.set()
    except Exception as exc:
        support.finish("error")
        logging.getLogger("arby").exception("No se pudo ejecutar Arby")
        print(f"No se pudo ejecutar Arby: {type(exc).__name__}: {exc}")
        return 1
    support.finish("stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
