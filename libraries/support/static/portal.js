'use strict';

const $ = id => document.getElementById(id);
const views = {
  overview: ['¿Cómo está Arby?', 'Todo lo esencial, de un vistazo.'],
  audio: ['Escuchar y hacerse escuchar.', 'Elige los dispositivos que Arby debe recordar.'],
  experience: ['A su propio ritmo.', 'Prepara el comportamiento y la iluminación para la feria.'],
  tests: ['Un momento para comprobar.', 'Prueba la voz, las expresiones y los colores de Arby.'],
  network: ['Siempre cerca.', 'Revisa internet y la conexión del equipo.'],
  system: ['Cuidar del equipo.', 'Reinicia o apaga la Raspberry de forma ordenada.'],
};
const componentNames = {trill: 'Sensores Trill', microphone: 'Micrófono', speaker: 'Altavoz', eyes: 'Ojos', strip: 'Tira de luces'};
const stateLabels = {ready: 'Funcionando', disabled: 'Desactivado', error: 'Con error', unknown: 'Sin comprobar'};
let csrf = '', dirty = false, filled = false, latest = null, timer = null;
let noticeTimer, refreshing = false, audioLoading = false, audioDevices = [];
let audioDraft = {input: null, output: null}, audioInventory = null;
let audioChecked = 0;
let demoCatalog = [], networkLoaded = false, powerMessage = '', powerUntil = 0;

function notice(message, error = false) {
  $('notice').textContent = message;
  $('notice').classList.toggle('error', error);
  $('notice').hidden = false;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => $('notice').hidden = true, 10000);
}

async function api(url, method = 'GET', data) {
  const response = await fetch(url, {
    method,
    headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf},
    body: data === undefined ? undefined : JSON.stringify(data),
    signal: AbortSignal.timeout(40000),
  });
  const payload = await response.json().catch(() => ({error: 'Respuesta inesperada. Recarga la página.'}));
  if (!response.ok) {
    if (response.status === 401 && url !== '/api/login') showLogin();
    if (response.status === 403) {
      const info = await fetch('/api/session').then(result => result.json());
      csrf = info.csrf;
      if (!info.authenticated) showLogin();
    }
    throw new Error(payload.error || 'No se pudo completar la acción.');
  }
  return payload;
}

function showLogin() {
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
    if (view === 'audio' && (!audioInventory || Date.now() - audioChecked > 3000)) loadAudio().catch(error => notice(error.message, true));
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
  for (const definition of demoCatalog) {
    const button = document.querySelector(`[data-test="${definition.id}"]`);
    if (button) button.disabled = !ready || runtime.busy || !definition.requires.every(key => runtime.capabilities?.[key] === true);
  }
  const running = latest?.commands.some(command => ['pending', 'running'].includes(command.state) && command.kind !== 'cancel');
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
    if (!filled && !dirty) fill(data);
    updateVisibility(runtime);
    renderDemos(data.tests || []);
    updateTestButtons();
    pendingLabel();
    if (data.commands[0]) $('test-result').textContent = data.commands[0].message;
    if (currentView() === 'audio' && Date.now() - audioChecked > 10000) {
      await loadAudio().catch(error => { $('audio-discovery').textContent = error.message; });
    }
  } catch (error) {
    $('connection').textContent = 'Sin conexión';
    $('summary').textContent = powerMessage || 'No se pudo consultar Arby. Intentando reconectar…';
    $('summary').classList.add('error');
    if (latest) { latest.runtime.fresh = false; renderComponents(latest.runtime, false); renderActivity(latest.runtime, false); }
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
$('refresh-network').addEventListener('click', () => guarded($('refresh-network'), async () => {
  const result = await api('/api/network');
  const states = {full: 'Internet disponible', limited: 'Conectividad limitada', portal: 'La red puede requerir iniciar sesión', none: 'Sin conexión a internet', unknown: 'Internet sin comprobar'};
  const devices = result.devices.filter(device => device[1] !== 'loopback').map(device => `${device[0]}: ${device[3] || device[2]}`).join(' · ');
  $('network-status').textContent = `${states[result.connectivity] || 'Internet sin comprobar'}. ${devices}. IP: ${result.addresses.join(', ') || 'sin dirección'}`;
  $('networks').replaceChildren();
  for (const network of result.networks) {
    const option = new Option(network.ssid, network.ssid);
    option.label = `${network.signal}% · ${network.security || 'abierta'}`;
    $('networks').append(option);
  }
  networkLoaded = true;
}));
$('wifi-form').addEventListener('submit', event => {
  event.preventDefault();
  guarded(event.submitter, async () => {
    if (!await confirmAction('Cambiar de red Wi-Fi', 'Se cambiará la conexión a internet de wlan0. Si estás accediendo por esa red, el panel puede desconectarse o cambiar de IP. La configuración de wlan1 se conserva. ¿Continuar?')) return;
    const password = $('wifi-password').value;
    $('wifi-password').value = '';
    const result = await api('/api/network/connect', 'POST', {ssid: $('ssid').value, password});
    notice(result.message);
  });
});

(async () => {
  try {
    const result = await api('/api/session');
    csrf = result.csrf;
    result.authenticated ? await showPortal() : showLogin();
  } catch (error) { showLogin(); notice('No se pudo abrir el portal. Recarga la página.', true); }
})();
