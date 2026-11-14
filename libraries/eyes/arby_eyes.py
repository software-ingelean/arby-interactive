"""Procedural 32x32 eyes. Pillow renderer independent of GPIO and Pygame."""
from __future__ import annotations

from dataclasses import dataclass, replace
from collections.abc import Mapping
import math
import time
import unicodedata

from PIL import Image, ImageDraw

from libraries.core.arby_response import MATRIX_STATES

EMOTION_STATES = MATRIX_STATES
SYSTEM_STATES = ("default", "cargando")
STATES = EMOTION_STATES + SYSTEM_STATES
ALIASES = {"default": "default", "reposo": "default", "idle": "default",
           "cargando": "cargando", "loading": "cargando", "triste": "triste", "tristes": "triste", "alegre": "alegres", "alegres": "alegres",
           "sorprendido": "sorprendidos", "sorprendidos": "sorprendidos",
           "pensativo": "pensativos", "pensativos": "pensativos", "loco": "locos", "locos": "locos",
           "enojado": "enojado", "duda": "duda", "guino ojo": "guiño ojo",
           "dormido": "dormido", "relato extenso": "relato extenso"}

ALIASES.update({state: state for state in EMOTION_STATES})
ALIASES.update({"enamorado": "enamorados", "timido": "timidos", "curioso": "curiosos",
                "dolar": "dolares", "muerto": "aturdidos", "aturdido": "aturdidos"})


def normalize_state(state: str) -> str:
    if not isinstance(state, str):
        raise TypeError("state must be a string")
    key = unicodedata.normalize("NFKD", state.casefold().replace("_", " "))
    key = " ".join("".join(c for c in key if not unicodedata.combining(c)).split())
    if key not in ALIASES:
        raise ValueError(f"Unknown eye state: {state!r}")
    return ALIASES[key]


@dataclass(frozen=True)
class EyePose:
    width: float = 24
    height: float = 15
    cy: float = 21
    brow_outer: float = 7
    brow_inner: float = 7
    brow_arch: float = -1
    pupil_x: float = 0
    pupil_y: float = 0
    pupil_radius: float = 4.5
    lid_outer: float = 0
    lid_inner: float = 0
    closed: float = 0
    brow_width: float = 2
    smile: float = 0
    heart: float = 0
    star: float = 0
    spiral: float = 0
    sunglasses: float = 0
    dollar: float = 0
    cross: float = 0
    sweat: float = 0


def _mix(a, b, amount):
    return EyePose(**{k: getattr(a, k) + (getattr(b, k) - getattr(a, k)) * amount
                      for k in a.__dataclass_fields__})


def _smooth(value):
    value = min(1.0, max(0.0, value))
    return value * value * (3 - 2 * value)


def _blink(t):
    # Short close/open event; rendering remains deterministic for exports/tests.
    phase = (t + 2.9) % 4.7
    if phase >= 0.20:
        return 0.0
    return math.sin(math.pi * phase / 0.20) ** 2


def _pose(state, side, t):
    gaze = 1.25 * math.sin(t * 0.7)
    p = EyePose(pupil_x=gaze)
    phase = 2 * math.pi * t / 4
    bounce = (1 + math.sin(phase * 2)) / 2
    if state == "default":
        p = replace(p, height=14, pupil_x=1.5 * math.sin(phase),
                    brow_outer=8, brow_inner=8, brow_arch=-1)
    elif state == "cargando":
        wave = math.sin(phase * 2 + side * math.pi)
        p = replace(p, height=12, pupil_radius=4,
                    pupil_x=3 * math.cos(phase * 2), pupil_y=2 * math.sin(phase * 2),
                    brow_outer=7 + 3 * wave, brow_inner=7 + 3 * wave,
                    brow_arch=-3, brow_width=3)
    elif state == "alegres":
        p = replace(p, height=12, pupil_x=0,
                    brow_outer=8 - 2 * bounce, brow_inner=8 - 2 * bounce,
                    brow_arch=-10, cy=22 - bounce, brow_width=3, smile=1)
    elif state == "triste":
        p = replace(p, height=12, brow_outer=10, brow_inner=6,
                    pupil_y=2, lid_outer=3, lid_inner=0)
    elif state == "sorprendidos":
        p = replace(p, width=21, height=18 + bounce, cy=22,
                    brow_outer=5 + bounce, brow_inner=5 + bounce,
                    brow_arch=-8, pupil_radius=2.5, pupil_x=0, brow_width=3)
    elif state == "pensativos":
        p = replace(p, height=14 if side == 0 else 10, pupil_x=3, pupil_y=-3,
                    brow_outer=4 if side == 0 else 12,
                    brow_inner=7 if side == 0 else 9,
                    brow_arch=-5 if side == 0 else 0, brow_width=3)
    elif state == "locos":
        phase = t * 4.4 + side * math.pi
        p = replace(p, width=22, height=16 + side * 2,
                    pupil_x=3.5 * math.cos(phase), pupil_y=3 * math.sin(phase),
                    brow_outer=6 + 2 * math.sin(phase), brow_inner=8 - 2 * math.sin(phase))
    elif state == "enojado":
        p = replace(p, height=13, brow_outer=5, brow_inner=11,
                    brow_arch=0, lid_outer=0, lid_inner=7, pupil_x=0)
    elif state == "duda":
        p = replace(p, height=17 if side == 0 else 9,
                    pupil_x=2.5 * math.sin(phase), pupil_y=0,
                    brow_outer=6 if side == 0 else 7,
                    brow_inner=4 if side == 0 else 13,
                    brow_arch=-6 if side == 0 else 1,
                    lid_inner=0 if side == 0 else 2, brow_width=3)
    elif state == "guiño ojo":
        wink = _smooth((math.sin(t * 2 * math.pi / 3.2) - 0.4) / 0.4) if side == 1 else 0
        p = replace(p, brow_outer=6, brow_inner=8, closed=wink,
                    pupil_x=1)
    elif state == "dormido":
        p = replace(p, closed=1, brow_outer=12, brow_inner=12,
                    cy=22 + 0.6 * math.sin(t * 1.5), brow_arch=1)
    elif state == "relato extenso":
        emphasis = (1 + math.sin(t * 2.0)) / 2
        p = replace(p, height=13 + emphasis * 2,
                    brow_outer=7 - emphasis * 1.4,
                    brow_inner=7 - emphasis * 1.4,
                    pupil_x=1.6 * math.sin(t * 0.8), pupil_y=0.5 * math.sin(t * 1.1))
    elif state == "enamorados":
        p = replace(p, heart=1, width=22 + 2*bounce, height=18 + 2*bounce,
                    cy=22, brow_outer=6, brow_inner=7, brow_arch=-4)
    elif state == "estrellas":
        p = replace(p, star=1, width=20+4*bounce, height=18+3*bounce, cy=22-bounce,
                    pupil_x=0, pupil_y=0, brow_outer=5, brow_inner=5, brow_arch=-4)
    elif state == "gafas de sol":
        p = replace(p, sunglasses=1, cy=21, pupil_x=math.sin(t*1.5),
                    brow_outer=7, brow_inner=8, brow_arch=-2)
    elif state == "riendo":
        p = replace(p, smile=1, cy=22-2*bounce, brow_outer=6-bounce,
                    brow_inner=6-bounce, brow_arch=-5, brow_width=3)
    elif state == "timidos":
        p = replace(p, width=20, height=11, pupil_x=-2 if side == 0 else 2,
                    pupil_y=3, brow_outer=9, brow_inner=6, brow_arch=-2)
    elif state == "orgullosos":
        p = replace(p, height=10, cy=20, pupil_y=-2, pupil_x=0,
                    brow_outer=5, brow_inner=8, brow_arch=-3, lid_outer=2)
    elif state == "relajados":
        p = replace(p, height=7, cy=22+math.sin(t*1.4), pupil_radius=3,
                    brow_outer=10, brow_inner=10, brow_arch=-2)
    elif state == "curiosos":
        p = replace(p, width=22 if side == 0 else 25, height=19 if side == 0 else 14,
                    pupil_x=3*math.sin(t*1.2), pupil_y=-1, pupil_radius=5,
                    brow_outer=4 if side == 0 else 8, brow_inner=6, brow_arch=-3)
    elif state == "asustados":
        p = replace(p, width=19, height=21, cy=21, pupil_radius=2,
                    pupil_x=math.sin(t*20), brow_outer=6, brow_inner=3, brow_arch=-2)
    elif state == "aburridos":
        p = replace(p, height=8, pupil_y=2, pupil_x=2*math.sin(t*.3),
                    brow_outer=11, brow_inner=11, lid_outer=2, lid_inner=2)
    elif state == "mareados":
        p = replace(p, spiral=1, width=22, height=19, cy=22,
                    pupil_x=math.sin(t*3+side), pupil_y=math.cos(t*3+side),
                    brow_outer=7+2*math.sin(t*3+side), brow_inner=7)
    elif state == "traviesos":
        p = replace(p, height=10 if side == 0 else 14, pupil_x=-3,
                    brow_outer=5 if side == 0 else 9, brow_inner=10 if side == 0 else 5,
                    lid_inner=3 if side == 0 else 0, brow_arch=-2)
    elif state == "dolares":
        p = replace(p, dollar=1, cy=22-bounce, pupil_x=0,
                    brow_outer=5, brow_inner=5, brow_arch=-3)
    elif state == "aturdidos":
        p = replace(p, cross=1, cy=21+math.sin(t*3+side), pupil_x=0,
                    brow_outer=8, brow_inner=6, brow_arch=2)
    elif state == "risa nerviosa":
        p = replace(p, sweat=1, smile=1, cy=23-bounce,
                    brow_outer=7, brow_inner=5, brow_arch=-3,
                    pupil_y=2*math.sin(t*2))
    if state != "dormido":
        p = replace(p, closed=max(p.closed, _blink(t)))
    return p


def _curve(draw, points, fill, width=2):
    a, b, c = points
    coords = []
    for i in range(25):
        f = i / 24
        coords.append((round((1-f)**2*a[0]+2*(1-f)*f*b[0]+f*f*c[0]),
                       round((1-f)**2*a[1]+2*(1-f)*f*b[1]+f*f*c[1])))
    draw.line(coords, fill=fill, width=width)


@dataclass(frozen=True)
class EyeStyle:
    eye_color: tuple[int, int, int] = (40, 215, 255)
    brow_color: tuple[int, int, int] = (135, 240, 255)
    highlight_color: tuple[int, int, int] = (245, 255, 255)


def _validate_rgb(color):
    if isinstance(color, Mapping):
        if set(color) != {"r", "g", "b"}:
            raise ValueError("RGB requires exactly r, g and b")
        color = (color["r"], color["g"], color["b"])
    if not isinstance(color, (tuple, list)) or len(color) != 3:
        raise ValueError("RGB must contain three integer channels")
    if any(type(channel) is not int or not 0 <= channel <= 255 for channel in color):
        raise ValueError("RGB channels must be integers between 0 and 255")
    return tuple(color)


class EyeAnimator:
    """Call render() regularly from ONE render loop; set_state at any time.

    Returns an RGB 64x32 PIL image: left eye x=0..31, right eye x=32..63.
    All geometry is drawn at native pixel resolution, without resampling.
    """
    def __init__(self, state="default", *, style=None, transition_seconds=0.30):
        if transition_seconds < 0:
            raise ValueError("transition_seconds must not be negative")
        import threading
        self._lock = threading.RLock()
        self.style = style or EyeStyle()
        self._idle_style = self.style
        self.transition_seconds = transition_seconds
        self._state = normalize_state(state)
        self._start = None
        self._from = None

    @property
    def state(self):
        with self._lock:
            return self._state

    def set_state(self, state, *, color=None, now=None):
        """Set expression and optional RGB atomically; system states reset idle colors.

        color accepts {"r": int, "g": int, "b": int} or a three-channel sequence.
        Explicit RGB colors both the eye and eyebrow, preserving the highlight.
        """
        state = normalize_state(state)
        rgb = _validate_rgb(color) if color is not None else None
        now = time.monotonic() if now is None else float(now)
        with self._lock:
            if rgb is not None:
                self.style = replace(self.style, eye_color=rgb, brow_color=rgb)
            elif state in SYSTEM_STATES:
                self.style = self._idle_style
            if state == self._state:
                return
            self._from = [self._current_pose(side, now) for side in (0, 1)]
            self._state = state
            self._start = now

    def apply_response(self, result, *, now=None):
        """Read matrix_state and strip_led.color; this does not drive the LED strip.

        Validate every field before changing either the expression or the color.
        """
        if not isinstance(result, Mapping):
            raise ValueError("The bot response must be a mapping")
        try:
            state = normalize_state(result["matrix_state"])
            strip = result["strip_led"]
            if not isinstance(strip, Mapping):
                raise ValueError("strip_led must be a mapping")
            rgb = _validate_rgb(strip["color"])
            mood = normalize_state(strip["mood"])
        except KeyError as exc:
            raise ValueError(f"Missing bot field: {exc.args[0]}") from exc
        if state not in EMOTION_STATES or mood != state:
            raise ValueError("matrix_state and strip_led.mood must match an emotion")
        self.set_state(state, color=rgb, now=now)

    def _current_pose(self, side, now):
        target = _pose(self._state, side, now)
        if self._start is None or self._from is None or self.transition_seconds == 0:
            return target
        fraction = (now-self._start) / self.transition_seconds
        if fraction >= 1:
            return target
        return _mix(self._from[side], target, _smooth(fraction))

    def render(self, now=None):
        now = time.monotonic() if now is None else float(now)
        with self._lock:
            frame = Image.new("RGB", (64, 32))
            for side in (0, 1):
                frame.paste(self._draw_eye(self._current_pose(side, now), side), (side * 32, 0))
            return frame

    def _draw_eye(self, pose, side):
        panel = Image.new("RGB", (32, 32))
        draw = ImageDraw.Draw(panel)
        brow_color = tuple(round(c * (1-pose.sweat)) for c in self.style.brow_color)
        outer, inner = ((5, pose.brow_outer), (26, pose.brow_inner))
        if side == 1:
            outer, inner = ((26, pose.brow_outer), (5, pose.brow_inner))
        _curve(draw, [outer, (15.5, (outer[1]+inner[1])/2+pose.brow_arch), inner],
               brow_color, 2)
        openness = max(pose.sunglasses, pose.cross, pose.dollar, pose.sweat, 1-pose.closed)
        if openness < 0.15:
            _curve(draw, [(5,pose.cy),(15.5,pose.cy+4),(26,pose.cy)], self.style.eye_color, 2)
            if pose.brow_width > 2:
                _curve(draw, [outer, (15.5, (outer[1]+inner[1])/2+pose.brow_arch), inner],
                       brow_color, round(pose.brow_width))
            return panel
        # Compose sclera and pupil first; clip the whole eye with a lid mask.
        eye = Image.new("RGB", (32, 32), self.style.eye_color)
        eye_draw = ImageDraw.Draw(eye)
        x0, x1 = round(16-pose.width/2), round(16+pose.width/2-1)
        h = max(2, pose.height * openness)
        y0, y1 = round(pose.cy-h/2), round(pose.cy+h/2)
        mask = Image.new("L", (32,32))
        md = ImageDraw.Draw(mask)
        md.rounded_rectangle((x0,y0,x1,y1), radius=min(6,round(h/2)), fill=255)
        # Cut the top edge at different heights near the temple and nose.
        left_cut, right_cut = (pose.lid_outer,pose.lid_inner) if side == 0 else (pose.lid_inner,pose.lid_outer)
        for x in range(max(0,x0),min(31,x1)+1):
            f=(x-x0)/max(1,x1-x0)
            cut=left_cut*(1-f)+right_cut*f
            if cut > 0:
                md.line((x,y0,x,round(y0+cut*openness)),fill=0)
        px = min(x1-5,max(x0+5,16+pose.pupil_x))
        py = pose.cy+pose.pupil_y
        r=pose.pupil_radius
        eye_draw.ellipse((round(px-r),round(py-r),round(px+r),round(py+r)),fill=(0,5,12))
        eye_draw.rectangle((round(px-2),round(py-3),round(px-1),round(py-2)),
                           fill=self.style.highlight_color)
        panel.paste(eye,(0,0),mask)
        if pose.brow_width > 2:
            _curve(ImageDraw.Draw(panel),
                   [outer, (15.5, (outer[1]+inner[1])/2+pose.brow_arch), inner],
                   brow_color, round(pose.brow_width))
        if pose.smile > 0 and pose.closed < 0.85:
            smiling = panel.copy()
            smile_draw = ImageDraw.Draw(smiling)
            smile_draw.rectangle((0, 12, 31, 31), fill=(0, 0, 0))
            lift = 6 * (1 - pose.closed)
            _curve(smile_draw, [(5, pose.cy + 3),
                               (15.5, pose.cy + 3 - 2 * lift),
                               (26, pose.cy + 3)], self.style.eye_color, 3)
            panel = Image.blend(panel, smiling, min(1.0, pose.smile))
        for kind, amount in (("heart", pose.heart), ("star", pose.star), ("spiral", pose.spiral),
                             ("sunglasses", pose.sunglasses), ("dollar", pose.dollar),
                             ("cross", pose.cross)):
            if amount <= 0:
                continue
            special = Image.new("RGB", (32, 32))
            sd = ImageDraw.Draw(special)
            _curve(sd, [outer, (15.5, (outer[1]+inner[1])/2+pose.brow_arch), inner],
                   brow_color, max(2, round(pose.brow_width)))
            cx, cy = 16 + pose.pupil_x, pose.cy
            if kind == "heart":
                points = []
                for i in range(80):
                    angle = 2 * math.pi * i / 80
                    x = 16 * math.sin(angle)**3
                    y = 13*math.cos(angle)-5*math.cos(2*angle)-2*math.cos(3*angle)-math.cos(4*angle)
                    points.append((round(16+x*pose.width/32),
                                   round(cy-y*pose.height*openness/32)))
                sd.polygon(points, fill=self.style.eye_color)
            elif kind == "star":
                points = []
                for i in range(10):
                    angle = -math.pi/2 + i*math.pi/5
                    radius = 1 if i % 2 == 0 else .45
                    points.append((round(cx+math.cos(angle)*pose.width/2*radius),
                                   round(cy+math.sin(angle)*pose.height/2*openness*radius)))
                sd.polygon(points, fill=self.style.eye_color)
            elif kind == "sunglasses":
                top, bottom = round(cy-6), round(cy+7)
                sd.rounded_rectangle((3, top, 28, bottom), radius=4,
                                     fill=(0, 5, 12), outline=self.style.eye_color, width=2)
                # Temples at the outer edges, bridge toward the adjacent panel.
                sd.line((0, top, 31, top), fill=self.style.eye_color, width=2)
                bridge_x = 31 if side == 0 else 0
                sd.line((28 if side == 0 else 3, top+3, bridge_x, top+3),
                        fill=self.style.eye_color, width=2)
                shine = round(9+pose.pupil_x)
                sd.line((shine, top+3, shine-3, top+8),
                        fill=self.style.highlight_color, width=2)
                sd.line((shine+5, top+3, shine+2, top+8),
                        fill=self.style.eye_color, width=1)
            elif kind == "dollar":
                y = round(cy)
                _curve(sd, [(23,y-7),(8,y-12),(9,y-3)], self.style.eye_color, 3)
                _curve(sd, [(9,y-3),(12,y),(22,y+1)], self.style.eye_color, 3)
                _curve(sd, [(22,y+1),(26,y+11),(8,y+7)], self.style.eye_color, 3)
                sd.line((16,y-11,16,y+10), fill=self.style.eye_color, width=2)
            elif kind == "cross":
                y = round(cy)
                sd.line((7,y-7,25,y+7), fill=self.style.eye_color, width=4)
                sd.line((7,y+7,25,y-7), fill=self.style.eye_color, width=4)
            else:
                points = []
                for i in range(100):
                    angle = i/99*math.pi*4
                    radius = 1+i/99*8
                    points.append((round(cx+math.cos(angle)*radius),
                                   round(cy+math.sin(angle)*radius*openness)))
                sd.line(points, fill=self.style.eye_color, width=2)
            panel = Image.blend(panel, special, min(1.0, amount))
        if pose.sweat > 0 and side == 1:
            sweating = panel.copy()
            sd = ImageDraw.Draw(sweating)
            y = round(6+pose.pupil_y)
            sd.polygon([(27,y),(23,y+7),(23,y+10),(26,y+12),
                        (29,y+11),(30,y+8)], fill=(40,180,255))
            sd.line((27,y+5,26,y+8), fill=self.style.highlight_color, width=1)
            panel = Image.blend(panel, sweating, min(1.0, pose.sweat))
        return panel
