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
  <div id="contacto-sync" data-url="/contacto/sincronizar/" data-usuario="1" data-total="0" data-ultimo="0" data-consultado="1"><span id="contacto-sync-estado"></span><a id="contacto-sync-nuevos" hidden>Ver nuevos</a></div>`;
const datos = (nuevos=0) => ({success:true,usuario_id:1,nuevos,total:nuevos,ultimo_id:nuevos,ultima_consulta:'2026-11-21T00:00:00Z'});

test('consulta con sesión y CSRF sin superponer peticiones ni recargar la página', async t => {
  const c = await pantalla(t, bandeja);
  assert.equal(c.peticiones.length, 1);
  assert.equal(c.peticiones[0].opciones.method, 'POST');
  assert.equal(c.peticiones[0].opciones.headers['X-CSRFToken'], 'csrf-fixture');
  assert.equal(c.peticiones[0].opciones.credentials, 'same-origin');
  assert.equal(c.intervalos[0].tiempo, 60000);
  c.intervalos[0].callback(); assert.equal(c.peticiones.length, 1);
  c.peticiones[0].resolve({ok:true,json:async()=>datos(2)}); await tick();
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
  c.peticiones[1].resolve({ok:true,json:async()=>datos()}); await tick();
  assert.match(c.el('contacto-sync-estado').textContent, /Bandeja consultada/);
  assert.equal(c.el('contacto-sync-nuevos').hidden, true);
});

test('muestra el motivo de Zoho como texto y permite volver a consultar', async t => {
  const c = await pantalla(t, bandeja);
  c.peticiones[0].resolve({ok:false,json:async()=>({success:false,codigo:'permisos',mensaje:'Zoho necesita permisos <script>no ejecutar</script>'})}); await tick();
  assert.equal(c.el('contacto-sync-estado').textContent, 'Zoho necesita permisos <script>no ejecutar</script>');
  assert.equal(c.el('contacto-sync-estado').querySelector('script'), null);
  c.intervalos[0].callback(); assert.equal(c.peticiones.length, 2);
  assert.equal(c.peticiones[1].opciones.body, 'automatico=1');
  c.peticiones[1].resolve({ok:true,json:async()=>datos()}); await tick();
});

test('detecta correos incorporados por otra pestaña aunque esta consulta no importe nuevos', async t => {
  const c = await pantalla(t, bandeja);
  c.peticiones[0].resolve({ok:true,json:async()=>({...datos(),total:1,ultimo_id:8})}); await tick();
  assert.equal(c.el('contacto-sync-nuevos').hidden, false);
});

test('al cambiar de sesión deja de actualizar y no presenta información de otra cuenta', async t => {
  const c = await pantalla(t, bandeja);
  c.peticiones[0].resolve({ok:true,json:async()=>({...datos(2),usuario_id:5})}); await tick();
  assert.match(c.el('contacto-sync-estado').textContent, /sesión cambió/);
  assert.equal(c.el('contacto-sync-nuevos').hidden, true);
  c.intervalos[0].callback(); assert.equal(c.peticiones.length, 1);
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
