# TRIKI - Voz neuronal corregida

## Instalar y ejecutar
Desde la raíz del proyecto:

1. Instala las dependencias con `uv sync` y verifica que `ffmpeg` esté instalado.
2. Para usar la configuración de ejemplo, copia `config/triki_config_corregido.json` a `config/triki_config.json`; antes guarda una copia de tu configuración si ya calibraste las zonas táctiles.
3. Ejecuta `uv run python -m app.triki_humano_real_corregido`.

En el primer inicio genera las frases de Edge TTS y las guarda en `assets/audio_triki/`. Puede demorar, según la conexión a Internet. No inicia el rostro hasta que termine de cargar los audios. Después las reutiliza.

Se mantiene la salida ALSA al Nuroum C10 y el Trill Craft en `0x30`. Se procesa una sola frase por toque, sin cola; se espera 1.2 s después de terminar antes de permitir otra.

## Cambios
- Corregido argumento `--rate=-5%` para el CLI de Edge TTS.
- Muestra la razón real de cada fallo en la consola.
- Sin sustitución automática por eSpeak robótico.
- Archivos WAV escritos temporalmente y renombrados solo si se completan.
- Solo se seleccionan frases realmente cargadas, evitando subtítulos sin sonido.

Si aparece un error, copia las líneas `[TRIKI TTS]` de la terminal.

## Voz de plantita

La configuración incluida usa Camila (`es-PE-CamilaNeural`), voz femenina peruana, velocidad `-12%` y tono `+15Hz`. Las frases presentan a Triki como una plantita tierna. Puedes ajustar `edge_rate` y `edge_pitch` en `config/triki_config.json`; los audios se regeneran con una caché distinta al cambiar esos valores.
