"""Offline lifecycle tests and real ffplay decoding with SDL dummy audio."""
import asyncio
from pathlib import Path
import shutil
import subprocess
import threading
import unittest

from libraries.audio.arby_tts import ArbyTTS, TTSConfig
from libraries.audio.plant_speech import PlantSpeech


class QuietTTS(ArbyTTS):
    async def _play_stream(self, job, text, started):
        await asyncio.sleep(30)


class BrokenTTS(ArbyTTS):
    async def _play_stream(self, job, text, started):
        raise OSError("simulated")


@unittest.skipUnless(shutil.which("ffplay"), "ffplay not installed")
class TTSTests(unittest.TestCase):
    def make(self, cls=QuietTTS, **kwargs):
        tts = cls(stream_factory=lambda _: None, **kwargs)
        self.addCleanup(tts.close)
        return tts

    def test_empty_and_type(self):
        tts = self.make()
        self.assertFalse(tts.speak(" "))
        with self.assertRaises(TypeError):
            tts.speak(None)
        with self.assertRaises(ValueError):
            tts.speak("a" * 4001)

    def test_busy_and_cancel(self):
        tts = self.make()
        self.assertTrue(tts.speak("hola"))
        self.assertTrue(tts.is_speaking)
        self.assertFalse(tts.speak("segunda"))
        self.assertTrue(tts.stop())
        self.assertFalse(tts.is_speaking)
        self.assertEqual(tts.last_status, "cancelled")

    def test_interrupt_and_close(self):
        tts = self.make()
        tts.speak("primera")
        self.assertTrue(tts.speak("segunda", interrupt=True))
        tts.close()
        self.assertFalse(tts.is_speaking)
        with self.assertRaises(RuntimeError):
            tts.speak("cerrado")

    def test_error(self):
        tts = self.make(BrokenTTS)
        tts.speak("hola")
        self.assertTrue(tts.wait(2))
        self.assertEqual(tts.last_status, "failed")
        self.assertIn("OSError", tts.last_error)

    def test_timeout(self):
        tts = self.make(config=TTSConfig(timeout_seconds=0.05))
        tts.speak("hola")
        self.assertTrue(tts.wait(2))
        self.assertEqual(tts.last_status, "failed")

    def test_concurrent_starts(self):
        tts = self.make()
        results = []
        threads = [threading.Thread(target=lambda: results.append(tts.speak("hola")))
                   for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(results.count(True), 1)
        tts.stop()

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_real_ffplay_pipe(self):
        # Generate a tone in memory, stream MP3 packets, decode through ffplay.
        audio = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=0.6",
            "-ar", "24000", "-ac", "1", "-codec:a", "libmp3lame",
            "-b:a", "48k", "-f", "mp3", "pipe:1"],
            check=True, capture_output=True, timeout=10).stdout
        async def stream(_):
            yield {"type": "WordBoundary", "text": "ignored"}
            for offset in range(0, len(audio), 512):
                yield {"type": "audio", "data": audio[offset:offset + 512]}
                await asyncio.sleep(0.005)
        with ArbyTTS(TTSConfig(audio_driver="dummy", timeout_seconds=10),
                     stream_factory=stream) as tts:
            tts.speak("test tone")
            self.assertTrue(tts.wait(12))
            self.assertEqual(tts.last_status, "completed", tts.last_error)
            self.assertIsNotNone(tts.first_chunk_seconds)

    def test_no_audio(self):
        async def stream(_):
            yield {"type": "WordBoundary"}
        with ArbyTTS(TTSConfig(audio_driver="dummy"), stream_factory=stream) as tts:
            tts.speak("hola")
            self.assertTrue(tts.wait(5))
            self.assertEqual(tts.last_status, "failed")

    def test_cancel_real_player_while_waiting_for_audio(self):
        opened = threading.Event()
        async def stream(_):
            opened.set()
            await asyncio.sleep(30)
            yield {"type": "audio", "data": b"unused"}
        with ArbyTTS(TTSConfig(audio_driver="dummy"), stream_factory=stream) as tts:
            tts.speak("hola")
            self.assertTrue(opened.wait(3))
            self.assertTrue(tts.stop())
            self.assertEqual(tts.last_status, "cancelled")


class FakeFixed:
    def __init__(self):
        self.active = False
        self.error = None
        self.sounds = {("cabeza", 0): "cached"}

    def busy(self):
        return self.active

    def ready(self):
        return not self.active

    def speak(self, *_):
        if self.active:
            return False
        self.active = True
        return True

    def close(self):
        self.active = False


@unittest.skipUnless(shutil.which("ffplay"), "ffplay not installed")
class CoordinationTests(unittest.TestCase):
    def test_exclusion_both_directions(self):
        fixed = FakeFixed()
        with QuietTTS(stream_factory=lambda _: None) as tts:
            speech = PlantSpeech(fixed, tts)
            self.assertTrue(speech.speak("cabeza", 0))
            self.assertFalse(speech.speak_text("hola"))
            fixed.active = False
            self.assertTrue(speech.speak_text("hola"))
            self.assertFalse(speech.speak("cabeza", 0))
            self.assertFalse(speech.ready())
            self.assertTrue(speech.busy())
            self.assertEqual(speech.sounds[("cabeza", 0)], "cached")
            speech.close()


if __name__ == "__main__":
    unittest.main()
