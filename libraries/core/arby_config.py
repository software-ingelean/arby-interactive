"""Shared runtime schema and validation, without hardware imports."""
import math
from types import SimpleNamespace

FIELDS = {
    "push_to_talk": (bool, False, None),
    "microphone_enabled": (bool, True, None),
    "input_mode": (str, "text", ("text", "voice")),
    "mic_device": (str, "0", None),
    "mic_channel": (str, "left", ("left", "right")),
    "mic_language": (str, "es-CO", None),
    "mic_gain_db": (float, 6.0, None),
    "mic_graves": (float, 80.0, None),
    "mic_agudos": (float, 8000.0, None),
    "mic_block_ms": (int, 20, None),
    "mic_queue_blocks": (int, 8, None),
    "mic_threshold": (float, 0.5, None),
    "mic_silence_ms": (int, 450, None),
    "mic_preroll_ms": (int, 320, None),
    "mic_followup_seconds": (float, 8.0, None),
    "mic_request_timeout": (float, 10.0, None),
    "mic_max_utterance_seconds": (float, 15.0, None),
    "eyes": (str, "preview", ("preview", "none", "matrix")),
    "strip": (bool, False, None),
    "strip_gpio": (int, 12, None),
    "strip_leds": (int, 55, None),
    "strip_brightness": (int, 20, None),
    "strip_effect": (str, "solid", ("solid", "breathing", "bounce", "center_out", "ripple")),
    "multiplexing": (int, None, None),
    "row_address_type": (int, 0, None),
    "matrix_brightness": (int, 25, None),
    "matrix_mapping": (str, "regular", ("regular", "regular-oe5")),
    "matrix_rgb_sequence": (str, "RGB", ("RGB", "RBG", "GRB", "GBR", "BRG", "BGR")),
    "slowdown": (int, 2, None),
    "swap_eyes": (bool, False, None),
    "model": (str, None, None),
    "model_cooldown_seconds": (float, 60.0, None),
    "bot_timeout": (float, 30.0, None),
    "voice": (str, None, None),
    "rate": (str, None, None),
    "pitch": (str, None, None),
    "ffplay": (str, None, None),
    "audio_driver": (str, None, None),
    "audio_device": (str, None, None),
    "audio_recover_on_exit": (bool, False, None),
    "mute": (bool, False, None),
    "demo": (bool, False, None),
    "trill": (bool, False, None),
}

def parse_config(overrides, environment):
    settings = {}
    for name, (convert, default, choices) in FIELDS.items():
        variable = "GEMINI_MODEL" if name == "model" else f"ARBY_{name.upper()}"
        raw = ("" if overrides[name] is None else str(overrides[name]).strip()) if name in overrides else environment.get(variable, "").strip()
        value = default
        if raw:
            try:
                if convert is bool:
                    if raw.casefold() not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
                        raise ValueError("usa true/false, 1/0, yes/no u on/off")
                    value = raw.casefold() in {"true", "1", "yes", "on"}
                else:
                    value = convert(raw)
                if choices is not None and value not in choices:
                    raise ValueError(f"opciones: {', '.join(choices)}")
            except ValueError as exc:
                raise ValueError(f"{variable}: valor inválido ({exc})") from exc
        settings[name] = value
    config = SimpleNamespace(**settings)
    mic_values = {name[4:]: value for name, value in settings.items() if name.startswith("mic_")}
    if not all(math.isfinite(v) for v in mic_values.values() if isinstance(v, (int, float))):
        raise ValueError("Los parámetros ARBY_MIC deben ser finitos.")
    if (not 0 < config.mic_graves < config.mic_agudos < 24000
            or not -30 <= config.mic_gain_db <= 36
            or config.mic_block_ms not in (10, 20, 40)
            or not 1 <= config.mic_queue_blocks <= 100
            or not 0 < config.mic_threshold < 1
            or not 0 < config.mic_silence_ms <= 5000
            or not 0 <= config.mic_preroll_ms <= 2000
            or not 0 < config.mic_followup_seconds <= 120
            or not 0 < config.mic_request_timeout <= 120
            or not 1 <= config.mic_max_utterance_seconds <= 60):
        raise ValueError("Revisa los límites de ARBY_MIC en .env.example.")
    if str(mic_values["device"]).isdigit():
        mic_values["device"] = int(mic_values["device"])
    config.microphone = SimpleNamespace(**mic_values)
    if not 0 < config.model_cooldown_seconds < float("inf"):
        raise ValueError("ARBY_MODEL_COOLDOWN_SECONDS debe ser positivo y finito.")
    if not 0 < config.bot_timeout < float("inf"):
        raise ValueError("ARBY_BOT_TIMEOUT debe ser positivo y finito.")
    if config.eyes == "matrix" and config.multiplexing is None:
        raise ValueError("ARBY_MULTIPLEXING es obligatorio en modo matrix; valida el valor sobre tus paneles.")
    matrix_pins = {4, 7, 8, 9, 10, 11, 17, 18, 22, 23, 24, 25, 27}
    if config.matrix_mapping == "regular-oe5":
        matrix_pins = (matrix_pins - {18}) | {5}
    if config.eyes == "matrix" and config.strip and config.strip_gpio in matrix_pins:
        raise ValueError("ARBY_STRIP_GPIO coincide con el cableado de las matrices seleccionado.")
    if config.strip_gpio < 0 or config.strip_leds < 1 or not 0 <= config.strip_brightness <= 100:
        raise ValueError("Revisa ARBY_STRIP_GPIO (>=0), ARBY_STRIP_LEDS (>0) y ARBY_STRIP_BRIGHTNESS (0–100).")
    if not 1 <= config.matrix_brightness <= 100:
        raise ValueError("ARBY_MATRIX_BRIGHTNESS debe estar entre 1 y 100.")
    return config
