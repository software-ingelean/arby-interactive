"""Standalone audio test. Run from the folder containing arby_tts.py."""
from arby_tts import ArbyTTS


def main():
    with ArbyTTS() as tts:
        while True:
            try:
                text = input("Texto (salir para terminar): ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if text.lower() == "salir":
                break
            if tts.speak(text):
                try:
                    tts.wait()
                except KeyboardInterrupt:
                    tts.stop()
                print("Estado:", tts.last_status, "Error:", tts.last_error)
                print("Primer fragmento:", tts.first_chunk_seconds)


if __name__ == "__main__":
    main()
