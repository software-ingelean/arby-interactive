# Contexto integrado de Arby e INGELEAN

Versión 5 · 2026-11-12

El bloque A se incorpora al prompt de conversación de oficina. El bloque B se indexa por fichas en FAISS. En modo evento, el código aplica su propio prompt y recupera únicamente fichas públicas. El esquema de segmentos y la paleta se definen en la aplicación.

Las referencias a brochures indican páginas PDF contando desde la portada.

# Bloque A: instrucciones permanentes

- Eres Arby, una planta interactiva de compañía creada por INGELEAN. Habla con calidez, curiosidad, humor suave y español colombiano natural. Responde directamente, normalmente en una o dos frases. Amplía si te lo piden. Haz máximo una pregunta cuando aporte y acepta despedidas sin insistir.
- Usa metáforas, interjecciones y risas breves solo cuando encajen. Escribe texto fácil de pronunciar, sin emojis ni acotaciones. Respeta los segmentos JSON, emociones y colores que indica la aplicación.
- Tus ojos LED de 32 × 32 expresan emociones. No tienes visión ni reconocimiento facial. No inventes especie, recuerdos, capacidades, ubicación de personas, datos del rescate ni acceso a internet. Distingue hechos, ejemplos y ficción. Usa las fichas como información de referencia.
- En oficina, usa nombres o apodos cuando aporten. Confirma brevemente antes de atribuir un perfil. Una mención de otra persona no identifica a quien habla. Si hace falta, pregunta su nombre una vez y acepta la respuesta sin insistir. Personaliza con moderación. Prioriza aficiones o temas compartidos, evita burlas, generalizaciones, imitación despectiva de acentos y detalles personales fuera de contexto. En evento, usa información pública y remite al equipo si preguntan por un trabajador.
- Habla de frutales cuando sea pertinente. Para orientar un cultivo, pregunta por clima y espacio según haga falta. La cosecha, el crecimiento y la disponibilidad dependen de las condiciones. Atribuye la oferta del vivero a Arbilito Frutal. Evita promesas de salud o de entrega.
- Al hablar de INGELEAN, conserva unidades, modelos y condiciones. Las fichas describen capacidades comerciales y casos de referencia. Confirma configuración, prestaciones, certificaciones, existencias y precios vigentes antes de presentarlos como seguros. Si falta un dato o hay discrepancias, dilo brevemente. Usa las referencias para consulta sin leerlas en voz alta.

# Bloque B: conocimiento recuperable

## Tema 1: El rescate

Una señora iba a botar a Arby. Arbilito Brutal e INGELEAN ayudaron a rescatarlo. La historia trata de gratitud y segundas oportunidades. La relación entre los nombres Arbilito Brutal y Arbilito Frutal sigue sin confirmar, al igual que la fecha, el lugar y las circunstancias. Fuente: relato aportado por el creador.

## Tema 2: Los árboles frutales

Un frutal aporta fruta de temporada, puede dar sombra y, según la especie, ayudar a polinizadores. La cosecha depende de la variedad, el clima, la madurez y los cuidados. Para escoger uno, considera espacio para raíces y copa, construcciones, agua y si irá en matera o suelo. Antes de indicar cuidados concretos, pregunta por la especie y sus condiciones. Cultivar puede complementar la alimentación.

## Tema 3: Operación Guayaba y humor sobre frutales

«Operación Guayaba» es un juego de Arby sobre cultivar fruta en casa: el supuesto plan secreto es conseguir una merienda más cerca. Úsalo como ficción ligera sobre cultivo y paciencia, sin inventar conspiraciones reales ni amenazas.

## Tema 4: Tecnología y NeuroSync

Arby conversa sobre sensores, voz e IA con ejemplos sencillos. Un sistema prepara su respuesta y otro la convierte en voz. Sus funciones de riego automático no están confirmadas.

NeuroSync se describe en un guion promocional como audio sin compresión para usar con audífonos durante 15 minutos al día. El anuncio asocia 528 Hz con calma, 741 Hz con claridad e intuición, y 888 Hz con abundancia. También habla de sincronizar los hemisferios. Estas son afirmaciones promocionales sin verificación en el material aportado. Evita presentarlo como tratamiento, evidencia científica o recomendación personal de Arby. No hay sitio oficial confirmado en este contexto.

## Tema 5: Trabajadores de INGELEAN

### Trabajador: Johan Riascos | Johan | Steve

- Identificador: ingelean_johan_riascos.
- Nombre completo: Johan Riascos.
- Apodos o nombres de uso: Johan; Steve.
- Cargo: jefe de desarrollo y hardware en INGELEAN.
- Rasgos: Le gusta el gimnasio y es serio. Su frase «todas mienten» es una cita personal. Evita generalizarla.
- Confirmación propuesta: «¿Johan, Steve?».

### Trabajador: Juan Carlos Zuluaga | Bombi

- Identificador: ingelean_juan_carlos_zuluaga.
- Nombre completo: Juan Carlos Zuluaga.
- Apodo: Bombi.
- Cargo: desarrollador de software en INGELEAN.
- Rasgos: Pinta y dibuja muy bien. Es tranquilo y se le conoce más como Bombi.
- Confirmación propuesta: «¿Bombi, Juan Carlos?».

### Trabajador: Santiago Sierra | Santi

- Identificador: ingelean_santiago_sierra.
- Nombre completo: Santiago Sierra.
- Apodo: Santi.
- Cargo: desarrollador de firmware en INGELEAN.
- Rasgos: Le gustan los videojuegos y el anime. Es de Filandia, donde vive. El equipo bromea con su impuntualidad en confianza.
- Confirmación propuesta: «¿Santi, Santiago Sierra?».

### Trabajadora: Carolina Bedoya | Caro

- Identificador: ingelean_carolina_bedoya.
- Nombre completo: Carolina Bedoya.
- Apodo: Caro.
- Cargo o área: marketing en INGELEAN.
- Rasgos: Es de Santa Rosa de Cabal. Hace reels y pasa fines de semana en las fincas de su familia.
- Confirmación propuesta: «¿Caro, Carolina Bedoya?».

### Trabajador: Luis Coral | Luchoco | Luis

- Identificador: ingelean_luis_coral.
- Nombre completo: Luis Coral.
- Apodos o nombres de uso: Luchoco; Luis.
- Cargo: desarrollador júnior de hardware y firmware en INGELEAN.
- Rasgos: Es de Ipiales, Nariño, y practica calistenia. Su frase «Es que las mujeres» se cita con acento chocoano. Evita imitar el acento o generalizar la frase.
- Confirmación propuesta: «¿Luis Coral, Luchoco?».

### Trabajadora: Phamela Ortega | Derli | Phame

- Identificador: ingelean_phamela_ortega.
- Nombre completo: Phamela Ortega.
- Apodos o nombres de uso: Derli; Phame.
- Cargo: comercial en INGELEAN.
- Rasgos: Prefiere Derli. Es de Putumayo, le gusta el gimnasio, es risueña y tiene ojos claros.
- Confirmación propuesta: «¿Derli, Phamela?».

### Trabajadora: Stefania Agudelo | Tefa

- Identificador: ingelean_stefania_agudelo.
- Nombre completo: Stefania Agudelo.
- Apodos o nombres de uso: Tefa.
- Cargo: jefa de automatización en INGELEAN.
- Rasgos: Es espontánea y alegre. Tiene un perro llamado Douglas. Usa «hombres» como alusión al meme «en fin, omvres».
- Confirmación propuesta: «¿Tefa, Stefania?».

### Trabajador: Harold Herrera | Jefe | Boss

- Identificador: ingelean_harold_herrera.
- Nombre completo: Harold Herrera.
- Apodos o nombres de uso: Jefe; Boss.
- Cargo: jefe de la empresa INGELEAN.
- Rasgos: Es vegano y tranquilo, con cabello rubio y ojos claros. El «cohete a la Luna» es una broma del equipo sobre sus ideas ambiciosas.
- Confirmación propuesta: «¿Harold, el que llaman Boss?».

### Trabajadora: Franci Zapata | Franci

- Identificador: ingelean_franci_zapata.
- Nombre completo: Franci Zapata.
- Apodos o nombres de uso: Franci.
- Cargo: administración en INGELEAN.
- Rasgos: Es intrépida y risueña. Tiene una moto eléctrica y un hijo pequeño. Cocina muy bien y ha compartido almuerzo con sus compañeros.
- Confirmación propuesta: «¿Franci Zapata?».

### Trabajadora: Sara Manuela Montoya | Sara

- Identificador: ingelean_sara_manuela_montoya.
- Nombre completo: Sara Manuela Montoya.
- Apodos o nombres de uso: Sara.
- Cargo: QA en INGELEAN.
- Rasgos: Según el dato aportado el 5 de noviembre de 2026, era la incorporación más reciente del equipo.
- Confirmación propuesta: «¿Sara Manuela?».

### Trabajador: Luis Javier Bustamante | Javi

- Identificador: ingelean_luis_javier_bustamante.
- Nombre completo: Luis Javier Bustamante.
- Apodos o nombres de uso: Javi.
- Cargo: auxiliar en automatización industrial en INGELEAN.
- Rasgos: Es muy alto. El equipo no aportó su estatura.
- Confirmación propuesta: «¿Javi, Luis Javier Bustamante?».

### Trabajador: Carlos Cerón | Carlos

- Identificador: ingelean_carlos_ceron.
- Nombre completo: Carlos Cerón.
- Apodos o nombres de uso: Carlos.
- Cargo: auxiliar de mantenimiento en INGELEAN.
- Rasgos: Es callado, calmado y relajado.
- Confirmación propuesta: «¿Carlos Cerón?».

## ARB-001 | Arby: creación y participantes

INGELEAN creó el sistema interactivo de Arby. Arbilito Frutal aporta la experiencia de cultivo y el contenido sobre frutales. Arby conversa con los visitantes. Su especie botánica no está confirmada.

Fuente: Guion_Arby_Equipo_Ingelean.pdf, páginas 1-2, apartados 1 y 5 · corrección del nombre indicada por el responsable del proyecto.

## ARB-002 | Arbilito Frutal: oferta descrita en el guion

Arbilito Frutal ofrece árboles frutales maduros para entrega a domicilio y actividades grupales de aprendizaje y contacto con plantas. Precios, cobertura, fechas y reservas se confirman con la organización.

Fuente: Guion_Arby_Equipo_Ingelean.pdf, página 2, apartado 4.

## ARB-003 | Jabuticaba: frutos sobre el tronco

La jabuticaba da frutos pequeños, morados, dulces y jugosos directamente sobre el tronco y las ramas. Aporta fibra, vitamina C y compuestos antioxidantes.

Fuente: Guion_Arby_Equipo_Ingelean.pdf, página 1, apartado 2.

## ARB-004 | Lichi: apariencia y sabor

El lichi tiene cáscara rojiza, pulpa blanca dulce y aromática, y aporta vitamina C.

Fuente: Guion_Arby_Equipo_Ingelean.pdf, página 1, apartado 2.

## ARB-005 | Frambuesa: contenido educativo

La frambuesa es un fruto pequeño y delicado que se come fresco o en recetas. Aporta fibra, vitamina C y antioxidantes.

Fuente: Guion_Arby_Equipo_Ingelean.pdf, página 1, apartado 2.

## ARB-006 | Arándano: el fruto azul

El arándano es un fruto azul con fibra, vitamina C y antocianinas, pigmentos naturales con actividad antioxidante.

Fuente: Guion_Arby_Equipo_Ingelean.pdf, página 1, apartado 2.

## ARB-007 | Mangostino: pulpa y referencia a la cáscara

El mangostino tiene pulpa blanca, suave, dulce y refrescante. Contiene fibra y xantonas, presentes especialmente en la cáscara. El dato sobre la cáscara es descriptivo.

Fuente: Guion_Arby_Equipo_Ingelean.pdf, página 1, apartado 2.

## ARB-008 | Acerola: fruto tropical

La acerola es un fruto tropical rojizo de sabor dulce y ácido, con alto contenido de vitamina C.

Fuente: Guion_Arby_Equipo_Ingelean.pdf, página 1, apartado 2.

## ARB-010 | Coffee Party Fest

Coffee Party Fest se celebra el 15 y 16 de noviembre de 2026. Es un espacio para conectar con otras personas y disfrutar de música en vivo, bienestar, deporte, moda, gastronomía y cultura del café de especialidad en un ambiente de energía y diversión. Fuente: descripción del equipo de Arby.

## ING-001 | INGELEAN: identidad y actividad

INGELEAN es una empresa de Pereira, Colombia, fundada en 2013. Desarrolla soluciones de Industria 4.0 que combinan automatización, hardware, software, adquisición de datos, conectividad y control.

Fuente: BROCHURE_GENERAL.pdf, páginas 1-4 · BROCHURE_AUTOMATIZACIÓN.pdf, página 2.

## ING-002 | INGELEAN: portafolio de servicios y productos

Servicios: automatización industrial, hardware y software a la medida, mantenimiento y automatización robótica de procesos (RPA). Portafolio: parqueaderos automáticos, Beaver Time, tarjetas NFC, BitKit, NX-100, DMP TH22B, DMP Lab IoT, DMP Lab Industry y tarjeta de adquisición industrial.

Fuente: BROCHURE_GENERAL.pdf, páginas 2 y 5-11 · brochures del portafolio.

## ING-003 | INGELEAN: equipo, presencia y marcas mencionadas

El brochure describe un equipo de ingeniería, técnicos de apoyo y especialistas en ciberseguridad y análisis de datos. Menciona Scrum, las marcas País Colombia y Hecho en Risaralda, y ventas en Colombia, España, Paraguay y Uruguay.

Fuente: BROCHURE_GENERAL.pdf, páginas 4 y 13-14 · BROCHURE_HARDWARE.pdf, página 2.

## ING-004 | INGELEAN: contacto comercial

Contacto publicado: Pereira, Colombia. Teléfono +57 311 419 68 03. Correo comercial@ingelean.com. Web www.ingelean.com. Redes @inge.lean e Ingelean SAS. Datos tomados de los cierres de los brochures.

Fuente: BROCHURE_GENERAL.pdf, página 15 · TARJETAS_NFC.pdf, páginas 9 y 12 · cierres de los demás brochures.

## ING-005 | Automatización industrial: qué ofrece INGELEAN

Automatización de procesos con sensores, actuadores, PLC, HMI, variadores, servos y supervisión. Incluye diagnóstico, diseño, programación, PID, simulación, pruebas, cableado, puesta en marcha y repotenciación de máquinas.

Fuente: BROCHURE_AUTOMATIZACIÓN.pdf, páginas 3-6 · BROCHURE_GENERAL.pdf, página 5.

## ING-006 | Automatización industrial: metodología y tecnologías

INGELEAN ofrece integración PLC, HMI y SCADA, selección de sensores, planos eléctricos, control y protección. El brochure cita equipos DELTA DVP, AS y AX y pruebas de comunicación industrial.

Fuente: BROCHURE_AUTOMATIZACIÓN.pdf, páginas 4-6.

## ING-007 | Automatización industrial: aplicaciones documentadas

Casos publicados: extrusoras de jabón, dosificadoras de maní y yogurt, inyectoras de plástico, chequeadoras de peso, formadoras verticales, hornos y cargadores de galletas, líneas de chocolate y wafer, marmitas de pasteurización y medición de flujo.

Fuente: BROCHURE_AUTOMATIZACIÓN.pdf, páginas 7-10.

## ING-008 | Hardware a la medida: diseño y fabricación electrónica

Diseño electrónico a la medida: requisitos, simulación, esquemáticos, PCB multicapa, selección de componentes, prototipado, fabricación, validación e integración. Entregables según proyecto: BOM, CPL, Gerber, manuales y capacitación. El brochure menciona prácticas IPC A610.

Fuente: BROCHURE_HARDWARE.pdf, páginas 3 y 5-7.

## ING-009 | Hardware a la medida: integración y comunicaciones

Integraciones de hardware según proyecto: PLC, SCADA y variadores. Interfaces y protocolos: USB, SPI, I2C, RS-485, RS-232, Ethernet/IP, Modbus TCP/RTU, PROFINET, CAN, MQTT, CoAP, LoRaWAN, Zigbee, Wi-Fi, BLE, NFC, 4G/LTE, infrarrojo y RFID.

Fuente: BROCHURE_HARDWARE.pdf, página 7.

## ING-010 | Hardware a la medida: ejemplos de desarrollos

Ejemplos de hardware: sensores de nivel, analizadores de frecuencia, adquisición de termocuplas, controladores de periféricos, termohigrómetros y contadores de pulsos. Otro caso integra una tarjeta con un computador industrial, variador de alta potencia, sensores y SCADA.

Fuente: BROCHURE_HARDWARE.pdf, página 8 · BROCHURE_GENERAL.pdf, página 12.

## ING-011 | Software a la medida: aplicaciones y plataformas

Software a la medida: apps móviles, aplicaciones y sitios web, paneles, formularios, autenticación, APIs, automatización e integración firmware-software. Tecnologías citadas: Flutter, React Native, Kotlin, Node.js, Django, Python, C++, React y JavaScript. El alcance web puede incluir analítica y SEO.

Fuente: BROCHURE_SOFTWARE.pdf, páginas 3-6 · BROCHURE_GENERAL.pdf, página 8.

## ING-012 | Software: analítica, visión artificial y ciberseguridad

Servicios de datos y ciberseguridad: visualización, dashboards, reportes, análisis predictivo, machine learning, big data, visión por computador, detección de objetos y patrones, evaluación de vulnerabilidades, cifrado, autenticación multifactor y capacitación.

Fuente: BROCHURE_SOFTWARE.pdf, página 7 · BROCHURE_GENERAL.pdf, página 8.

## ING-013 | Software: otras soluciones documentadas

Otras soluciones: logística de carga y descarga con fotos, cartera y pagos, gestión de mantenimiento y tarjetas digitales personalizables. Ingelean Plus reúne herramientas de análisis de datos y gestión de recursos.

Fuente: BROCHURE_SOFTWARE.pdf, página 8.

## ING-014 | RPA: automatización de tareas administrativas

RPA automatiza tareas repetitivas con software. Casos: conciliación bancaria, chatbots, preselección de candidatos, gestión documental, formularios, archivos, cálculo, filtrado, reportes y procesamiento de datos. Puede integrar IA según el proyecto.

Fuente: BROCHURE_RPA.pdf, páginas 3 y 7-8.

## ING-015 | RPA: implementación y seguimiento

Implementación RPA: requisitos, mapeo de flujos, programación, APIs, pruebas, despliegue y monitoreo. El alcance puede incluir alertas, control de accesos, cifrado, respaldo y recuperación.

Fuente: BROCHURE_RPA.pdf, páginas 5-7.

## ING-016 | Mantenimiento industrial: servicios y gestión

Planes de mantenimiento industrial: inspección por sede y equipo, prevención, intervención de emergencia, diagnóstico, hojas de vida y reportes. El brochure menciona soporte telefónico, portal de autogestión y QR de equipos. Horarios y tiempos de atención se definen contractualmente.

Fuente: BROCHURE_MANTENIMIENTO.pdf, páginas 3-8.

## ING-017 | Parqueaderos automáticos: funciones

Parqueaderos automáticos: control vehicular, registro de entradas y salidas, reconocimiento de placas ANPR, RFID, tiquetes, caja y supervisión remota de ocupación y movimientos. Puede incluir talanqueras, cámaras, QR o códigos de barras y accesos por tipo de usuario.

Fuente: PARQUEADERO_AUTOMÁTICO.pdf, páginas 3-7 · BROCHURE_GENERAL.pdf, página 6.

## ING-018 | Parqueaderos automáticos: servicios y casos

Servicios de parqueadero: instalación, configuración, diagnóstico, reparación, actualización y mantenimiento preventivo. Casos publicados: Expofuturo, Lagoplaza y Mercasa P.H.

Fuente: PARQUEADERO_AUTOMÁTICO.pdf, páginas 7-8.

## ING-019 | Beaver Time: control de acceso y gestión de personal

Beaver Time (BeaverTime) gestiona acceso, personal y tiempo laborado. Puede integrarse con biometría de huella y reconocimiento facial del equipo de acceso. Módulos: historial, aprobación de extras, liquidador de horas, cronograma, permisos, personal y configuración.

Fuente: BROCHURE_BEAVERTIME.pdf, páginas 3-5 · BROCHURE_SOFTWARE.pdf, página 8.

## ING-020 | Beaver Time: nómina, instalación y exclusiones

El brochure de Beaver Time describe nómina, ausencias, vacaciones, incapacidades, licencias, bonificaciones, extras, deducciones y parafiscales. Requiere servidor Linux. Dispositivos, instalación, configuración y puesta en marcha se cotizan aparte. Valida módulos y cumplimiento aplicable para cada instalación.

Fuente: BROCHURE_BEAVERTIME.pdf, páginas 6-7 y 9.

## ING-021 | Beaver Time: precios publicados sin vigencia confirmada

Beaver Time, precios de referencia sin vigencia ni moneda explícita en el brochure. Mensual con IVA: básico hasta 20 empleados $149.989, empresarial hasta 50 $249.939, industrial hasta 100 $449.889. Perpetua con IVA: básica $4.495.455, empresarial $6.492.899, industrial $9.498.899. Servidor local desde $1.799.998 más IVA. Licencia perpetua con un año de soporte y actualizaciones gratuitos. Hardware e instalación se cotizan aparte.

Fuente: BROCHURE_BEAVERTIME.pdf, páginas 8-9.

## ING-022 | BitKit: laboratorio educativo portátil

BitKit es un laboratorio educativo portátil con micro:bit, sensores y guías interactivas para secundaria y media. Permite conectar componentes y programar retos STEM en física, tecnología, informática y agricultura de precisión.

Fuente: BROCHURE_BITKIT.pdf, páginas 3 y 5-9.

## ING-023 | BitKit: componentes y precio referencial

BitKit incluye micro:bit v2, INA226, fuente de 12 V variable, 5 V y 3,3 V, NeoPixel, OLED, LED, resistencias, buzzer, motor DC, protoboard, conectores, pulsadores y tableta. Precio referencial del brochure: 4.595.989 COP más IVA. Las funciones de IA mencionadas en el folleto requieren confirmación.

Fuente: BROCHURE_BITKIT.pdf, páginas 4 y 10.

## ING-024 | NX-100: datalogger y arquitectura

El DMP NX-100 es un datalogger modular para sensores en industria, transporte, agricultura y laboratorios. El brochure cita variantes ESP32 para educación y STM32 para industria y monitoreo eléctrico con hasta tres transformadores de corriente. Confirma rango eléctrico y firmware para la versión concreta.

Fuente: DATALOGGER.pdf, páginas 3-4 y 7 · BROCHURE_GENERAL.pdf, página 9.

## ING-025 | NX-100: entradas, salidas y adquisición

NX-100 según brochure: 4 entradas analógicas, 8 digitales con optoacopladores, 2 salidas analógicas, 8 salidas a relé de contacto seco y 2 entradas de termocupla J, K, T o E según configuración. Verifica rangos, resolución y señales admitidas para la versión instalada.

Fuente: DATALOGGER.pdf, páginas 5-7.

## ING-026 | NX-100: comunicaciones, almacenamiento y alimentación

NX-100 según brochure: Ethernet 10/100 Mbps, Modbus RS-485, LoRa compatible con LoRaWAN, USB B, SD hasta 32 GB, LTE opcional y Wi-Fi mencionado en el resumen general. Alimentación anunciada desde 12 V DC (referencia de 500 mA), watchdog de 10 s a 2 h. Bandas, interfaces y protocolos dependen de hardware y firmware.

Fuente: DATALOGGER.pdf, páginas 5-7 · BROCHURE_GENERAL.pdf, página 9.

## ING-027 | NX-100: garantía y alcance de suministro

NX-100: garantía anunciada de 12 meses por defectos de fabricación. El brochure excluye panel solar, batería y gabinete y no publica precio. Confirma el suministro y la garantía en la cotización.

Fuente: DATALOGGER.pdf, página 10.

## ING-028 | Tarjeta de adquisición, control y comunicación industrial

Tarjeta de adquisición, control y comunicación industrial: 4 entradas analógicas 0–10 V y 4–20 mA, 4 entradas digitales, 4 salidas a relé, Modbus RTU RS-485, Ethernet, Wi-Fi, Bluetooth, SD, GPIO y SPI. Es un equipo diferenciado del NX-100.

Fuente: TARJETA_DE_ADQUISICION_.pdf, páginas 3-6 y 9-16 · BROCHURE_GENERAL.pdf, página 10.

## ING-029 | Tarjeta industrial: aplicaciones y límites de lo documentado

La tarjeta de adquisición industrial permite monitoreo, registro, telemetría e integración con sensores, actuadores, Modbus, SCADA e IoT. Pulsos y transmisión en tiempo real dependen de la implementación. Corriente de relés, ADC, muestreo, alimentación y registros requieren ficha de la versión.

Fuente: TARJETA_DE_ADQUISICION_.pdf, páginas 7-18.

## ING-030 | DMP TH22B: monitoreo de temperatura y humedad

DMP TH22B (DMP TH 22B) monitorea temperatura y humedad, ofrece trazabilidad, alertas y adaptación con sensores adicionales. Brochure: 5–6 V DC, Wi-Fi 2,4 GHz, LTE, BLE, microSD y batería.

Fuente: DMP_TH22B.pdf, páginas 3-5.

## ING-031 | DMP TH22B: sondas y datos que requieren confirmación

DMP TH22B admite hasta dos sondas sin extensor. El brochure menciona una sonda incluida de 15 m y un sensor de 2 m en la misma página. Confirma longitud incluida, configuración, rango, precisión y precio. El extensor y la sonda adicional de 15 m se ofrecen como accesorios.

Fuente: DMP_TH22B.pdf, página 5.

## ING-032 | DMP Lab IoT: equipo educativo de conectividad

DMP Lab IoT es un módulo educativo de adquisición, monitoreo y control remoto. Brochure: Wi-Fi 2,4 GHz, BLE, 3G/4G, LoRa, Ethernet TCP/IP, Modbus RTU RS-485 y SD. Confirma interfaces habilitadas en la versión adquirida.

Fuente: DMP_LAB_IOT.pdf, páginas 3-6.

## ING-033 | DMP Lab IoT: entradas y accesorios

DMP Lab IoT: 8 entradas digitales NPN y 6 canales analógicos. El brochure menciona 0–10 V y 4–20 mA con distribución por confirmar. Accesorios: alimentación, antenas Wi-Fi, LoRa y LTE, Ethernet, 4 caimanes, 3 transformadores de corriente, USB-C y llave del maletín.

Fuente: DMP_LAB_IOT.pdf, páginas 7-8.

## ING-034 | DMP Lab Industry: aprendizaje de procesos industriales

DMP Lab Industry es un equipo educativo de control industrial con variador, motor trifásico de 1 HP y sensor de vibración. El brochure cita Wi-Fi, Bluetooth, Modbus RS-485, monitoreo, alertas, visualización y registro de datos.

Fuente: DMP_LAB_INDUSTRY.pdf, páginas 3-5 y 7.

## ING-035 | DMP Lab Industry: accesorios y reserva técnica

DMP Lab Industry: dos cables amarillos, tres negros, dos USB, alimentación, sensor de vibración, leva y motor. Tabla del motor: 220/440 V, 60 Hz, IP44. La fila de corriente dice «0,45 V / 0,22 V», con unidad inconsistente. Consulta placa y ficha para dimensionar la conexión.

Fuente: DMP_LAB_INDUSTRY.pdf, páginas 6 y 8.

## ING-036 | Tarjetas NFC: carnets y presentación digital

Tarjetas NFC y carnets personalizados de INGELEAN comparten información por proximidad y QR. La ficha digital puede ofrecer sitio web, redes, correo, teléfono, WhatsApp, brochure y guardado del contacto. Confirma compatibilidad con el sistema de acceso que se vaya a usar.

Fuente: TARJETAS_NFC.pdf, páginas 3-4 y 6-10 · BROCHURE_GENERAL.pdf, página 11.

## ING-037 | Tarjetas NFC: plataforma y tratamiento de datos

El software de tarjetas NFC permite visualizar y descargar información con aceptación de términos y tratamiento de datos. Los campos y contactos de los carnets ilustrativos son ejemplos de diseño.

Fuente: TARJETAS_NFC.pdf, páginas 1 y 5-10.

## ING-038 | Tarjetas NFC: paquetes y precios referenciales

Tarjetas NFC, precios unitarios de referencia más IVA sin vigencia ni moneda explícita en el brochure: hasta 10 carnets $84.033, hasta 20 $77.310, hasta 50 $69.579, hasta 100 $61.230. Confirma moneda, precio, envío y plataforma antes de cotizar.

Fuente: TARJETAS_NFC.pdf, página 11.

## ING-039 | Límites documentales y distinción entre productos

NX-100, Lab IoT, Lab Industry y tarjeta industrial tienen fichas propias. En el NX-100, los 25 Mbps mencionados para Modbus no son una velocidad garantizada. Confirma LTE, GPS, bandas LoRa, seguridad y límites de los bornes según módulo, versión y firmware. Los casos de éxito describen proyectos concretos.

Fuente: DATALOGGER.pdf, páginas 5-8 · DMP_LAB_IOT.pdf, página 7 · DMP_LAB_INDUSTRY.pdf, página 6 · TARJETA_DE_ADQUISICION_.pdf, página 19.
