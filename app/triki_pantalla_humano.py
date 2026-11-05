#!/usr/bin/env python3
"""TRIKI v2 - rostro mas humano y expresivo para Raspberry Pi con Trill Craft.
Teclas: 1..5 simular zonas, F1 diagnostico, F2 pantalla completa, C recalibrar, ESC salir.
"""
import json
import math
import os
import random
import subprocess
import tempfile
import time
from collections import deque
from pathlib import Path

import pygame

try:
    from app.hardware.trill_lib import TrillLib
except ImportError:
    TrillLib = None

BASE = Path(__file__).resolve().parents[1]
CONFIG_PATH = BASE / "config" / "triki_config.json"
DEFAULTS = {
    "i2c_bus": 1,
    "i2c_address": "0x30",
    "prescaler": 6,
    "noise_threshold": 0.01,
    "touch_threshold": 0.05,
    "release_threshold": 0.025,
    "poll_seconds": 0.05,
    "hold_seconds": 2.5,
    "voice_language": "es",
    "voice_speed": 145,
    "fullscreen": True,
    "demo_without_sensor": False,
    "zones": {
        "cabeza": [0, 1, 2, 3],
        "barriga": [4, 5, 6, 7],
        "mano": [8, 9, 10, 11],
        "saludo": [12, 13],
        "ayuda": [14, 15],
    },
}

PHRASES = {
    "cabeza": [
        "¡Ey! ¡Cuidado con el peinado!",
        "¡Me acabas de revolver las ideas!",
        "¡Mi cabeza también necesita respeto!",
    ],
    "barriga": [
        "¡Ja, ja! ¡Eso me da cosquillas!",
        "¡Oye, tengo hambre de electricidad!",
        "¡No sabía que mi panza era tan sensible!",
    ],
    "mano": [
        "¡Mucho gusto!",
        "¡Hola, humano! Qué gusto verte.",
        "¡Encantado de saludarte!",
    ],
    "saludo": [
        "¡Bienvenido! Soy TRIKI, el anfitrión de esta sala.",
        "¡Hola! Me alegra verte por aquí.",
        "¡Hola! Puedes tocarme si quieres interactuar conmigo.",
    ],
    "ayuda": [
        "Si necesitas información de tu visita, el equipo de recepción puede ayudarte.",
        "¿Tienes una cita? Consulta con recepción para confirmar tu llegada.",
        "Si estás esperando a alguien, puedo hacerte la espera más entretenida.",
    ],
    "repetido": [
        "¡Oye, oye! ¡Con suavidad!",
        "¡Me gusta jugar, pero no soy un tambor!",
        "¡Ya entendí, ya entendí!",
    ],
    "sostenido": [
        "¿Me estás haciendo un masaje?",
        "¡Ya puedes soltarme, gracias!",
        "Mmm… eso ya es demasiado cariño.",
    ],
}

EXPRESSIONS = {
    "cabeza": "sorpresa",
    "barriga": "risa",
    "mano": "feliz",
    "saludo": "feliz",
    "ayuda": "atento",
    "repetido": "molesto",
    "sostenido": "molesto",
}

PALETTE = {
    "bg1": (10, 18, 32),
    "bg2": (20, 37, 66),
    "panel": (27, 43, 74),
    "panel2": (35, 57, 96),
    "cyan": (77, 232, 236),
    "cyan2": (112, 247, 255),
    "white": (241, 248, 255),
    "ink": (11, 19, 34),
    "pupil": (36, 88, 109),
    "lip": (242, 125, 162),
    "tongue": (233, 101, 144),
    "blush": (255, 120, 164),
    "subtle": (148, 170, 194),
    "warn": (255, 167, 126),
}

FACE_PRESETS = {
    "feliz": dict(
        eye_open=1.0, brow_l=0.18, brow_r=-0.18, smile=0.95,
        mouth_open=0.10, pupil=0.95, blush=0.25, eyelid=0.08
    ),
    "atento": dict(
        eye_open=1.02, brow_l=0.05, brow_r=-0.05, smile=0.45,
        mouth_open=0.06, pupil=0.92, blush=0.12, eyelid=0.03
    ),
    "sorpresa": dict(
        eye_open=1.28, brow_l=-0.18, brow_r=0.18, smile=0.15,
        mouth_open=0.70, pupil=0.55, blush=0.05, eyelid=-0.03
    ),
    "risa": dict(
        eye_open=0.62, brow_l=0.28, brow_r=-0.28, smile=1.18,
        mouth_open=0.48, pupil=0.82, blush=0.40, eyelid=0.25
    ),
    "molesto": dict(
        eye_open=0.50, brow_l=-0.42, brow_r=0.42, smile=-0.58,
        mouth_open=0.12, pupil=0.85, blush=0.02, eyelid=0.34
    ),
}


def clamp(value, low, high):
    return max(low, min(high, value))


def lerp(a, b, t):
    return a + (b - a) * t


def ease(current, target, rate, dt):
    # Suavizado exponencial estable, ideal para transiciones orgánicas.
    alpha = 1.0 - math.exp(-rate * dt)
    return current + (target - current) * alpha


class TrillReader:
    def __init__(self, cfg):
        self.cfg = cfg
        self.sensor = None
        self.error = None
        self.last_values = [0.0] * 30
        if cfg["demo_without_sensor"]:
            return
        if TrillLib is None:
            self.error = "Falta la libreria trill_lib; habilita modo demo para probar."
            return
        try:
            address = int(str(cfg["i2c_address"]), 0)
            sensor = TrillLib(cfg["i2c_bus"], "craft", address)
            sensor.setMode("DIFF")
            sensor.setPrescaler(cfg["prescaler"])
            sensor.setNoiseThreshold(cfg["noise_threshold"])
            self.sensor = sensor
            self.calibrate()
        except Exception as exc:
            self.error = f"Error de sensor: {exc}"
            self.sensor = None

    def calibrate(self):
        if self.sensor:
            self.sensor.updateBaseLine()

    def read(self):
        if self.sensor is None:
            return self.last_values
        try:
            self.sensor.readTrill()
            vals = []
            for idx in range(30):
                try:
                    val = float(self.sensor.getRawData(idx))
                except (AttributeError, TypeError):
                    val = float(self.sensor.rawData[idx])
                vals.append(max(0.0, val))
            self.last_values = vals
            self.error = None
        except Exception as exc:
            self.error = f"Lectura I2C: {exc}"
            self.last_values = [0.0] * 30
        return self.last_values


class Speech:
    def __init__(self, cfg):
        self.cfg = cfg
        self.sounds = {}
        self.channel = None
        self.error = None
        self.tmp = tempfile.TemporaryDirectory(prefix="triki_audio_")
        self.ready = pygame.mixer.get_init() is not None
        if not self.ready:
            self.error = "Audio no disponible: revisa salida de sonido."
            return
        import shutil
        if not shutil.which("espeak-ng"):
            self.error = "Instala espeak-ng: sudo apt install espeak-ng"
            return
        for kind, phrases in PHRASES.items():
            for i, phrase in enumerate(phrases):
                output = str(Path(self.tmp.name) / f"{kind}_{i}.wav")
                result = subprocess.run(
                    [
                        "espeak-ng", "-v", cfg["voice_language"], "-s", str(cfg["voice_speed"]),
                        "-w", output, phrase,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    timeout=15,
                    check=False,
                )
                if result.returncode == 0 and os.path.exists(output):
                    try:
                        self.sounds[(kind, i)] = pygame.mixer.Sound(output)
                    except pygame.error as exc:
                        self.error = f"Error al cargar WAV: {exc}"
                else:
                    self.error = "No fue posible sintetizar la voz. Prueba otra voz de espeak-ng."
        self.channel = pygame.mixer.Channel(0)

    def busy(self):
        return bool(self.channel and self.channel.get_busy())

    def speak(self, kind, index):
        sound = self.sounds.get((kind, index))
        if not sound or self.busy():
            return False
        self.channel.play(sound)
        return True

    def close(self):
        if self.channel:
            self.channel.stop()
        self.sounds.clear()
        self.tmp.cleanup()


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

        channel = max(range(30), key=lambda i: values[i])
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


class FaceRig:
    def __init__(self):
        self.state = dict(FACE_PRESETS["feliz"])
        self.target = dict(FACE_PRESETS["feliz"])
        self.mood_name = "feliz"
        self.look_x = 0.0
        self.look_y = 0.0
        self.look_tx = 0.0
        self.look_ty = 0.0
        self.next_look_change = 0.0
        self.breath = 0.0
        self.blink_until = 0.0
        self.next_blink = 0.0

    def set_mood(self, name):
        self.mood_name = name
        self.target = dict(FACE_PRESETS[name])

    def update(self, now, dt, speaking):
        # respiracion / flotacion suave
        self.breath = math.sin(now * 1.7) * 1.0

        if now >= self.next_blink:
            self.blink_until = now + random.uniform(0.10, 0.15)
            self.next_blink = now + random.uniform(2.4, 5.4)

        if now >= self.next_look_change:
            self.look_tx = random.uniform(-0.22, 0.22)
            self.look_ty = random.uniform(-0.10, 0.10)
            self.next_look_change = now + random.uniform(1.0, 2.3)

        self.look_x = ease(self.look_x, self.look_tx, 2.8, dt)
        self.look_y = ease(self.look_y, self.look_ty, 2.4, dt)

        for key, target in self.target.items():
            self.state[key] = ease(self.state[key], target, 7.0, dt)

        # al hablar, la boca nunca queda estática
        if speaking:
            talk = 0.35 + 0.55 * (0.5 + 0.5 * math.sin(now * 13.5))
            self.state["mouth_open"] = max(self.state["mouth_open"], talk)
            self.state["smile"] = max(self.state["smile"], 0.15)

    def is_blinking(self, now):
        return now < self.blink_until


def load_config():
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULTS, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    provided = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    cfg = dict(DEFAULTS)
    cfg.update(provided)
    if cfg["release_threshold"] >= cfg["touch_threshold"]:
        raise ValueError("release_threshold debe ser menor que touch_threshold")
    for zone, channels in cfg["zones"].items():
        if zone not in ("cabeza", "barriga", "mano", "saludo", "ayuda"):
            raise ValueError(f"Zona no soportada: {zone}")
        if any(not isinstance(ch, int) or not 0 <= ch < 30 for ch in channels):
            raise ValueError(f"Canales invalidos en {zone}: {channels}")
    return cfg


def draw_text(screen, font, text, pos, color, center=True):
    surf = font.render(text, True, color)
    rect = surf.get_rect(center=pos) if center else surf.get_rect(topleft=pos)
    screen.blit(surf, rect)


def draw_background(screen, now):
    w, h = screen.get_size()
    screen.fill(PALETTE["bg1"])
    for i in range(8, 0, -1):
        radius = int((0.12 + i * 0.12) * min(w, h))
        alpha = 18 + i * 7
        color = tuple(int(lerp(PALETTE["bg1"][j], PALETTE["bg2"][j], i / 8)) for j in range(3))
        surf = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
        pygame.draw.circle(surf, (*color, alpha), (radius, radius), radius)
        x = int(w * 0.5 + math.sin(now * 0.21 + i) * 40 - radius)
        y = int(h * 0.36 + math.cos(now * 0.18 + i * 0.8) * 25 - radius)
        screen.blit(surf, (x, y))


def draw_face(screen, rig, now, speaking):
    w, h = screen.get_size()
    scale = min(w / 1000.0, h / 720.0)
    cx = w / 2
    cy = h * 0.43 + rig.breath * 2.4 * scale

    # Panel principal tipo holográfico
    panel = pygame.Rect(0, 0, int(660 * scale), int(470 * scale))
    panel.center = (cx, cy)
    shadow = panel.inflate(int(28 * scale), int(28 * scale))
    pygame.draw.rect(screen, (0, 0, 0, 0), shadow, border_radius=int(110 * scale))
    pygame.draw.rect(screen, PALETTE["panel"], panel, border_radius=int(110 * scale))
    pygame.draw.rect(screen, PALETTE["cyan"], panel, max(2, int(4 * scale)), border_radius=int(110 * scale))
    inner = panel.inflate(int(-30 * scale), int(-26 * scale))
    pygame.draw.rect(screen, PALETTE["panel2"], inner, border_radius=int(90 * scale))

    # Cabeza / contorno facial
    head = pygame.Rect(0, 0, int(470 * scale), int(330 * scale))
    head.center = (cx, cy + 6 * scale)
    head_surface = pygame.Surface(head.size, pygame.SRCALPHA)
    pygame.draw.ellipse(head_surface, (242, 248, 255, 238), head_surface.get_rect())
    pygame.draw.ellipse(head_surface, (223, 235, 248, 90), head_surface.get_rect().inflate(-14, -16), 0)
    screen.blit(head_surface, head.topleft)

    # Mejillas
    blush_alpha = int(140 * clamp(rig.state["blush"], 0, 1))
    for sign in (-1, 1):
        blush = pygame.Surface((int(85 * scale), int(52 * scale)), pygame.SRCALPHA)
        pygame.draw.ellipse(blush, (*PALETTE["blush"], blush_alpha), blush.get_rect())
        screen.blit(blush, (cx + sign * 118 * scale - blush.get_width() / 2, cy + 45 * scale))

    # Ojos y cejas
    eye_dx = 108 * scale
    eye_y = cy - 34 * scale
    eye_w = 108 * scale
    base_eye_h = 92 * scale
    open_factor = 0.05 if rig.is_blinking(now) else clamp(rig.state["eye_open"], 0.1, 1.35)
    eye_h = base_eye_h * open_factor

    # Cejas
    brow_y = eye_y - 63 * scale
    for sign, brow_tilt in ((-1, rig.state["brow_l"]), (1, rig.state["brow_r"])):
        bx = cx + sign * eye_dx
        length = 102 * scale
        dy = brow_tilt * 38 * scale
        x1 = bx - length / 2
        x2 = bx + length / 2
        y1 = brow_y - dy
        y2 = brow_y + dy
        pygame.draw.line(screen, PALETTE["ink"], (x1, y1), (x2, y2), max(4, int(10 * scale)))

    for sign in (-1, 1):
        ex = cx + sign * eye_dx
        eye_rect = pygame.Rect(0, 0, int(eye_w), int(max(10, eye_h)))
        eye_rect.center = (ex, eye_y)
        pygame.draw.ellipse(screen, PALETTE["white"], eye_rect)
        pygame.draw.ellipse(screen, (209, 221, 237), eye_rect, max(1, int(2 * scale)))

        # Parpado superior suave
        lid_amount = clamp(rig.state["eyelid"], -0.15, 0.55)
        lid_h = max(4, int((0.20 + lid_amount) * eye_rect.height))
        lid_rect = pygame.Rect(eye_rect.left - 2, eye_rect.top - 2, eye_rect.width + 4, lid_h)
        pygame.draw.ellipse(screen, (232, 240, 250), lid_rect)

        # Pupila / iris con micro mirada
        iris_r = 18 * scale * rig.state["pupil"] + 9 * scale
        px = ex + rig.look_x * 20 * scale
        py = eye_y + rig.look_y * 12 * scale
        pygame.draw.circle(screen, PALETTE["pupil"], (int(px), int(py)), int(iris_r))
        pygame.draw.circle(screen, PALETTE["ink"], (int(px), int(py)), int(iris_r * 0.55))
        pygame.draw.circle(screen, PALETTE["white"], (int(px - iris_r * 0.28), int(py - iris_r * 0.28)), max(2, int(iris_r * 0.23)))

    # Nariz mínima
    nose_y = cy + 8 * scale
    pygame.draw.line(screen, (192, 206, 222), (cx, nose_y - 14 * scale), (cx - 2 * scale, nose_y + 12 * scale), max(1, int(3 * scale)))
    pygame.draw.arc(screen, (192, 206, 222), (cx - 16 * scale, nose_y + 8 * scale, 22 * scale, 13 * scale), 0.1, 2.9, max(1, int(2 * scale)))

    # Boca humana simplificada
    mouth_cy = cy + 98 * scale
    mouth_w = 128 * scale + max(0, rig.state["smile"]) * 44 * scale
    smile = clamp(rig.state["smile"], -1.0, 1.2)
    mouth_open = clamp(rig.state["mouth_open"], 0.02, 1.0)
    lip_thick = max(2, int(4 * scale))

    if smile >= -0.05:
        top_rect = pygame.Rect(cx - mouth_w / 2, mouth_cy - 24 * scale, mouth_w, 66 * scale)
        start = math.pi * (0.12 + 0.08 * (1 - clamp(smile, 0, 1.2)))
        end = math.pi * (0.88 - 0.08 * (1 - clamp(smile, 0, 1.2)))
        pygame.draw.arc(screen, PALETTE["ink"], top_rect, start, end, lip_thick)
        if mouth_open > 0.08:
            open_h = 16 * scale + 42 * scale * mouth_open
            inner = pygame.Rect(cx - mouth_w * 0.34, mouth_cy - 2 * scale, mouth_w * 0.68, open_h)
            pygame.draw.ellipse(screen, PALETTE["ink"], inner)
            tongue = pygame.Rect(inner.left + inner.width * 0.18, inner.top + inner.height * 0.46, inner.width * 0.64, inner.height * 0.42)
            pygame.draw.ellipse(screen, PALETTE["tongue"], tongue)
            # labio superior
            pygame.draw.arc(screen, PALETTE["lip"], top_rect.inflate(-8, -5), start, end, max(2, int(2 * scale)))
    else:
        frown = pygame.Rect(cx - mouth_w / 2, mouth_cy + 2 * scale, mouth_w, 58 * scale)
        pygame.draw.arc(screen, PALETTE["ink"], frown, 0.15, math.pi - 0.15, lip_thick)

    # Resplandor si está hablando
    if speaking:
        halo_r = int((240 + 20 * math.sin(now * 8)) * scale)
        halo = pygame.Surface((halo_r * 2, halo_r * 2), pygame.SRCALPHA)
        pygame.draw.circle(halo, (*PALETTE["cyan2"], 22), (halo_r, halo_r), halo_r)
        screen.blit(halo, (int(cx - halo_r), int(cy - halo_r - 10 * scale)))


def main():
    cfg = load_config()
    pygame.mixer.pre_init(22050, -16, 1, 512)
    pygame.init()
    flags = pygame.FULLSCREEN if cfg["fullscreen"] else pygame.RESIZABLE
    screen = pygame.display.set_mode((1000, 720), flags)
    pygame.display.set_caption("TRIKI v2 - anfitrión interactivo")
    pygame.mouse.set_visible(not cfg["fullscreen"])

    font_title = pygame.font.SysFont("dejavusans", 36, bold=True)
    font_body = pygame.font.SysFont("dejavusans", 29)
    font_small = pygame.font.SysFont("dejavusans", 19)
    clock = pygame.time.Clock()

    reader = TrillReader(cfg)
    speech = Speech(cfg)
    detector = TouchDetector(cfg)
    rig = FaceRig()

    subtitle = "¡Hola! Soy TRIKI. Tócame para interactuar conmigo."
    mood_name = "feliz"
    mood_until = 0.0
    last_spoken = -999.0
    previous_index = {}
    debug = False
    next_read = 0.0
    last_loop = time.monotonic()
    running = True

    def wrap_text(text, font, max_width):
        words = text.split()
        lines, line = [], ""
        for word in words:
            proposal = f"{line} {word}".strip()
            if font.size(proposal)[0] > max_width and line:
                lines.append(line)
                line = word
            else:
                line = proposal
        if line:
            lines.append(line)
        return lines[:3]

    def react(kind, channel=None):
        nonlocal subtitle, mood_name, mood_until, last_spoken
        now = time.monotonic()
        mood_name = EXPRESSIONS[kind]
        rig.set_mood(mood_name)
        mood_until = now + 3.5
        choices = [i for i in range(len(PHRASES[kind])) if i != previous_index.get(kind)]
        idx = random.choice(choices or list(range(len(PHRASES[kind]))))
        subtitle = PHRASES[kind][idx]
        if now - last_spoken >= 1.0 and speech.speak(kind, idx):
            last_spoken = now
            previous_index[kind] = idx
        print(f"Evento {kind} / canal {channel}: {subtitle}", flush=True)

    try:
        while running:
            now = time.monotonic()
            dt = max(0.001, min(0.05, now - last_loop))
            last_loop = now

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key == pygame.K_F1:
                        debug = not debug
                    elif event.key == pygame.K_F2:
                        cfg["fullscreen"] = not cfg["fullscreen"]
                        flags = pygame.FULLSCREEN if cfg["fullscreen"] else pygame.RESIZABLE
                        screen = pygame.display.set_mode((1000, 720), flags)
                        pygame.mouse.set_visible(not cfg["fullscreen"])
                    elif event.key == pygame.K_c:
                        reader.calibrate()
                        subtitle = "Sensor recalibrado."
                    elif pygame.K_1 <= event.key <= pygame.K_5:
                        react(["cabeza", "barriga", "mano", "saludo", "ayuda"][event.key - pygame.K_1])

            if now >= next_read:
                values = reader.read()
                for kind, channel in detector.update(values, now):
                    react(kind, channel)
                next_read = now + cfg["poll_seconds"]

            if now > mood_until and not speech.busy() and mood_name != "feliz":
                mood_name = "feliz"
                rig.set_mood("feliz")

            rig.update(now, dt, speech.busy())

            draw_background(screen, now)
            draw_face(screen, rig, now, speech.busy())

            w, h = screen.get_size()
            draw_text(screen, font_title, "TRIKI", (w // 2, int(h * 0.08)), PALETTE["cyan2"])
            draw_text(screen, font_small, "Asistente interactivo · Sala de espera", (w // 2, int(h * 0.125)), PALETTE["subtle"])

            bubble = pygame.Rect(int(w * 0.15), int(h * 0.78), int(w * 0.70), int(h * 0.14))
            bubble_surf = pygame.Surface((bubble.width, bubble.height), pygame.SRCALPHA)
            pygame.draw.rect(bubble_surf, (13, 23, 42, 210), bubble_surf.get_rect(), border_radius=28)
            pygame.draw.rect(bubble_surf, (*PALETTE["cyan"], 180), bubble_surf.get_rect(), 2, border_radius=28)
            screen.blit(bubble_surf, bubble.topleft)

            for i, line in enumerate(wrap_text(subtitle, font_body, bubble.width - 40)):
                draw_text(screen, font_body, line, (w // 2, bubble.top + 36 + i * 34), PALETTE["white"])

            status = f"Estado: {mood_name}"
            draw_text(screen, font_small, status, (w // 2, bubble.bottom + 20), PALETTE["subtle"])

            if reader.error:
                draw_text(screen, font_small, reader.error[:110], (w // 2, h - 18), PALETTE["warn"])
            elif speech.error:
                draw_text(screen, font_small, speech.error[:110], (w // 2, h - 18), PALETTE["warn"])

            if debug:
                vals = reader.last_values
                high = sorted(enumerate(vals), key=lambda p: p[1], reverse=True)[:8]
                draw_text(screen, font_small, "Canales fuertes: " + " | ".join(f"{ch}:{val:.3f}" for ch, val in high), (18, h - 60), PALETTE["subtle"], center=False)
                draw_text(screen, font_small, "F1 diagnostico · F2 pantalla · C baseline · 1-5 simular · ESC salir", (18, h - 36), PALETTE["subtle"], center=False)

            pygame.display.flip()
            clock.tick(30)
    finally:
        speech.close()
        pygame.quit()


if __name__ == "__main__":
    main()
