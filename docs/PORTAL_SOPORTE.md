# Portal local de soporte

Para el uso diario, consulta la [guía rápida ilustrada](GUIA_RAPIDA_PORTAL.md) o su [versión PDF](GUIA_RAPIDA_PORTAL.pdf).

El portal vive en la Raspberry, funciona sin cargar recursos de internet y sigue
respondiendo aunque Arby esté detenido. Abre `http://IP-DE-LA-RASPBERRY:8080` desde
el celular en la misma red o `http://localhost:8080` en la pantalla local.
No está diseñado para publicarse en internet. Usa una red local de confianza:
el acceso HTTP local no cifra la clave en tránsito.

## Direcciones de esta instalación

- `http://100.101.87.24:8080`: desde dispositivos con acceso a esa red.
- `http://10.42.0.1:8080`: conectado a la red Arby-Soporte.
- `http://localhost:8080`: desde la propia Raspberry.

Usa `ARBY_PORTAL_HOST=0.0.0.0` y `ARBY_PORTAL_PORT=8080` para que el
servicio escuche en todas las interfaces IPv4. La disponibilidad de cada
IP depende de que su interfaz esté activa y el dispositivo tenga acceso a esa red.

## Qué incluye

- Estado actualizado cada tres segundos: Arby, Trill, micrófono, altavoz, ojos y tira.
- Vistas separadas: Resumen, Audio, Experiencia, Pruebas, Conexión y Equipo.
- Selector de micrófono y altavoz predeterminados, canal de entrada y medidor de nivel.
- Modo oficina/evento, tiempos, silencio de voz, velocidad, ganancia y brillo.
- Saludo, invitación, prueba de sonido, cuatro expresiones y tres colores de tira;
  cancelación de la demostración sin cancelar conversaciones. Observación de actividad
  del micrófono y último toque Trill, sin grabar audio ni conversaciones.
- Redes Wi-Fi mediante NetworkManager y `wlan0`; reinicio de Arby y Raspberry,
  y apagado del sistema con confirmación.
- Conserva el hotspot instalado en `wlan1`; no cambia su perfil ni el controlador USB.

«Funcionando» en luces confirma inicialización y ejecución sin error conocido;
la comprobación visual corresponde al operador. En audio, se informa «Sin
comprobar» hasta completar reproducción sin error, y el operador debe confirmar
que se escucha. Con el proceso detenido o el estado de más de ocho segundos,
los componentes dejan de mostrarse como operativos.

Guardar no reinicia nada. «Aplicar y reiniciar Arby» interrumpe la conversación,
libera los recursos y vuelve a iniciar con los ajustes guardados. Esos ajustes
tienen prioridad sobre `.env` solo para los controles del portal. Cableado,
modelos y claves siguen en `.env`. Sin una selección de audio en el panel, los
dispositivos conservan los valores de `.env`. Para volver a usar exclusivamente
los valores del entorno en esos controles, con Arby detenido elimina la fila de
`support_settings` (no la base de datos completa).

## Acceder por todas las IP locales (puerto 8080)

El servicio de este repositorio carga `/etc/arby/portal.env`. En la Raspberry,
edita ese archivo conservando el hash de la clave y deja una sola definición de
cada variable:

```bash
sudo nano /etc/arby/portal.env
```

```text
ARBY_PORTAL_HOST=0.0.0.0
ARBY_PORTAL_PORT=8080
```

Aplica y comprueba:

```bash
sudo systemctl restart arby-portal.service
sudo systemctl status arby-portal.service --no-pager
sudo ss -ltnp 'sport = :8080'
hostname -I
```

La escucha debe aparecer como `0.0.0.0:8080`. Abre `http://127.0.0.1:8080`
en la Raspberry o `http://IP-DE-LA-RASPBERRY:8080` desde otro equipo con acceso
a esa red. Cada dirección IPv4 de la Raspberry puede servir el portal, según
las rutas y el firewall. `0.0.0.0` es la dirección de escucha, no la URL para
el navegador; esta configuración no habilita escucha en IPv6.

Cambiar únicamente `portal.env` requiere reiniciar el servicio; no requiere
`daemon-reload`. Si cambias el archivo `.service`, ejecuta antes
`sudo systemctl daemon-reload`. Si la instalación usa otra unidad, consulta
`sudo systemctl cat arby-portal.service` para identificar su `EnvironmentFile`.
El puerto predeterminado del código es 8080; esta guía lo configura explícitamente.

## Selección estable de audio

En **Audio y dispositivos**, pulsa «Buscar dispositivos», elige la entrada y la
salida y guarda. Los selectores muestran hardware ALSA físico sin abrirlo, así
que siguen funcionando cuando el servicio Arby está detenido. Las salidas sin
captura nunca se ofrecen como micrófono. La detección utiliza `/proc/asound/pcm`
y sysfs, sin permisos de administrador ni paquetes nuevos.

Se guardan controlador, modelo, USB VID/PID, número de serie si existe, puerto y
canal PCM en `support_audio_settings`. No se guarda el índice de tarjeta ALSA ni
el índice PortAudio. Al arrancar se busca la identidad y se resuelve el índice
actual de entrada o la ruta ALSA actual para salida:

- Con número de serie, se exige esa unidad aunque se conecte a otro puerto.
- Sin serie, se prefiere el mismo puerto; si cambió, solo se acepta una coincidencia
  única de modelo/controlador. Dos unidades ambiguas requieren nueva selección.
- No basta con el controlador: varios adaptadores distintos usan `snd-usb-audio`.
- Si falta el predeterminado, el panel lo indica y Arby no cambia silenciosamente a
  otro dispositivo. El servicio puede reintentar su arranque hasta que vuelva.
- Elegir «Usar configuración instalada» restaura la selección de `.env` para ese rol.
- La resolución se hace al iniciar Arby. Después de cambiar o reconectar hardware,
  usa «Aplicar y reiniciar Arby»; no se reabre el micrófono en medio de una frase.

El indicador de nivel es RMS de la entrada S32 normalizada y del canal seleccionado;
se actualiza con la telemetría, sin guardar muestras. No mide el volumen del altavoz.
Las demos se ejecutan con la configuración aplicada; los cambios guardados siguen
pendientes hasta reiniciar. Los colores de prueba pueden afectar también el color
de los ojos porque comparten la salida visual de Arby.

## Actualizar una instalación existente

Desde el checkout actualizado en la Raspberry, conserva módulos locales como
`rgbmatrix` usando `--inexact` si necesitas sincronizar dependencias. Esta versión
no añade dependencias nuevas. Reinstala el ayudante para habilitar el apagado:

```bash
cd ~/arby-interactive
sudo install -o root -g root -m 644 deploy/arby-system.py /usr/local/libexec/arby-system.py
sudo systemctl restart arby-portal.service arby.service
```

No cambió la regla sudoers ni las plantillas de servicios. La tabla de preferencias
se crea automáticamente al iniciar el portal o la telemetría; los ajustes existentes
se conservan. Recarga el navegador para obtener las nuevas vistas. Prueba el apagado
solo cuando puedas volver a encender físicamente la Raspberry.

## Instalación en Raspberry Pi OS

Se necesitan `systemd`, `sudo` y NetworkManager (`nmcli`). Los ejemplos asumen
`/home/arley/arby-interactive`: **sustituye esa ruta por el checkout real**, accesible en lectura
y ejecución al usuario `arby-portal`, incluidos sus directorios padres. Los ejemplos
no trasladan el proyecto ni cambian tu configuración de hardware.

1. Instala el extra desde la raíz del proyecto, conservando los extras de hardware
   que ya uses: `uv sync --inexact --extra support --extra voice --extra led`.
   Usa `--inexact` para conservar módulos instalados localmente, como el binding
   personalizado `rgbmatrix`, que no está declarado en `pyproject.toml`.
   Si ya se eliminó, reinstálalo desde tu checkout local siguiendo
   [la guía de matrices](MATRIZ_OE_GPIO5.md), conservando el mapeo personalizado.
2. Crea la cuenta y prepara el directorio compartido. Detén previamente cualquier
   ejecución manual de Arby para evitar dos procesos usando el mismo hardware.

```bash
sudo groupadd --system arby-support
sudo useradd --system --gid arby-support --no-create-home --shell /usr/sbin/nologin arby-portal
sudo install -d -o root -g arby-support -m 2770 /home/arley/arby-interactive/config
sudo chgrp arby-support /home/arley/arby-interactive/config/arby_settings.sqlite3
sudo chmod 660 /home/arley/arby-interactive/config/arby_settings.sqlite3
```

Los dos últimos comandos solo aplican si la base ya existe. Si aún no existe,
el portal la creará con el grupo compartido. No cambies permisos de `.env`
para dar acceso al portal: el servidor web no necesita leerla. Mantén `.env`
legible para quien ejecute Arby y fuera del acceso del usuario del portal.
Las credenciales del portal se configuran aparte.

3. Genera un hash (la clave se solicita sin mostrarla):

```bash
.venv/bin/python -c 'from getpass import getpass; from werkzeug.security import generate_password_hash; print(generate_password_hash(getpass("Clave de soporte: ")))'
```

Crea `/etc/arby/portal.env` con propietario `root:arby-support` y modo `0640`:

```text
ARBY_PORTAL_PASSWORD_HASH=PEGA_EL_HASH_GENERADO
ARBY_PORTAL_HOST=0.0.0.0
ARBY_PORTAL_PORT=8080
```

El servidor exige un hash, limita intentos de acceso y protege acciones con una
sesión y token CSRF. Las sesiones caducan tras cuatro horas sin uso y también al
reiniciar el portal. Para cambiar la clave, reemplaza el hash y reinicia el portal.

4. Instala el ayudante privilegiado. **Debe ser una copia propiedad de root**,
   nunca un enlace a un archivo modificable por el servidor web.

```bash
sudo install -d -o root -g root -m 755 /usr/local/libexec
sudo install -o root -g root -m 644 deploy/arby-system.py /usr/local/libexec/arby-system.py
sudo visudo -cf deploy/arby-portal.sudoers
sudo install -o root -g root -m 440 deploy/arby-portal.sudoers /etc/sudoers.d/arby-portal
```

El ayudante solo admite consultar red, conectar `wlan0`, reiniciar `arby.service`
y programar un reinicio o apagado del equipo. No ejecuta shell ni acepta nombres de
servicios o interfaces elegidos por el navegador. La contraseña Wi-Fi viaja por
stdin y por un archivo temporal privado; no aparece en argumentos de procesos.
NetworkManager conserva la conexión para próximos arranques.

5. Copia las plantillas de `deploy/systemd/` a `/etc/systemd/system/` y reemplaza
   **todas** las apariciones de `@PROJECT_DIR@` por la ruta absoluta del proyecto.
   Las plantillas requieren una ruta sin espacios. Si ya tienes un servicio Arby,
   adapta el existente en lugar de iniciar otro proceso paralelo.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now arby-portal.service arby.service
sudo systemctl status arby-portal.service arby.service
```

El servicio Arby conserva root por el hardware, como el arranque documentado del
proyecto. El portal usa una cuenta restringida y solo puede escribir en `config`.
El servicio Arby está pensado para el perfil `ARBY_INPUT_MODE=voice` y ojos físicos
o `none`; la consola de texto y la ventana de previsualización requieren sesión
interactiva y no se deben usar como perfil de feria sin escritorio.

## Ejecución manual y desarrollo

Instala `uv sync --inexact --extra support` y exporta `ARBY_PORTAL_PASSWORD_HASH` con el hash
generado. Ejecuta `.venv/bin/python -m libraries.support.server`.
Para publicar el estado del proceso manual usa `ARBY_SUPPORT=true
.venv/bin/python run_arby.py` en una sola línea, con los permisos habituales del
hardware. El portal no inicia otro proceso de Arby por su cuenta. Sin instalar
el ayudante y los servicios, red y reinicios devolverán un error explicativo;
el resto del panel puede probarse localmente.

La base usa tablas separadas para ajustes, instantánea y comandos, sin guardar
secretos ni frases de visitantes. Las solicitudes de prueba caducan a los treinta
segundos y se limpian después de un día. La telemetría se limita a una escritura
por segundo y sus fallos no detienen la conversación. El portal no consume la
cola de eventos de consola.

## Comprobación en la feria

1. Abre el panel en celular y pantalla local; verifica acceso con y sin clave.
2. Comprueba micrófono hablando y Trill tocando cada zona; mira el estado físico.
3. Ejecuta las pruebas de sonido y ojos con Arby libre y verifica el resultado.
4. Guarda un intervalo nuevo: no debe cambiar nada hasta aplicar y reiniciar.
5. Reinicia Arby: el portal debe seguir abierto y recuperar un estado reciente.
6. Prueba cambio de Wi-Fi y reinicio completo con acceso SSH alternativo disponible.

Diagnóstico por SSH: `journalctl -u arby -u arby-portal -n 80`.
El portal no expone esos registros porque pueden contener conversaciones.
Si falta NetworkManager o hay problemas de permisos, el panel sigue disponible
y muestra el fallo de la acción. No cambies la red de la Raspberry automáticamente
al instalar este portal.

## Bluetooth desde el portal

El panel **Bluetooth**, dentro de **Conexión**, consulta el adaptador de la Raspberry, busca dispositivos
(encendiendo el adaptador), empareja sin PIN, conecta y desconecta. Las acciones
requieren la sesión de soporte y protección CSRF. Los dispositivos que requieren
introducir o confirmar un PIN deben emparejarse previamente por SSH con
`bluetoothctl`. La conexión no cambia automáticamente la selección de audio de Arby.

La lista muestra el nombre anunciado por el dispositivo y consulta su nombre o alias
si BlueZ devuelve una dirección como etiqueta. La MAC queda en **Identificador del
dispositivo**, un detalle desplegable. Los dispositivos sin nombre se omiten de la
lista de conexión; el panel indica cuántos se omitieron. Activa el modo de
emparejamiento y vuelve a buscar si falta el tuyo. Un equipo ya conectado permanece
visible aunque no anuncie nombre, para permitir desconectarlo.

En la Raspberry instala BlueZ y actualiza el helper después de traer estos cambios:

```bash
sudo apt install bluez
sudo systemctl enable --now bluetooth
sudo install -o root -g root -m 644 deploy/arby-system.py /usr/local/libexec/arby-system.py
```

Reinicia el portal (o vuelve a ejecutar el comando de desarrollo) y abre la sección
**Conexión**, donde aparece el panel Bluetooth. El helper requiere los permisos sudo configurados en esta guía; iniciar
solo Flask no concede acceso al Bluetooth. Si usas otra cuenta para desarrollo,
las reglas de `arby-portal` no se aplican a esa cuenta.

Si el portal muestra «Acción no disponible», comprueba desde el checkout en la
Raspberry que el helper instalado y sus permisos corresponden a esta versión:

```bash
sudo systemctl status bluetooth --no-pager
sudo -u arby-portal sudo -n /usr/bin/python3 -I /usr/local/libexec/arby-system.py <<<'{"action":"bluetooth"}'
sudo -u arby-portal sudo -n /usr/bin/python3 -I /usr/local/libexec/arby-system.py <<<'{"action":"bluetooth_scan"}'
```

Las dos últimas órdenes deben devolver JSON. Si sudo rechaza la ejecución, revisa
`deploy/arby-portal.sudoers`. Si falta el helper, reinstálalo con el comando anterior.
Esta versión reserva `bluetoothctl --timeout` para el escaneo: usarlo también en
las consultas y conexiones fuerza esperas completas y puede agotar el plazo HTTP.
Después de actualizar el helper y el código, ejecuta
`sudo systemctl restart arby-portal.service`.

Implementación basada en los comandos de [BlueZ bluetoothctl](https://kernel.googlesource.com/pub/scm/bluetooth/bluez.git/+/a93047cd044fb17d687f43bef95289ec834876b2/doc/bluetoothctl.rst).

## Depuración

Con `ARBY_SUPPORT=true`, abre **Depuración** en el menú del portal. Tras
actualizar el código, reinicia Arby y recarga el navegador. La vista incluye:

- Esquema de entradas → cola → modelo → voz, ojos y luces → espera.
- Etapa actual y tiempo transcurrido, con ubicación en el código y pila
  muestreada de los hilos de conversación, captura y reconocimiento.
- Toques Trill con zona, canal, intensidad y reacción aceptada u omitida;
  liberaciones del sensor, inicio de voz y finalización del reconocimiento.
- Cambios de pausa de captura, modo de escucha, pérdidas de bloques de audio,
  solicitudes recibidas, completadas, interrumpidas y fallidas.
- Últimos 250 eventos con filtro de texto y pausa de visualización. El historial
  se reemplaza al reiniciar Arby y no guarda preguntas, respuestas ni audio.

El proceso publica aproximadamente cada segundo; el navegador consulta cada
3 segundos. Tras 8 segundos sin publicación se indica pérdida de actualizaciones:
puede significar proceso detenido o bloqueo del bucle principal. La última pila
recibida es histórica en ese caso. Las etapas de inicialización y consulta al
modelo se marcan prolongadas tras 60 segundos; reproducción y ejecución general,
tras 120 segundos. Son indicios para investigar, no un diagnóstico definitivo.
Esperar solicitudes sin trabajo pendiente es normal y no dispara esa alerta.

La consola conserva respuestas y errores. Los mensajes habituales del pipeline
de voz pasan al nivel DEBUG de Python; las advertencias de captura y errores de
reconocimiento permanecen visibles.
