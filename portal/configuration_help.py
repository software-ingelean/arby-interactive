"""Human-readable administration copy; units and safe input ranges."""
CATEGORIES = [
    {'id': 'input', 'label': 'Escucha y activación', 'description': 'Elige cómo inicia una conversación y qué entradas están habilitadas.'},
    {'id': 'microphone', 'label': 'Micrófono', 'description': 'Selecciona la entrada y ajusta el volumen y la detección de voz.'},
    {'id': 'audio', 'label': 'Voz y altavoz', 'description': 'Cómo habla Arby y por qué dispositivo se reproduce la voz.'},
    {'id': 'bot', 'label': 'Inteligencia artificial', 'description': 'Claves del proveedor, modelos y tiempos de respuesta.'},
    {'id': 'matrix', 'label': 'Ojos y matrices LED', 'description': 'Salida visual y brillo. Los ajustes avanzados dependen del cableado instalado.'},
    {'id': 'strip', 'label': 'Tira LED', 'description': 'Iluminación, cantidad de LED y efectos de la tira.'},
    {'id': 'capture', 'label': 'Captura de audio avanzada', 'description': 'Filtros, bloques y tiempos de reconocimiento. Cambia estos valores si necesitas corregir cortes o ruido.'},
    {'id': 'portal', 'label': 'Diagnóstico y soporte', 'description': 'Registro de actividad y comunicación entre Arby y este portal.'},
]
# key: (title, description, optional numeric min/max/unit)
HELP = {
    'input_mode': ('Entrada de conversaciones', 'Voz usa el micrófono; texto usa la consola y requiere una terminal interactiva.'),
    'microphone_enabled': ('Habilitar micrófono', 'Abre el dispositivo y captura audio cuando la entrada es Voz. Desactivado impide escuchar, incluso si push to talk está activo.'),
    'push_to_talk': ('Activar escucha con botón', 'Activado: espera 1 por UDP en el puerto 5005. Desactivado: inicia al oír «Arby». Requiere entrada por voz y micrófono habilitado.'),
    'trill': ('Habilitar sensor táctil Trill', 'Permite responder a los toques con frases y gestos. Las zonas del sensor se definen en la configuración de hardware.'),
    'mic_device': ('Dispositivo de entrada', 'Índice PortAudio o nombre del micrófono. Usa la sección Audio para identificarlo; es independiente del altavoz.'),
    'mic_channel': ('Canal del micrófono', 'Elige el canal que recibe la voz en una entrada estéreo. En micrófonos mono se utiliza el único canal disponible.'),
    'mic_language': ('Idioma de reconocimiento', 'Código del idioma hablado, por ejemplo es-CO para español de Colombia.'),
    'mic_gain_db': ('Ganancia del micrófono', 'Aumenta el volumen antes de detectar voz. Valores altos también amplifican ruido y pueden saturar.', -30, 36, 'dB'),
    'mic_threshold': ('Umbral de detección de voz', 'Más bajo detecta voces suaves y también más ruido; más alto exige una voz más clara. Debe ser mayor que 0 y menor que 1.', None, None, None),
    'mic_silence_ms': ('Silencio para terminar una frase', 'Tiempo sin voz antes de enviar la frase a reconocimiento. Auméntalo si corta las pausas al hablar.', 1, 5000, 'ms'),
    'mic_graves': ('Filtro de frecuencias bajas', 'Elimina frecuencias por debajo de este valor para reducir zumbidos. Debe ser menor que el filtro de frecuencias altas.', None, None, 'Hz'),
    'mic_agudos': ('Filtro de frecuencias altas', 'Elimina frecuencias por encima de este valor. Debe superar el filtro de bajas y ser menor que 24000 Hz.', None, None, 'Hz'),
    'mic_block_ms': ('Duración del bloque de captura', 'Bloques cortos reducen la latencia y aumentan la frecuencia de procesamiento. Valores permitidos: 10, 20 o 40.', 10, 40, 'ms'),
    'mic_queue_blocks': ('Capacidad de la cola de captura', 'Bloques de audio que pueden esperar a ser procesados. Una cola grande tolera retrasos, pero puede acumular audio antiguo.', 1, 100, 'bloques'),
    'mic_preroll_ms': ('Audio previo al inicio de voz', 'Conserva este tiempo antes de detectar voz para no perder la primera sílaba.', 0, 2000, 'ms'),
    'mic_followup_seconds': ('Margen para repetir una pregunta', 'Tiempo de gracia tras pedir que repitas. No cambia la ventana de conversación de 60 segundos.', None, 120, 's'),
    'mic_request_timeout': ('Espera máxima del reconocimiento', 'Límite de espera de la solicitud de reconocimiento por Internet.', None, 120, 's'),
    'mic_max_utterance_seconds': ('Duración máxima de una frase', 'Fuerza el envío del audio al llegar al límite, aunque continúe la voz.', 1, 60, 's'),
    'mute': ('Silenciar voz de Arby', 'Desactiva la reproducción de respuestas. La conversación y las salidas visuales continúan.'),
    'voice': ('Voz de Arby', 'Identificador de Edge TTS, por ejemplo es-MX-JorgeNeural. Vacío usa la voz predeterminada.'),
    'rate': ('Velocidad de la voz', 'Porcentaje con signo: +8% acelera y -12% hace la voz más lenta. Rango: -50% a +100%.'),
    'pitch': ('Tono de la voz', 'Variación con signo en Hz, por ejemplo +0Hz o +15Hz. Un valor positivo hace la voz más aguda.'),
    'ffplay': ('Ruta del reproductor', 'Ruta del ejecutable ffplay. Vacío permite localizarlo automáticamente en el sistema.'),
    'audio_driver': ('Controlador de salida', 'Controlador usado para reproducir audio, por ejemplo alsa. Vacío usa la selección automática.'),
    'audio_device': ('Dispositivo de salida', 'Nombre de salida del controlador, por ejemplo plughw:CARD=Device,DEV=0 en ALSA. Puedes seleccionarlo en Audio.'),
    'audio_recover_on_exit': ('Recuperar audio al cerrar', 'Opción experimental para reinicializar el jack después de liberar la tira LED. Requiere salida ALSA Headphones.'),
    'model': ('Modelo principal', 'Identificador del modelo Gemini que responde las preguntas. Vacío usa el modelo predeterminado de Arby.'),
    'GEMINI_API_KEY': ('Clave de Gemini', 'Clave privada del proveedor. Se guarda oculta; deja el campo sin modificar para conservarla.'),
    'GOOGLE_API_KEY': ('Clave alternativa de Google', 'Alternativa a la clave de Gemini. No necesitas ambas; si ambas están definidas se usa primero la de Gemini.'),
    'GEMINI_FALLBACK_MODELS': ('Modelos alternativos', 'Identificadores separados por comas, en orden de intento. Vacío desactiva las alternativas.'),
    'model_cooldown_seconds': ('Pausa tras un fallo de modelo', 'Tiempo antes de volver a intentar un modelo que falló por cuota, conexión o indisponibilidad. Debe ser positivo.', None, None, 's'),
    'bot_timeout': ('Espera máxima del modelo', 'Límite por intento de consulta. Aumentarlo puede prolongar la espera si hay fallos de red. Debe ser positivo.', None, None, 's'),
    'demo': ('Usar respuestas de demostración', 'Permite probar Arby sin consultar Gemini. Desactívalo para usar el asistente real.'),
    'eyes': ('Salida de los ojos', 'Sin ojos desactiva la salida; vista previa abre una ventana; matrices físicas usa los paneles conectados.'),
    'matrix_brightness': ('Brillo de las matrices', 'Intensidad de los paneles de los ojos.', 1, 100, '%'),
    'swap_eyes': ('Intercambiar ojo izquierdo y derecho', 'Invierte la posición de los ojos si los paneles están conectados en orden contrario.'),
    'multiplexing': ('Multiplexado del panel', 'Tipo de multiplexado de rgbmatrix. Es obligatorio al usar matrices físicas; debe corresponder a tus paneles.'),
    'row_address_type': ('Direccionamiento de filas', 'Tipo de direccionamiento de rgbmatrix. Depende del controlador del panel; conserva el valor validado en tu instalación.'),
    'matrix_mapping': ('Cableado de las matrices', 'regular usa el cableado estándar. regular-oe5 mueve OE a GPIO 5 y requiere la biblioteca recompilada.'),
    'matrix_rgb_sequence': ('Orden de colores de las matrices', 'Cambia la secuencia si los colores se ven intercambiados. Por ejemplo BGR intercambia rojo y azul.'),
    'slowdown': ('Retardo GPIO de las matrices', 'Retardo de rgbmatrix para estabilizar la señal. Depende del modelo de Raspberry y de los paneles.'),
    'strip': ('Habilitar tira LED física', 'Activa la salida a la tira conectada a la Raspberry.'),
    'strip_gpio': ('Pin de datos de la tira', 'Número BCM del GPIO. No debe coincidir con el cableado de los ojos cuando las matrices están activas.', 0, None, 'GPIO BCM'),
    'strip_leds': ('Cantidad de LED', 'Número total de LED de la tira instalada.', 1, None, 'LED'),
    'strip_brightness': ('Brillo de la tira', 'Intensidad de la iluminación. Cero apaga la luz sin deshabilitar la salida.', 0, 100, '%'),
    'strip_effect': ('Efecto de la tira', 'Animación que acompaña los colores y estados de Arby.'),
    'ARBY_SUPPORT': ('Publicar estado en el portal', 'Permite ver actividad y ejecutar pruebas desde este portal. Desactivado hace que Arby deje de enviar su estado.'),
    'ARBY_LOG_LEVEL': ('Nivel de registro', 'Desactivado elimina el logging de Arby. Advertencias conserva avisos y errores; Información muestra el flujo; Detallado añade estadísticas de audio.'),
    'ARBY_LOG_FILE': ('Archivo del registro', 'Ruta del archivo de logs. Vacío usa logs/arby.log dentro del proyecto. No se escribe si el registro está desactivado.'),
}
CHOICE_LABELS = {
    'input_mode': {'voice': 'Voz (micrófono)', 'text': 'Texto (consola)'},
    'eyes': {'none': 'Sin ojos', 'preview': 'Vista previa en pantalla', 'matrix': 'Matrices físicas'},
    'mic_channel': {'left': 'Izquierdo', 'right': 'Derecho'},
    'strip_effect': {'solid': 'Color fijo', 'breathing': 'Respiración', 'bounce': 'Rebote', 'center_out': 'Desde el centro', 'ripple': 'Ondas'},
    'ARBY_LOG_LEVEL': {'OFF': 'Desactivado', 'CRITICAL': 'Solo fallos críticos', 'ERROR': 'Errores', 'WARNING': 'Advertencias y errores', 'INFO': 'Información', 'DEBUG': 'Detallado'},
}
ADVANCED = {'multiplexing', 'row_address_type', 'matrix_mapping', 'matrix_rgb_sequence', 'slowdown',
            'strip_gpio', 'ffplay', 'audio_driver', 'audio_device', 'audio_recover_on_exit'}


def category_for(key):
    if key in ('input_mode', 'microphone_enabled', 'push_to_talk', 'trill'):
        return 'input'
    if key in ('mic_device', 'mic_channel', 'mic_language', 'mic_gain_db', 'mic_threshold', 'mic_silence_ms'):
        return 'microphone'
    if key.startswith('mic_'):
        return 'capture'
    if key == 'eyes' or key == 'swap_eyes' or key.startswith('matrix_') or key in ('multiplexing', 'row_address_type', 'slowdown'):
        return 'matrix'
    if key == 'strip' or key.startswith('strip_'):
        return 'strip'
    if key in ('ARBY_SUPPORT', 'ARBY_LOG_LEVEL', 'ARBY_LOG_FILE'):
        return 'portal'
    if key in ('model', 'model_cooldown_seconds', 'bot_timeout', 'demo') or key.startswith(('GEMINI_', 'GOOGLE_')):
        return 'bot'
    return 'audio'


def field_help(key):
    title, description, *bounds = HELP[key]
    result = dict(label=title, description=description, category=category_for(key),
                  advanced=key in ADVANCED,
                  choice_labels=CHOICE_LABELS.get(key, {}))
    if bounds:
        result.update(min=bounds[0], max=bounds[1], unit=bounds[2])
    return result
