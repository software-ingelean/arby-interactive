#!/usr/bin/env python3
"""TRIKI: prototipo táctil parlante basado en Trill Craft.
Requiere trill_lib y espeak-ng. Ejecutar en Raspberry Pi.
"""
import random
import shutil
import subprocess
import time
from collections import deque
from app.hardware.trill_lib import TrillLib

BUS = 1
ADDRESS = 0x30
THRESHOLD = 0.05  # ajustar segun electrodos y ambiente
RELEASE_THRESHOLD = 0.025
REQUIRED_SAMPLES = 2
POLL_INTERVAL = 0.05
TOUCH_HOLD_SECONDS = 2.5
COOLDOWN = 1.2

# Adaptar a los canales fisicos realmente conectados.
ZONES = {
    "cabeza": {0, 1, 2, 3},
    "barriga": {4, 5, 6, 7},
    "mano": {8, 9, 10, 11},
    "saludo": {12, 13},
    "ayuda": {14, 15},
}
PHRASES = {
    "cabeza": ["¡Ey! ¡Cuidado con el peinado!", "¡Tengo ideas brillantes, no me las despeines!", "¿Me estás tomando la temperatura?"],
    "barriga": ["¡Ja ja! ¡Eso me da cosquillas!", "¡Oye, tengo hambre de electricidad!", "¡Cosquillas no, por favor!"],
    "mano": ["¡Mucho gusto!", "¡Ese sí fue un buen saludo!", "¡Hola, humano! Qué gusto verte."],
    "saludo": ["¡Bienvenido! Soy Triki, el anfitrión de esta sala.", "¡Hola! ¿Primera vez por aquí? Soy Triki."],
    "ayuda": ["¡Claro! Puedes acercarte a recepción para solicitar información.", "Estoy aquí para acompañarte mientras esperas. El personal de recepción puede ayudarte con tu cita."],
    "repetido": ["¡Bueno, bueno! ¡Que me vas a desgastar!", "¡Me encanta la atención, pero con suavidad!"],
    "sostenido": ["¿Me estás dando un masaje o qué?", "¡Eh! ¡Ya puedes soltarme!"],
}


def zone_for(channel):
    for zone, channels in ZONES.items():
        if channel in channels:
            return zone
    return None


class Voice:
    def __init__(self):
        if not shutil.which("espeak-ng"):
            raise RuntimeError("Instala el sintetizador: sudo apt install espeak-ng")
        self.proc = None

    def speak(self, text):
        if self.proc is not None and self.proc.poll() is None:
            return False
        print("TRIKI:", text, flush=True)
        self.proc = subprocess.Popen(["espeak-ng", "-v", "es-419", "-s", "145", "-p", "48", text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True

    def busy(self):
        return self.proc is not None and self.proc.poll() is None

    def close(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()


def read_channel(sensor, channel):
    try:
        return float(sensor.getRawData(channel))
    except (AttributeError, TypeError):
        return float(sensor.rawData[channel])


def main():
    voice = Voice()
    sensor = TrillLib(BUS, "craft", ADDRESS)
    sensor.setMode("DIFF")
    sensor.setPrescaler(6)
    sensor.setNoiseThreshold(0.01)
    print("No toques los electrodos: calibrando baseline...")
    time.sleep(1)
    sensor.updateBaseLine()
    time.sleep(0.5)
    print("Listo. Toca las zonas del personaje. Ctrl+C para salir.")

    active_channel = None
    candidate = None
    candidate_samples = 0
    start_touch = 0.0
    held_announced = False
    last_spoken = 0.0
    recent_touches = deque()
    last_phrase = {}

    def say(kind):
        nonlocal last_spoken
        choices = [p for p in PHRASES[kind] if p != last_phrase.get(kind)]
        if not choices:
            choices = PHRASES[kind]
        phrase = random.choice(choices)
        if voice.speak(phrase):
            last_phrase[kind] = phrase
            last_spoken = time.monotonic()

    try:
        while True:
            sensor.readTrill()
            values = [read_channel(sensor, i) for i in range(30)]
            ch = max(range(30), key=lambda i: values[i])
            strongest = values[ch]
            now = time.monotonic()

            # Histeresis para evitar que el ruido genere nuevos toques.
            if active_channel is not None:
                if values[active_channel] < RELEASE_THRESHOLD:
                    active_channel = None
                    candidate = None
                    candidate_samples = 0
                elif not held_announced and now - start_touch > TOUCH_HOLD_SECONDS:
                    held_announced = True
                    if not voice.busy() and now - last_spoken > COOLDOWN:
                        say("sostenido")
            elif strongest >= THRESHOLD:
                if candidate == ch:
                    candidate_samples += 1
                else:
                    candidate, candidate_samples = ch, 1
                if candidate_samples >= REQUIRED_SAMPLES:
                    active_channel = ch
                    start_touch = now
                    held_announced = False
                    zone = zone_for(ch)
                    print(f"Canal {ch} / zona {zone or 'sin asignar'} / valor {strongest:.3f}")
                    if zone and now - last_spoken >= COOLDOWN and not voice.busy():
                        recent_touches.append(now)
                        while recent_touches and now - recent_touches[0] > 10:
                            recent_touches.popleft()
                        say("repetido" if len(recent_touches) >= 4 else zone)
            else:
                candidate = None
                candidate_samples = 0

            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        print("\nTRIKI apagado.")
    finally:
        voice.close()


if __name__ == "__main__":
    main()
