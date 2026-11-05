#!/usr/bin/env python3
"""TRIKI v3 - avatar humano con Trill Craft para Raspberry Pi.
Teclas: 1..5 simular zonas, F1 diagnostico, F2 pantalla completa, C recalibrar, ESC salir.
"""
import json
import math
import os
import random
import subprocess
import tempfile
import shutil
import hashlib
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
    "voice_engine": "edge",
    "edge_voice": "es-CO-SalomeNeural",
    "edge_rate": "-0%",
    "edge_pitch": "+0Hz",
    "audio_device": "plughw:C10,0",
    "speech_cooldown_seconds": 1.2,
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
        "Santi, silencio",
        "Ay, qué rico que acaricies mis hojitas.",
        "Con esas caricias me dan ganas de florecer.",
        "Suavecito, mis hojitas son delicadas.",
    ],
    "barriga": [
        "Ji, ji, me haces cosquillitas.",
        "Un poquito de agua y cariño me hacen feliz.",
        "Con tanto cariño, voy a echar raíces aquí.",
    ],
    "mano": [
        "Hola, te regalo un saludito de mi ramita.",
        "Qué lindo tenerte cerquita.",
        "Estoy encantada de conocerte.",
    ],
    "saludo": [
        "Hola, soy Triki, tu plantita de compañía.",
        "Qué alegría verte. ¿Me acompañas un ratito?",
        "Acércate, puedes acariciar mis hojitas con suavidad.",
    ],
    "ayuda": [
        "Si necesitas ayuda con tu visita, en recepción te orientan con mucho gusto.",
        "¿Vienes a una cita? Puedes avisar en recepción que ya llegaste.",
        "Mientras esperas, me quedo aquí contigo.",
    ],
    "repetido": [
        "Despacito, que soy una plantita delicada.",
        "Me encantan las caricias suaves.",
        "Aquí estoy. Vamos con calma.",
    ],
    "sostenido": [
        "Qué bonito sentirte cerquita.",
        "Gracias por el cariño. ¿Me dejas descansar un poquito?",
        "Mis hojitas necesitan un descansito.",
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
    """Voz exclusiva: Edge TTS, sin cola, sin superposición y caché WAV."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.sounds = {}
        self.channel = None
        self.error = None
        self.last_end = -1e9
        self.was_busy = False
        self.cache = BASE / "assets" / "audio_triki"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.engine = cfg.get("voice_engine", "edge").lower()
        self.missing = []
        if pygame.mixer.get_init() is None:
            self.error = "Audio de Pygame no inicializado."
            return
        self.channel = pygame.mixer.Channel(0)
        if self.engine not in ("edge", "espeak"):
            self.error = f"Motor desconocido: {self.engine}"
            return
        if self.engine == "edge" and (not shutil.which("edge-tts") or not shutil.which("ffmpeg")):
            self.error = "Falta edge-tts o ffmpeg en este entorno. Activa ~/triki-venv."
            return
        if self.engine == "espeak" and not shutil.which("espeak-ng"):
            self.error = "No se encontro espeak-ng."
            return

        for kind, phrases in PHRASES.items():
            for i, phrase in enumerate(phrases):
                wav = self._wav_path(kind, i)
                try:
                    if not wav.is_file() or wav.stat().st_size < 128:
                        self._generate(phrase, wav)
                    self.sounds[(kind, i)] = pygame.mixer.Sound(str(wav))
                except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, pygame.error) as exc:
                    # No sustituir silenciosamente por una voz robotica.
                    if wav.exists() and wav.stat().st_size < 128:
                        wav.unlink()
                    detail = str(exc).replace("\n", " ")
                    self.missing.append((kind, i))
                    print(f"[TRIKI TTS] Error en {kind}[{i}]: {detail}", flush=True)
                    if not self.error:
                        self.error = f"Error de voz en {kind}: {detail[:105]}"
        print(f"[TRIKI TTS] Audios listos: {len(self.sounds)} de {sum(map(len, PHRASES.values()))}", flush=True)

    def _wav_path(self, kind, idx):
        phrase = PHRASES[kind][idx]
        key = f"{self.engine}|{self.cfg.get('edge_voice')}|{self.cfg.get('edge_rate')}|{self.cfg.get('edge_pitch', '+15Hz')}|{self.cfg.get('voice_speed')}|{phrase}"
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        return self.cache / f"{kind}_{idx}_{digest}.wav"

    def _generate(self, phrase, wav):
        temporary_wav = wav.with_name(wav.stem + ".tmp.wav")
        mp3 = wav.with_suffix(".mp3")
        for path in (temporary_wav, mp3):
            path.unlink(missing_ok=True)
        try:
            if self.engine == "edge":
                # Importante: usar --rate=-5% (en una sola cadena) para evitar
                # que argparse interprete '-5%' como otra opcion.
                rate = self.cfg.get("edge_rate", "-12%")
                pitch = self.cfg.get("edge_pitch", "+15Hz")
                command = ["edge-tts", "--voice", self.cfg.get("edge_voice", "es-PE-CamilaNeural"),
                           f"--rate={rate}", f"--pitch={pitch}", "--text", phrase, "--write-media", str(mp3)]
                self._run_checked(command, timeout=70)
                if not mp3.is_file() or mp3.stat().st_size < 128:
                    raise RuntimeError("Edge TTS no genero un MP3 valido")
                self._run_checked(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                                   "-i", str(mp3), "-ar", "22050", "-ac", "1", str(temporary_wav)], timeout=25)
            else:
                self._run_checked(["espeak-ng", "-v", self.cfg.get("voice_language", "es"),
                                   "-s", str(self.cfg.get("voice_speed", 145)),
                                   "-w", str(temporary_wav), phrase], timeout=20)
            if not temporary_wav.is_file() or temporary_wav.stat().st_size < 128:
                raise RuntimeError("No se genero un WAV valido")
            temporary_wav.replace(wav)
        finally:
            mp3.unlink(missing_ok=True)
            temporary_wav.unlink(missing_ok=True)

    @staticmethod
    def _run_checked(command, timeout):
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "fallo sin detalle").strip()
            raise RuntimeError(f"{command[0]} (codigo {result.returncode}): {detail[-500:]}")

    def busy(self):
        active = bool(self.channel and self.channel.get_busy())
        if self.was_busy and not active:
            self.last_end = time.monotonic()
        self.was_busy = active
        return active

    def ready(self):
        return (not self.busy()) and (
            time.monotonic() - self.last_end >= self.cfg.get("speech_cooldown_seconds", 1.2))

    def speak(self, kind, index):
        if not self.ready():
            return False
        sound = self.sounds.get((kind, index))
        if sound is None or self.channel is None:
            return False
        self.channel.play(sound)
        self.was_busy = True
        return True

    def close(self):
        if self.channel:
            self.channel.stop()
        self.sounds.clear()

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


def poly_curve(surface, color, points, width=3):
    """Dibuja una curva suave con puntos de control cuadraticos."""
    if len(points) < 3:
        return
    a,b,c = points[:3]
    out=[]
    for i in range(31):
        t=i/30
        out.append((int((1-t)**2*a[0]+2*(1-t)*t*b[0]+t*t*c[0]),
                    int((1-t)**2*a[1]+2*(1-t)*t*b[1]+t*t*c[1])))
    pygame.draw.lines(surface, color, False, out, max(1,int(width)))


def draw_face(screen, rig, now, speaking):
    """Avatar humano vectorial: busto, pelo, rostro, orejas, nariz, ojos y labios."""
    w,h=screen.get_size()
    # Dibuja en un lienzo logico de 1000x720 para mantener proporciones.
    scene=pygame.Surface((1000,720), pygame.SRCALPHA)
    cx=500
    breathe=math.sin(now*1.45)*3
    nod=math.sin(now*0.73)*2
    mood=rig.mood_name
    skin=(226,164,119)
    skin_light=(246,194,148)
    skin_shadow=(169,105,78)
    hair=(41,34,43)
    hair_hi=(76,57,59)
    eyebrow=(51,39,44)
    white=(246,245,237)
    iris=(70,117,126)
    dark=(39,36,43)
    lips=(147,74,74)
    # Parte superior del cuerpo: hombros, camisa, cuello.
    pygame.draw.ellipse(scene,(8,13,27,90),(209,606,582,206))
    pygame.draw.ellipse(scene,(34,83,107),(206,int(556+breathe),588,370))
    pygame.draw.ellipse(scene,(52,119,140),(245,int(574+breathe),514,252))
    pygame.draw.polygon(scene,(25,54,76),[(395,586),(500,661),(605,586),(569,720),(431,720)])
    pygame.draw.polygon(scene,skin_shadow,[(438,524),(562,524),(560,607),(500,661),(440,607)])
    pygame.draw.ellipse(scene,skin,(439,522,122,110))
    # Orejas y silueta del cabello, ligeramente inclinadas por movimiento.
    oy=int(nod)
    pygame.draw.ellipse(scene,hair,(301,110+oy,400,471))
    pygame.draw.ellipse(scene,hair_hi,(321,129+oy,356,430))
    pygame.draw.ellipse(scene,skin_shadow,(311,335+oy,65,108))
    pygame.draw.ellipse(scene,skin_shadow,(625,335+oy,65,108))
    pygame.draw.ellipse(scene,skin_light,(322,346+oy,43,83))
    pygame.draw.ellipse(scene,skin_light,(634,346+oy,43,83))
    poly_curve(scene,skin_shadow,[(344,371+oy),(329,382+oy),(347,410+oy)],3)
    poly_curve(scene,skin_shadow,[(656,371+oy),(671,382+oy),(653,410+oy)],3)
    # Rostro oval completo con barbilla.
    pygame.draw.ellipse(scene,skin_shadow,(343,143+oy,314,414))
    pygame.draw.ellipse(scene,skin,(347,139+oy,306,405))
    pygame.draw.ellipse(scene,skin_light,(374,164+oy,255,350))
    pygame.draw.ellipse(scene,(242,178,139),(391,196+oy,216,303))
    # Sombras laterales y pómulos.
    pygame.draw.ellipse(scene,(226,151,118),(371,347+oy,83,77))
    pygame.draw.ellipse(scene,(226,151,118),(546,347+oy,83,77))
    blush=int(65*clamp(rig.state['blush'],0,1))
    if blush:
        layer=pygame.Surface((1000,720), pygame.SRCALPHA)
        pygame.draw.ellipse(layer,(232,74,93,blush),(384,368+oy,74,35))
        pygame.draw.ellipse(layer,(232,74,93,blush),(542,368+oy,74,35))
        scene.blit(layer,(0,0))
    # Flequillo + laterales, pelo con volumen y mechas.
    pygame.draw.ellipse(scene,hair,(325,112+oy,352,179))
    pygame.draw.polygon(scene,hair,[(335,203+oy),(350,139+oy),(469,141+oy),(440,239+oy),
                                   (395,251+oy),(353,287+oy)])
    pygame.draw.polygon(scene,hair,[(485,128+oy),(645,153+oy),(665,286+oy),
                                   (607,222+oy),(555,252+oy)])
    pygame.draw.ellipse(scene,hair,(333,219+oy,45,145))
    pygame.draw.ellipse(scene,hair,(624,208+oy,47,161))
    poly_curve(scene,hair_hi,[(374,168+oy),(446,121+oy),(525,164+oy)],9)
    poly_curve(scene,hair_hi,[(499,160+oy),(582,121+oy),(627,192+oy)],7)
    # Cejas: del gesto molesto al sorprendido.
    brows=rig.state
    left=brows['brow_l']*28
    right=brows['brow_r']*28
    poly_curve(scene,eyebrow,[(390,306+oy+left),(431,287+oy-left*.2),(472,303+oy-left)],9)
    poly_curve(scene,eyebrow,[(528,303+oy-right),(569,287+oy-right*.2),(610,306+oy+right)],9)
    # Ojos humanos ovalados y pupilas contenidas en párpados.
    blink=rig.is_blinking(now)
    openness=0.065 if blink else clamp(rig.state['eye_open'],0.22,1.32)
    eh=int(37*openness)
    for ex in (430,570):
        ey=338+oy
        if eh < 7:
            poly_curve(scene,dark,[(ex-43,ey),(ex,ey+5),(ex+43,ey)],4)
            continue
        rect=pygame.Rect(ex-49,ey-eh//2,98,eh)
        pygame.draw.ellipse(scene,(124,84,72),rect.inflate(4,5))
        pygame.draw.ellipse(scene,white,rect)
        # Iris restringido geométricamente al interior del ojo.
        iris_radius=min(16,max(5,eh//2-3))
        px=int(ex+clamp(rig.look_x,-.5,.5)*19)
        py=int(ey+clamp(rig.look_y,-.4,.4)*8)
        px=int(clamp(px,ex-28,ex+28))
        py=int(clamp(py,rect.top+iris_radius,rect.bottom-iris_radius))
        pygame.draw.circle(scene,iris,(px,py),iris_radius)
        pygame.draw.circle(scene,dark,(px,py),max(3,int(iris_radius*.55)))
        pygame.draw.circle(scene,white,(px-4,py-5),max(2,int(iris_radius*.24)))
        # Párpado y pequeñas pestañas.
        poly_curve(scene,dark,[(ex-48,ey),(ex,ey-eh*.9),(ex+48,ey)],4)
        poly_curve(scene,skin_shadow,[(ex-46,ey+9),(ex,ey+eh*.65+7),(ex+46,ey+9)],2)
    # Nariz y sombras (evitamos nariz como simple punto).
    poly_curve(scene,skin_shadow,[(502,365+oy),(488,400+oy),(501,423+oy)],3)
    poly_curve(scene,skin_shadow,[(478,430+oy),(500,441+oy),(521,430+oy)],3)
    pygame.draw.ellipse(scene,(183,109,81),(480,428+oy,10,5))
    pygame.draw.ellipse(scene,(183,109,81),(511,428+oy,10,5))
    # Boca: expresiones y varias aperturas. Es animación estimada,
    # no sincronización real por fonemas.
    m=float(clamp(rig.state['mouth_open'],0,1))
    if mood=='sorpresa' and not speaking:
        pygame.draw.ellipse(scene,(91,42,51),(475,457+oy,50,61))
        pygame.draw.ellipse(scene,lips,(474,456+oy,52,64),4)
    elif mood=='molesto' and not speaking:
        poly_curve(scene,lips,[(455,485+oy),(500,471+oy),(545,485+oy)],5)
    else:
        opening= max(5,int(39*m))
        mw=int(57+22*max(0,rig.state['smile']))
        pygame.draw.ellipse(scene,(99,42,51),(cx-mw//2,472+oy,mw,opening+8))
        if opening>16:
            pygame.draw.ellipse(scene,(244,238,223),(cx-mw//2+9,474+oy,mw-18,12))
            pygame.draw.ellipse(scene,(210,96,109),(cx-23,476+oy+opening//2,46,max(4,opening//3)))
        poly_curve(scene,lips,[(cx-mw//2,478+oy),(cx,472+oy-opening*.13),(cx+mw//2,478+oy)],4)
        if not speaking and m<.20:
            poly_curve(scene,lips,[(cx-mw//2,479+oy),(cx,500+oy+12*max(0,rig.state['smile'])),(cx+mw//2,479+oy)],3)
    # Detalles: luz en barbilla y costura de la ropa.
    poly_curve(scene,(241,176,137),[(465,525+oy),(500,539+oy),(534,524+oy)],2)
    pygame.draw.line(scene,(106,163,177),(501,652),(501,720),3)
    pygame.draw.circle(scene,(137,202,213),(501,689),4)
    # Encajar en cualquier resolucion sin deformar el rostro.
    factor=min(w/1000,h/720)
    dest=pygame.transform.smoothscale(scene,(max(1,int(1000*factor)),max(1,int(720*factor))))
    screen.blit(dest,((w-dest.get_width())//2,(h-dest.get_height())//2))

def main():
    cfg = load_config()
    requested_audio_device = cfg.get("audio_device", "").strip()
    if requested_audio_device:
        os.environ["SDL_AUDIODRIVER"] = "alsa"
        os.environ["AUDIODEV"] = requested_audio_device
    pygame.mixer.pre_init(22050, -16, 1, 512)
    pygame.init()
    audio_error = None
    if pygame.mixer.get_init() is None:
        first_error = pygame.get_error() or "causa desconocida"
        if requested_audio_device:
            print(
                f"[TRIKI AUDIO] No se pudo abrir {requested_audio_device}: {first_error}",
                flush=True,
            )
            print("[TRIKI AUDIO] Probando el dispositivo ALSA predeterminado...", flush=True)
            os.environ.pop("AUDIODEV", None)
            try:
                pygame.mixer.init(22050, -16, 1, 512)
                print("[TRIKI AUDIO] Dispositivo predeterminado iniciado.", flush=True)
            except pygame.error as exc:
                audio_error = (
                    f"No se pudo iniciar {requested_audio_device} ni el audio "
                    f"predeterminado: {exc}"
                )
        else:
            audio_error = f"No se pudo iniciar el audio predeterminado: {first_error}"
        if audio_error:
            print(f"[TRIKI AUDIO] {audio_error}", flush=True)
    flags = pygame.FULLSCREEN if cfg["fullscreen"] else pygame.RESIZABLE
    screen = pygame.display.set_mode((1000, 720), flags)
    pygame.display.set_caption("TRIKI v3 - anfitrión humano interactivo")
    pygame.mouse.set_visible(not cfg["fullscreen"])

    font_title = pygame.font.SysFont("dejavusans", 36, bold=True)
    font_body = pygame.font.SysFont("dejavusans", 24)
    font_small = pygame.font.SysFont("dejavusans", 19)
    clock = pygame.time.Clock()

    reader = TrillReader(cfg)
    speech = Speech(cfg)
    if audio_error:
        speech.error = audio_error
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
        # No aceptar otra accion ni cambiar subtitulos mientras habla o descansa.
        if not speech.ready():
            return
        available = [i for i in range(len(PHRASES[kind])) if (kind, i) in speech.sounds]
        if not available:
            return
        mood_name = EXPRESSIONS[kind]
        rig.set_mood(mood_name)
        mood_until = now + 3.5
        choices = [i for i in available if i != previous_index.get(kind)]
        idx = random.choice(choices or available)
        if speech.speak(kind, idx):
            subtitle = PHRASES[kind][idx]
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
            draw_text(screen, font_small, "Anfitrión virtual · Sala de espera", (w // 2, int(h * 0.125)), PALETTE["subtle"])

            bubble = pygame.Rect(int(w * 0.15), int(h * 0.82), int(w * 0.70), int(h * 0.12))
            bubble_surf = pygame.Surface((bubble.width, bubble.height), pygame.SRCALPHA)
            pygame.draw.rect(bubble_surf, (13, 23, 42, 210), bubble_surf.get_rect(), border_radius=28)
            pygame.draw.rect(bubble_surf, (*PALETTE["cyan"], 180), bubble_surf.get_rect(), 2, border_radius=28)
            screen.blit(bubble_surf, bubble.topleft)

            for i, line in enumerate(wrap_text(subtitle, font_body, bubble.width - 40)):
                draw_text(screen, font_body, line, (w // 2, bubble.top + 30 + i * 30), PALETTE["white"])

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
