"""Offline bot for checking Arby responses and expressions."""

from libraries.core.arby_response import EMOTION_COLORS, normalize_reply


class DemoBot:
    """Offline wiring check only; production uses the existing ArbyBot."""
    colors = EMOTION_COLORS

    def respond(self, text):
        state = next((s for s in self.colors if s in text.casefold()), "alegres")
        r, g, b = self.colors[state]
        segment = {"matrix_state": state,
                "strip_led": {"color": {"r": r, "g": g, "b": b}, "mood": state},
                "response": f"Prueba de integración: expresión {state}."}
        if text.casefold().strip() == "emociones":
            return normalize_reply({"segments": [
                {"matrix_state": "alegres", "strip_led": {
                    "color": {"r": 0, "g": 255, "b": 80}, "mood": "alegres"},
                 "response": "Sí Luis, qué bueno verte."},
                {"matrix_state": "pensativos", "strip_led": {
                    "color": {"r": 120, "g": 60, "b": 255}, "mood": "pensativos"},
                 "response": "Eso que me cuentas me dejó pensando."},
            ]})
        return normalize_reply({"segments": [segment]})

    def reset_session(self):
        pass

    def close(self):
        pass
