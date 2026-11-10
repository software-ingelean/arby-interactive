"""Coordinate the original cached Speech object with streamed ArbyTTS audio."""
import threading


class PlantSpeech:
    """Use this wrapper for ALL fixed/dynamic starts to prevent overlap.

    Keep calls involving the original Pygame Speech on the main UI thread.
    Send background Gemini results to that thread before calling speak_text().
    """
    def __init__(self, fixed_speech, dynamic_tts):
        self.fixed = fixed_speech
        self.tts = dynamic_tts
        self._lock = threading.RLock()

    @property
    def sounds(self):
        return self.fixed.sounds

    @property
    def error(self):
        return self.fixed.error or self.tts.last_error

    @error.setter
    def error(self, value):
        self.fixed.error = value

    def busy(self):
        # Poll fixed.busy even during dynamic speech to update its cooldown.
        fixed_busy = self.fixed.busy()
        return fixed_busy or self.tts.is_speaking

    def ready(self):
        return not self.tts.is_speaking and self.fixed.ready()

    def speak(self, kind, index):
        with self._lock:
            if self.tts.is_speaking:
                return False
            return self.fixed.speak(kind, index)

    def speak_text(self, text):
        with self._lock:
            if self.fixed.busy():
                return False
            return self.tts.speak(text)

    def stop_dynamic(self):
        return self.tts.stop()

    def close(self):
        try:
            self.tts.close()
        finally:
            self.fixed.close()
