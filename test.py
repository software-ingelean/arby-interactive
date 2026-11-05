from libraries.arby_bot import ArbyBot, BotConfig
from libraries.arby_tts import ArbyTTS, TTSConfig



tts = ArbyTTS(TTSConfig(ffplay_path=r"C:\ffmpeg\bin\ffplay.exe"))

bot = ArbyBot(
    config=BotConfig(model="gemini-3.1-flash-lite")
)


while True:
    text = input("Tú: ").strip()

    if text.lower() == "salir":
        break

    if text:
        response = bot.respond(text)
        print("Arby:", response)
        tts.speak(response)