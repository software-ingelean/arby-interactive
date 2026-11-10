"""Optional ALSA playback reinitialization after releasing a PWM LED strip."""
import logging
import shutil
import subprocess

LOGGER = logging.getLogger(__name__)
HEADPHONES_DEVICE = "plughw:CARD=Headphones,DEV=0"


def close_strip_and_recover_audio(strip, *, recover=False):
    """Release LEDs first; never open the jack if strip cleanup failed."""
    strip.close()
    if recover:
        return recover_headphones()
    return None


def recover_headphones():
    """Try a finite silent ALSA stream, without changing mixer/system settings.

    Successful playback only confirms that ALSA accepted the stream. Whether
    this clears a residual PWM tone must be checked on the Raspberry itself.
    """
    player = shutil.which("aplay")
    if player is None:
        LOGGER.warning("Recuperación del jack omitida: falta aplay (alsa-utils).")
        return False
    command = [player, "-q", "-D", HEADPHONES_DEVICE, "-t", "raw",
               "-f", "S16_LE", "-r", "48000", "-c", "2"]
    try:
        # 0.25 seconds, 48000 frames/s, stereo, signed 16-bit PCM silence.
        result = subprocess.run(command, input=bytes(48000),
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                timeout=3, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        LOGGER.warning("Falló la recuperación del jack: %s", type(exc).__name__)
        return False
    if result.returncode:
        detail = result.stderr.decode(errors="replace").strip()[-1000:]
        LOGGER.warning("Falló la recuperación del jack: %s", detail)
        return False
    print("Estado: finalizó la prueba de recuperación del jack; comprueba si cesó el pitido.",
          flush=True)
    return True
