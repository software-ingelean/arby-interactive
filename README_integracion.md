# Integración de Arby: emociones por oración

La entrada actual es texto escrito en consola. La aplicación usa `ArbyBot`
con respuestas divididas en segmentos, tu `ArbyTTS` de Edge con reproducción de cada frase completa mediante ffplay y las
animaciones de ojos aprobadas. La tira conserva 55 NeoPixel, GPIO BCM12, orden
GRB y brillo inicial de 20 %, como en el archivo que enviaste.

## Archivos que debes agregar o reemplazar

Extrae el ZIP en la raíz de `arby-interactive`, combinando la carpeta `libraries`
con la existente. No reemplaces la carpeta completa ni su `__init__.py`.

| Archivo | Acción |
| --- | --- |
| `run_arby.py` | Configuración, consola, composición de dispositivos y bucle principal |
| `libraries/simulation/arby_demo_bot.py` | Bot de demostración sin conexión |
| `libraries/simulation/arby_memory_pixels.py` | Tira LED simulada en memoria |
| `libraries/simulation/arby_muted_tts.py` | Adaptador de voz silencioso |
| `libraries/preview/arby_preview.py` | Vista previa de ojos y tira LED con Pygame |
| `main.py` | Entrada mínima opcional; úsala si quieres que este sea tu main principal |
| `libraries/core/arby_runtime.py` | Agregar; coordina cola, Gemini, voz y estado visual |
| `libraries/bot/arby_bot.py` | Reemplazar; nuevo esquema de segmentos y reglas de charla natural |
| `libraries/core/arby_response.py` | Agregar; contrato compartido, validación, paleta y esquema de Gemini |
| `libraries/leds/arby_strip_led.py` | Agregar; adaptador sin bucles bloqueantes para la tira |
| `libraries/leds/control_tira_led.py` | Copiar tu archivo original a esta ruta; se incluye sin cambios |
| `libraries/eyes/arby_eyes.py` | Reemplazar por la copia incluida, con `apply_response` y soporte RGB |
| `libraries/eyes/matrix_output.py` | Reemplazar; agrega la opción para compartir el periférico PWM con NeoPixel |
| `tests/test_integration.py` | Agregar; pruebas que no requieren Raspberry, API ni audio |
| `tests/test_segments.py` | Agregar; pruebas del nuevo formato y sincronización por segmento |

Conserva tus versiones actuales de `arby_knowledge.py`,
`arby_tts.py`, `contexto_arby.md` y `faiss_index/`. Este ZIP no los sustituye.
El bot incluido devuelve `segments` y un `response` agregado calculado en Python.
Cada segmento tiene `matrix_state`, `strip_led` y `response`, y el bot continúa
exponiendo `EMOTION_COLORS`. La librería TTS debe tener `speak`, `wait`, `stop`
y `close`, como en la interfaz de voz existente.

Si tu `main.py` ya hace otras tareas, consérvalo y ejecuta `run_arby.py`
directamente. Para llamar esta aplicación desde un main dedicado:

```python
from run_arby import main

if __name__ == "__main__":
    raise SystemExit(main())
```

La función `main()` ocupa el hilo principal mientras funciona Arby, para
mantener allí Pygame y los dispositivos. No debe llamarse desde un worker de GUI.

Si ya habías instalado la integración anterior, reemplaza `libraries/bot/arby_bot.py`,
`libraries/core/arby_runtime.py` y `run_arby.py`, y agrega `libraries/core/arby_response.py`
y los módulos de simulación y vista previa de la tabla anterior.
Los demás módulos de hardware de este ZIP conservan la versión anterior.
Actualiza las pruebas y esta guía si las utilizas. No hay dependencias nuevas ni
necesitas reconstruir el índice FAISS, porque las reglas cambian en el prompt del bot.

## Dependencias

Para instalar y ejecutar `run_arby.py` con GPIO12 paso a paso, consulta la
[guía de ejecución con LED](docs/EJECUTAR_ARBY_LED.md). No necesitas un Python
global: puedes ejecutar el Python de `.venv` con permisos de administrador.

Desde la raíz, si no están todavía declaradas:

```bash
uv add pillow pygame
```

En la Raspberry, las dependencias de tu controlador NeoPixel deben estar en el
mismo entorno que ejecuta Arby. Si ya funcionaba allí con ese entorno, conserva
esa instalación. Si faltan, agrégalas desde la Raspberry:

```bash
uv sync --extra led
```

Mantén también las dependencias actuales del bot y `edge-tts`. `ffplay` debe estar
instalado en el sistema o indicado con `ARBY_FFPLAY` en `.env`. Después de versionar los
cambios de `pyproject.toml` y `uv.lock`, en la Raspberry haz pull y
`uv sync --extra led`. Conserva `--extra led` en futuras sincronizaciones o
ejecuciones mediante `uv run --extra led` para mantener los paquetes de hardware.

## Primera ejecución con Gemini y voz

Configura todo en `.env`; `run_arby.py` y `main.py` ya no aceptan argumentos.
Usa `ARBY_DEMO=false` y `ARBY_MUTE=false` para la ejecución real. Para escritorio
usa `ARBY_EYES=preview`; por SSH usa `ARBY_EYES=none`. Activa la tira con
`ARBY_STRIP=true`, configura `ARBY_STRIP_LEDS` y sincroniza con `uv sync --extra led`.
Consulta [los perfiles de ejecución](docs/EJECUTAR_ARBY_LED.md).

En un equipo con escritorio, sin activar GPIO ni requerir matrices:

```bash
uv run python run_arby.py
```

Verás los ojos y una tira simulada; escribe en la consola. La ventana debe
permanecer abierta. Esta ejecución usa Gemini y Edge TTS reales, requiere la
clave ya configurada y el índice FAISS de tu proyecto.

Para la Raspberry con la tira real conectada y todavía sin matrices físicas:

```bash
uv run --extra led python run_arby.py
```

Si estás conectado por SSH sin escritorio, usa:

```bash
uv run --extra led python run_arby.py
```

`ARBY_EYES=none` solo desactiva la salida de ojos; la consola, Gemini, voz y tira
continúan funcionando. La aplicación admite también `main.py` con las mismas
variables de entorno.

Si el controlador GPIO requiere root, usa el Python de tu entorno, conservando
las variables de la API:

```bash
sudo --preserve-env=GEMINI_API_KEY,GOOGLE_API_KEY,GEMINI_MODEL .venv/bin/python run_arby.py
```

No ejecutes `sudo uv run`, pues puede usar otro entorno/configuración de uv.
La reproducción con sudo depende de los permisos y la salida de audio del
sistema: si la sesión de escritorio usa PulseAudio/PipeWire, root puede no
tener acceso a esa sesión. Las opciones `ARBY_AUDIO_DRIVER` y `ARBY_AUDIO_DEVICE`
se pasan al `TTSConfig` existente para usar una salida que esté disponible en
el usuario de ejecución. La prueba sin GPIO permite verificar la voz por separado.

## Comandos de consola

| Entrada | Resultado |
| --- | --- |
| Cualquier texto | Se envía a Gemini y la respuesta se reproduce |
| `reiniciar` | Reinicia el contexto de conversación cuando le toque en la cola |
| `/frase Hola, gracias por cuidarme.` | Prueba una frase fija sin consultar Gemini |
| `salir` | Detiene reproducción, cancela solicitudes pendientes y apaga las salidas |
| Ctrl+C / Esc / cerrar ventana | Cierre de la aplicación |

La cola admite ocho solicitudes pendientes y un único trabajo activo. Puedes
escribir mientras Arby habla: los textos se procesan en orden, sin mezclar las
voces. Si la cola se llena, se informa y no se acepta ese texto. `reiniciar` no
interrumpe una frase en curso. `salir` sí solicita detenerla.

La consola lee en un hilo de entrada, por lo que los mensajes de Arby pueden
aparecer mientras se ve el indicador `Tú:`. El fin de entrada (EOF) termina
después de procesar la cola; `salir` cancela la cola inmediatamente.

## Comportamiento visual

| Momento | Ojos | Tira |
| --- | --- | --- |
| Reposo | `default`, cian | Respiración suave cian |
| Esperando Gemini | `cargando`, cian | Punto con cola y rebote, cian |
| Respuesta / reproducción | Emoción y RGB recibidos | RGB recibido, fijo por defecto |
| Fin de reproducción | Regresa a reposo | Regresa a respiración suave |

Gemini recibe un esquema que pide exclusivamente `{"segments": [...]}`. Cada
elemento representa una oración completa o una intervención corta coherente:

```python
{
    "segments": [
        {
            "matrix_state": "alegres",
            "strip_led": {
                "color": {"r": 0, "g": 255, "b": 80},
                "mood": "alegres",
            },
            "response": "Sí Luis, qué bueno verte.",
        },
        {
            "matrix_state": "pensativos",
            "strip_led": {
                "color": {"r": 120, "g": 60, "b": 255},
                "mood": "pensativos",
            },
            "response": "Eso me dejó pensando.",
        },
    ],
}
```

El resultado de `bot.respond()` incluye también `response` con el texto completo
de todos los segmentos, unido por espacios, para mostrarlo o registrarlo.
Este campo se calcula en Python; no es una segunda versión redactada por Gemini.
El runtime imprime ese texto una sola vez y reproduce exclusivamente los textos
de `segments`, por lo que no repite el audio.

Se valida toda la lista antes de reproducir el primer segmento. Por cada segmento
se aplica su emoción y RGB a ojos, cejas y tira, se reproduce solo ese texto y se
espera su final antes de pasar al siguiente. No se vuelve a reposo entre oraciones;
el regreso a reposo ocurre después de terminar el último segmento.

La capa TTS actual recibe una solicitud por segmento. Esto permite cambiar los
gestos en los límites de frase sin estimar tiempos por cantidad de caracteres,
pero puede añadir una pausa o demora de red entre oraciones. No se ha implementado
precarga de audio ni sincronización por palabras. La entonación de Edge conserva
las limitaciones del motor; los metadatos de emoción no le añaden control actoral.

El prompt pide normalmente una a tres oraciones, con un máximo de ocho segmentos.
Puede repetir una emoción en segmentos contiguos: no se inventan cambios de ánimo
para rellenar la lista. El límite de salida se elevó de 1.024 a 2.048 tokens para
dar espacio a los metadatos, sin pedir respuestas más largas. El esquema obliga
a la estructura; la segmentación lingüística y el tono dependen de que el modelo
siga las instrucciones y deben evaluarse con conversaciones reales.

También se añadió una regla explícita para hablar de manera cotidiana:
preferir «Sí Luis, eso también me pasa» frente a «Sí, Luis. Eso también me pasa»,
integrar los nombres en la idea, no cortar por comas y no usar mayúsculas para
simular emociones. Se mantienen las reglas de brevedad, preguntas ocasionales
y referencias personales solo cuando aportan algo.

Si usabas una integración propia, ya no existe una única emoción en la raíz:
itera sobre `result["segments"]`. `eyes.apply_response(segment)` sigue funcionando
para cada elemento, pero no recibe la respuesta completa. Usa preferiblemente
el runtime, que ya coordina luces y audio en el orden correcto.

Se utilizan los valores RGB de cada segmento. El orden GRB es una opción
del controlador físico, no cambia el orden `r`, `g`, `b` del diccionario.
La tira tiene su brillo global al 20 %; por eso el RGB lógico y su intensidad
física no son equivalentes. En respiración y rebote se modula la intensidad sin
cambiar la proporción entre canales. Durante TTS se muestra la emoción desde
que empieza la solicitud de voz de ese segmento hasta que termina su reproducción.

Puedes elegir otro efecto configurando `ARBY_STRIP_EFFECT=ripple` en `.env`:

```bash
uv run --extra led python run_arby.py
```

Efectos admitidos: `solid`, `breathing`, `bounce`, `center_out`, `ripple`.
`center_out` y `ripple` reutilizan la función `expansion` de tu archivo original.
El menú original sigue disponible si ejecutas ese archivo por separado, pero
no lo ejecutes a la vez que Arby sobre los mismos LED.

## Modelo y voz

Se conserva el modelo que el bot elige actualmente y los valores por defecto de
tu `TTSConfig`. Este paquete continúa con Edge TTS; no migra a Gemini TTS.

Para cambiar la voz, configura `ARBY_VOICE=es-MX-JorgeNeural`,
`ARBY_RATE=+12%` y `ARBY_PITCH=+0Hz` en `.env`:

```bash
uv run python run_arby.py
```

Fija el modelo principal con `GEMINI_MODEL` y las alternativas con
`GEMINI_FALLBACK_MODELS`, separadas por comas (por defecto `gemini-flash-lite-latest`).
Una lista vacía desactiva las alternativas. Usa modelos disponibles para tu clave
que admitan salida JSON estructurada; los nombres duplicados se eliminan.
Ante HTTP 404, 408, 429, 500, 502, 503, 504 o fallos de conexión/timeout,
se prueba el siguiente modelo conservando historial y contexto. Cada modelo se
intenta una vez por respuesta, sin reintentos adicionales del SDK.
El modelo fallido queda en pausa `ARBY_MODEL_COOLDOWN_SECONDS` (60 segundos);
luego vuelve a probarse en orden de prioridad. Si todos fallan o están en pausa,
Arby devuelve su respuesta local de error sin agregarla al historial.
Errores de autenticación, permisos o entrada inválida no activan cambios de modelo.
Los logs indican el modelo fallido sin imprimir mensajes del proveedor;
`bot.last_model` indica qué modelo devolvió la última generación.
`ARBY_BOT_TIMEOUT` se aplica por intento: la espera total puede crecer con el pool.
Cambiar de modelo no elimina cuotas compartidas del proyecto ni límites de gasto.
Consulta los [límites de Gemini](https://ai.google.dev/gemini-api/docs/rate-limits).
`ARBY_FFPLAY` acepta el nombre `ffplay` o una ruta del equipo donde ejecutas.

## STT y sensores: puntos de conexión preparados

La entrada de consola llama a este método público:

```python
future = runtime.submit_text(recognized_text)
```

Cuando tengamos STT, su callback entregará el string a ese mismo método. Vuelve
inmediatamente y devuelve un `Future`; no llames `future.result()` desde el
hilo de dibujo ni desde un callback que deba volver rápido.

Para un sensor que seleccione una frase fija:

```python
future = runtime.submit_fixed_phrase(
    "Gracias por cuidarme.",
    state="alegres",
)
```

El ejemplo usa una frase de prueba: no se ha inventado una biblioteca de sensores
ni un catálogo definitivo. La frase pasa por el mismo reproductor y no entra en
el historial de Gemini. Su color se obtiene de `EMOTION_COLORS` del bot, salvo
que proporciones `color=(r, g, b)`.

Por ahora estas frases se sintetizan con el TTS actual. Si la librería pendiente
trae audios fijos precargados, adaptaremos su reproducción al mismo coordinador
para conservar la exclusión de audio. No se han cambiado ni eliminado tus
archivos de frases o reproductores anteriores; no los uses en paralelo hasta
conectarlos al coordinador.

## Matrices físicas y PWM

El modo físico está preparado, pero aún necesita el `multiplexing` y el
direccionamiento comprobados con tus paneles 32 × 32 de barrido 1/8. No se
selecciona `8` automáticamente. El programa exige ese parámetro antes de iniciar.

Se mantiene el cableado `regular` y la cadena de dos paneles. Cuando se active
la tira real junto con las matrices, el runner pasa
`disable_hardware_pulsing=True` al driver de matrices. Esto reserva el periférico
PWM para NeoPixel y genera los pulsos de la matriz por software. Puede afectar
la estabilidad de la imagen y deberá comprobarse sobre el hardware.

Es una precaución basada en que NeoPixel emplea PWM/DMA y el driver HUB75 también
puede usar PWM para OE. Además se rechaza asignar la tira a uno de los GPIO ya
ocupados por las matrices. Se inicializa la tira antes del driver de matrices,
porque este último puede reducir los privilegios después de arrancar.

Referencias: [NeoPixel en Raspberry Pi](https://learn.adafruit.com/neopixels-on-raspberry-pi),
[opciones de matriz](https://github.com/hzeller/rpi-rgb-led-matrix/blob/master/include/led-matrix.h).

## Prueba completamente offline

Configura `ARBY_DEMO=true`, `ARBY_MUTE=true`, `ARBY_STRIP=false` y
`ARBY_EYES=preview` en `.env` antes de ejecutar:

```bash
uv run python run_arby.py
```

No usa Gemini, FAISS, ffplay ni GPIO. Escribe `emociones` para ver dos oraciones
consecutivas con alegría y reflexión. También admite nombres de emociones, por ejemplo
`enojado`, `triste` o `sorprendidos`, para comprobar el recorrido y los colores.
La ventana muestra también la tira simulada y sus efectos. `ARBY_MUTE=true` mantiene
la expresión medio segundo para que sea visible.

Ejecutar pruebas:

```bash
uv run python -m unittest discover -s tests -v
```

Se verificaron 28 pruebas: cola y orden, estado de carga durante la consulta,
emoción hasta fin del audio, RGB, frases fijas sin Gemini, recuperación de errores,
cierre sin voz tardía, cancelación de pendientes, validación del mapper/GPIO,
efectos y limpieza de la tira con un controlador simulado; esquema por oración,
emoción hasta terminar cada audio, cancelación de segmentos pendientes, validación
de toda la lista antes de hablar e instrucciones del bot con SDK simulado. También se ejecutó
la aplicación con Pygame y pantalla simulada. No se ha probado aquí el hardware
real, el audio real ni una solicitud real a tu API.

Al cerrar se solicita detener el audio y se espera hasta cinco segundos al worker.
Una consulta a Gemini que ya estaba en curso no puede abortarse desde esta capa;
si termina después del cierre, su resultado se descarta y no se reproduce.

## Respuestas automáticas con Trill Craft

Activa `ARBY_TRILL=true` en `.env` y ejecuta `.venv/bin/python run_arby.py`
(o `main.py`). El sensor se escucha en paralelo a la conversación por consola.
La conversación sigue usando Gemini; los toques usan frases automáticas sin
consultar Gemini ni modificar el historial. Conserva la voz TTS, ojos y tira
configurados para Arby. Para ejecutarlo sin ventana usa `ARBY_EYES=none`;
la integración del sensor no importa el script de prueba ni pygame.
`ARBY_TRILL=false` desactiva únicamente el sensor. Para probar sin Gemini,
usa `ARBY_DEMO=true`. Sal con `salir` o Ctrl+C; si la consola recibe EOF,
el sensor sigue activo hasta Ctrl+C.

Se reutiliza `config/triki_config.json`: bus I2C 1, dirección `0x30`, modo
DIFF, prescaler, umbral de ruido, umbrales de toque/liberación, intervalo de
lectura y duración de toque sostenido. Las zonas iniciales son cabeza (0–3),
barriga (4–7), mano (8–11), saludo (12–13) y ayuda (14–15). Cambia `zones`
para que coincida con tu cableado. Inicia sin tocar los electrodos: el sensor
calibra la línea base al abrirse. I2C debe estar habilitado y accesible para
el usuario que ejecuta Arby; `smbus2` ya está declarado como dependencia.

Las frases y emociones están en `libraries/core/arby_touch.py`. Se confirma
cada toque con dos lecturas y se detectan toques sostenidos y cuatro toques
en diez segundos. Los canales sin zona se ignoran. Los eventos durante una
respuesta, una consulta a Gemini o durante `speech_cooldown_seconds` se
descartan, sin acumular voz. Si escribes durante una reacción al toque,
la conversación se encola y continúa al terminar esa reacción. La lectura
del sensor, la consola y las animaciones continúan mientras trabaja el bot;
la voz y las expresiones se coordinan mediante una sola cola de respuestas.
Las opciones de audio y pantalla del antiguo JSON no se utilizan: voz y
salidas se configuran con las variables `ARBY_*` de `.env`.
Un error de lectura I2C detiene la aplicación y libera sus recursos.

### Conversación por micrófono

Instala el grupo opcional con `uv sync --extra voice` y configura
`ARBY_INPUT_MODE=voice` en `.env`. Ejecuta `uv run --extra voice run_arby.py`.
Para volver al teclado usa `ARBY_INPUT_MODE=text` (predeterminado si no existe
la variable). `ARBY_MUTE` controla la salida de voz de forma independiente.
En Linux, sounddevice necesita PortAudio del sistema (`libportaudio2` en Debian).

La entrada reutiliza `libraries/voice_input/arby_google_vad_iir.py`: captura
I2S estéreo S32 a 48 kHz, filtro IIR con estado, limitador, remuestreo a 16 kHz,
Silero ONNX y reconocimiento Google en un hilo separado. La dependencia
`silero-onnx` procede del repositorio del autor y queda fijada en `uv.lock`.
El reconocimiento Google requiere conexión a Internet.

Di **“Arby, ¿qué puedes hacer?”**, o **“Arby”** y luego tu pregunta
antes de 8 segundos. Cada nueva pregunta requiere activación, como en el script
original. No hay saludo hablado adicional al activar. La pregunta se envía al
mismo runtime que coordina Gemini, voz, emociones y LED. Trill sigue funcionando
en paralelo. Mientras hay una respuesta pendiente, se descarta audio de entrada;
se retoma la escucha 350 ms después para reducir la captación de la propia voz.
Se vacían las colas y el estado de audio al retomar; no hay interrupción por voz.

`ARBY_MIC_DEVICE` selecciona el índice PortAudio o el nombre de la entrada;
`ARBY_AUDIO_DEVICE` sigue seleccionando la salida. Para listar entradas:
`uv run --extra voice python -m sounddevice`. El canal predeterminado es `left`;
puedes usar `ARBY_MIC_CHANNEL=right`. Los demás ajustes están en `.env.example`.
Las colas son acotadas y cada segmento se limita a 15 segundos para controlar
memoria y latencia; al llegar al límite se envía ese segmento al reconocimiento.
Ctrl+C, SIGTERM y el cierre de la ventana detienen también la captura.
