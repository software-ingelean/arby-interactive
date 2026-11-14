# Arby: animaciones de ojos aprobadas, 27 estados con RGB

Dos paneles de 32 × 32, cada uno con un ojo y su ceja. El lienzo lógico mide
64 × 32. Los dibujos se calculan con Pillow a resolución nativa; los GIF son
referencias y no se necesitan para ejecutar las animaciones.

## Archivos y reemplazo

Extrae el ZIP en la raíz de `arby-interactive`, combinando su carpeta `libraries`
con la que ya existe. Reemplaza solamente los archivos de ojos del mismo nombre.
Conserva tu `libraries/__init__.py` si ya existe: no se incluye otro para evitar
reemplazarlo. Python también puede importar esta carpeta como paquete namespace.

| Archivo del ZIP | Destino | Acción |
| --- | --- | --- |
| `libraries/eyes/arby_eyes.py` | `arby-interactive/libraries/eyes/arby_eyes.py` | Reemplazar o agregar; motor de las 27 animaciones |
| `libraries/examples/demo_eyes.py` | `arby-interactive/libraries/examples/demo_eyes.py` | Reemplazar o agregar; simulador actualizado |
| `libraries/eyes/matrix_output.py` | `arby-interactive/libraries/eyes/matrix_output.py` | Copiar si falta; adaptador físico, igual a la entrega anterior |
| `libraries/examples/export_previews.py` | `arby-interactive/libraries/examples/export_previews.py` | Reemplazar o agregar; herramienta opcional para regenerar GIF |
| `libraries/tests/test_eyes.py` | `arby-interactive/libraries/tests/test_eyes.py` | Reemplazar o agregar; pruebas sin hardware |
| `previews/` | `arby-interactive/previews/` | Referencias visuales opcionales |

Los archivos de Gemini, FAISS y TTS no necesitan reemplazo para instalar este motor.
Si conservabas la demo anterior en otra carpeta, usa ahora los comandos siguientes
para ejecutar la versión nueva.

## Instalar y probar sin matrices

Desde la raíz de tu proyecto:

```bash
uv add pillow pygame
uv run python -m libraries.examples.demo_eyes --auto
```

Esto actualiza `pyproject.toml` y `uv.lock`. En la Raspberry, después de subir esos
cambios al repositorio y hacer pull, ejecuta `uv sync`. Si las dos dependencias ya
están declaradas, basta con `uv sync` en el equipo donde harás la prueba.

La simulación necesita un escritorio gráfico. Por SSH sin pantalla puedes revisar
los GIF desde otro equipo. El motor de dibujo y el adaptador físico no requieren
Pygame: únicamente el simulador lo utiliza.

| Tecla | Acción |
| --- | --- |
| 1 | triste |
| 2 | alegres |
| 3 | sorprendidos |
| 4 | pensativos |
| 5 | locos |
| 6 | enojado |
| 7 | duda |
| 8 | guiño ojo |
| 9 | dormido |
| 0 | relato extenso |
| D | default / reposo |
| C | cargando |
| Espacio | Siguiente estado entre los 24; incluye todas las expresiones nuevas |
| A | Activar o desactivar el cambio automático cada cinco segundos |
| G | Mostrar u ocultar cuadrícula |
| Esc | Cerrar |

Ejemplos para iniciar en un estado específico:

```bash
uv run python -m libraries.examples.demo_eyes --state cargando
uv run python -m libraries.examples.demo_eyes --state enamorados
```

## Estados y diseño

Se conservan los diez nombres de emoción ya usados por Gemini:
`triste`, `alegres`, `sorprendidos`, `pensativos`, `locos`, `enojado`, `duda`,
`guiño ojo`, `dormido`, `relato extenso`.

Se suman quince expresiones, disponibles también para la conversación:

| Estado | Diseño |
| --- | --- |
| enamorados | Ojos de corazón con un pequeño latido |
| estrellas | Ojos de estrella pulsantes |
| gafas de sol | Lentes oscuros con montura, puente y reflejos animados |
| riendo | Ojos sonrientes con rebote más marcado |
| timidos | Mirada baja hacia los lados y cejas suaves |
| orgullosos | Mirada alta y ojos entrecerrados |
| relajados | Ojos bajos con movimiento de respiración |
| curiosos | Ojos asimétricos y mirada exploradora |
| asustados | Ojos altos, pupilas pequeñas y temblor |
| aburridos | Párpados bajos y mirada lenta |
| mareados | Ojos en espiral con movimiento |
| traviesos | Cejas opuestas y mirada lateral |
| dolares | Signos de dólar con rebote |
| aturdidos | Ojos en X con balanceo |
| risa nerviosa | Ojos sonrientes sin cejas y una gota de sudor azul en el panel derecho |

El catálogo de emociones y colores tiene una única fuente en
`libraries/core/arby_response.py`; el motor y el esquema del bot lo comparten.
Las instrucciones del bot explican cuándo usar cada expresión.

Se mantienen dos estados de aplicación: `default` y `cargando`. `EMOTION_STATES`
contiene las 25 emociones; `SYSTEM_STATES` contiene estos dos estados;
`STATES` reúne los 27 estados. El estado inicial de `EyeAnimator()` ahora es `default`.

| Estado actualizado | Diseño |
| --- | --- |
| alegres | Cejas gruesas muy arqueadas y ojos sonrientes con movimiento leve |
| sorprendidos | Cejas muy altas, ojos grandes y pupilas pequeñas |
| pensativos | Mirada arriba a un lado y ceja elevada frente a la otra más baja |
| duda | Gran asimetría entre cejas, un ojo entrecerrado y mirada lateral |
| default | Mirada tranquila, cejas relajadas y parpadeo |
| cargando | Pupilas en movimiento circular y cejas que suben alternadamente |

Las expresiones anteriores conservan su diseño. Las nuevas formas de corazón,
estrella y espiral se mezclan suavemente durante las transiciones.
Los cambios de estado duran 0,30 segundos; se interpolan geometría y cejas, y se
mezcla suavemente la forma sonriente al entrar o salir de `alegres`.

## Uso en tu aplicación

```python
from libraries.eyes.arby_eyes import EyeAnimator

eyes = EyeAnimator()  # default
eyes.set_state("cargando")
eyes.set_state("alegres")
frame = eyes.render()  # PIL.Image, RGB, 64x32
```

Crear el animador no abre una ventana ni envía imágenes a los paneles. Debes
mantener un bucle de dibujo a unos 30 fps que llame a `eyes.render()` y entregue
la imagen al simulador o al adaptador físico. Mantén este bucle activo mientras
esperas Gemini o el audio. Ejecuta Gemini y las esperas del TTS en un worker;
si usas Pygame, deja su ventana y eventos en el hilo principal.

En el worker de conversación, usando tus instancias `bot`, `tts` y `eyes`:

```python
def handle_text(text: str) -> dict:
    eyes.set_state("cargando")
    try:
        result = bot.respond(text)
        eyes.apply_response(result)
        if tts.speak(result["response"]):
            tts.wait()  # Wait in this worker while the render loop continues.
        return result
    finally:
        eyes.set_state("default")
```

Este fragmento muestra dónde cambiar los estados; no sustituye tu aplicación
completa ni crea el worker o el bucle de dibujo. No hace falta ampliar el esquema
de Gemini: `cargando` indica que tu programa está esperando y `default` que está
en reposo. La emoción de su respuesta se sigue tomando de `matrix_state`.

`apply_response(result)` aplica en una sola operación la expresión de `matrix_state`
y el RGB de `strip_led.color`, en el formato `{"r": 255, "g": 0, "b": 0}`.
Colorea ambos ojos y sus cejas con esos valores exactos y conserva el reflejo
blanco. Comprueba los canales enteros de 0 a 255 y la coincidencia de `mood`
con la emoción antes de cambiar el estado. El método no acciona la tira LED;
su controlador debe seguir consumiendo ese mismo `strip_led.color`.

Para aplicar un color directamente también puedes usar:

```python
eyes.set_state("alegres", color=(0, 255, 80))
```

Al pasar a `default` o `cargando` sin indicar un color, se restaura el estilo de
reposo configurado al crear el animador, cian por defecto. Una emoción sin RGB
conserva el color actual. Los GIF incluidos muestran la geometría con el estilo
cian de referencia; el color real se toma del diccionario durante la ejecución.

Para comprobar un color en la ventana, desde la raíz:

```bash
uv run python -m libraries.examples.demo_eyes --state enojado --color 255 0 0
```

`set_state()` vuelve inmediatamente y admite llamadas desde el worker. Repetir
el mismo estado no reinicia la transición. Un solo hilo debe llamar a `render()`
y a la salida física. Se normalizan tildes, mayúsculas y separadores; por ejemplo,
`Guiño_ojo` equivale a `guiño ojo`. También se aceptan `reposo` y `loading`.

## Salida física

```python
from libraries.eyes.arby_eyes import EyeAnimator
from libraries.eyes.matrix_output import MatrixOutput

eyes = EyeAnimator()
output = MatrixOutput(
    multiplexing=confirmed_mux,
    row_address_type=confirmed_row_type,
)
try:
    # Repeat this call in your existing render loop:
    output.show(eyes.render())
finally:
    output.close()
```

`confirmed_mux` y `confirmed_row_type` son valores que se validarán cuando estén
los paneles. El barrido 1/8 no determina por sí solo el mapper. No se debe pasar
automáticamente `8` a `multiplexing`. El adaptador mantiene los parámetros previos:
`rows=32`, `cols=32`, `chain_length=2`, `parallel=1`, `hardware_mapping="regular"`,
brillo 25 y slowdown 2. Para intercambiar izquierda y derecha usa `swap_eyes=True`.
El binding `rgbmatrix` debe estar instalado en el intérprete que ejecute el código.

El renderizado se comprobó sin hardware. El mapper, el direccionamiento y el
aspecto sobre los LED quedan pendientes de prueba con los paneles físicos.

## Verificación y GIF

```bash
uv run python -m unittest libraries.tests.test_eyes -v
uv run python -m libraries.examples.export_previews
```

La entrega superó catorce pruebas, incluidas las 144 combinaciones de transición entre
estados, los alias, el tamaño RGB de 64 × 32 y el contrato del adaptador simulado.
También se comprobaron colores en ambos paneles y sus cejas, validación sin
cambios parciales, actualización de RGB sin reiniciar la emoción y vuelta al color
de reposo.
Los controles D, C y Esc se comprobaron ejecutando Pygame con pantalla simulada.
`export_previews` genera el tablero y 27 GIF de 64 × 32 en `previews/`.

Referencias del controlador: [repositorio](https://github.com/hzeller/rpi-rgb-led-matrix),
[mapeo GPIO](https://github.com/hzeller/rpi-rgb-led-matrix/blob/master/wiring.md).
