"""Silent speech adapter implementing the runtime TTS interface."""


class MutedTTS:
    last_error = None

    def speak(self, text):
        return True

    def wait(self, timeout=None):
        return True

    def stop(self):
        return True

    def close(self):
        pass
