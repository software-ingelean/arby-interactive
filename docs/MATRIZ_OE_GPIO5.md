# Matrices con OE en GPIO5

Se conserva el pinout regular de la primera cadena y solo se mueve OE:
BCM18 (pin físico 12) → BCM5 (pin físico 29). Los dos paneles van encadenados
OUT → IN, con parallel=1. La tira conserva BCM12 (pin físico 32) y Trill
conserva I²C1 (BCM2/BCM3). No confundir BCM12 con pin físico 12.

El binding estándar no permite asignar OE arbitrariamente desde Python.
Hay que agregar el mapeo al código fuente y reinstalar el binding compilado.
El mapeo nuevo se llama regular-oe5; el regular original sigue disponible.
Se omiten las cadenas paralelas adicionales para evitar la colisión de OE
con G1 de la segunda cadena paralela. Esto no limita los dos paneles en serie.
El pulso por hardware se desactiva automáticamente al seleccionar regular-oe5.

## Preparar el controlador en la Raspberry

Desde la raíz de Arby, suponiendo que el repositorio del controlador está en
~/rpi-rgb-led-matrix (ajusta esa ruta si es diferente):

```bash
python3 herramientas/preparar_mapping_oe5.py ~/rpi-rgb-led-matrix
```

La herramienta guarda lib/hardware-mapping.c.arby-backup antes del cambio.
Para un checkout actual que admite instalación desde la raíz:

```bash
uv pip install --python .venv/bin/python --reinstall ~/rpi-rgb-led-matrix
```

Esto compila e instala el código local modificado; no uses una instalación
desde GitHub porque no incluiría el mapeo personalizado. Si tu checkout antiguo
solo admite setup.py en bindings/python, usa en cambio:

```bash
make -C ~/rpi-rgb-led-matrix clean
make -C ~/rpi-rgb-led-matrix
uv pip install --python .venv/bin/python --reinstall ~/rpi-rgb-led-matrix/bindings/python
```

No hace falta sudo para instalar dentro de .venv. Si falta compilador o cabeceras,
resuelve el error de compilación antes de mover el cable.

## Conexión y prueba

Con Raspberry y paneles apagados, mueve únicamente el cable OE de BCM18 al
BCM5 (pin físico 29). Conserva los demás cables, alimentación y GND común.
Con el archivo diagnosticos/matrix_scan.py actualizado:

```bash
sudo .venv/bin/python -m diagnosticos.matrix_scan --chain-length 2 --mux 6 --hardware-mapping regular-oe5 --seconds 5
```

Si dice que regular-oe5 no existe, todavía está cargando un binding sin el cambio.
Puedes localizarlo con `.venv/bin/python -c 'import rgbmatrix; print(rgbmatrix.__file__)'`.

Para Arby, configura en tu .env:

```dotenv
ARBY_EYES=matrix
ARBY_MATRIX_MAPPING=regular-oe5
ARBY_MULTIPLEXING=6
ARBY_STRIP_GPIO=12
```

Conserva el multiplexado que hayas confirmado en tus paneles si difiere de 6.
Ejecuta `sudo .venv/bin/python run_arby.py` desde la raíz del proyecto.
Para los ojos sin bot:

```bash
sudo .venv/bin/python -m libraries.examples.demo_eyes --backend matrix --multiplexing 6 --hardware-mapping regular-oe5 --brightness 10 --slowdown 4 --auto
```

Mover OE no garantiza resolver el conflicto entre el audio analógico y la tira
NeoPixel en BCM12: ambos pueden seguir compartiendo PWM.

Referencias: https://github.com/hzeller/rpi-rgb-led-matrix/blob/master/lib/hardware-mapping.c
y https://github.com/hzeller/rpi-rgb-led-matrix/blob/master/bindings/python/README.md.
