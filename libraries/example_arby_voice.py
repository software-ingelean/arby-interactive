"""Place at your project root; put the new modules inside libraries/."""
from libraries.arby_bot import ArbyBot, BotConfig
from libraries.arby_tts import ArbyTTS


def main():
    with ArbyBot(config=BotConfig(model="gemini-3.1-flash-lite")) as bot, ArbyTTS() as tts:
        while True:
            try:
                text = input("Tú: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if text.casefold() == "salir":
                break
            if text.casefold() == "reiniciar":
                tts.stop()
                bot.reset_session()
                continue
            if not text:
                continue
            answer = bot.respond(text)
            print("Arby:", answer)
            if tts.speak(answer):
                try:
                    tts.wait()
                except KeyboardInterrupt:
                    tts.stop()
                if tts.last_error:
                    print("Error TTS:", tts.last_error)


if __name__ == "__main__":
    main()
