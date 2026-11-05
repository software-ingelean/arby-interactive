#!/usr/bin/env python3
"""Genera y reproduce muestras de voz para Triki."""

import argparse
import subprocess
import sys
import time
from pathlib import Path

import pygame


BASE = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE / "assets" / "muestras_voz"
DEFAULT_TEXT = "Hola, soy Arby, a Luis le van a tronar los cachetes de marrana flaca"

PROFILES = {
    "natural": ("es-CO-SalomeNeural", "+0%", "+0Hz"),
    "tierna": ("es-CO-SalomeNeural", "-8%", "+8Hz"),
    "dulce": ("es-CO-SalomeNeural", "-12%", "+15Hz"),
    "animada": ("es-CO-SalomeNeural", "+5%", "+10Hz"),
    "neutral_mx": ("es-MX-DaliaNeural", "-12%", "+15Hz"),
    "neutral_us": ("es-US-PalomaNeural", "-12%", "+15Hz"),
    "neutral_pe": ("es-PE-CamilaNeural", "-0%", "-0Hz"),
    "neutral_ec": ("es-EC-AndreaNeural", "-12%", "+15Hz"),
    "hombre_co": ("es-CO-GonzaloNeural", "-8%", "-20Hz"),
    "hombre_mx": ("es-MX-JorgeNeural", "-8%", "-20Hz"),
    "hombre_us": ("es-US-AlonsoNeural", "-8%", "-20Hz"),
    "hombre_pe": ("es-PE-AlexNeural", "-8%", "-20Hz"),
    "hombre_ec": ("es-EC-LuisNeural", "-8%", "-20Hz"),
}

NEUTRAL_PROFILES = ("neutral_pe", "natural" )
MALE_PROFILES = ("hombre_co", "hombre_mx", "hombre_us", "hombre_pe", "hombre_ec")
#"natural", "tierna", "dulce", "animada", 

def synthesize(name, text, voice, rate, pitch):
    OUTPUT_DIR.mkdir(exist_ok=True)
    output = OUTPUT_DIR / f"{name}.mp3"
    command = [
        sys.executable,
        "-m",
        "edge_tts",
        "--voice",
        voice,
        f"--rate={rate}",
        f"--pitch={pitch}",
        "--text",
        text,
        "--write-media",
        str(output),
        "--no-progress",
    ]
    for attempt in range(3):
        try:
            subprocess.run(command, check=True)
            break
        except subprocess.CalledProcessError:
            if attempt == 2:
                raise
            print("Edge TTS no entregó audio; reintentando...")
            time.sleep(1)
    return output


def play(path):
    if pygame.mixer.get_init() is None:
        pygame.mixer.init()
    pygame.mixer.music.load(path)
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        pygame.time.wait(100)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=PROFILES, default="tierna")
    parser.add_argument("--compare", action="store_true", help="prueba los cuatro perfiles")
    parser.add_argument(
        "--neutral-compare",
        action="store_true",
        help="compara cuatro voces femeninas más neutrales",
    )
    parser.add_argument(
        "--male-compare",
        action="store_true",
        help="compara cinco voces masculinas latinoamericanas",
    )
    parser.add_argument("--text", default=DEFAULT_TEXT, help="texto de la muestra")
    parser.add_argument("--voice", help="reemplaza la voz del perfil")
    parser.add_argument("--rate", help="reemplaza la velocidad, por ejemplo -8%%")
    parser.add_argument("--pitch", help="reemplaza el tono, por ejemplo +8Hz")
    parser.add_argument("--no-play", action="store_true", help="solo genera los MP3")
    parser.add_argument("--list-voices", action="store_true", help="lista las voces disponibles")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.list_voices:
        subprocess.run([sys.executable, "-m", "edge_tts", "--list-voices"], check=True)
        return

    if args.male_compare:
        names = list(MALE_PROFILES)
    elif args.neutral_compare:
        names = list(NEUTRAL_PROFILES)
    elif args.compare:
        names = ["natural", "tierna", "dulce", "animada"]
    else:
        names = [args.profile]
    for name in names:
        profile_voice, profile_rate, profile_pitch = PROFILES[name]
        voice = args.voice or profile_voice
        rate = args.rate or profile_rate
        pitch = args.pitch or profile_pitch
        print(f"\n{name}: {voice}, velocidad {rate}, tono {pitch}")
        output = synthesize(name, args.text, voice, rate, pitch)
        print(f"Muestra guardada en {output}")
        if not args.no_play:
            play(output)


if __name__ == "__main__":
    main()
