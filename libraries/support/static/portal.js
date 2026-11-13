'use strict';

const $ = id => document.getElementById(id);
const views = {
  debug: ["Depuración de Arby", "Flujo, sensores y registro de ejecución en tiempo real."],
  visits: ['Visitas de Arby', 'Conversaciones iniciadas durante los eventos.'],
  overview: ['¿Cómo está Arby?', 'Todo lo esencial, de un vistazo.'],
  audio: ['Escuchar y hacerse escuchar.', 'Elige los dispositivos que Arby debe recordar.'],
  experience: ['A su propio ritmo.', 'Prepara el comportamiento y la iluminación para la feria.'],
  tests: ['Un momento para comprobar.', 'Prueba la voz, las expresiones y los colores de Arby.'],
  network: ['Siempre cerca.', 'Administra la conexión Wi-Fi y los dispositivos Bluetooth del equipo.'],
  system: ['Cuidar del equipo.', 'Reinicia o apaga la Raspberry de forma ordenada.'],
};
const componentNames = {trill: 'Sensores Trill', microphone: 'Micrófono', speaker: 'Altavoz', eyes: 'Ojos', strip: 'Tira de luces'};
const stateLabels = {ready: 'Funcionando', disabled: 'Desactivado', error: 'Con error', unknown: 'Sin comprobar'};
let csrf = '', dirty = false, filled = false, latest = null, timer = null;
let noticeTimer, refreshing = false, audioLoading = false, audioDevices = [];
let audioDraft = {input: null, output: null}, audioInventory = null;
let audioChecked = 0;
let demoCatalog = [], networkLoaded = false, powerMessage = '', powerUntil = 0;

const mobileMenu = window.matchMedia('(max-width: 760px)');
function setMenu(open, restoreFocus = true) {
  open = open && mobileMenu.matches;
  document.body.classList.toggle('menu-open', open);
  $('menu-open').setAttribute('aria-expanded', String(open));
  $('menu-backdrop').hidden = !open;
  const sidebar = $('portal-sidebar');
  sidebar.inert = mobileMenu.matches && !open;
  document.querySelector('main').inert = open;
  document.querySelector('.mobile-header').inert = open;
  if (open) {
    sidebar.setAttribute('role', 'dialog');
    sidebar.setAttribute('aria-modal', 'true');
    $('menu-close').focus();
  } else {
    sidebar.removeAttribute('role');
    sidebar.removeAttribute('aria-modal');
    if (restoreFocus && mobileMenu.matches) $('menu-open').focus();
  }
}
$('menu-open').addEventListener('click', () => setMenu(true));
$('menu-close').addEventListener('click', () => setMenu(false));
$('menu-backdrop').addEventListener('click', () => setMenu(false));
document.querySelectorAll('[data-nav], .sidebar .brand').forEach(link => {
  link.addEventListener('click', () => setMenu(false));
});
document.addEventListener('keydown', event => {
  if (!document.body.classList.contains('menu-open')) return;
  if (event.key === 'Escape') setMenu(false);
  if (event.key === 'Tab') {
    const items = [...$('portal-sidebar').querySelectorAll('a[href], button:not(:disabled)')];
    const first = items[0], last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }
});
mobileMenu.addEventListener('change', () => setMenu(false, false));
setMenu(false, false);

function notice(message, error = false) {
  $('notice').textContent = message;
  $('notice').classList.toggle('error', error);
  $('notice').hidden = false;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => $('notice').hidden = true, 10000);
}

async function api(url, method = 'GET', data, retried = false) {
  const response = await fetch(url, {
    method,
    headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf},
    body: data === undefined ? undefined : JSON.stringify(data),
    signal: AbortSignal.timeout(url === '/api/bluetooth/connect' ? 60000 : 40000),
  });
  const payload = await response.json().catch(() => ({error: 'Respuesta inesperada. Recarga la página.'}));
  if (!response.ok) {
    if (response.status === 401 && url !== '/api/login') showLogin();
    if (!retried && response.status === 403 && payload.code === 'csrf_mismatch') {
      const info = await api('/api/session');
      csrf = info.csrf;
      if (info.authenticated || url === '/api/login') {
        return api(url, method, data, true);
      }
      showLogin();
      throw new Error('Introduce la clave de soporte para continuar.');
    }
    throw new Error(payload.error || 'No se pudo completar la acción.');
  }
  return payload;
}

function showLogin() {
  setMenu(false, false);
  clearInterval(timer);
  $('login').hidden = false;
  $('portal').hidden = true;
}

async function showPortal() {
  $('login').hidden = true;
  $('portal').hidden = false;
  filled = false;
  dirty = false;
  latest = null;
  audioInventory = null;
  powerMessage = '';
  await refresh();
  navigate();
  clearInterval(timer);
  timer = setInterval(refresh, 3000);
}

function currentView() {
  const value = location.hash.slice(1);
  return Object.hasOwn(views, value) ? value : 'overview';
}

function navigate() {
  const view = currentView();
  document.querySelectorAll('[data-view]').forEach(node => node.hidden = node.dataset.view !== view);
  document.querySelectorAll('[data-nav]').forEach(node => {
    if (node.dataset.nav === view) node.setAttribute('aria-current', 'page');
    else node.removeAttribute('aria-current');
  });
  $('page-title').textContent = views[view][0];
  $('page-description').textContent = views[view][1];
  document.title = `${views[view][0]} · Arby`;
  $('savebar').hidden = !['audio', 'experience'].includes(view);
  if (!$('portal').hidden) {
    if (view === 'visits') loadVisits().catch(error => { $('visits-summary').textContent = error.message; });
    if (view === 'audio' && (!audioInventory || Date.now() - audioChecked > 3000)) loadAudio().catch(error => notice(error.message, true));
    if (view === 'network') loadBluetooth(true).catch(error => notice(error.message, true));
    if (view === 'network' && !networkLoaded) $('refresh-network').click();
  }
}
window.addEventListener('hashchange', navigate);

function confirmAction(title, text, danger = false) {
  const dialog = $('confirmation');
  $('confirm-title').textContent = title;
  $('confirm-text').textContent = text;
  $('confirm-ok').classList.toggle('danger', danger);
  dialog.returnValue = '';
  dialog.showModal();
  return new Promise(resolve => dialog.addEventListener('close', () => resolve(dialog.returnValue === 'ok'), {once: true}));
}

async function guarded(button, action) {
  button.disabled = true;
  try { await action(); }
  catch (error) { notice(error.message || 'Se perdió la conexión con el portal.', true); }
  finally { button.disabled = Boolean(powerMessage && !powerUntil); updateTestButtons(); }
}

function pendingLabel() {
  $('pending').textContent = dirty ? 'Tienes ajustes sin guardar.' : latest?.runtime.pending_changes ?
    'Hay ajustes guardados pendientes de aplicar.' : 'Guardar no interrumpe una conversación.';
  $('save-title').textContent = dirty ? 'Cambios sin guardar' : latest?.runtime.pending_changes ? 'Listo para aplicar' : 'Configuración de Arby';
}

function fill(data) {
  const controls = {...data.defaults, ...data.runtime.effective?.controls, ...data.saved.controls};
  const ambient = data.saved.ambient;
  $('mode').value = ambient.mode;
  $('gesture-min').value = ambient.gesture_min_seconds;
  $('gesture-max').value = ambient.gesture_max_seconds;
  $('invitation-min').value = ambient.invitation_min_seconds;
  $('invitation-max').value = ambient.invitation_max_seconds;
  $('voice-on').checked = !controls.mute;
  $('rate').value = parseInt(controls.rate, 10);
  $('gain').value = controls.mic_gain_db;
  $('mic-channel').value = controls.mic_channel || 'left';
  $('matrix-brightness').value = controls.matrix_brightness;
  $('strip-brightness').value = controls.strip_brightness;
  audioDraft = structuredClone(data.saved.audio || {input: null, output: null});
  renderAudio();
  filled = true;
}

function updateVisibility(runtime) {
  const capabilities = runtime.capabilities || {};
  $('eyes-control').hidden = capabilities.eyes === false;
  $('strip-control').hidden = capabilities.strip === false;
  $('intervals').hidden = $('mode').value !== 'evento';
  $('light-hint').textContent = capabilities.eyes === false && capabilities.strip === false ?
    'No hay iluminación física activada en este perfil.' : 'Un brillo moderado suele ser más cómodo en interiores.';
}

function renderComponents(runtime, okay) {
  const list = $('components');
  list.replaceChildren();
  for (const [key, name] of Object.entries(componentNames)) {
    const component = runtime.components?.[key] || {state: 'unknown', detail: 'Esperando información de Arby.'};
    const state = okay ? component.state : component.state === 'disabled' ? 'disabled' : 'unknown';
    const card = document.createElement('article');
    card.className = 'card';
    const heading = document.createElement('div');
    heading.className = 'card-head';
    const title = document.createElement('strong');
    title.textContent = name;
    const badge = document.createElement('span');
    badge.className = `badge ${state}`;
    badge.textContent = stateLabels[state] || stateLabels.unknown;
    const detail = document.createElement('p');
    detail.textContent = okay || state === 'disabled' ? component.detail : 'Sin comprobación actual. Revisa Arby antes de probar.';
    heading.append(title, badge);
    card.append(heading, detail);
    list.append(card);
  }
}

function renderActivity(runtime, okay) {
  const mic = okay && runtime.capabilities?.microphone ?
    `Micrófono: ${runtime.microphone_activity ? 'detectando actividad o procesando' : 'en espera'}` : 'Micrófono: sin actividad confirmada';
  const touch = okay && runtime.last_touch ?
    `Último toque: ${runtime.last_touch.zone} · canal ${runtime.last_touch.channel} · ${new Date(runtime.last_touch.at * 1000).toLocaleTimeString()}` :
    'Sin toques recientes confirmados.';
  for (const id of ['mic-activity', 'audio-mic-activity', 'test-mic-activity']) $(id).textContent = mic;
  for (const id of ['touch-activity', 'test-touch-activity']) $(id).textContent = touch;
  const rms = okay ? Number(runtime.microphone_level || 0) : 0;
  const level = rms > 0 ? Math.min(100, Math.max(0, 100 + 20 * Math.log10(rms))) : 0;
  for (const id of ['overview-meter', 'audio-meter', 'test-meter']) { $(id).value = level; $(id).textContent = Math.round(level); }
  for (const role of ['input', 'output']) {
    const active = runtime.audio_active?.[role];
    $(`${role}-active`).textContent = !okay ? 'En uso: sin confirmar.' : active ? `En uso: ${active.name} · ${active.detail}` : 'En uso: configuración instalada.';
  }
}

function renderDemos(tests) {
  if (demoCatalog.length) return;
  demoCatalog = tests;
  for (const test of tests) {
    const button = document.createElement('button');
    button.className = 'demo-button';
    button.dataset.test = test.id;
    const title = document.createElement('strong');
    title.textContent = test.label;
    const detail = document.createElement('span');
    detail.textContent = test.requires.includes('speaker') ? 'Voz y expresión · escuchar' : test.requires.includes('strip') ? 'Color de la tira · 3 segundos' : 'Expresión · 3 segundos';
    button.append(title, detail);
    button.addEventListener('click', () => guarded(button, async () => {
      if (dirty || latest?.runtime.pending_changes) notice('La prueba usa los ajustes actualmente aplicados.');
      await api('/api/tests', 'POST', {kind: test.id});
      $('test-result').textContent = 'Prueba solicitada…';
      await refresh();
    }));
    $('demo-buttons').append(button);
  }
}

function updateTestButtons() {
  const runtime = latest?.runtime;
  const ready = runtime?.fresh && runtime.state === 'ready' && !powerMessage;
  const running = latest?.commands.some(command => ['pending', 'running'].includes(command.state) && command.kind !== 'cancel');
  const visitorBusy = runtime?.visitor_busy ?? runtime?.busy;
  const blocked = powerMessage ? 'Las pruebas no están disponibles durante el reinicio o apagado.' :
    !runtime?.fresh ? 'Sin comunicación reciente con Arby. Comprueba que esté iniciado y que ARBY_SUPPORT esté activado.' :
    runtime.state !== 'ready' ? `Arby no está listo (${runtime.state}). Revisa el estado en Resumen o Depuración.` :
    running ? 'Hay una demostración solicitada. Puedes detenerla o esperar a que termine.' :
    visitorBusy ? 'Arby está atendiendo una conversación. Espera a que termine para probar.' : '';
  $('tests-availability').textContent = blocked || 'Elige una demostración. Si hay una animación automática, la prueba esperará su turno.';
  for (const definition of demoCatalog) {
    const button = document.querySelector(`[data-test="${definition.id}"]`);
    const unavailable = definition.requires.filter(key => runtime?.capabilities?.[key] !== true);
    const names = unavailable.map(key => componentNames[key] || key).join(', ');
    const reason = blocked || (unavailable.length ? `No disponible: ${names}. Revisa los componentes y los ajustes aplicados.` : '');
    if (button) {
      button.disabled = !ready || visitorBusy || running || unavailable.length > 0;
      button.title = reason;
      button.querySelector('span').textContent = reason || (definition.requires.includes('speaker') ? 'Voz y expresión · escuchar' : definition.requires.includes('strip') ? 'Color de la tira · 3 segundos' : 'Expresión · 3 segundos');
    }
  }
  $('cancel-test').disabled = !ready || !running;
}

async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    const data = await api('/api/status');
    latest = data;
    const runtime = data.runtime;
    const okay = runtime.fresh && runtime.state === 'ready';
    $('connection').textContent = powerMessage && !powerUntil ? 'Apagado solicitado' : 'Portal conectado';
    $('summary').classList.toggle('error', !okay);
    if (powerMessage && powerUntil && Date.now() > powerUntil) powerMessage = '';
    $('summary').textContent = powerMessage || (!runtime.fresh ? 'Sin información reciente de Arby. Revisa si está detenido o reinícialo.' :
      runtime.state === 'starting' ? 'Arby está iniciando…' : runtime.state === 'error' ? 'Arby tuvo un error. Revisa los dispositivos y prueba reiniciarlo.' :
      runtime.state === 'stopped' ? 'Arby está detenido. Puedes iniciarlo desde Equipo y energía.' : runtime.busy ?
      'Arby está atendiendo. Espera para hacer pruebas.' : 'Arby está disponible. Todo listo para comprobar el equipo.');
    $('mode-label').textContent = runtime.effective?.ambient?.mode === 'evento' ? 'Modo evento' :
      runtime.effective?.ambient?.mode === 'oficina' ? 'Modo oficina' : 'Modo sin confirmar';
    $('updated').textContent = runtime.fresh ? 'Estado actualizado' : 'Estado sin actualizar';
    renderComponents(runtime, okay);
    renderActivity(runtime, okay);
    renderDebug(runtime);
    if (!filled && !dirty) fill(data);
    updateVisibility(runtime);
    renderDemos(data.tests || []);
    updateTestButtons();
    pendingLabel();
    if (data.commands[0]) $('test-result').textContent = data.commands[0].message;
    if (currentView() === 'visits') await loadVisits();
    if (currentView() === 'audio' && Date.now() - audioChecked > 10000) {
      await loadAudio().catch(error => { $('audio-discovery').textContent = error.message; });
    }
  } catch (error) {
    $('connection').textContent = 'Sin conexión';
    $('summary').textContent = powerMessage || 'No se pudo consultar Arby. Intentando reconectar…';
    $('summary').classList.add('error');
    if (latest) { latest.runtime.fresh = false; renderDebug(latest.runtime); renderComponents(latest.runtime, false); renderActivity(latest.runtime, false); }
    updateTestButtons();
  } finally { refreshing = false; }
}

function sameIdentity(left, right) {
  return left && right && Object.keys(left).every(key => left[key] === right[key]);
}

function renderAudio() {
  for (const role of ['input', 'output']) {
    const select = $(`${role}-device`);
    select.replaceChildren(new Option('Usar configuración instalada', ''));
    for (const device of audioDevices.filter(item => item.role === role)) {
      select.add(new Option(`${device.name} · ${device.detail}`, device.id));
    }
    const draft = audioDraft[role];
    const exact = audioDevices.find(device => device.role === role && sameIdentity(draft, device.identity));
    const isSaved = sameIdentity(draft, latest?.saved.audio?.[role]);
    const matching = exact || (isSaved && audioDevices.find(device => device.id === audioInventory?.preferred[role]?.id));
    if (draft && !matching) select.add(new Option(`No conectado · ${draft.name}`, '__saved__'));
    select.value = draft ? matching ? matching.id : '__saved__' : '';
    const message = !draft ? 'Sin selección en el panel. Se conserva la configuración instalada.' : matching ?
      `Predeterminado: ${draft.name}. Se reconocerá aunque cambie de número.` :
      (isSaved ? audioInventory?.preferred[role]?.message : null) || 'El predeterminado no está conectado. Conéctalo o elige otro.';
    $(`${role}-preference`).textContent = message;
    $(`${role}-preference`).classList.toggle('unavailable', Boolean(draft && !matching));
  }
}

async function loadAudio() {
  if (audioLoading) return;
  audioLoading = true;
  $('refresh-audio').disabled = true;
  try {
    audioInventory = await api('/api/audio/devices');
    audioDevices = audioInventory.devices;
    audioChecked = Date.now();
    $('audio-discovery').textContent = audioInventory.message;
    renderAudio();
  } finally { audioLoading = false; $('refresh-audio').disabled = false; }
}

$('refresh-audio').addEventListener('click', () => loadAudio().catch(error => notice(error.message, true)));
for (const role of ['input', 'output']) {
  $(`${role}-device`).addEventListener('change', event => {
    const device = audioDevices.find(item => item.id === event.target.value && item.role === role);
    if (event.target.value === '__saved__') return;
    audioDraft[role] = device ? structuredClone(device.identity) : null;
    dirty = true;
    renderAudio();
    pendingLabel();
  });
}

function visitsQuery() {
  const query = new URLSearchParams();
  if ($('visits-start').value) query.set('start', $('visits-start').value);
  if ($('visits-end').value) query.set('end', $('visits-end').value);
  return query.toString();
}
async function loadVisits() {
  try {
    const query = visitsQuery();
    const data = await api(`/api/visits?${query}`);
    $('visits-export').href = `/api/visits/export.csv?${query}`;
    $('visits-summary').textContent = `${data.total} visitas · ${data.messages} mensajes.` +
      (data.incomplete ? ' Conteo incompleto: hubo fallos de almacenamiento.' : '') +
      (data.error ? ` ${data.error}` : '');
    $('visits-summary').classList.toggle('error', data.incomplete);
    $('visits-rows').replaceChildren();
    const format = value => value ? new Date(value).toLocaleString('es-CO', {timeZone: 'America/Bogota'}) : '—';
    const reasons = {timeout: 'Finalizada', shutdown: 'Cierre del programa', interrupted: 'Interrumpida'};
    for (const visit of data.visits) {
      const row = document.createElement('tr');
      for (const value of [format(visit.started_at), format(visit.last_activity_at), format(visit.ended_at),
        reasons[visit.close_reason] || 'Activa', visit.messages]) {
        const cell = document.createElement('td');
        cell.textContent = value;
        row.append(cell);
      }
      $('visits-rows').append(row);
    }
    if (!data.visits.length) $('visits-summary').textContent += ' Sin visitas en este período.';
  } catch (error) {
    $('visits-rows').replaceChildren();
    $('visits-summary').textContent = `Conteo no disponible: ${error.message}`;
    throw error;
  }
}
$('visits-form').addEventListener('submit', event => {
  event.preventDefault();
  guarded(event.submitter, loadVisits);
});

$('login-form').addEventListener('submit', event => {
  event.preventDefault();
  guarded(event.submitter, async () => {
    const result = await api('/api/login', 'POST', {password: $('password').value});
    $('password').value = '';
    csrf = result.csrf;
    await showPortal();
  });
});
$('logout').addEventListener('click', () => guarded($('logout'), async () => {
  await api('/api/logout', 'POST', {});
  const result = await api('/api/session');
  csrf = result.csrf;
  dirty = false;
  filled = false;
  showLogin();
}));
$('settings-form').addEventListener('input', () => {
  dirty = true;
  pendingLabel();
  updateVisibility(latest?.runtime || {});
});
$('settings-form').addEventListener('submit', event => {
  event.preventDefault();
  const invalid = $('settings-form').querySelector(':invalid');
  if (invalid) {
    location.hash = invalid.closest('[data-view]').dataset.view;
    navigate();
    invalid.reportValidity();
    return;
  }
  guarded(event.submitter, async () => {
    const value = id => Number($(id).value);
    const rate = value('rate');
    const payload = {
      ambient: {mode: $('mode').value, gesture_min_seconds: value('gesture-min'), gesture_max_seconds: value('gesture-max'),
        invitation_min_seconds: value('invitation-min'), invitation_max_seconds: value('invitation-max')},
      controls: {mute: !$('voice-on').checked, rate: `${rate >= 0 ? '+' : ''}${rate}%`, mic_gain_db: value('gain'),
        mic_channel: $('mic-channel').value, matrix_brightness: value('matrix-brightness'), strip_brightness: value('strip-brightness')},
      audio: audioDraft,
    };
    await api('/api/settings', 'PUT', payload);
    dirty = false;
    notice('Ajustes guardados. Aplica los cambios cuando Arby esté libre.');
    await refresh();
    if (currentView() === 'audio') await loadAudio();
  });
});

async function energyAction(target) {
  if (dirty && target === 'arby') { notice('Guarda primero los ajustes que acabas de cambiar.', true); return; }
  const shutdown = target === 'shutdown';
  const title = shutdown ? 'Apagar la Raspberry' : target === 'arby' ? 'Reiniciar Arby' : 'Reiniciar la Raspberry';
  let description = shutdown ? 'Se cerrarán los servicios y el equipo se apagará. El panel dejará de responder y tendrás que encender la Raspberry físicamente para volver a usarla.' :
    target === 'arby' ? 'Se interrumpirá la conversación actual y se aplicarán los ajustes guardados. El panel permanecerá abierto.' :
    'Se interrumpirá la conversación. El panel dejará de responder mientras la Raspberry vuelve a arrancar.';
  if (dirty) description += ' Los cambios sin guardar no se aplicarán.';
  if (!await confirmAction(title, description, shutdown)) return;
  const result = await api(shutdown ? '/api/power' : '/api/restart', 'POST', {target});
  powerMessage = result.message;
  powerUntil = shutdown ? 0 : Date.now() + 12000;
  $('summary').textContent = powerMessage;
  notice(result.message);
  if (shutdown) {
    clearInterval(timer);
    $('connection').textContent = 'Apagado solicitado';
    document.querySelectorAll('main button').forEach(button => button.disabled = true);
  }
  updateTestButtons();
}
for (const [id, target] of [['apply', 'arby'], ['restart-arby', 'arby'], ['restart-pi', 'raspberry'], ['shutdown-pi', 'shutdown']]) {
  $(id).addEventListener('click', () => guarded($(id), () => energyAction(target)));
}
$('cancel-test').addEventListener('click', () => guarded($('cancel-test'), async () => {
  await api('/api/tests/cancel', 'POST', {});
  await refresh();
}));
let wifiNetworks = [];
function updateWifiSelection() {
  const network = wifiNetworks.find(item => item.ssid === $('ssid').value);
  const secured = Boolean(network?.security && network.security !== '--');
  $('wifi-credentials').hidden = !network || !secured;
  $('wifi-password').disabled = !secured;
  $('connect-wifi').disabled = !network;
  $('wifi-hint').textContent = network ? (secured ? 'Introduce la contraseña y pulsa Conectar a la red.' : 'Esta red es abierta. Puedes conectarte sin contraseña.') : 'Elige una red de la lista. Pulsa Buscar redes para volver a explorar.';
}
$('ssid').addEventListener('change', () => {
  $('wifi-password').value = '';
  updateWifiSelection();
});
$('show-wifi-password').addEventListener('change', event => {
  $('wifi-password').type = event.target.checked ? 'text' : 'password';
});
$('refresh-network').addEventListener('click', () => guarded($('refresh-network'), async () => {
  $('network-status').textContent = 'Buscando redes Wi-Fi cercanas…';
  try {
    const result = await api('/api/network');
    const states = {full: 'Internet disponible', limited: 'Conectividad limitada', portal: 'La red puede requerir iniciar sesión', none: 'Sin conexión a internet', unknown: 'Internet sin comprobar'};
    const devices = result.devices.filter(device => device[1] !== 'loopback').map(device => `${device[0]}: ${device[3] || device[2]}`).join(' · ');
    $('network-status').textContent = `${states[result.connectivity] || states.unknown}. ${devices}. IP: ${result.addresses.join(', ') || 'sin dirección'}`;
    const selected = $('ssid').value;
    wifiNetworks = result.networks.sort((a, b) => Number(b.signal) - Number(a.signal));
    $('ssid').replaceChildren(new Option(wifiNetworks.length ? 'Selecciona una red disponible' : 'No se encontraron redes', ''));
    for (const network of wifiNetworks) {
      const signal = Number(network.signal);
      const strength = signal >= 70 ? 'alta' : signal >= 40 ? 'media' : 'baja';
      const security = network.security && network.security !== '--' ? network.security : 'Abierta, sin contraseña';
      $('ssid').add(new Option(`${network.ssid} · Señal ${strength} (${network.signal}%) · ${security}`, network.ssid));
    }
    $('ssid').value = wifiNetworks.some(item => item.ssid === selected) ? selected : '';
    $('ssid').disabled = !wifiNetworks.length;
    updateWifiSelection();
    if (!wifiNetworks.length) $('wifi-hint').textContent = 'Acerca Arby al router y pulsa Buscar redes para intentarlo de nuevo.';
    networkLoaded = true;
  } catch (error) {
    $('network-status').textContent = `No se pudieron buscar las redes: ${error.message}`;
    throw error;
  }
}));
$('wifi-form').addEventListener('submit', event => {
  event.preventDefault();
  guarded(event.submitter, async () => {
    if (!await confirmAction('Cambiar de red Wi-Fi', 'Se cambiará la conexión a internet de wlan0. Si estás accediendo por esa red, el panel puede desconectarse o cambiar de IP. La configuración de wlan1 se conserva. ¿Continuar?')) return;
    const password = $('wifi-password').disabled ? '' : $('wifi-password').value;
    $('network-status').textContent = `Conectando a ${$('ssid').value}… Esto puede tardar unos segundos.`;
    $('wifi-password').value = '';
    try {
      const result = await api('/api/network/connect', 'POST', {ssid: $('ssid').value, password});
      $('network-status').textContent = result.message;
      notice(result.message);
    } catch (error) {
      $('network-status').textContent = `No se pudo conectar: ${error.message}`;
      throw error;
    }
  });
});

let bluetoothBusy = false;
function identifiableBluetoothDevice(device) {
  const name = (device.name || '').trim();
  return Boolean(name && name !== 'Dispositivo sin nombre'
    && !/^(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}$/i.test(name));
}

async function loadBluetooth(scan = false) {
  if (bluetoothBusy) return;
  bluetoothBusy = true;
  $('refresh-bluetooth').disabled = $('scan-bluetooth').disabled = true;
  $('bluetooth-devices').replaceChildren();
  $('bluetooth-status').textContent = scan ? 'Buscando dispositivos y sus nombres… Pon tus audífonos en modo de emparejamiento. Puede tardar unos 25 segundos.' : 'Consultando Bluetooth…';
  try {
    const result = await api(scan ? '/api/bluetooth/scan' : '/api/bluetooth', scan ? 'POST' : 'GET');
    const devices = result.devices.filter(device => identifiableBluetoothDevice(device) || device.connected);
    const hiddenCount = result.devices.length - devices.length;
    $('bluetooth-status').textContent = result.powered
      ? (devices.length ? 'Bluetooth encendido. Elige tu dispositivo por su nombre.' : 'No se encontraron dispositivos con nombre. Activa el modo de emparejamiento del equipo y pulsa Buscar dispositivos.')
      : 'Bluetooth apagado. Pulsa Buscar dispositivos para encenderlo.';
    if (result.powered && hiddenCount) $('bluetooth-status').textContent += ` Se omitieron ${hiddenCount} dispositivos sin identificar. Si falta el tuyo, activa su modo de emparejamiento y vuelve a buscar.`;
    for (const device of devices.sort((a, b) => Number(b.connected) - Number(a.connected) || Number(b.paired) - Number(a.paired) || (a.name || '').localeCompare(b.name || ''))) {
      const displayName = identifiableBluetoothDevice(device) ? device.name : 'Dispositivo conectado sin nombre';
      const card = document.createElement('article');
      card.className = 'card bluetooth-device';
      const name = document.createElement('strong');
      name.textContent = displayName;
      const state = document.createElement('p');
      state.textContent = device.connected ? 'Conectado' : device.paired ? 'Emparejado' : 'Sin emparejar';
      const details = document.createElement('details');
      const summary = document.createElement('summary');
      summary.textContent = 'Identificador del dispositivo';
      const address = document.createElement('p');
      address.textContent = device.address;
      details.append(summary, address);
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'secondary';
      button.textContent = device.connected ? 'Desconectar' : device.paired ? 'Conectar' : 'Emparejar y conectar';
      button.setAttribute('aria-label', `${button.textContent} ${displayName}`);
      button.addEventListener('click', () => guarded(button, async () => {
        if (bluetoothBusy) return;
        bluetoothBusy = true;
        button.textContent = device.connected ? 'Desconectando…' : 'Conectando…';
        $('bluetooth-status').textContent = `${device.connected ? 'Desconectando' : 'Conectando'} ${displayName}…`;
        $('refresh-bluetooth').disabled = $('scan-bluetooth').disabled = true;
        $('bluetooth-devices').querySelectorAll('button').forEach(item => item.disabled = true);
        let actionError = '';
        try {
          const response = await api(`/api/bluetooth/${device.connected ? 'disconnect' : 'connect'}`, 'POST', {address: device.address});
          notice(response.message);
          audioInventory = null;
        } catch (error) {
          actionError = error.message;
          throw error;
        } finally {
          bluetoothBusy = false;
          try {
            await loadBluetooth();
          } finally {
            if (actionError) $('bluetooth-status').textContent = actionError;
          }
        }
      }));
      card.append(name, state, button, details);
      $('bluetooth-devices').append(card);
    }
  } catch (error) {
    $('bluetooth-status').textContent = error.message;
    throw error;
  } finally {
    bluetoothBusy = false;
    $('refresh-bluetooth').disabled = $('scan-bluetooth').disabled = false;
  }
}
for (const [id, scan] of [['refresh-bluetooth', false], ['scan-bluetooth', true]]) {
  $(id).addEventListener('click', () => guarded($(id), () => loadBluetooth(scan)));
}

(async () => {
  try {
    const result = await api('/api/session');
    csrf = result.csrf;
    result.authenticated ? await showPortal() : showLogin();
  } catch (error) { showLogin(); notice('No se pudo abrir el portal. Recarga la página.', true); }
})();


let debugPaused = false, debugEvents = [];
function debugNode(tag, text, className) {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
}
function renderDebug(runtime) {
  const debug = runtime.debug;
  const stale = !runtime.fresh;
  const slow = Object.values(debug?.stages || {}).some(stage => stage.slow);
  $('debug-health').textContent = !debug ? 'Sin telemetría de depuración. Activa ARBY_SUPPORT y reinicia Arby.' :
    stale ? `Sin actualizaciones: posible detención o bloqueo. Último dato: ${new Date(runtime.updated_at * 1000).toLocaleString()}.` :
    runtime.state !== 'ready' ? `Estado del proceso: ${runtime.state}` :
    slow ? 'Operación prolongada: revisa la etapa y el hilo correspondiente.' :
    runtime.busy ? 'Arby está ejecutando una solicitud.' : 'Arby está esperando actividad.';
  const stages = $('debug-stages'); stages.replaceChildren();
  for (const [source, stage] of Object.entries(debug?.stages || {})) {
    const card = debugNode('article', '', 'debug-stage');
    card.append(debugNode('strong', `${source}: ${stage.name}`),
      debugNode('p', `${stage.elapsed} s${stage.slow ? ' · operación prolongada' : ''}${stale ? ' · último dato recibido' : ''}`),
      debugNode('code', stage.location));
    stages.append(card);
  }
  const flow = $('debug-flow'); flow.replaceChildren();
  const phase = runtime.phase || 'idle';
  for (const [key, title] of [['input', 'Sensores / voz / consola'], ['queue', 'Cola'], ['loading', 'Modelo'], ['speaking', 'Voz + ojos + luces'], ['idle', 'Espera']]) {
    const active = !stale && runtime.state === 'ready' && (key === phase || key === 'queue' && runtime.busy || key === 'input' && runtime.microphone_activity);
    flow.append(debugNode('span', title, active ? 'debug-step active' : 'debug-step'));
  }
  $('debug-inputs').textContent = `Pendientes: ${runtime.debug?.pending ?? '—'} · Captura de voz: ${runtime.capture_blocked ? 'pausada por una solicitud o reproducción' : 'sin pausa del runtime'} · Actividad de micrófono: ${runtime.microphone_activity ? 'sí' : 'no'} · Nivel: ${Number(runtime.microphone_level || 0).toFixed(4)} · Último toque: ${runtime.last_touch ? `${runtime.last_touch.zone}, canal ${runtime.last_touch.channel}, ${new Date(runtime.last_touch.at * 1000).toLocaleTimeString()}` : 'ninguno registrado'}${stale ? ' · Datos sin actualizar' : ''}`;
  const threads = $('debug-threads'); threads.replaceChildren();
  for (const thread of debug?.threads || []) {
    threads.append(debugNode('h3', thread.name), debugNode('pre', thread.stack.join('\n')));
  }
  if (!debugPaused) debugEvents = debug?.events || [];
  renderDebugEvents();
}
function renderDebugEvents() {
  const query = $('debug-filter').value.toLocaleLowerCase();
  const list = $('debug-events'); list.replaceChildren();
  for (const event of [...debugEvents].reverse()) {
    const detail = JSON.stringify(event.details);
    const text = `${new Date(event.at * 1000).toLocaleTimeString()} · ${event.level} · ${event.source} · ${event.message} · ${detail}`;
    if (!text.toLocaleLowerCase().includes(query)) continue;
    list.append(debugNode('pre', text, event.level === 'error' ? 'debug-error' : ''));
  }
  if (!list.children.length) list.append(debugNode('p', 'Sin eventos para mostrar.'));
}
$('debug-filter').addEventListener('input', renderDebugEvents);
$('debug-pause').addEventListener('click', () => {
  debugPaused = !debugPaused;
  $('debug-pause').textContent = debugPaused ? 'Reanudar registro' : 'Pausar registro';
  if (latest) renderDebug(latest.runtime);
});
