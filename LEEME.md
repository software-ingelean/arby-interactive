# TRIKI v4 - voz natural y una sola respuesta por toque

Conserva el personaje de v3, Trill Craft I²C y la salida de audio USB Nuroum C10.

## Estructura del proyecto

```text
app/                 Versiones de TRIKI y lógica de la interfaz
  hardware/          Controlador compartido del sensor Trill
config/              Configuración activa y configuración de ejemplo
diagnosticos/        Escaneo I²C, pruebas manuales y visualizadores del sensor
herramientas/        Generación y comparación de voces
assets/
  audio_triki/       Caché de frases WAV
  muestras_voz/      Muestras MP3 generadas
  test_voice.mp3     Audio de prueba
docs/                Guías de versiones anteriores y voz corregida
```

Ejecuta los comandos desde la raíz del proyecto usando `python -m` para
resolver los módulos compartidos. Las rutas de configuración y audio se
calculan desde la ubicación del proyecto.

Los entornos `.venv/`, `triki-venv/` y `trill_env/` conservan su ubicación;
`uv sync` utiliza `.venv/`.

## Diagnóstico del sensor

Estas utilidades son pruebas manuales que requieren el sensor conectado a la
Raspberry Pi; no son una suite de pruebas automáticas.

```bash
uv run python -m diagnosticos.trill_scan
uv run python -m diagnosticos.test_trill_craft
uv run python -m diagnosticos.trill_test
uv run python -m diagnosticos.graphic_trill
uv run python -m diagnosticos.trill_bar_gui
uv run python -m diagnosticos.trill_bar_triqui
```

Para ejecutar otra versión, usa su módulo, por ejemplo
`uv run python -m app.triki_craft` o `uv run python -m app.triki_pantalla_humano`.
Consulta también las [instrucciones de voz](docs/INSTRUCCIONES_TRIKI_VOZ.md)
y la [guía de TRIKI v2](docs/LEEME_TRIKI_v2.md).

## Instalación con uv

```bash
sudo apt update
sudo apt install ffmpeg i2c-tools python3-tk
uv sync
```

`uv sync` crea `.venv` e instala las dependencias Python declaradas en
`pyproject.toml`: `pygame`, `smbus2` y `edge-tts`. El archivo `uv.lock`
mantiene las versiones reproducibles entre instalaciones. El proyecto usa
Python 3.13 mediante `.python-version`, ya que `pygame 2.6` todavía no ofrece
un paquete precompilado para Python 3.14.

Si todavía no tienes uv en la Raspberry Pi, instálalo con el método oficial:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

`ffmpeg`, `i2c-tools` y `python3-tk` son paquetes del sistema y por eso no se
incluyen en `pyproject.toml`. `espeak-ng` es opcional y solo hace falta para las
versiones antiguas o si configuras `"voice_engine": "espeak"`.

## Ejecución

### Variables de entorno de Arby

Después de `uv sync`, copia `.env.example` a `.env` si aún no existe:

```bash
cp .env.example .env
```

Edita `.env` y completa `GEMINI_API_KEY` con tu clave. También puedes usar
`GOOGLE_API_KEY` como alternativa y cambiar `GEMINI_MODEL`.
Ejecuta Arby con `uv run python main.py` o `uv run python run_arby.py`.
Ambas entradas cargan el `.env` de la raíz del proyecto, incluso al ejecutar
desde otro directorio. Las variables que ya existan en el entorno tienen
prioridad; `--model` permite elegir el modelo para una ejecución.

`.env` está excluido de Git: guarda ahí las claves locales. `.env.example`
documenta las variables sin incluir secretos. Los archivos de `config/*.json`
siguen siendo la configuración estructurada de voz y hardware.

```bash
uv run python -m app.triki_humano_real
```

**Voz natural:** usa Edge TTS (requiere Internet durante la síntesis inicial). Por defecto `es-PE-CamilaNeural` (femenina peruana), velocidad `-12%` y tono `+15Hz`; los WAV se guardan en `assets/audio_triki/` y luego pueden reproducirse sin conexión. La primera ejecución puede tardar en generar todas las frases. Si falla Edge, se informa del error sin cambiar automáticamente a una voz robótica. Las frases son tiernas y presentan a Triki como una plantita de compañía.

**Audio Nuroum:** `audio_device` queda en `plughw:C10,0` (referencia estable por nombre). Si tu ALSA no resuelve este identificador, usa `plughw:3,0` según tu `aplay -l` actual, o pon `audio_device` vacío para usar el dispositivo predeterminado.

Al arrancar, TRIKI intenta primero `audio_device`. Si ese dispositivo no existe,
prueba automáticamente la salida ALSA predeterminada y muestra en la terminal el
error concreto de ambos intentos.

**Sin voces superpuestas:** cuando habla, descarta nuevos toques (sin cola), y al terminar espera 1.2 s antes de responder a otro toque. Mantiene la detección y gestos del Trill.

**Controles:** 1-5 simulación de zonas; F1 diagnóstico; F2 pantalla; C recalibración; ESC salir.

Si prefieres una voz totalmente local, escribe `"voice_engine": "espeak"` en `config/triki_config.json`; la calidad no será neuronal.

## Ajustar la voz de la plantita

En `config/triki_config.json`, `edge_rate` controla la velocidad y `edge_pitch` el tono. El perfil activo usa Camila con `-12%` y `+15Hz`: ritmo pausado y tono más agudo. Para escuchar el tono original de Camila, cambia `edge_pitch` a `+0Hz`.

Al cambiar la voz, el tono o las frases, se generan nuevos WAV sin borrar los anteriores. Necesitas Internet al generarlos por primera vez. Ambas entradas, `triki_humano_real.py` y `triki_humano_real_corregido.py`, usan este perfil. Las versiones antiguas `triki_interactivo.py` y `triki_pantalla_humano.py` siguen usando eSpeak; ejecuta una de las entradas neuronales para escuchar la voz nueva.

## Probar voces

Para comparar cuatro variantes de Salomé con el mismo texto:

```bash
uv run python -m herramientas.probar_voces --compare
```

Para comparar voces femeninas más neutrales de México, Estados Unidos, Perú y
Ecuador, sin elevar artificialmente el tono:

```bash
uv run python -m herramientas.probar_voces --neutral-compare
```

Para comparar voces masculinas de Colombia, México, Estados Unidos, Perú y
Ecuador:

```bash
uv run python -m herramientas.probar_voces --male-compare
```

Para probar solo el perfil usado por el bot:

```bash
uv run python -m herramientas.probar_voces --profile tierna
```

Puedes usar otro texto o ajustar la voz manualmente:

```bash
uv run python -m herramientas.probar_voces --text "Hola, ¿cómo estás?" --rate=-10% --pitch=+12Hz
```

Las muestras quedan en `assets/muestras_voz/`. La síntesis necesita Internet; después
puedes reproducir los MP3 sin conexión. Usa `--no-play` si solo quieres generar
los archivos y `--list-voices` para consultar todas las voces disponibles.
