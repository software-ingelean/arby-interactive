# TRIKI v2 - rostro más humano

Esta versión mejora el personaje anterior con una animación facial más orgánica y expresiva, pensada para una pantalla conectada a Raspberry Pi y control táctil mediante Trill Craft.

## Mejoras principales

- Ojos con párpados y pupilas animadas.
- Cejas expresivas para dar intención emocional.
- Mejillas y nariz para humanizar el rostro.
- Boca con sonrisa, sorpresa, molestia y animación al hablar.
- Microanimaciones: respiración, mirada flotante, parpadeo automático.
- Transiciones suaves entre emociones.
- Mantiene compatibilidad con Trill Craft y `config/triki_config.json`.

## Archivos

- `triki_pantalla_humano.py`: versión mejorada de la interfaz.
- `config/triki_config.json`: configuración de sensor y zonas táctiles.

## Dependencias

```bash
sudo apt update
sudo apt install python3-pygame espeak-ng i2c-tools
```

También debes tener disponible la librería `trill_lib` en la Raspberry Pi.

## Ejecución

```bash
uv run python -m app.triki_pantalla_humano
```

## Controles de prueba

- `1` → cabeza
- `2` → barriga
- `3` → mano
- `4` → saludo
- `5` → ayuda
- `F1` → diagnóstico de canales
- `F2` → alternar pantalla completa
- `C` → recalibrar baseline
- `ESC` → salir

## Notas técnicas

- Dirección I2C esperada por defecto: `0x30`
- Modo de Trill: `DIFF`
- Prescaler por defecto: `6`
- Umbral de toque por defecto: `0.05`

## Siguiente paso recomendado

Integrar una capa conversacional:
- micrófono USB,
- reconocimiento de voz,
- asistente con respuestas contextuales,
- flujo orientado a atención en sala de espera.
