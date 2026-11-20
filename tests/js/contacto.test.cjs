const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const fuente = readFileSync(path.resolve(__dirname, '../../static/js/contacto.js'), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));

async function pantalla(t, html) {
  const dom = new JSDOM(html, {runScripts:'outside-only', url:'http://localhost/contacto/bandeja/', pretendToBeVisual:true});
  t.after(() => dom.window.close());
  const {window} = dom, peticiones = [], intervalos = [];
  window.fetch = (url, opciones) => new Promise((resolve, reject) => peticiones.push({url, opciones, resolve, reject}));
  window.setInterval = (callback, tiempo) => { intervalos.push({callback, tiempo}); return 1; };
  window.eval(fuente);
  await tick();
  return {window, peticiones, intervalos, el:id => window.document.getElementById(id)};
}
const bandeja = `<form id="ss-cerrar-sesion"><input name="csrfmiddlewaretoken" value="csrf-fixture"></form>
  <div id="contacto-sync" data-url="/contacto/sincronizar/"><span id="contacto-sync-estado"></span><a id="contacto-sync-nuevos" hidden>Ver nuevos</a></div>`;

test('consulta con sesión y CSRF sin superponer peticiones ni recargar la página', async t => {
  const c = await pantalla(t, bandeja);
  assert.equal(c.peticiones.length, 1);
  assert.equal(c.peticiones[0].opciones.method, 'POST');
  assert.equal(c.peticiones[0].opciones.headers['X-CSRFToken'], 'csrf-fixture');
  assert.equal(c.peticiones[0].opciones.credentials, 'same-origin');
  assert.equal(c.intervalos[0].tiempo, 60000);
  c.intervalos[0].callback(); assert.equal(c.peticiones.length, 1);
  c.peticiones[0].resolve({ok:true,json:async()=>({success:true,nuevos:2})}); await tick();
  assert.equal(c.el('contacto-sync-nuevos').hidden, false);
  assert.match(c.el('contacto-sync-estado').textContent, /correos nuevos/);
  c.intervalos[0].callback(); assert.equal(c.peticiones.length, 1);
});

test('una pestaña oculta no consulta el buzón y un error permite reintentar', async t => {
  const c = await pantalla(t, bandeja);
  c.peticiones[0].reject(new TypeError('sin red')); await tick();
  assert.match(c.el('contacto-sync-estado').textContent, /No pudimos/);
  Object.defineProperty(c.window.document, 'hidden', {value:true,configurable:true});
  c.intervalos[0].callback(); assert.equal(c.peticiones.length, 1);
  Object.defineProperty(c.window.document, 'hidden', {value:false,configurable:true});
  c.intervalos[0].callback(); assert.equal(c.peticiones.length, 2);
  c.peticiones[1].resolve({ok:true,json:async()=>({success:true,nuevos:0})}); await tick();
  assert.match(c.el('contacto-sync-estado').textContent, /Bandeja consultada/);
  assert.equal(c.el('contacto-sync-nuevos').hidden, true);
});

test('sin conexión configurada no hace consultas automáticas', async t => {
  const c = await pantalla(t, '<p>Conecta tu buzón de Zoho Mail</p>');
  assert.equal(c.peticiones.length, 0);
  assert.equal(c.intervalos.length, 0);
});

for (const bloqueado of [false,true]) test(`editar un borrador exige guardarlo y conserva bloqueo original=${bloqueado}`, async t => {
  const c = await pantalla(t, `<form data-borrador-editor><textarea>Texto guardado</textarea></form>
    <button data-respuesta-enviar ${bloqueado?'disabled':''}>Enviar</button><p id="contacto-enviar-ayuda">Revisa el texto</p>`);
  const editor = c.window.document.querySelector('textarea'), enviar = c.window.document.querySelector('button');
  editor.value = 'Texto sin guardar'; editor.dispatchEvent(new c.window.Event('input'));
  assert.equal(enviar.disabled, true); assert.match(c.el('contacto-enviar-ayuda').textContent, /Guarda los cambios/);
  editor.value = 'Texto guardado'; editor.dispatchEvent(new c.window.Event('input'));
  assert.equal(enviar.disabled, bloqueado); assert.equal(c.el('contacto-enviar-ayuda').textContent, 'Revisa el texto');
  assert.equal(c.peticiones.length, 0);
});
