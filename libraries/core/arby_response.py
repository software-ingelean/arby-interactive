"""Shared structured response contract; no SDK, hardware or model imports."""
import json
import re


EMOTION_COLORS = {
    "triste": (0, 80, 255), "alegres": (0, 255, 80),
    "sorprendidos": (255, 220, 0), "pensativos": (120, 60, 255),
    "locos": (255, 0, 180), "enojado": (255, 0, 0),
    "duda": (255, 130, 0), "guiño ojo": (255, 80, 140),
    "dormido": (0, 0, 35), "relato extenso": (0, 180, 180),
    "enamorados": (255, 50, 110),
}
MATRIX_STATES = tuple(EMOTION_COLORS)
DEFAULT_STATE = "pensativos"
MAX_SEGMENTS = 8

SEGMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "matrix_state": {"type": "string", "enum": list(MATRIX_STATES)},
        "strip_led": {
            "type": "object",
            "properties": {
                "color": {
                    "type": "object",
                    "properties": {channel: {"type": "integer", "minimum": 0, "maximum": 255}
                                   for channel in ("r", "g", "b")},
                    "required": ["r", "g", "b"], "additionalProperties": False,
                },
                "mood": {"type": "string", "enum": list(MATRIX_STATES)},
            },
            "required": ["color", "mood"], "additionalProperties": False,
        },
        "response": {"type": "string", "minLength": 1},
    },
    "required": ["matrix_state", "strip_led", "response"],
    "additionalProperties": False,
}
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {"segments": {"type": "array", "items": SEGMENT_SCHEMA,
                                "minItems": 1, "maxItems": MAX_SEGMENTS}},
    "required": ["segments"], "additionalProperties": False,
}


def clean_for_speech(text):
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"(?m)^\s*(?:#{1,6}\s*|[-*]\s+|\d+[.)]\s+)", "", text)
    text = re.sub(r"[*_`]+", "", text)
    text = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]", "", text)
    return " ".join(text.split())


def validate_color(color):
    if isinstance(color, dict):
        if set(color) != {"r", "g", "b"}:
            raise ValueError("RGB requires r, g and b")
        color = tuple(color[k] for k in ("r", "g", "b"))
    if not isinstance(color, (tuple, list)) or len(color) != 3:
        raise ValueError("RGB must have three channels")
    if any(type(c) is not int or not 0 <= c <= 255 for c in color):
        raise ValueError("RGB channels must be integers from 0 to 255")
    return tuple(color)


def make_segment(text, state=DEFAULT_STATE, *, color=None):
    if not isinstance(state, str) or state not in EMOTION_COLORS:
        raise ValueError("Unknown emotion")
    if not isinstance(text, str) or not clean_for_speech(text):
        raise ValueError("The segment must contain speech text")
    r, g, b = validate_color(EMOTION_COLORS[state] if color is None else color)
    return {"matrix_state": state,
            "strip_led": {"color": {"r": r, "g": g, "b": b}, "mood": state},
            "response": clean_for_speech(text)}


def _validate_segment(segment, *, canonical_colors=False):
    if not isinstance(segment, dict) or set(segment) != {"matrix_state", "strip_led", "response"}:
        raise ValueError("Invalid segment structure")
    strip = segment["strip_led"]
    if not isinstance(strip, dict) or set(strip) != {"color", "mood"}:
        raise ValueError("Invalid strip structure")
    if strip["mood"] != segment["matrix_state"]:
        raise ValueError("Matrix state and strip mood must match")
    rgb = validate_color(strip["color"])
    return make_segment(segment["response"], segment["matrix_state"],
                        color=None if canonical_colors else rgb)


def normalize_reply(reply, *, allow_legacy=True, canonical_colors=False):
    """Validate ALL segments before playback; derive aggregate text in Python."""
    if not isinstance(reply, dict):
        raise ValueError("The bot must return a dictionary")
    if "segments" in reply:
        if set(reply) - {"segments", "response"}:
            raise ValueError("Unexpected response fields")
        segments = reply["segments"]
    elif allow_legacy:
        segments = [reply]
    else:
        raise ValueError("Gemini must return a segments array")
    if not isinstance(segments, list) or not 1 <= len(segments) <= MAX_SEGMENTS:
        raise ValueError(f"Response requires 1 to {MAX_SEGMENTS} segments")
    segments = [_validate_segment(segment, canonical_colors=canonical_colors)
                for segment in segments]
    return {"segments": segments,
            "response": " ".join(segment["response"] for segment in segments)}


def make_reply(text, state=DEFAULT_STATE):
    """Wrap locally generated speech as one block; empty input has no blocks."""
    if not isinstance(text, str):
        raise TypeError("Speech text must be a string")
    if not clean_for_speech(text):
        return {"segments": [], "response": ""}
    return normalize_reply({"segments": [make_segment(text, state)]})


def parse_reply(raw):
    """Validate provider JSON and keep Python's fixed emotion-to-RGB palette."""
    return normalize_reply(json.loads(raw), allow_legacy=False, canonical_colors=True)
