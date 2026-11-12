# Modo oficina y evento de Arby

Copia los archivos de este paquete sobre la raíz de `arby-interactive`, conservando `libraries/` y `assets/ambient/`. Usa `run_arby.py` como punto de entrada. Los clips WAV son efectos sintetizados de silbido y tarareo, de aproximadamente uno y dos segundos. Se reproducen localmente con el `ffplay` y la salida de audio configurados para Arby.

## Seleccionar el modo

En Raspberry Pi, ejecuta desde la raíz del proyecto:

```bash
.venv/bin/python -m libraries.core.arby_ambient evento
.venv/bin/python -m libraries.core.arby_ambient ver
```

El comando `evento` guarda la selección en `config/arby_settings.sqlite3`. El modo se lee al arrancar Arby. Reinicia el proceso después de cambiarlo. Selecciona `oficina` para desactivar las acciones programadas. Una instalación sin la base empieza en oficina.

En modo evento, los tiempos iniciales son 60–120 segundos para gestos y 300–420 segundos para invitaciones. Los intervalos se eligen independientemente. Si ambos vencen al mismo tiempo, se dice primero la invitación y se deja un mínimo de diez segundos de pausa antes de otra acción. Una conversación o un toque vuelve a iniciar ambos tiempos.

## Probar con intervalos cortos

```bash
.venv/bin/python -m libraries.core.arby_ambient evento --gestos 5 8 --invitaciones 15 20
```

Después inicia Arby con tu comando habitual. Para probar por consola, con ojos desactivados, sin Gemini y con voz silenciada, puedes ejecutar:

```bash
ARBY_DEMO=true ARBY_MUTE=true ARBY_EYES=none ARBY_INPUT_MODE=text .venv/bin/python run_arby.py
```

Deja la consola abierta para ver una invitación. Para oír los efectos, arranca con tu configuración de audio habitual y `ARBY_MUTE=false`. Para recuperar los tiempos normales, guarda nuevamente los intervalos y reinicia:

```bash
.venv/bin/python -m libraries.core.arby_ambient evento --gestos 60 120 --invitaciones 300 420
```

## Captura y contexto durante el evento

- Las acciones esperan a que terminen la captura de voz, la transcripción y la ventana de pregunta abierta al decir «Arby». La voz ambiente puede aplazar una acción hasta que el micrófono vuelva a estar disponible.
- Los guiños dejan el micrófono abierto y se interrumpen cuando el VAD detecta voz. Los efectos audibles y las invitaciones usan la pausa de captura de la aplicación. Espera a que termine un sonido para hablar por el micrófono. Una orden escrita o una reacción al toque tiene prioridad y puede detener la acción automática.
- El bot reutiliza el índice FAISS de la instalación. En evento solo envía a Gemini las fichas públicas recuperadas con títulos `ARB-*`, `ING-*` o los temas del rescate y los frutales. Omite las instrucciones y fichas de personal y la confirmación de nombres de trabajadores. Con el contexto integrado y su índice ya construido, puedes cambiar de modo sin reconstruir el índice.
