"""Trill Craft input and automatic reactions, independent of pygame and Gemini."""
from collections import deque
import json
import math
from pathlib import Path
import random
import time

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "triki_config.json"

DEFAULTS = {'i2c_bus': 1,
 'i2c_address': '0x30',
 'prescaler': 6,
 'noise_threshold': 0.01,
 'touch_threshold': 0.05,
 'release_threshold': 0.025,
 'poll_seconds': 0.05,
 'hold_seconds': 2.5,
 'speech_cooldown_seconds': 1.2,
 'zones': {'cabeza': [0, 1, 2, 3],
           'barriga': [4, 5, 6, 7],
           'mano': [8, 9, 10, 11],
           'saludo': [12, 13],
           'ayuda': [14, 15]}}

PHRASES = {
    "cabeza": [
        "¡Uy! Casi me despeinas las hojas.",
        "¡Quiubo! Soy Arby, la planta de INGELEAN.",
        "Suavecito, que hoy sí me peiné.",
    ],
    "barriga": [
        "¡Uy! No sabía que las plantas tenían cosquillas.",
        "Con ese toque me hiciste parpadear.",
        "¡Ave María! Casi se me cae una hoja del susto.",
    ],
    "mano": [
        "¡Chóquela! Bueno, yo pongo la rama.",
        "¡Todo bien, todo bien! ¿Cómo vas?",
        "¡Buenas! Así sí da gusto saludar.",
    ],
    "saludo": [
        "¡Hola! Soy Arby. ¿Qué me cuentas?",
        "¡Quiubo! ¿Sabías que hay árboles que dan fruta en el tronco?",
        "Si te gusta el café, pregúntame por el Coffee Party Fest.",
    ],
    "ayuda": [
        "¿Quieres saber qué hacemos en INGELEAN? Pregúntame.",
        "Si buscas ideas para sembrar un frutal, te puedo contar de Arbilito Frutal.",
        "Si necesitas orientación con tu visita, el equipo te puede ayudar.",
    ],
    "repetido": [
        "¡Ya te sentí! Dame un segundito.",
        "Suave, que no soy botón de ascensor.",
        "Un toque a la vez, que hasta las plantas nos enredamos.",
    ],
    "sostenido": [
        "Listo, ya puedes soltarme.",
        "Pausa técnica. Hasta las plantas descansan.",
        "¿Me das un momentico para acomodar las hojas?",
    ],
}

class TouchDetector:
    def __init__(self, cfg):
        self.cfg = cfg
        self.active = None
        self.candidate = None
        self.samples = 0
        self.started = 0.0
        self.hold_sent = False
        self.recent = deque()
        self.mapping = {ch: zone for zone, channels in cfg["zones"].items() for ch in channels}

    def update(self, values, now):
        events = []
        threshold = self.cfg["touch_threshold"]
        release = self.cfg["release_threshold"]
        if self.active is not None:
            if values[self.active] < release:
                self.active = None
                self.candidate = None
                self.samples = 0
            elif not self.hold_sent and now - self.started > self.cfg["hold_seconds"]:
                self.hold_sent = True
                events.append(("sostenido", self.active))
            return events

        channel = max(self.mapping, key=lambda i: values[i])
        if values[channel] < threshold:
            self.candidate = None
            self.samples = 0
            return events

        if self.candidate == channel:
            self.samples += 1
        else:
            self.candidate, self.samples = channel, 1

        if self.samples >= 2:
            self.active = channel
            self.started = now
            self.hold_sent = False
            zone = self.mapping.get(channel)
            if zone:
                self.recent.append(now)
                while self.recent and now - self.recent[0] > 10:
                    self.recent.popleft()
                events.append(("repetido" if len(self.recent) >= 4 else zone, channel))
        return events


STATES = {"cabeza": "sorprendidos", "barriga": "alegres", "mano": "alegres",
          "saludo": "alegres", "ayuda": "pensativos", "repetido": "enojado",
          "sostenido": "enojado"}


def load_touch_config(path=CONFIG_PATH):
    cfg = dict(DEFAULTS)
    if Path(path).exists():
        cfg.update(json.loads(Path(path).read_text(encoding="utf-8")))
    for key in ("poll_seconds", "hold_seconds", "touch_threshold", "release_threshold",
                "speech_cooldown_seconds", "noise_threshold"):
        value = cfg[key]
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"Trill: {key} debe ser un número finito no negativo")
    if not 0 < cfg["release_threshold"] < cfg["touch_threshold"] <= 1:
        raise ValueError("Trill: requiere 0 < release_threshold < touch_threshold <= 1")
    if cfg["poll_seconds"] <= 0 or cfg["hold_seconds"] <= 0:
        raise ValueError("Trill: poll_seconds y hold_seconds deben ser positivos")
    channels = []
    for zone, assigned in cfg["zones"].items():
        if zone not in STATES or zone in ("sostenido", "repetido"):
            raise ValueError(f"Zona Trill no soportada: {zone}")
        if not isinstance(assigned, list) or any(type(ch) is not int or not 0 <= ch < 30 for ch in assigned):
            raise ValueError(f"Canales Trill inválidos en {zone}")
        channels.extend(assigned)
    if not channels or len(channels) != len(set(channels)):
        raise ValueError("Trill: configura canales sin duplicados en zones")
    address = int(str(cfg["i2c_address"]), 0)
    if not 0x30 <= address <= 0x38:
        raise ValueError("Trill Craft: dirección fuera de 0x30–0x38")
    return cfg


class TrillReader:
    """Open before matrix initialization can drop hardware privileges."""

    def __init__(self, cfg):
        from app.hardware.trill_lib import TrillLib
        self.sensor = None
        try:
            self.sensor = TrillLib(cfg["i2c_bus"], "craft", int(str(cfg["i2c_address"]), 0))
            for result in (self.sensor.setMode("DIFF"),
                           self.sensor.setPrescaler(cfg["prescaler"]),
                           self.sensor.setNoiseThreshold(cfg["noise_threshold"]),
                           self.sensor.updateBaseLine()):
                if result:
                    raise RuntimeError("No se pudo configurar Trill Craft")
        except BaseException as exc:
            self.close()
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            raise RuntimeError(f"No se pudo iniciar Trill Craft: {exc}") from exc

    def read(self):
        if self.sensor.readTrill():
            raise OSError("Lectura incompleta de Trill Craft")
        return [max(0.0, float(value)) for value in self.sensor.rawData[:30]]

    def close(self):
        if self.sensor is not None:
            self.sensor.bus.close()
            self.sensor = None


class TouchReactions:
    """Poll continuously; discard busy touches instead of queueing speech."""

    def __init__(self, reader, cfg):
        self.reader, self.cfg = reader, cfg
        self.detector = TouchDetector(cfg)
        self.next_read = 0.0
        self.ready_at = 0.0
        self.pending = None
        self.previous = {}
        self.last_touch = None

    def update(self, runtime, now):
        if self.pending is not None and self.pending.done():
            self.pending = None
            self.ready_at = now + self.cfg["speech_cooldown_seconds"]
        if now < self.next_read:
            return self.detector.active is not None
        self.next_read = now + self.cfg["poll_seconds"]
        events = self.detector.update(self.reader.read(), now)
        for kind, channel in events:
            self.last_touch = {"zone": kind, "channel": channel, "at": time.time()}
            if self.pending is not None or runtime.pending_count or now < self.ready_at:
                continue
            choices = [phrase for phrase in PHRASES[kind] if phrase != self.previous.get(kind)]
            phrase = random.choice(choices or PHRASES[kind])
            self.pending = runtime.submit_fixed_phrase(phrase, state=STATES[kind])
            self.previous[kind] = phrase
            runtime.events.put(("info", f"Toque {kind}, canal {channel}"))
        return self.detector.active is not None
