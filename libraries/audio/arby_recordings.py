"""Catálogo de frases y generación de grabaciones con la voz de Arby."""
from __future__ import annotations

import asyncio
from hashlib import sha256
import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from libraries.core.arby_response import clean_for_speech


RECORDINGS_DIR = Path(__file__).resolve().parents[2] / "assets" / "phrases"

REPEAT_QUESTION = "Perdón, no te escuché bien. ¿Me lo repites?"
SOUND_TEST = "Hola, soy Arby. Esta es una prueba de sonido."
BOT_ERROR = "Se me enredaron un poquito las ramas."
BOT_TRY_LATER = "¿Me lo repites en un momento?"
IDENTITY_CLARIFY = "Gracias por aclararlo. ¿Cómo prefieres que te llame?"
IDENTITY_CHOOSE = "¿Cuál de los nombres que te mencioné es el tuyo?"

EVENT_PHRASES = (
    "¡Holaaa! Soy Arby, el Árbol de la Felicidad. ¿Qué te hace sonreír hoy?",
    "Un pequeño descanso también es una forma de cuidarte. ¿Cómo te sientes hoy?",
    "¿Respiramos juntos? Inhala suave... y exhala. ¡Muy bien!",
    "¡Qué buena energía! Muévete a tu ritmo, disfruta y recuerda hidratarte.",
    "Así como las plantas necesitan cuidados, tú también mereces tiempo y cariño.",
    "Aquí se mezclan el café, las sonrisas y las buenas conversaciones.",
    "¡Qué alegría que estés aquí! La felicidad también crece cuando la compartimos.",
    "Me llaman el Árbol de la Felicidad. Mi secreto: crecer con calma y disfrutar lo simple.",
    "¿Sabías que la jabuticaba puede dar frutos directamente en su tronco?",
    "Gracias por visitarme. ¡Que hoy florezcan muchas cosas bonitas para ti!",
)


def recording_path(config, text):
    profile = (config.voice, config.rate, config.pitch, config.volume)
    key = json.dumps((*profile, text), ensure_ascii=False).encode("utf-8")
    return RECORDINGS_DIR / f"{sha256(key).hexdigest()}.mp3"


def phrases_to_record():
    from libraries.core.arby_ambient import INVITATIONS
    from libraries.core.arby_touch import PHRASES

    phrases = (
        REPEAT_QUESTION, SOUND_TEST, BOT_ERROR, BOT_TRY_LATER,
        IDENTITY_CLARIFY, IDENTITY_CHOOSE,
        *EVENT_PHRASES,
        *(action.text for action in INVITATIONS),
        *(phrase for group in PHRASES.values() for phrase in group),
    )
    return tuple(dict.fromkeys(map(clean_for_speech, phrases)))


async def record_phrases(config):
    import edge_tts

    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    phrases = phrases_to_record()
    print(f"Voz: {config.voice} | velocidad: {config.rate} | tono: {config.pitch}", flush=True)
    for index, text in enumerate(phrases, 1):
        target = recording_path(config, text)
        if target.is_file() and 0 < target.stat().st_size <= config.max_prefetch_bytes:
            continue
        with NamedTemporaryFile(dir=RECORDINGS_DIR, suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
        try:
            print(f"[{index}/{len(phrases)}] {text}", flush=True)
            tts = edge_tts.Communicate(text, config.voice, rate=config.rate,
                                       pitch=config.pitch, volume=config.volume)
            await asyncio.wait_for(tts.save(str(temporary)), config.timeout_seconds)
            if not 0 < temporary.stat().st_size <= config.max_prefetch_bytes:
                raise ValueError("El audio generado está vacío o excede el tamaño permitido.")
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    print(f"{len(phrases)} frases disponibles para reproducción local.", flush=True)


def main():
    from libraries.audio.arby_tts import TTSConfig
    from libraries.core.arby_env import load_environment
    from run_arby import load_config

    load_environment()
    settings = load_config()
    profile = {key: getattr(settings, key) for key in ("voice", "rate", "pitch")
               if getattr(settings, key) is not None}
    asyncio.run(record_phrases(TTSConfig(**profile)))


if __name__ == "__main__":
    main()
