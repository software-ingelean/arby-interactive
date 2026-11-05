# Voz de Arby por streaming

La entrada es un texto completo. `edge-tts` recibe ese texto y entrega audio MP3 progresivamente; los bytes van a la entrada estándar de `ffplay`, que decodifica y reproduce. No se crean archivos de audio ni se espera a descargar toda la respuesta antes de enviarla al reproductor. Hay búferes de red y reproducción, así que no se garantiza latencia cero.

Esta entrega añade voz; conserva tu versión actual de `arby_bot.py`, sus cambios de estilo, modelo, reintentos y FAISS. No modifica tus frases fijas ni su caché. El stream añadido es de audio TTS, no de tokens de Gemini. La respuesta de Gemini llega completa antes de iniciar esta síntesis.

## 1. Instalar y probar en Windows con uv

En la raíz de tu proyecto:

```powershell
uv add edge-tts
ffplay -version
```

`ffplay` es un ejecutable de FFmpeg, no un paquete Python: no se instala con `uv add ffmpeg`. Si falta, instala una distribución de FFmpeg que lo incluya desde las opciones de [descarga de FFmpeg](https://ffmpeg.org/download.html) y añade su carpeta `bin` a PATH. Reinicia PyCharm después de cambiar PATH. También puedes indicar una ruta absoluta a `ffplay.exe`.

Copia `arby_tts.py` y `plant_speech.py` dentro de `libraries/`. No reemplaces `arby_bot.py` ni `arby_knowledge.py`.

Para probar solamente la voz, ejecuta `example_tts.py` desde la carpeta extraída (junto a `arby_tts.py`). No requiere clave Gemini ni un token Hugging Face. La síntesis Edge sí requiere Internet.

Para probar conversación, copia `example_arby_voice.py` a la raíz de tu proyecto y ejecútalo con tu configuración de `GEMINI_API_KEY`. El ejemplo usa el modelo que acordamos, `gemini-3.1-flash-lite`; puedes conservar tu configuración actual si has cambiado ese modelo.

## 2. Uso de la librería

```python
from libraries.arby_tts import ArbyTTS, TTSConfig

tts = ArbyTTS(TTSConfig(
    voice="es-CO-SalomeNeural",
    rate="+0%",
    pitch="+0Hz",
    # ffplay_path="C:/ffmpeg/bin/ffplay.exe",
))

accepted = tts.speak("Hola, soy Arby. Qué gusto saludarte.")
# Returns immediately. Your main loop can keep updating the eyes and sensors.

if tts.is_speaking:
    pass

# At application shutdown:
tts.close()
```

| Método o propiedad | Comportamiento |
| --- | --- |
| `speak(text)` | Devuelve True si acepta el texto; False si está ocupado o el texto está vacío |
| `speak(text, interrupt=True)` | Detiene la voz dinámica anterior y acepta la nueva; puede esperar mientras cancela |
| `is_speaking` | True desde que acepta el texto hasta que acaba la conexión, síntesis y reproducción |
| `wait(timeout=None)` | Espera el final; True si terminó, incluso si fue cancelado o falló; False si vence la espera |
| `stop()` | Cancela la petición y termina ffplay; espera hasta 5 segundos y devuelve si terminó |
| `close()` | Detiene y cierra la instancia; no acepta más textos |
| `last_status` | idle, starting, streaming, finishing, completed, cancelled o failed |
| `last_error` | Resumen del error o None |
| `first_chunk_seconds` | Tiempo desde aceptar el texto hasta recibir el primer fragmento; NO mide inicio audible |
| `total_seconds` | Duración total de la operación, incluida reproducción; disponible al terminar |

No existe cola automática: un False significa que NO quedó pendiente para después. `is_speaking` es un estado de operación ocupada, no un detector de voz audible; para animación exacta haría falta medir la salida de audio. Límite inicial: 4000 caracteres, 120 segundos por operación completa. Ambos se ajustan en `TTSConfig`.

Los errores de red/reproducción ocurren en segundo plano y quedan en `last_error`. No se repite automáticamente una síntesis fallida: un reintento después de haber hablado podría repetir palabras. Los errores de configuración, texto inválido o instancia cerrada generan excepciones directamente. Para diagnóstico detallado puedes activar logging DEBUG en pruebas; el nivel normal no imprime el texto enviado.

## 3. Conservar las frases al tocar la planta y evitar superposición

Tu clase `Speech` actual precarga los WAV de `PHRASES` y sigue haciéndolo igual. El adaptador `PlantSpeech` conserva `sounds`, `ready()`, `busy()`, `speak(kind, index)`, `error` y `close()`, y añade `speak_text(text)`.

En el archivo de la planta agrega:

```python
from libraries.arby_tts import ArbyTTS, TTSConfig
from libraries.plant_speech import PlantSpeech
```

En `main()`, reemplaza únicamente:

```python
speech = Speech(cfg)
```

por:

```python
speech = PlantSpeech(
    Speech(cfg),
    ArbyTTS(TTSConfig(
        voice=cfg.get("edge_voice", "es-CO-SalomeNeural"),
        rate=cfg.get("edge_rate", "+0%"),
        pitch=cfg.get("edge_pitch", "+0Hz"),
    )),
)
```

Mantén la clase `Speech`, `PHRASES`, `_generate()` y `react()` originales. Las frases táctiles continúan usando su caché y Pygame. Las respuestas nuevas se inician con:

```python
accepted = speech.speak_text(response_text)
```

Todo inicio de audio debe pasar por este adaptador: no llames por fuera a `speech.fixed.speak()` ni a `speech.tts.speak()`. Así se comprueba la exclusión en ambas direcciones. Si habla una frase fija se rechaza la respuesta dinámica y viceversa; el adaptador no la encola ni interrumpe las frases fijas. La aplicación debe decidir qué hacer si recibe False.

En una GUI/Pygame, Gemini debe ejecutarse en un worker. Transfiere el resultado mediante una cola o señal al hilo principal y llama allí a `speech.speak_text()`. Las operaciones de la voz fija Pygame permanecen en el hilo principal. No uses `tts.wait()` dentro del bucle de dibujo; úsalo solo en pruebas de consola.

`PlantSpeech.busy()` incluye ambas voces: tus animaciones actuales pueden seguir consultándolo. El cooldown de la voz fija se conserva. La voz dinámica no añade una espera artificial después de terminar.

## 4. Raspberry Pi

Usa los mismos módulos con Python 3.10 o superior e instala el paquete del sistema que incluya `ffplay` (en Raspberry Pi OS normalmente `sudo apt install ffmpeg`). No requiere CUDA.

El proceso hijo hereda el entorno de audio de tu programa. Tu script original define `SDL_AUDIODRIVER` y `AUDIODEV` para ALSA; si deseas configurarlos expresamente para streaming:

```python
tts = ArbyTTS(TTSConfig(
    audio_driver="alsa",
    audio_device="plughw:C10,0",
))
```

Ese nombre es el de tu ejemplo, no una identificación universal. Usa el dispositivo real. En Windows deja ambos campos en None para usar el audio predeterminado. La selección ALSA mediante SDL depende de la compilación y debe probarse en la Raspberry.

Pygame y ffplay son clientes de audio diferentes. Aunque no hablen al mismo tiempo, Pygame puede mantener abierto un dispositivo ALSA exclusivo como `plughw`. Si ffplay informa que el dispositivo está ocupado, configura `"audio_device": "default"` en el JSON original y usa la salida predeterminada compartida del sistema para ambos, en lugar de abrir directamente el hardware. La disponibilidad de mezcla compartida depende de la configuración de audio de la Raspberry; no se comprobó en este entorno.

## 5. Validación

```powershell
uv run python -m unittest discover -s RUTA_A_LA_CARPETA_EXTRAIDA -p test_tts.py -v
```

Las pruebas no usan el servicio Edge. Incluyen una reproducción real por tubería de un tono MP3 generado en memoria, con salida SDL dummy (sin altavoz). Requieren `ffplay`; la del tono también necesita `ffmpeg`.

Las pruebas comprueban cancelación, llamadas concurrentes, exclusión entre voz fija y dinámica, errores y cierre. No sustituyen la escucha en Windows/Raspberry ni comprueban la disponibilidad del servicio remoto. Consulta `VALIDACION.md` para los resultados de este entorno.

Referencias: [edge-tts](https://github.com/rany2/edge-tts), [FFplay](https://ffmpeg.org/ffplay.html).
