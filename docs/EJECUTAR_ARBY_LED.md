# Ejecutar Arby con la tira LED

Arby se configura exclusivamente mediante variables de entorno. Edita `.env`
en la raíz del proyecto; `run_arby.py` y `main.py` se ejecutan sin argumentos.
Las variables exportadas por el proceso tienen prioridad sobre `.env`; los
valores vacíos conservan los predeterminados. `sudo` puede eliminar variables
exportadas, pero el script sigue leyendo `.env` desde la raíz del proyecto.

## Instalación en la Raspberry

No necesitas Python global. Usa `.venv` para el bot y la tira; los permisos de
GPIO son independientes del entorno Python. Desde la raíz del repositorio:

```bash
sudo apt update
sudo apt install ffmpeg
uv sync --extra led
```

Usa `--extra led` en futuras sincronizaciones para conservar los paquetes de
hardware. Si ejecutas mediante uv, usa `uv run --extra led python run_arby.py`.
No uses `sudo uv run` ni `sudo pip install`.

Esta guía corresponde al backend `board` + `neopixel`, LED RGB en orden GRB,
y datos en GPIO BCM12 (pin físico 32). Confirma la compatibilidad del backend
con tu modelo de Raspberry y sistema operativo. Conecta con la alimentación
apagada, usa una fuente de 5 V adecuada y masa común. No alimentes la tira
desde un GPIO.

## Configuración normal

Si todavía no tienes `.env`, créalo sin sobrescribir uno existente:

```bash
test -f .env || cp .env.example .env
```

Conserva tu clave y agrega o ajusta estas variables:

```dotenv
GEMINI_API_KEY=tu_clave
GEMINI_MODEL=gemini-flash-latest
ARBY_BOT_TIMEOUT=60
ARBY_EYES=none
ARBY_STRIP=true
ARBY_STRIP_GPIO=12
ARBY_STRIP_LEDS=82
ARBY_STRIP_BRIGHTNESS=20
ARBY_STRIP_EFFECT=solid
ARBY_DEMO=false
ARBY_MUTE=false
```

También puedes usar `GOOGLE_API_KEY`. La ejecución real requiere el índice y la
configuración del bot descritos en [la guía de integración](../README_integracion.md).
Ejecuta siempre desde la raíz con el mismo comando:

```bash
sudo "$(pwd)/.venv/bin/python" "$(pwd)/run_arby.py"
```

Para un equipo sin hardware, usa `.venv/bin/python run_arby.py` sin `sudo`.
`main.py` también lee las mismas variables. Los argumentos antiguos se rechazan
con un aviso antes de inicializar hardware o servicios.

## Perfiles de prueba

Modifica estas variables en `.env` y reinicia el programa tras cada cambio:

| Prueba | ARBY_EYES | ARBY_STRIP | ARBY_DEMO | ARBY_MUTE |
| --- | --- | --- | --- | --- |
| Tira sin Gemini ni voz | none | true | true | true |
| Simulación sin hardware ni servicios | none | false | true | true |
| Voz sin Gemini ni hardware (ejecutar sin sudo) | none | false | true | false |
| Gemini sin voz ni hardware | none | false | false | true |
| Bot completo con tira | none | true | false | false |

Escribe `alegres`, `pensativos` o `emociones` en modo demo. Para probar la voz,
escribe `/frase Hola, esta es una prueba de voz`. `salir` o Ctrl+C cierra y apaga
la tira. Con escritorio puedes elegir `ARBY_EYES=preview`; las matrices físicas
usan `ARBY_EYES=matrix` y requieren `ARBY_MULTIPLEXING` validado, además de
`rgbmatrix`. Consulta la guía de integración antes de activarlas.

## Variables adicionales

Consulta todas las variables en [`.env.example`](../.env.example).
Los booleanos aceptan `true/false`, `1/0`, `yes/no` y `on/off`.

| Variables | Uso |
| --- | --- |
| ARBY_VOICE, ARBY_RATE, ARBY_PITCH | Voz Edge TTS, velocidad y tono; por ejemplo `+12%` y `+0Hz`. |
| ARBY_FFPLAY | Nombre o ruta del reproductor ffplay. |
| ARBY_AUDIO_DRIVER, ARBY_AUDIO_DEVICE | Salida de audio disponible para el usuario que ejecuta Arby. |
| ARBY_MULTIPLEXING, ARBY_ROW_ADDRESS_TYPE | Configuración comprobada de los paneles físicos. |
| ARBY_MATRIX_BRIGHTNESS, ARBY_SLOWDOWN, ARBY_SWAP_EYES | Brillo, temporización e intercambio de ojos. |
| ARBY_STRIP_EFFECT | solid, breathing, bounce, center_out o ripple. |

## Problemas frecuentes

- Si falta `board`, `neopixel`, `gpiod` o `rpi_ws281x`, repite `uv sync --extra led`
  y ejecuta con el Python de `.venv`.
- Si aparece `Operation not permitted`, `mailbox` o acceso a `/dev/mem`, usa
  `sudo` con la ruta explícita al Python. Si persiste, revisa la compatibilidad
  del backend con la placa y el sistema operativo.
- Ante HTTP 504, prueba `ARBY_BOT_TIMEOUT=60`. Son segundos por intento y hay
  hasta tres intentos. Aumentarlo prolonga la espera y no garantiza resolver
  una demora del servidor.
- Si falla la voz, usa el perfil de voz sin hardware y sin `sudo`. Si funciona,
  repite con `sudo`: un fallo exclusivo de root apunta al acceso a la salida de
  audio. Ajusta `ARBY_AUDIO_DRIVER` y `ARBY_AUDIO_DEVICE` según tu dispositivo.
- Para separar fallos de Gemini/FAISS de los del hardware, usa el perfil de tira
  sin Gemini ni voz.

Referencia: [guía oficial de Adafruit](https://learn.adafruit.com/neopixels-on-raspberry-pi/python-usage).

## Jack analógico y tira en GPIO12

Con el backend PWM de `rpi_ws281x`, la tira en GPIO12 y el audio analógico
`bcm2835 Headphones` comparten PWM. Seleccionar otra tarjeta en `.env` no
resuelve esa colisión. Puede fallar la reproducción o aparecer un pitido.
Referencia: [limitaciones oficiales de rpi_ws281x](https://github.com/jgarff/rpi_ws281x#limitations).

Para aislarlo, cierra Arby y reinícialo con un perfil temporal sin tira ni matrices:

```bash
sudo env ARBY_STRIP=false ARBY_EYES=none ARBY_DEMO=true ARBY_MUTE=false \
  ARBY_AUDIO_DRIVER=alsa ARBY_AUDIO_DEVICE=plughw:CARD=Headphones,DEV=0 \
  "$(pwd)/.venv/bin/python" "$(pwd)/run_arby.py"
```

Escribe `/frase Prueba de audio`. Las variables de este comando tienen prioridad
sobre `.env` y no modifican el archivo. Si funciona, usa audio USB/HDMI o adapta
el control LED a un periférico compatible antes de volver a usar ambos juntos.

## Cierre y diagnóstico de voz

`salir`, Ctrl+C, SIGTERM y SIGHUP solicitan el cierre de recursos. Arby cancela
la síntesis, cierra la entrada del reproductor y termina su propio `ffplay`,
escalando a kill si no responde. No termina reproductores externos ni las
pruebas `speaker-test` que se hayan iniciado por separado. SIGKILL o una pérdida
de alimentación no permiten ejecutar la limpieza de Python.

Los fallos de voz muestran el driver, el dispositivo y el diagnóstico de
`ffplay`; incluye esa información al reportar problemas.

### Prueba experimental de recuperación del jack al cerrar

Esta opción está desactivada por defecto. Después de cerrar la voz, las matrices
si las hay, y liberar correctamente la tira con `deinit()`, intenta abrir y cerrar
el jack mediante un cuarto de segundo de silencio PCM con `aplay`. El comando
se limita a tres segundos; si falta `aplay` o falla el dispositivo, avisa y no
impide terminar. No cambia el mezclador, descarga módulos ni reinicia servicios.

Para activarla en `.env`:

```dotenv
ARBY_AUDIO_DRIVER=alsa
ARBY_AUDIO_DEVICE=plughw:CARD=Headphones,DEV=0
ARBY_AUDIO_RECOVER_ON_EXIT=true
```

Requiere `aplay` del paquete `alsa-utils`. La recuperación solo se ejecuta si
`ARBY_STRIP=true`; también se intenta ante un fallo posterior del arranque si
la tira ya fue creada y se libera correctamente. No se abre el jack si falla
la liberación de la tira. Si la inicialización de la propia tira falla antes
de devolver su controlador, solo se aplica su limpieza interna.

Ejecuta `sudo "$(pwd)/.venv/bin/python" "$(pwd)/run_arby.py"`, espera a que arranque
y termina con Ctrl+C. Compara si queda el pitido con esta opción activada y con
`ARBY_AUDIO_RECOVER_ON_EXIT=false`. El mensaje de finalización confirma únicamente
que ALSA aceptó el silencio; no puede verificar que el pitido haya desaparecido.
Este experimento no soluciona el conflicto de PWM mientras tira y jack funcionan
a la vez. Para deshacerlo, vuelve a poner la opción en `false`.
