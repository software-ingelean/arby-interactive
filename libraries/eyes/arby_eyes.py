"""Procedural 32x32 eyes. Pillow renderer independent of GPIO and Pygame."""
from __future__ import annotations

from dataclasses import dataclass, replace
from collections.abc import Mapping
import math
import time
import unicodedata

from PIL import Image, ImageDraw

EMOTION_STATES = ("triste", "alegres", "sorprendidos", "pensativos", "locos", "enojado",
          "duda", "guiño ojo", "dormido", "relato extenso", "enamorados")
SYSTEM_STATES = ("default", "cargando")
STATES = EMOTION_STATES + SYSTEM_STATES
ALIASES = {"default": "default", "reposo": "default", "idle": "default",
           "cargando": "cargando", "loading": "cargando", "triste": "triste", "tristes": "triste", "alegre": "alegres", "alegres": "alegres",
           "sorprendido": "sorprendidos", "sorprendidos": "sorprendidos",
           "pensativo": "pensativos", "pensativos": "pensativos", "loco": "locos", "locos": "locos",
           "enojado": "enojado", "duda": "duda", "guino ojo": "guiño ojo",
           "dormido": "dormido", "relato extenso": "relato extenso",
           "enamorado": "enamorados", "enamorados": "enamorados"}


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
        outer, inner = ((5, pose.brow_outer), (26, pose.brow_inner))
        if side == 1:
            outer, inner = ((26, pose.brow_outer), (5, pose.brow_inner))
        _curve(draw, [outer, (15.5, (outer[1]+inner[1])/2+pose.brow_arch), inner],
               self.style.brow_color, 2)
        openness = max(0, 1-pose.closed)
        if openness < 0.15:
            _curve(draw, [(5,pose.cy),(15.5,pose.cy+4),(26,pose.cy)], self.style.eye_color, 2)
            if pose.brow_width > 2:
                _curve(draw, [outer, (15.5, (outer[1]+inner[1])/2+pose.brow_arch), inner],
                       self.style.brow_color, round(pose.brow_width))
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
                   self.style.brow_color, round(pose.brow_width))
        if pose.smile > 0 and pose.closed < 0.85:
            smiling = panel.copy()
            smile_draw = ImageDraw.Draw(smiling)
            smile_draw.rectangle((0, 12, 31, 31), fill=(0, 0, 0))
            lift = 6 * (1 - pose.closed)
            _curve(smile_draw, [(5, pose.cy + 3),
                               (15.5, pose.cy + 3 - 2 * lift),
                               (26, pose.cy + 3)], self.style.eye_color, 3)
            panel = Image.blend(panel, smiling, min(1.0, pose.smile))
        if pose.heart > 0:
            heart_panel = Image.new("RGB", (32, 32))
            hd = ImageDraw.Draw(heart_panel)
            _curve(hd, [outer, (15.5, (outer[1]+inner[1])/2+pose.brow_arch), inner],
                   self.style.brow_color, max(2, round(pose.brow_width)))
            points = []
            for i in range(80):
                angle = 2 * math.pi * i / 80
                x = 16 * math.sin(angle)**3
                y = (13*math.cos(angle)-5*math.cos(2*angle)
                     -2*math.cos(3*angle)-math.cos(4*angle))
                points.append((round(16+x*pose.width/32),
                               round(pose.cy-y*pose.height*openness/32)))
            hd.polygon(points, fill=self.style.eye_color)
            panel = Image.blend(panel, heart_panel, min(1.0, pose.heart))
        return panel
