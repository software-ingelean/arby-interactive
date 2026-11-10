# Ejecutar Arby con la tira LED

No necesitas instalar Arby en el Python global. Usa el mismo entorno `.venv`
para el bot y para la tira; los permisos de acceso al hardware son un asunto
distinto del entorno Python. Para la salida NeoPixel por GPIO12, normalmente
debes ejecutar con `sudo`, indicando el Python de `.venv` explícitamente.

Esta guía corresponde al controlador actual: `board` + `neopixel`, 55 LED RGB
en orden GRB y datos en **GPIO BCM12** (pin físico 32). Está orientada a
Raspberry Pi con un backend PWM compatible; no presupone compatibilidad con
Raspberry Pi 5. Si usas ese modelo, hay que verificar el backend y el cableado
antes de seguir estos pasos.

## 1. Instalar en la Raspberry Pi

Abre una terminal en la raíz del repositorio (la carpeta de `run_arby.py`).
Ejecuta la instalación como tu usuario habitual:

```bash
sudo apt update
sudo apt install ffmpeg
uv sync --extra led
```

Las dependencias de hardware están declaradas en el extra `led` de
`pyproject.toml`, incluidas `gpiod` y `Adafruit-Blinka-Raspberry-Pi-PWM`.
Usa siempre `uv sync --extra led` al sincronizar esta Raspberry; `uv sync`
sin el extra puede quitar estos paquetes. Si ejecutas mediante `uv run`, usa
también `uv run --extra led`. Los comandos de esta guía usan directamente
`.venv/bin/python`; no hace falta activar el entorno ni instalar `pip`.

Comprueba que las dependencias están en el Python correcto:

```bash
.venv/bin/python -c 'import sys, board, neopixel, rpi_ws281x; print(sys.executable); print("Dependencias LED disponibles")'
```

Este comando comprueba las importaciones; todavía no prueba el acceso a la tira.
No uses `sudo pip install` ni `--break-system-packages`.

## 2. Probar solo la integración y la tira

Conecta la tira con la Raspberry apagada. Usa una fuente de 5 V adecuada para
la tira y masa común con la Raspberry; conecta los datos a DIN. No alimentes
los 55 LED desde un GPIO.

Desde la raíz del proyecto:

```bash
sudo "$(pwd)/.venv/bin/python" "$(pwd)/run_arby.py" --eyes none --strip --demo --mute --strip-gpio 12 --strip-leds 55 --strip-brightness 20
```

Esta prueba no usa Gemini, el índice FAISS ni el audio. Escribe `alegres`,
`pensativos` o `emociones` y pulsa Enter para probar cambios de expresión y
color. Escribe `salir` para cerrar y apagar la tira. También puedes usar Ctrl+C.

Sin una Raspberry o sin tira, puedes comprobar el arranque simulado:

```bash
.venv/bin/python run_arby.py --eyes none --demo --mute
```

## 3. Ejecutar el bot con voz y la tira

### Guardar las opciones en `.env`

Agrega estas líneas a tu `.env` existente, conservando la clave de API:

```dotenv
GEMINI_MODEL=gemini-flash-latest
ARBY_EYES=none
ARBY_STRIP=true
ARBY_STRIP_GPIO=12
ARBY_STRIP_LEDS=82
ARBY_STRIP_BRIGHTNESS=20
ARBY_STRIP_EFFECT=solid
ARBY_DEMO=false
ARBY_MUTE=false
```

Con este perfil basta con ejecutar, desde la raíz:

```bash
sudo "$(pwd)/.venv/bin/python" "$(pwd)/run_arby.py"
```

Cada opción de consola tiene una variable `ARBY_` con el nombre en mayúsculas
y guiones convertidos a guiones bajos: por ejemplo, `--audio-device` corresponde
a `ARBY_AUDIO_DEVICE`. La excepción es `--model`, que usa `GEMINI_MODEL`.
Consulta todas las variables en [`.env.example`](../.env.example) o con `--help`.
Un valor vacío conserva el valor predeterminado. Los booleanos aceptan
`true/false`, `1/0`, `yes/no` y `on/off`.

Los argumentos explícitos tienen prioridad sobre el entorno. Puedes usar
`--no-strip`, `--no-demo`, `--no-mute` y `--no-swap-eyes` para desactivar
opciones activadas en `.env`. Para probar sin hardware ni servicios externos:

```bash
.venv/bin/python run_arby.py --eyes none --no-strip --demo --mute
```

Las variables exportadas por el proceso tienen prioridad sobre `.env`.
`sudo` puede eliminar esas variables, pero Arby sigue leyendo el archivo `.env`.

### Configuración de la API

Si todavía no tienes `.env`, créalo sin sobrescribir uno existente:

```bash
test -f .env || cp .env.example .env
```

Edita `.env` y configura `GEMINI_API_KEY` (o `GOOGLE_API_KEY`). El script carga
este archivo desde la raíz del proyecto incluso al ejecutarse con `sudo`.
La ejecución real también necesita el índice y la configuración del bot
descritos en [la guía de integración](../README_integracion.md).

```bash
sudo "$(pwd)/.venv/bin/python" "$(pwd)/run_arby.py" --eyes none --strip
```

Si exportaste la clave en la terminal en lugar de usar `.env`:

```bash
sudo --preserve-env=GEMINI_API_KEY,GOOGLE_API_KEY,GEMINI_MODEL "$(pwd)/.venv/bin/python" "$(pwd)/run_arby.py" --eyes none --strip
```

No uses `sudo python3` ni `sudo uv run`: podrían seleccionar un entorno distinto.
Con escritorio, puedes sustituir `--eyes none` por `--eyes preview`; la ventana
requiere acceso a la sesión gráfica del usuario. Por SSH, usa `--eyes none`.
Las matrices físicas requieren además `rgbmatrix` y un valor de
`--multiplexing` validado: consulta la guía de integración antes de activarlas.

## Problemas frecuentes

| Mensaje o síntoma | Qué revisar |
| --- | --- |
| `No module named board`, `neopixel` o `rpi_ws281x` | Repite la instalación de hardware en `.venv` y usa ese mismo Python con `sudo`. |
| `Operation not permitted`, `mailbox` o acceso a `/dev/mem` | Ejecuta la prueba LED con `sudo` y la ruta explícita al Python del entorno. Si persiste, revisa compatibilidad del modelo de Raspberry, sistema operativo y backend. |
| Error de plataforma o placa no compatible | Confirma el modelo de Raspberry y el soporte de Blinka/rpi_ws281x; elevar permisos no resuelve una incompatibilidad de hardware. |
| Error de pantalla | Usa `--eyes none` si no hay sesión gráfica disponible. |
| La tira funciona pero no se escucha la voz | Prueba primero sin `--strip` y sin `sudo`. Root puede no acceder a la sesión PulseAudio/PipeWire; configura una salida ALSA disponible mediante `--audio-driver` y `--audio-device`. |
| Falla Gemini o FAISS | Repite con `--demo --mute` para comprobar la tira por separado y revisa la configuración del bot. |

Referencia: [guía oficial de Adafruit para NeoPixel en Raspberry Pi](https://learn.adafruit.com/neopixels-on-raspberry-pi/python-usage),
que documenta el entorno virtual y la ejecución con permisos de root.
