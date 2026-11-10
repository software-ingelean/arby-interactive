# Validación de Arby TTS

- 10 pruebas automáticas: entrada vacía/tipos/límites, estado ocupado, cancelación, interrupción y cierre, error de síntesis, timeout, llamadas concurrentes, ausencia de audio, exclusión con voz fija y reproducción por tubería.
- FFmpeg generó un tono MP3 en memoria, enviado en fragmentos a un proceso real de ffplay. La decodificación y reproducción terminaron con salida SDL dummy, sin altavoz ni archivos de audio.
- Cancelación comprobada con un proceso real de ffplay esperando audio; el proceso se termina y la operación queda cancelada.
- La prueba del servicio remoto Edge con Salomé falló por `ClientConnectorCertificateError` del entorno. No se deshabilitó la validación TLS. No se verificó la escucha de la voz ni la latencia audible.
- Windows, Raspberry Pi, dispositivo ALSA físico y sensor Trill no se ejecutaron aquí. El adaptador de exclusión se probó con una voz fija simulada que reproduce la interfaz de Speech.

Ejecuta `uv run python -m libraries.examples.example_tts` desde la raíz del proyecto en tu equipo para comprobar voz, red y dispositivo antes de integrar la planta. Los errores simulados que aparecen durante unittest son parte de las pruebas.
