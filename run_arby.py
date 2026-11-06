"""Compose console, bot, Edge TTS, animated eyes and NeoPixel strip."""
import argparse
from contextlib import ExitStack
import logging
import os
from queue import Empty
import threading
import time

from libraries.arby_eyes import EyeAnimator
from libraries.arby_runtime import ArbyRuntime
from libraries.arby_response import EMOTION_COLORS, normalize_reply
from libraries.arby_strip_led import LedStripController, StripConfig


class _MemoryPixels:
    """Same update path as physical LEDs, without importing GPIO packages."""

    def __init__(self, count):
        self.values = [(0, 0, 0)] * count
        self.brightness = 0.2

    def __len__(self):
        return len(self.values)

    def __setitem__(self, index, color):
        self.values[index] = color

    def fill(self, color):
        self.values[:] = [color] * len(self.values)

    def show(self):
        pass

    def deinit(self):
        pass


class _MutedTTS:
    last_error = None

    def speak(self, text):
        return True

    def wait(self, timeout=None):
        return True

    def stop(self):
        return True

    def close(self):
        pass


class _DemoBot:
    """Offline wiring check only; production uses the existing ArbyBot."""
    colors = EMOTION_COLORS

    def respond(self, text):
        state = next((s for s in self.colors if s in text.casefold()), "alegres")
        r, g, b = self.colors[state]
        segment = {"matrix_state": state,
                "strip_led": {"color": {"r": r, "g": g, "b": b}, "mood": state},
                "response": f"Prueba de integración: expresión {state}."}
        if text.casefold().strip() == "emociones":
            return normalize_reply({"segments": [
                {"matrix_state": "alegres", "strip_led": {
                    "color": {"r": 0, "g": 255, "b": 80}, "mood": "alegres"},
                 "response": "Sí Luis, qué bueno verte."},
                {"matrix_state": "pensativos", "strip_led": {
                    "color": {"r": 120, "g": 60, "b": 255}, "mood": "pensativos"},
                 "response": "Eso que me cuentas me dejó pensando."},
            ]})
        return normalize_reply({"segments": [segment]})

    def reset_session(self):
        pass

    def close(self):
        pass


class _Preview:
    def __init__(self, count):
        import pygame
        self.pg = pygame
        pygame.display.init()
        pygame.font.init()
        try:
            self.screen = pygame.display.set_mode((760, 490))
        except Exception:
            pygame.quit()
            raise
        pygame.display.set_caption("Arby / ojos y tira LED")
        self.font = pygame.font.Font(None, 28)
        self.small = pygame.font.Font(None, 22)
        self.count = count

    def requested_stop(self):
        return any(event.type == self.pg.QUIT or
                   (event.type == self.pg.KEYDOWN and event.key == self.pg.K_ESCAPE)
                   for event in self.pg.event.get())

    def show(self, frame, visual, pixels, *, physical_strip):
        pg = self.pg
        self.screen.fill((12, 18, 26))
        title = f"Arby / {visual.matrix_state} / RGB {visual.color}"
        self.screen.blit(self.font.render(title, True, (180, 235, 255)), (35, 24))
        for side, x in enumerate((76, 428)):
            panel = frame.crop((side*32, 0, side*32+32, 32))
            surface = pg.image.fromstring(panel.tobytes(), panel.size, "RGB")
            self.screen.blit(pg.transform.scale(surface, (256, 256)), (x, 85))
        label = "Tira física activa" if physical_strip else "Tira simulada"
        self.screen.blit(self.small.render(f"{label} / {visual.phase}", True,
                                         (170, 190, 205)), (76, 365))
        # Physical NeoPixel does not expose a plain RGB buffer; show its base RGB.
        colors = pixels.values if isinstance(pixels, _MemoryPixels) else [visual.color] * self.count
        step = 608 / self.count
        for i, color in enumerate(colors):
            pg.draw.rect(self.screen, color, (76 + i*step, 400, max(1, step-2), 18))
        self.screen.blit(self.small.render("Escribe en la consola / Esc o cerrar: salir", True,
                                         (170, 190, 205)), (76, 451))
        pg.display.flip()

    def close(self):
        self.pg.quit()


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eyes", choices=("preview", "none", "matrix"), default="preview")
    parser.add_argument("--strip", action="store_true", help="Enable the physical NeoPixel strip")
    parser.add_argument("--strip-gpio", type=int, default=12)
    parser.add_argument("--strip-leds", type=int, default=55)
    parser.add_argument("--strip-brightness", type=int, default=20)
    parser.add_argument("--strip-effect", choices=("solid", "breathing", "bounce", "center_out", "ripple"), default="solid")
    parser.add_argument("--multiplexing", type=int)
    parser.add_argument("--row-address-type", type=int, default=0)
    parser.add_argument("--matrix-brightness", type=int, default=25)
    parser.add_argument("--slowdown", type=int, default=2)
    parser.add_argument("--swap-eyes", action="store_true")
    parser.add_argument("--model", default=None, help="Use the existing bot default unless provided")
    parser.add_argument("--voice", default=None)
    parser.add_argument("--rate", default=None, help="For example: --rate=+12%%")
    parser.add_argument("--pitch", default=None, help="For example: --pitch=-8Hz")
    parser.add_argument("--ffplay", default=None)
    parser.add_argument("--audio-driver", default=None)
    parser.add_argument("--audio-device", default=None)
    parser.add_argument("--mute", action="store_true", help="Skip TTS for integration tests")
    parser.add_argument("--demo", action="store_true", help="Offline fake bot; bypass Gemini and FAISS")
    return parser


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
                    runtime.reset_session()
                elif text.startswith("/frase "):
                    runtime.submit_fixed_phrase(text[7:])
                else:
                    runtime.submit_text(text)
            except (ValueError, RuntimeError) as exc:
                print(f"\n{exc}")
    finally:
        input_done.set()


def _print_events(runtime):
    while True:
        try:
            kind, message = runtime.events.get_nowait()
        except Empty:
            return
        prefix = "Arby" if kind == "response" else "Estado" if kind == "info" else "Error"
        print(f"\n{prefix}: {message}", flush=True)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.eyes == "matrix" and args.multiplexing is None:
        parser.error("El modo matrix requiere --multiplexing validado sobre tus paneles.")
    matrix_pins = {4, 7, 8, 9, 10, 11, 17, 18, 22, 23, 24, 25, 27}
    if args.eyes == "matrix" and args.strip and args.strip_gpio in matrix_pins:
        parser.error("El GPIO de la tira coincide con el cableado regular de las matrices.")
    try:
        strip_config = StripConfig(args.strip_gpio, args.strip_leds,
                                   args.strip_brightness / 100, args.strip_effect)
    except ValueError as exc:
        parser.error(str(exc))
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    stop, input_done = threading.Event(), threading.Event()
    try:
        with ExitStack() as stack:
            # GPIO initialization comes before MatrixOutput can drop privileges.
            pixels = None if args.strip else _MemoryPixels(args.strip_leds)
            strip = LedStripController(strip_config, pixels=pixels)
            stack.callback(strip.close)
            matrix = preview = None
            if args.eyes == "matrix":
                from libraries.matrix_output import MatrixOutput
                matrix = MatrixOutput(multiplexing=args.multiplexing,
                    row_address_type=args.row_address_type, slowdown=args.slowdown,
                    brightness=args.matrix_brightness, swap_eyes=args.swap_eyes,
                    disable_hardware_pulsing=args.strip)
                stack.callback(matrix.close)
            elif args.eyes == "preview":
                preview = _Preview(args.strip_leds)
                stack.callback(preview.close)
            if args.demo:
                bot = _DemoBot()
                palette = bot.colors
            else:
                if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
                    raise ValueError("Configura GEMINI_API_KEY antes de ejecutar.")
                from libraries.arby_bot import ArbyBot, BotConfig, EMOTION_COLORS
                bot = ArbyBot(config=BotConfig(model=args.model)) if args.model else ArbyBot()
                palette = EMOTION_COLORS
            # Until runtime starts, protect client cleanup during partial startup.
            with ExitStack() as clients:
                clients.callback(bot.close)
                if args.mute:
                    tts = _MutedTTS()
                else:
                    from libraries.arby_tts import ArbyTTS, TTSConfig
                    overrides = {name: value for name, value in {
                        "voice": args.voice, "rate": args.rate, "pitch": args.pitch,
                        "ffplay_path": args.ffplay, "audio_driver": args.audio_driver,
                        "audio_device": args.audio_device}.items() if value is not None}
                    tts = ArbyTTS(TTSConfig(**overrides))
                clients.callback(tts.close)
                runtime = ArbyRuntime(bot, tts, emotion_colors=palette).start()
                clients.pop_all()  # Ownership is now held by the runtime worker.
            stack.callback(runtime.close)
            eyes = EyeAnimator()
            reader = threading.Thread(target=_console, args=(runtime, stop, input_done),
                                      name="arby-console", daemon=True)
            reader.start()
            revision = -1
            while not stop.is_set():
                started = time.monotonic()
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
                if input_done.is_set() and runtime.pending_count == 0:
                    break
                stop.wait(max(0, 1/30 - (time.monotonic() - started)))
            _print_events(runtime)
    except KeyboardInterrupt:
        stop.set()
    except Exception as exc:
        print(f"No se pudo ejecutar Arby: {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
