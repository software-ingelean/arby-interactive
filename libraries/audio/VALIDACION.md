# Validación de Arby TTS

Las pruebas actuales cubren síntesis antes de abrir el reproductor, reproducción
real de MP3 mono con `ffplay` y salida SDL dummy, cancelación durante la síntesis,
cierre repetido con un proceso activo, borrado del audio temporal al cancelar y
diagnóstico del dispositivo cuando falla el reproductor. También cubren estado
ocupado, límites de texto, errores, timeout y coordinación con la voz fija.

Ejecuta desde la raíz:

```bash
.venv/bin/python -m unittest libraries.tests.test_tts libraries.tests.test_audio_recovery -v
```

Los errores simulados que aparecen en los logs son parte de las pruebas.
La tarjeta USB de la Raspberry y la escucha de la voz deben verificarse en el
equipo: la salida dummy solo valida la decodificación y el cierre del reproductor.
