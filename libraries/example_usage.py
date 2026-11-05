"""Text-only example. Replace input/print with STT and TTS in your application."""
from arby_bot import ArbyBot


def main():
    with ArbyBot() as bot:
        while True:
            try:
                input_text = input("Tú: ")
            except (EOFError, KeyboardInterrupt):
                break
            if input_text.strip().casefold() == "salir":
                break
            if input_text.strip().casefold() == "reiniciar":
                bot.reset_session()
                continue
            output_text = bot.respond(input_text)
            if output_text:
                print("Arby:", output_text)


if __name__ == "__main__":
    main()
