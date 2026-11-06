# Integración de Arby: emociones por oración

La entrada actual es texto escrito en consola. La aplicación usa `ArbyBot`
con respuestas divididas en segmentos, tu `ArbyTTS` de Edge con streaming a ffplay y las
animaciones de ojos aprobadas. La tira conserva 55 NeoPixel, GPIO BCM12, orden
GRB y brillo inicial de 20 %, como en el archivo que enviaste.

## Archivos que debes agregar o reemplazar

Extrae el ZIP en la raíz de `arby-interactive`, combinando la carpeta `libraries`
con la existente. No reemplaces la carpeta completa ni su `__init__.py`.

| Archivo | Acción |
| --- | --- |
| `run_arby.py` | Agregar en la raíz; compone los dispositivos y ejecuta la aplicación |
| `main.py` | Entrada mínima opcional; úsala si quieres que este sea tu main principal |
| `libraries/arby_runtime.py` | Agregar; coordina cola, Gemini, voz y estado visual |
| `libraries/arby_bot.py` | Reemplazar; nuevo esquema de segmentos y reglas de charla natural |
| `libraries/arby_response.py` | Agregar; contrato compartido, validación, paleta y esquema de Gemini |
| `libraries/arby_strip_led.py` | Agregar; adaptador sin bucles bloqueantes para la tira |
| `libraries/control_tira_led.py` | Copiar tu archivo original a esta ruta; se incluye sin cambios |
| `libraries/arby_eyes.py` | Reemplazar por la copia incluida, con `apply_response` y soporte RGB |
| `libraries/matrix_output.py` | Reemplazar; agrega la opción para compartir el periférico PWM con NeoPixel |
| `tests/test_integration.py` | Agregar; pruebas que no requieren Raspberry, API ni audio |
| `tests/test_segments.py` | Agregar; pruebas del nuevo formato y sincronización por segmento |

Conserva tus versiones actuales de `arby_knowledge.py`,
`arby_tts.py`, `contexto_arby.md` y `faiss_index/`. Este ZIP no los sustituye.
El bot incluido devuelve `segments` y un `response` agregado calculado en Python.
Cada segmento tiene `matrix_state`, `strip_led` y `response`, y el bot continúa
exponiendo `EMOTION_COLORS`. La librería TTS debe tener `speak`, `wait`, `stop`
y `close`, como en la versión de streaming que ya usamos.

Si tu `main.py` ya hace otras tareas, consérvalo y ejecuta `run_arby.py`
directamente. Para llamar esta aplicación desde un main dedicado:

```python
from run_arby import main

if __name__ == "__main__":
    raise SystemExit(main())
```

La función `main()` ocupa el hilo principal mientras funciona Arby, para
mantener allí Pygame y los dispositivos. No debe llamarse desde un worker de GUI.

Si ya habías instalado la integración anterior, reemplaza `libraries/arby_bot.py`,
`libraries/arby_runtime.py` y `run_arby.py`, y agrega `libraries/arby_response.py`.
Los demás módulos de hardware de este ZIP conservan la versión anterior.
Actualiza las pruebas y esta guía si las utilizas. No hay dependencias nuevas ni
necesitas reconstruir el índice FAISS, porque las reglas cambian en el prompt del bot.

## Dependencias

Desde la raíz, si no están todavía declaradas:

```bash
uv add pillow pygame
```

En la Raspberry, las dependencias de tu controlador NeoPixel deben estar en el
mismo entorno que ejecuta Arby. Si ya funcionaba allí con ese entorno, conserva
esa instalación. Si faltan, agrégalas desde la Raspberry:

```bash
uv add adafruit-blinka adafruit-circuitpython-neopixel
```

Mantén también las dependencias actuales del bot y `edge-tts`. `ffplay` debe estar
instalado en el sistema o indicado con `--ffplay RUTA`. Después de versionar los
cambios de `pyproject.toml` y `uv.lock`, en la Raspberry haz pull y `uv sync`.
No se incluye un nuevo `pyproject.toml` para evitar cambiar tu resolución de
PyTorch y las otras dependencias del proyecto.

## Primera ejecución con Gemini y voz

En un equipo con escritorio, sin activar GPIO ni requerir matrices:

```bash
uv run python run_arby.py --eyes preview
```

Verás los ojos y una tira simulada; escribe en la consola. La ventana debe
permanecer abierta. Esta ejecución usa Gemini y Edge TTS reales, requiere la
clave ya configurada y el índice FAISS de tu proyecto.

Para la Raspberry con la tira real conectada y todavía sin matrices físicas:

```bash
uv run python run_arby.py --eyes preview --strip
```

Si estás conectado por SSH sin escritorio, usa:

```bash
uv run python run_arby.py --eyes none --strip
```

`--eyes none` solo desactiva la salida de ojos; la consola, Gemini, voz y tira
continúan funcionando. La aplicación admite también `main.py` con los mismos
argumentos.

Si el controlador GPIO requiere root, usa el Python de tu entorno, conservando
las variables de la API:

```bash
sudo --preserve-env=GEMINI_API_KEY,GOOGLE_API_KEY,GEMINI_MODEL .venv/bin/python run_arby.py --eyes none --strip
```

No ejecutes `sudo uv run`, pues puede usar otro entorno/configuración de uv.
La reproducción con sudo depende de los permisos y la salida de audio del
sistema: si la sesión de escritorio usa PulseAudio/PipeWire, root puede no
tener acceso a esa sesión. Las opciones `--audio-driver` y `--audio-device`
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

Puedes elegir otro efecto durante las respuestas:

```bash
uv run python run_arby.py --eyes preview --strip --strip-effect ripple
```

Efectos admitidos: `solid`, `breathing`, `bounce`, `center_out`, `ripple`.
`center_out` y `ripple` reutilizan la función `expansion` de tu archivo original.
El menú original sigue disponible si ejecutas ese archivo por separado, pero
no lo ejecutes a la vez que Arby sobre los mismos LED.

## Modelo y voz

Se conserva el modelo que el bot elige actualmente y los valores por defecto de
tu `TTSConfig`. Este paquete continúa con Edge TTS; no migra a Gemini TTS.

Para cambiar solo la voz desde la ejecución:

```bash
uv run python run_arby.py --eyes preview --voice es-MX-JorgeNeural --rate=+12% --pitch=+0Hz
```

Puedes fijar el modelo con `--model` o conservar tu variable `GEMINI_MODEL`.
`--ffplay` acepta el nombre `ffplay` o una ruta del equipo donde ejecutas.

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

```bash
uv run python run_arby.py --demo --mute --eyes preview
```

No usa Gemini, FAISS, ffplay ni GPIO. Escribe `emociones` para ver dos oraciones
consecutivas con alegría y reflexión. También admite nombres de emociones, por ejemplo
`enojado`, `triste` o `sorprendidos`, para comprobar el recorrido y los colores.
La ventana muestra también la tira simulada y sus efectos. `--mute` mantiene
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
