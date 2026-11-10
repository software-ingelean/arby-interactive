"""Offline contracts for queueing, coordinated colors, cleanup and startup."""
from concurrent.futures import CancelledError
import sys
import threading
import unittest
from unittest.mock import patch

from libraries.core.arby_runtime import ArbyRuntime, validate_reply
from libraries.leds.arby_strip_led import LedStripController, StripConfig
from libraries.eyes.matrix_output import MatrixOutput
import run_arby
from libraries.simulation.arby_memory_pixels import MemoryPixels


PALETTE = {"alegres": (0, 255, 80), "enojado": (255, 0, 0)}


def make_reply(text="Hello", state="enojado"):
    r, g, b = PALETTE[state]
    return {"matrix_state": state, "strip_led": {
        "color": {"r": r, "g": g, "b": b}, "mood": state}, "response": text}


class FakeBot:
    def __init__(self):
        self.calls = []
        self.resets = 0
        self.closed = False

    def respond(self, text):
        self.calls.append(text)
        return make_reply(text)

    def reset_session(self):
        self.resets += 1

    def close(self):
        self.closed = True


class FakeTTS:
    last_error = None

    def __init__(self):
        self.spoken = []
        self.started = threading.Event()
        self.finished = threading.Event()
        self.finished.set()
        self.closed = False
        self.stops = 0

    def speak(self, text):
        self.spoken.append(text)
        self.started.set()
        return True

    def wait(self, timeout=None):
        return self.finished.wait(timeout)

    def stop(self):
        self.stops += 1
        self.finished.set()
        return True

    def close(self):
        self.closed = True


class RuntimeTests(unittest.TestCase):
    def create(self, bot=None, tts=None, **kwargs):
        bot, tts = bot or FakeBot(), tts or FakeTTS()
        runtime = ArbyRuntime(bot, tts, emotion_colors=PALETTE, minimum_display=0, **kwargs).start()
        self.addCleanup(runtime.close)
        return runtime, bot, tts

    def test_emotion_and_rgb_stay_active_until_playback_finishes(self):
        tts = FakeTTS()
        tts.finished.clear()
        runtime, bot, tts = self.create(tts=tts)
        future = runtime.submit_text("First turn")
        self.assertTrue(tts.started.wait(1))
        visual = runtime.visual
        self.assertEqual((visual.matrix_state, visual.color, visual.phase),
                         ("enojado", (255, 0, 0), "speaking"))
        self.assertFalse(future.done())
        tts.finished.set()
        self.assertEqual(future.result(timeout=1), validate_reply(make_reply("First turn")))
        runtime._queue.join()
        self.assertEqual(runtime.visual.matrix_state, "default")

    def test_fixed_phrase_is_serialized_and_bypasses_gemini(self):
        tts = FakeTTS()
        tts.finished.clear()
        runtime, bot, tts = self.create(tts=tts)
        first = runtime.submit_text("Question")
        self.assertTrue(tts.started.wait(1))
        fixed = runtime.submit_fixed_phrase("Touch phrase")
        self.assertEqual(tts.spoken, ["Question"])
        tts.finished.set()
        first.result(timeout=1)
        self.assertEqual(fixed.result(timeout=1)["response"], "Touch phrase")
        self.assertEqual(bot.calls, ["Question"])
        self.assertEqual(tts.spoken, ["Question", "Touch phrase"])

    def test_loading_is_visible_while_bot_blocks(self):
        entered, release = threading.Event(), threading.Event()
        bot = FakeBot()
        def respond(text):
            entered.set()
            if not release.wait(2):
                raise TimeoutError()
            return make_reply(text)
        bot.respond = respond
        runtime, _, _ = self.create(bot=bot)
        try:
            future = runtime.submit_text("Wait")
            self.assertTrue(entered.wait(1))
            self.assertEqual(runtime.visual.phase, "loading")
            self.assertEqual(runtime.visual.matrix_state, "cargando")
        finally:
            release.set()
        future.result(timeout=1)

    def test_reset_is_ordered_and_does_not_speak(self):
        runtime, bot, tts = self.create()
        runtime.reset_session().result(timeout=1)
        self.assertEqual(bot.resets, 1)
        self.assertEqual(tts.spoken, [])

    def test_bad_rgb_never_reaches_tts_and_worker_recovers(self):
        bot = FakeBot()
        good = make_reply()
        bad = make_reply()
        bad["strip_led"]["color"]["r"] = 999
        bot.respond = lambda text: bad if text == "bad" else good
        runtime, bot, tts = self.create(bot=bot)
        with self.assertRaises(ValueError):
            runtime.submit_text("bad").result(timeout=1)
        runtime.submit_text("good").result(timeout=1)
        self.assertEqual(tts.spoken, ["Hello"])

    def test_close_cancels_pending_and_prevents_late_speech(self):
        entered, release = threading.Event(), threading.Event()
        bot = FakeBot()
        def respond(text):
            entered.set()
            release.wait(2)
            return make_reply()
        bot.respond = respond
        runtime, bot, tts = self.create(bot=bot)
        active = runtime.submit_text("Active")
        self.assertTrue(entered.wait(1))
        queued = runtime.submit_fixed_phrase("Pending")
        self.assertFalse(runtime.close(timeout=0.01))
        self.assertTrue(queued.cancelled())
        release.set()
        self.assertTrue(runtime.close(timeout=1))
        with self.assertRaises(CancelledError):
            active.result(timeout=1)
        self.assertEqual(tts.spoken, [])
        self.assertTrue(bot.closed)
        self.assertTrue(tts.closed)

    def test_bounded_queue_rejects_excess_input(self):
        tts = FakeTTS()
        tts.finished.clear()
        runtime, _, _ = self.create(tts=tts, queue_size=1)
        active = runtime.submit_text("Active")
        self.assertTrue(tts.started.wait(1))
        waiting = runtime.submit_text("Waiting")
        with self.assertRaises(RuntimeError):
            runtime.submit_text("Excess")
        tts.finished.set()
        active.result(timeout=1)
        waiting.result(timeout=1)

    def test_invalid_mood_rejected(self):
        reply = make_reply()
        reply["strip_led"]["mood"] = "alegres"
        with self.assertRaises(ValueError):
            validate_reply(reply)


class FakePixels(MemoryPixels):
    def __init__(self, count):
        super().__init__(count)
        self.shown = 0
        self.deinitialized = False

    def show(self):
        self.shown += 1

    def deinit(self):
        self.deinitialized = True


class StripTests(unittest.TestCase):
    def test_rgb_brightness_and_cleanup(self):
        pixels = FakePixels(55)
        strip = LedStripController(pixels=pixels)
        strip.set_visual((255, 0, 0), "speaking", now=0)
        strip.update(0.2)
        self.assertEqual(pixels.values, [(255, 0, 0)] * 55)
        self.assertEqual(pixels.brightness, 0.2)
        strip.close()
        strip.close()
        self.assertEqual(pixels.values, [(0, 0, 0)] * 55)
        self.assertTrue(pixels.deinitialized)

    def test_expansion_supports_even_and_odd_strips(self):
        for count in (1, 2, 54, 55):
            for effect in ("center_out", "ripple"):
                pixels = FakePixels(count)
                strip = LedStripController(StripConfig(led_count=count, response_effect=effect), pixels=pixels)
                strip.set_visual((0, 255, 80), "speaking", now=0)
                for step in range(35):
                    strip.update(step * .04)
                    self.assertTrue(all(0 <= c <= 255 for rgb in pixels.values for c in rgb))
                strip.close()

    def test_loading_animation_moves_without_sleeping(self):
        pixels = FakePixels(55)
        strip = LedStripController(pixels=pixels)
        strip.set_visual((0, 255, 80), "loading", now=0)
        strip.update(0)
        before = list(pixels.values)
        strip.update(.4)
        self.assertNotEqual(before, pixels.values)
        strip.close()


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict("os.environ", {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.argv = patch.object(sys, "argv", ["run_arby.py"])
        self.argv.start()
        self.addCleanup(self.argv.stop)
        self.dotenv = patch.object(run_arby, "load_environment")
        self.dotenv.start()
        self.addCleanup(self.dotenv.stop)

    def test_typed_environment_settings(self):
        with patch.dict("os.environ", {"ARBY_BOT_TIMEOUT": "60", "ARBY_STRIP": "true",
                                      "ARBY_STRIP_LEDS": "82", "ARBY_EYES": "none",
                                      "GEMINI_MODEL": "test-model"}):
            config = run_arby.load_config()
        self.assertEqual(config.bot_timeout, 60)
        self.assertTrue(config.strip)
        self.assertEqual(config.strip_leds, 82)
        self.assertEqual(config.model, "test-model")
        self.assertEqual(config.eyes, "none")

    def test_invalid_environment_rejected_before_startup(self):
        for variable, values in {"ARBY_BOT_TIMEOUT": ("0", "-1", "nan", "inf"),
                                 "ARBY_STRIP": ("maybe",), "ARBY_EYES": ("invalid",),
                                 "ARBY_STRIP_LEDS": ("abc", "0")}.items():
            for value in values:
                with self.subTest(variable=variable, value=value), patch.dict("os.environ", {variable: value}):
                    with self.assertRaisesRegex(ValueError, variable):
                        run_arby.load_config()
                    with patch("builtins.print"):
                        self.assertEqual(run_arby.main(), 2)

    def test_arguments_rejected(self):
        with patch.object(sys, "argv", ["run_arby.py", "--eyes", "none"]), patch("builtins.print"):
            self.assertEqual(run_arby.main(), 2)

    def test_offline_console_drains_input_before_eof(self):
        with patch.dict("os.environ", {"ARBY_DEMO": "true", "ARBY_MUTE": "true", "ARBY_EYES": "none"}):
            with patch("builtins.input", side_effect=["enojado", "/frase Test", EOFError]), patch("builtins.print") as printer:
                code = run_arby.main()
        self.assertEqual(code, 0)
        messages = " ".join(str(call) for call in printer.call_args_list)
        self.assertIn("expresión enojado", messages)
        self.assertIn("Arby: Test", messages)

    def test_matrix_requires_confirmed_mapping(self):
        with patch.dict("os.environ", {"ARBY_EYES": "matrix"}):
            with self.assertRaisesRegex(ValueError, "ARBY_MULTIPLEXING"):
                run_arby.load_config()

    def test_matrix_rejects_conflicting_strip_gpio(self):
        with patch.dict("os.environ", {"ARBY_EYES": "matrix", "ARBY_MULTIPLEXING": "1",
                                      "ARBY_STRIP": "true", "ARBY_STRIP_GPIO": "18"}):
            with self.assertRaisesRegex(ValueError, "ARBY_STRIP_GPIO"):
                run_arby.load_config()

    def test_driver_disables_hardware_pulsing_for_shared_pwm(self):
        from types import SimpleNamespace
        class Canvas:
            pass
        class Matrix:
            def __init__(self, options):
                self.options = options
                self.width, self.height = 64, 32
            def CreateFrameCanvas(self):
                return Canvas()
            def Clear(self):
                pass
        driver = SimpleNamespace(RGBMatrix=Matrix, RGBMatrixOptions=SimpleNamespace)
        with patch.dict(sys.modules, {"rgbmatrix": driver}):
            output = MatrixOutput(multiplexing=1, disable_hardware_pulsing=True)
            self.assertTrue(output.matrix.options.disable_hardware_pulsing)
            output.close()


if __name__ == "__main__":
    unittest.main()
