"""Offline lifecycle tests and real ffplay decoding with SDL dummy audio."""
import asyncio
import os
from pathlib import Path
import shutil
import subprocess
import threading
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

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
    def test_real_ffplay_complete_phrase(self):
        # Generate mono MP3 chunks; play the complete phrase with real ffplay.
        audio = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=0.6",
            "-ar", "24000", "-ac", "1", "-codec:a", "libmp3lame",
            "-b:a", "48k", "-f", "mp3", "pipe:1"],
            check=True, capture_output=True, timeout=10).stdout
        synthesized = threading.Event()
        async def stream(_):
            yield {"type": "WordBoundary", "text": "ignored"}
            for offset in range(0, len(audio), 512):
                yield {"type": "audio", "data": audio[offset:offset + 512]}
                await asyncio.sleep(0.005)
            synthesized.set()
        with ArbyTTS(TTSConfig(audio_driver="dummy", timeout_seconds=10),
                     stream_factory=stream) as tts:
            tts.speak_segments(["test tone"], on_segment=lambda _: self.assertTrue(synthesized.is_set()))
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

    def test_cancel_synthesis_before_opening_player(self):
        opened = threading.Event()
        async def stream(_):
            opened.set()
            await asyncio.sleep(30)
            yield {"type": "audio", "data": b"unused"}
        with ArbyTTS(TTSConfig(audio_driver="dummy"), stream_factory=stream) as tts:
            tts.speak("hola")
            self.assertTrue(opened.wait(3))
            self.assertIsNone(tts._job.process)
            self.assertTrue(tts.stop())
            self.assertEqual(tts.last_status, "cancelled")

    @unittest.skipIf(os.name == "nt", "POSIX executable fixture")
    def test_repeated_stop_reaps_player_and_removes_audio(self):
        opened = threading.Event()
        folders = []
        def audio_directory(**kwargs):
            folder = TemporaryDirectory(**kwargs)
            folders.append(Path(folder.name))
            return folder
        async def stream(_):
            yield {"type": "audio", "data": b"complete audio"}
        with TemporaryDirectory() as folder:
            player = Path(folder) / "slow-player"
            player.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(30)\n")
            player.chmod(0o755)
            with patch('libraries.audio.arby_tts.TemporaryDirectory', side_effect=audio_directory):
                with ArbyTTS(TTSConfig(ffplay_path=str(player)), stream_factory=stream) as tts:
                    tts.speak_segments(["cancel playback"], on_segment=lambda _: opened.set())
                    self.assertTrue(opened.wait(3))
                    process = tts._job.process
                    self.assertIsNotNone(process)
                    self.assertTrue((folders[0] / "speech.mp3").is_file())
                    tts.stop(timeout=0)
                    tts.close()
                    tts.close()
                    self.assertTrue(tts.wait(0))
                    self.assertIsNotNone(process.returncode)
                    self.assertEqual(tts.last_status, "cancelled")
                    self.assertFalse(folders[0].exists())

    @unittest.skipIf(os.name == "nt", "POSIX executable fixture")
    def test_player_failure_reports_device_and_stderr(self):
        async def stream(_):
            await asyncio.sleep(0.2)
            yield {"type": "audio", "data": b"audio"}
        with TemporaryDirectory() as folder:
            player = Path(folder) / "failed-player"
            player.write_text(f"#!{sys.executable}\n"
                              "import os, sys\n"
                              "sys.stderr.write('ALSA: cannot open ' + os.environ['AUDIODEV'])\n"
                              "sys.exit(1)\n")
            player.chmod(0o755)
            config = TTSConfig(ffplay_path=str(player), audio_driver="alsa",
                               audio_device="plughw:CARD=Headphones,DEV=0")
            with ArbyTTS(config, stream_factory=stream) as tts:
                tts.speak("test")
                self.assertTrue(tts.wait(3))
                self.assertEqual(tts.last_status, "failed")
                self.assertIn("ALSA: cannot open plughw:CARD=Headphones,DEV=0", tts.last_error)
                self.assertIn("driver=alsa", tts.last_error)


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
