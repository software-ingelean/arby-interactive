"""Offline logic/API-contract tests; no Gemini calls or model downloads."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
import numpy as np

from arby_bot import ArbyBot, BotConfig, clean_for_speech
from arby_knowledge import KnowledgeStore, build_index, normalize, parse_context

CONTEXT = Path(__file__).resolve().parent / "contexto_arby.md"


class FakeTokenizer:
    def encode(self, text, **kwargs):
        return text.split()

    def decode(self, tokens, **kwargs):
        return " ".join(tokens)


class FakeEncoder:
    model_name = "test-only"
    tokenizer = FakeTokenizer()

    def split_section(self, section):
        return [section]

    def encode(self, texts):
        return np.array([[1.0, float("Bombi" in t), float("frutales" in t)]
                         for t in texts], dtype="float32")


class BotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = TemporaryDirectory()
        cls.index = Path(cls.temp.name) / "index"
        build_index(CONTEXT, cls.index, embedding_model="test-only", encoder=FakeEncoder())

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.store = KnowledgeStore(CONTEXT, self.index, encoder=FakeEncoder())
        self.client = Mock()
        self.client.models.generate_content.return_value = SimpleNamespace(
            text="¡Hola! **Qué gusto** hablar contigo. 🌱", candidates=[])
        self.bot = ArbyBot(knowledge=self.store, client=self.client,
                           config=BotConfig(history_turns=2))

    def test_profiles_and_aliases(self):
        self.assertEqual(len(self.store.workers), 5)
        self.assertEqual(self.store.candidates("  BOMBI ")[0]["name"], "Juan Carlos Zuluaga")
        self.assertEqual(normalize("Jóhan"), "johan")

    def test_index_roundtrip(self):
        self.assertTrue(self.store.search("Bombi", min_score=-1))
        self.assertNotIn("Reconocimiento conversacional", " ".join(c["text"] for c in self.store.chunks))

    def test_confirmation_across_turns(self):
        self.assertIn("Juan Carlos", self.bot.respond("Soy Bombi"))
        self.assertIsNone(self.bot.confirmed_name)
        self.bot.respond("Sí")
        self.assertEqual(self.bot.confirmed_name, "Juan Carlos Zuluaga")
        self.client.models.generate_content.assert_not_called()

    def test_denial_and_reset(self):
        self.bot.respond("Steve")
        self.bot.respond("No")
        self.assertFalse(self.bot._pending)
        self.bot.respond("Soy Santi")
        self.bot.respond("Sí")
        self.bot.reset_session()
        self.assertIsNone(self.bot.confirmed_name)
        self.assertFalse(self.bot._history)

    def test_mention_not_identity(self):
        self.bot.respond("¿Dónde está Johan?")
        self.assertIsNone(self.bot.confirmed_name)
        self.assertFalse(self.bot._pending)

    def test_voice_and_history(self):
        self.assertEqual(self.bot.respond("Hola"), "¡Hola! Qué gusto hablar contigo.")
        self.bot.respond("¿Y tú?")
        args = self.client.models.generate_content.call_args.kwargs
        self.assertEqual([c.role for c in args["contents"]], ["user", "model", "user"])
        self.assertIn("planta de compañía", args["config"].system_instruction)
        self.assertNotIn("conocimiento_recuperado", self.bot._history[0][0])
        self.bot.respond("Cuéntame más")
        self.assertEqual(len(self.bot._history), 2)

    def test_current_profile_pinned(self):
        self.bot.respond("Luchoco")
        self.bot.respond("Sí")
        self.bot.respond("¿Qué sabes de mí?")
        self.assertIn("calistenia", str(self.client.models.generate_content.call_args))

    def test_failure_does_not_append_history(self):
        self.client.models.generate_content.side_effect = TimeoutError("test")
        self.assertIn("ramas", self.bot.respond("Hola"))
        self.assertEqual(self.bot.last_error, "TimeoutError")
        self.assertEqual(len(self.bot._history), 0)

    def test_empty_and_invalid_input(self):
        self.assertEqual(self.bot.respond("  "), "")
        with self.assertRaises(TypeError):
            self.bot.respond(None)
        with self.assertRaises(ValueError):
            self.bot.respond("x" * 4001)
        self.client.models.generate_content.assert_not_called()

    def test_close(self):
        self.bot.close()
        with self.assertRaises(RuntimeError):
            self.bot.respond("Hola")
        self.client.close.assert_not_called()  # Injected client belongs to caller.

    def test_changed_context_rejected(self):
        altered = Path(self.temp.name) / "changed.md"
        altered.write_bytes(CONTEXT.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "contexto cambió"):
            KnowledgeStore(altered, self.index, encoder=FakeEncoder())

    def test_clean_speech(self):
        self.assertEqual(clean_for_speech("**Hola**, [amigo](https://example.com) 🌱"), "Hola, amigo")

    def test_transcribed_introduction(self):
        self.assertIn("Juan Carlos", self.bot.respond("Hola, soy Bombi. ¿Cómo estás?"))
        self.bot.respond("Sí")
        self.assertEqual(self.bot.confirmed_name, "Juan Carlos Zuluaga")

    def test_unknown_identity_without_profile(self):
        self.bot.respond("Me llamo Pedro")
        self.assertEqual(self.bot.confirmed_name, "Pedro")
        self.assertEqual(self.bot._confirmed["text"], "")

    def test_non_name_statement(self):
        self.bot.respond("Soy feliz")
        self.assertIsNone(self.bot.confirmed_name)

    def test_multiple_alias_candidates(self):
        self.store.workers.append({**self.store.workers[0], "id": "another",
                                   "name": "Otra Persona", "aliases": ["Bombi"]})
        self.bot.respond("Bombi")
        self.bot.respond("Sí")
        self.assertIsNone(self.bot.confirmed_name)

    def test_truncated_response_not_stored(self):
        self.client.models.generate_content.return_value = SimpleNamespace(
            text="Esta frase quedó", candidates=[SimpleNamespace(finish_reason="MAX_TOKENS")])
        self.assertIn("ramas", self.bot.respond("Hola"))
        self.assertFalse(self.bot._history)


if __name__ == "__main__":
    unittest.main()
