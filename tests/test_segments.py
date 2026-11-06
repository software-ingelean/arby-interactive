"""Offline protocol, per-sentence playback and model instruction tests."""
from concurrent.futures import CancelledError
import importlib
import json
from queue import Queue
import sys
import threading
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from libraries.arby_response import (
    EMOTION_COLORS, MAX_SEGMENTS, RESPONSE_SCHEMA, make_segment,
    make_reply, normalize_reply, parse_reply,
)
from libraries.arby_runtime import ArbyRuntime


def sample():
    return {"segments": [
        make_segment("Sí Luis, qué bueno verte.", "alegres"),
        make_segment("Eso me dejó pensando.", "pensativos"),
    ]}


class ControlledTTS:
    last_error = None

    def __init__(self):
        self.spoken = []
        self.started = Queue()
        self.gates = [threading.Event() for _ in range(8)]
        self.index = -1

    def speak(self, text):
        if self.index >= 0 and not self.gates[self.index].is_set():
            raise AssertionError("Utterances overlapped")
        self.index += 1
        self.spoken.append(text)
        self.started.put(self.index)
        return True

    def wait(self, timeout=None):
        return self.gates[self.index].wait(timeout)

    def stop(self):
        for gate in self.gates:
            gate.set()
        return True

    def close(self):
        self.stop()


class ProtocolTests(unittest.TestCase):
    def test_model_schema_is_an_array_of_full_metadata_segments(self):
        self.assertEqual(RESPONSE_SCHEMA["required"], ["segments"])
        items = RESPONSE_SCHEMA["properties"]["segments"]["items"]
        self.assertEqual(set(items["required"]), {"matrix_state", "strip_led", "response"})

    def test_parse_keeps_sentences_and_derives_full_text(self):
        reply = parse_reply(json.dumps(sample()))
        self.assertEqual(len(reply["segments"]), 2)
        self.assertEqual(reply["response"], "Sí Luis, qué bueno verte. Eso me dejó pensando.")
        self.assertEqual(reply["segments"][0]["response"], "Sí Luis, qué bueno verte.")

    def test_repeated_emotions_are_allowed(self):
        reply = normalize_reply({"segments": [make_segment("Hola.", "alegres"),
                                               make_segment("Qué gusto verte.", "alegres")]})
        self.assertEqual([s["matrix_state"] for s in reply["segments"]], ["alegres", "alegres"])

    def test_provider_rgb_is_canonicalized_but_custom_fixed_rgb_is_kept(self):
        raw = sample()
        raw["segments"][0]["strip_led"]["color"] = {"r": 1, "g": 2, "b": 3}
        self.assertEqual(parse_reply(json.dumps(raw))["segments"][0]["strip_led"]["color"],
                         {"r": 0, "g": 255, "b": 80})
        self.assertEqual(normalize_reply(raw)["segments"][0]["strip_led"]["color"],
                         {"r": 1, "g": 2, "b": 3})

    def test_legacy_input_is_supported_only_at_runtime_boundary(self):
        legacy = make_segment("Hola.", "alegres")
        self.assertEqual(len(normalize_reply(legacy)["segments"]), 1)
        with self.assertRaises(ValueError):
            parse_reply(json.dumps(legacy))

    def test_empty_or_excess_segments_and_invalid_last_segment_are_rejected(self):
        invalid = sample()
        invalid["segments"][1]["strip_led"]["color"]["r"] = True
        for reply in ({"segments": []}, {"segments": [make_segment("Hola.")] * (MAX_SEGMENTS+1)}, invalid):
            with self.subTest(reply=reply), self.assertRaises(ValueError):
                normalize_reply(reply)
        self.assertEqual(make_reply(" "), {"segments": [], "response": ""})

    def test_aggregate_text_is_rebuilt_and_cannot_add_hidden_spoken_content(self):
        raw = sample()
        raw["response"] = "A different full answer"
        self.assertNotIn("different", normalize_reply(raw)["response"])


class SegmentedRuntimeTests(unittest.TestCase):
    def create(self, reply):
        bot = Mock()
        bot.respond.return_value = reply
        tts = ControlledTTS()
        runtime = ArbyRuntime(bot, tts, emotion_colors=EMOTION_COLORS, minimum_display=0).start()
        self.addCleanup(runtime.close)
        return runtime, tts, bot

    def test_each_color_stays_until_its_audio_finishes_and_prints_only_once(self):
        runtime, tts, _ = self.create(sample())
        future = runtime.submit_text("Question")
        self.assertEqual(tts.started.get(timeout=1), 0)
        self.assertEqual(runtime.visual.matrix_state, "alegres")
        self.assertEqual(runtime.visual.color, (0, 255, 80))
        self.assertEqual(tts.spoken, ["Sí Luis, qué bueno verte."])
        tts.gates[0].set()
        self.assertEqual(tts.started.get(timeout=1), 1)
        self.assertEqual(runtime.visual.matrix_state, "pensativos")
        self.assertEqual(runtime.visual.color, (120, 60, 255))
        self.assertFalse(future.done())
        tts.gates[1].set()
        self.assertEqual(len(future.result(timeout=1)["segments"]), 2)
        runtime._queue.join()
        self.assertEqual(runtime.visual.matrix_state, "default")
        events = []
        while not runtime.events.empty():
            events.append(runtime.events.get_nowait())
        self.assertEqual(len([e for e in events if e[0] == "response"]), 1)
        self.assertEqual(tts.spoken, [s["response"] for s in sample()["segments"]])

    def test_invalid_later_segment_does_not_play_the_first(self):
        bad = sample()
        bad["segments"][1]["response"] = " "
        runtime, tts, _ = self.create(bad)
        with self.assertRaises(ValueError):
            runtime.submit_text("Question").result(timeout=1)
        self.assertEqual(tts.spoken, [])

    def test_shutdown_during_first_segment_cancels_remaining_segments(self):
        runtime, tts, _ = self.create(sample())
        future = runtime.submit_text("Question")
        tts.started.get(timeout=1)
        self.assertTrue(runtime.close(timeout=1))
        with self.assertRaises(CancelledError):
            future.result(timeout=1)
        self.assertEqual(tts.spoken, ["Sí Luis, qué bueno verte."])


class BotContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # SDK and retrieval are deliberately stubbed: no API/network/model load.
        knowledge_module = ModuleType("libraries.arby_knowledge")
        knowledge_module.KnowledgeStore = Mock()
        knowledge_module.normalize = lambda text: text.casefold().strip()
        with patch.dict(sys.modules, {"libraries.arby_knowledge": knowledge_module}):
            cls.module = importlib.import_module("libraries.arby_bot")

    def setUp(self):
        self.knowledge = SimpleNamespace(workers=[], instructions="", candidates=lambda text: [],
                                         search=lambda text, **kwargs: [])
        self.client = Mock()
        self.client.models.generate_content.return_value = SimpleNamespace(
            text=json.dumps(sample()), candidates=[])
        self.bot = self.module.ArbyBot(knowledge=self.knowledge, client=self.client)
        self.addCleanup(self.bot.close)

    def sdk_stub(self):
        class Struct:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)
        types = SimpleNamespace(Content=Struct, GenerateContentConfig=Struct,
                                Part=SimpleNamespace(from_text=lambda **kwargs: Struct(**kwargs)))
        google, genai = ModuleType("google"), ModuleType("google.genai")
        genai.types = types
        google.genai = genai
        return {"google": google, "google.genai": genai}

    def test_bot_uses_new_schema_natural_rule_and_preserves_history(self):
        with patch.dict(sys.modules, self.sdk_stub()):
            reply = self.bot.respond("Hola")
            self.bot.respond("Cuéntame más")
        self.assertEqual(len(reply["segments"]), 2)
        arguments = self.client.models.generate_content.call_args.kwargs
        self.assertEqual(arguments["config"].response_json_schema, RESPONSE_SCHEMA)
        instructions = arguments["config"].system_instruction
        self.assertIn("una sola oración completa", instructions)
        self.assertIn("Sí Luis, eso también me pasa", instructions)
        self.assertIn("No separes por", instructions)
        self.assertIn("segments", json.loads(self.bot._history[0][1]))

    def test_failure_is_segmented_and_not_stored(self):
        self.client.models.generate_content.side_effect = TimeoutError("test")
        with patch.dict(sys.modules, self.sdk_stub()):
            reply = self.bot.respond("Hola")
        self.assertEqual([s["matrix_state"] for s in reply["segments"]], ["pensativos", "duda"])
        self.assertFalse(self.bot._history)

    def test_empty_input_does_not_call_provider(self):
        self.assertEqual(self.bot.respond(" "), {"segments": [], "response": ""})
        self.client.models.generate_content.assert_not_called()


if __name__ == "__main__":
    unittest.main()
