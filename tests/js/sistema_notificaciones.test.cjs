const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const {JSDOM, VirtualConsole} = require('jsdom');
const raiz = path.resolve(__dirname, '../..');
const html = readFileSync(path.join(raiz, 'templates/sistema/notificaciones.html'), 'utf8');
const codigo = readFileSync(path.join(raiz, 'static/js/sistema_notificaciones.js'), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
const id = '55b26dc0-67be-4e50-9cf6-92c0c6c57c63';
const noticia = (extra = {}) => ({id, titulo: 'Ficha actualizada', mensaje: 'Cambios guardados', fecha: '20/11/2026 12:00',
  empresa: 'Ferretería La Fragua', link: '', leida: false, ...extra});
const datos = (items = [], total = items.length, usuario_id = 91) => ({success: true,
  data: {items, total, usuario_id, hasta: '2026-11-20T12:00:00+00:00'}});

async function campana(t, opciones = {}) {
  const errores = [], virtualConsole = new VirtualConsole();
  virtualConsole.on('jsdomError', error => errores.push(error.message));
  const dom = new JSDOM(`<form id="ss-cerrar-sesion"><input name="csrfmiddlewaretoken" value="csrf-prueba"></form>
    ${html}<script id="sistema-confirmaciones" type="application/json"></script>`, {
    runScripts: 'outside-only', url: 'http://localhost/sistema/', pretendToBeVisual: true, virtualConsole,
  });
  t.after(() => dom.window.close());
  const w = dom.window, peticiones = [], intervalos = [];
  const el = nombre => w.document.getElementById('sistema-' + nombre);
  el('notificaciones').dataset.usuario = '91';
  el('notificaciones').dataset.url = '/sistema/notificaciones/';
  el('notificaciones').dataset.leerTodas = '/sistema/notificaciones/leer-todas/';
  el('confirmaciones').textContent = JSON.stringify(opciones.confirmaciones || []);
  if (opciones.vistos) w.sessionStorage.setItem('ss-sistema-confirmaciones:91', JSON.stringify(opciones.vistos));
  w.Notification = {requestPermission() { throw new Error('No pedir permisos del sistema'); }};
  w.setInterval = funcion => { intervalos.push(funcion); return intervalos.length; };
  w.SmartStockCarga = async (_, tarea) => tarea();
  w.fetch = (url, opciones) => new Promise((resolve, reject) => peticiones.push({url, opciones, resolve, reject}));
  w.eval(codigo); await tick();
  const responder = async (indice, respuesta = datos(), status = 200) => {
    peticiones[indice].resolve({ok: status >= 200 && status < 300, status, json: async () => respuesta}); await tick();
  };
  return {w, el, peticiones, intervalos, errores, responder};
}

test('la confirmación se muestra una sola vez y consultar la campana no vuelve a anunciarla', async t => {
  const c = await campana(t, {confirmaciones: [noticia()]});
  assert.equal(c.el('confirmacion').hidden, false);
  await c.responder(0, datos([noticia()]));
  c.el('confirmacion-cerrar').click();
  c.intervalos[0](); await c.responder(1, datos([noticia()]));
  assert.equal(c.el('confirmacion').hidden, true);
  assert.equal(c.el('notificaciones-total').textContent, '1');
  const vuelta = await campana(t, {confirmaciones: [noticia()], vistos: [id]});
  assert.equal(vuelta.el('confirmacion').hidden, true);
  await vuelta.responder(0, datos([noticia()]));
  assert.deepEqual(c.errores, []);
});

test('marcar todas usa sesión y CSRF, evita doble envío y conserva el historial', async t => {
  const c = await campana(t); await c.responder(0, datos([noticia()]));
  c.el('notificaciones-leer').click(); c.el('notificaciones-leer').click();
  assert.equal(c.peticiones.length, 2);
  const envio = c.peticiones[1];
  assert.equal(envio.url, '/sistema/notificaciones/leer-todas/');
  assert.equal(envio.opciones.headers['X-CSRFToken'], 'csrf-prueba');
  assert.equal(envio.opciones.credentials, 'same-origin');
  assert.equal(envio.opciones.headers.Authorization, undefined);
  assert.equal(JSON.parse(envio.opciones.body).hasta, '2026-11-20T12:00:00+00:00');
  await c.responder(1, {success: true}); await c.responder(2);
  assert.equal(c.el('notificaciones-total').hidden, true);
  assert.match(c.el('notificaciones-lista').textContent, /No tienes notificaciones nuevas/);
  c.el('notificaciones-historial').click();
  assert.match(c.peticiones[3].url, /historial=1/);
  await c.responder(3, datos([noticia({leida: true})], 0));
  assert.match(c.el('notificaciones-lista').textContent, /Ficha actualizada/);
  assert.equal(c.el('notificaciones-lista').querySelector('button').dataset.leida, 'true');
});

test('un fallo al marcar mantiene la intención y permite reintentar sin un aviso de éxito', async t => {
  const c = await campana(t); await c.responder(0, datos([noticia()]));
  c.el('notificaciones-leer').click(); await c.responder(1, {}, 500);
  assert.equal(c.el('notificaciones-error').hidden, false);
  assert.equal(c.el('notificaciones-leer').disabled, false);
  assert.equal(c.el('notificaciones-total').textContent, '1');
  assert.equal(c.el('confirmacion').hidden, true);
  c.el('notificaciones-leer').click(); await c.responder(2, {success: true}); await c.responder(3);
  assert.equal(c.el('notificaciones-total').hidden, true);
});

test('la campana presenta textos como datos y bloquea destinos externos', async t => {
  const c = await campana(t);
  await c.responder(0, datos([noticia({titulo: '<img src=x onerror="alert(1)">', mensaje: '<script>alert(1)</script>', link: 'https://example.invalid/'} )]));
  assert.equal(c.el('notificaciones-lista').querySelector('img'), null);
  assert.equal(c.el('notificaciones-lista').querySelector('script'), null);
  assert.match(c.el('notificaciones-lista').textContent, /<img/);
  c.el('notificaciones-lista').querySelector('button').click();
  await c.responder(1, {success: true}); await c.responder(2);
  assert.equal(c.w.location.pathname, '/sistema/');
  assert.deepEqual(c.errores, []);
});

test('las respuestas viejas no reemplazan el historial recién seleccionado', async t => {
  const c = await campana(t);
  c.el('notificaciones-historial').click();
  await c.responder(1, datos([noticia({titulo: 'Histórico correcto', leida: true})], 0));
  await c.responder(0, datos([noticia({titulo: 'Respuesta anterior'})]));
  assert.match(c.el('notificaciones-lista').textContent, /Histórico correcto/);
  assert.doesNotMatch(c.el('notificaciones-lista').textContent, /Respuesta anterior/);
});

test('el menú se cierra con Escape y detecta un cambio de cuenta antes de mostrar avisos', async t => {
  const c = await campana(t); await c.responder(0);
  c.el('notificaciones-boton').click(); await c.responder(1);
  assert.equal(c.el('notificaciones-panel').hidden, false);
  assert.equal(c.el('notificaciones-boton').getAttribute('aria-expanded'), 'true');
  c.w.document.dispatchEvent(new c.w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
  assert.equal(c.el('notificaciones-panel').hidden, true);
  assert.equal(c.w.document.activeElement, c.el('notificaciones-boton'));
  c.intervalos[0](); await c.responder(2, datos([noticia({titulo: 'Aviso de otra cuenta'})], 1, 90));
  assert.doesNotMatch(c.el('notificaciones-lista').textContent, /Aviso de otra cuenta/);
  assert.equal(c.el('notificaciones-error').hidden, false);
  assert.equal(c.el('notificaciones-leer').disabled, true);
});

test('fallar la consulta inicial retira el estado de carga y permite reintentar al abrir', async t => {
  const c = await campana(t); await c.responder(0, {}, 500);
  assert.doesNotMatch(c.el('notificaciones-lista').textContent, /Cargando/);
  assert.equal(c.el('notificaciones-error').hidden, false);
  c.el('notificaciones-boton').click(); await c.responder(1);
  assert.equal(c.el('notificaciones-error').hidden, true);
  assert.match(c.el('notificaciones-lista').textContent, /No tienes notificaciones nuevas/);
});
