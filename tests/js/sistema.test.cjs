const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');

async function pantalla(t) {
  const dom = new JSDOM(`
    <dialog id="ss-carga"><p id="ss-carga-texto"></p></dialog>
    <form data-ss-loading="Guardando cambios…">
      <input name="email" value="qa@example.invalid">
      <button type="submit" id="guardar">Guardar</button>
      <button type="submit" name="exportar" value="csv" id="exportar">Exportar CSV</button>
    </form>`, {runScripts: 'outside-only', url: 'http://localhost/sistema/'});
  t.after(() => dom.window.close());
  const {window} = dom;
  const dialogo = window.document.querySelector('dialog');
  dialogo.showModal = () => { dialogo.open = true; };
  dialogo.close = () => { dialogo.open = false; };
  window.eval(readFileSync(path.resolve(__dirname, '../../static/js/sistema.js'), 'utf8'));
  await new Promise(resolve => setImmediate(resolve));
  const formulario = window.document.querySelector('form');
  const enviar = id => {
    const evento = new window.SubmitEvent('submit', {cancelable: true, submitter: window.document.getElementById(id)});
    formulario.dispatchEvent(evento);
    return evento;
  };
  return {window, dialogo, formulario, enviar};
}

test('el panel muestra la carga y bloquea un segundo envío conservando los datos', async t => {
  const {window, dialogo, formulario, enviar} = await pantalla(t);
  assert.equal(enviar('guardar').defaultPrevented, false);
  assert.equal(dialogo.open, true);
  assert.equal(formulario.getAttribute('aria-busy'), 'true');
  assert.equal(enviar('guardar').defaultPrevented, true);
  assert.equal(new window.FormData(formulario).get('email'), 'qa@example.invalid');
});

test('una descarga no bloquea la página ni pierde el botón de exportar', async t => {
  const {dialogo, formulario, enviar} = await pantalla(t);
  assert.equal(enviar('exportar').defaultPrevented, false);
  assert.equal(dialogo.open, false);
  assert.notEqual(formulario.getAttribute('aria-busy'), 'true');
  assert.equal(formulario.querySelector('#exportar').disabled, false);
});

test('volver por el historial restablece los formularios y cierra la carga', async t => {
  const {window, dialogo, formulario, enviar} = await pantalla(t);
  enviar('guardar');
  window.dispatchEvent(new window.PageTransitionEvent('pageshow', {persisted: true}));
  assert.equal(formulario.getAttribute('aria-busy'), 'false');
  assert.equal(dialogo.open, false);
  assert.equal(enviar('guardar').defaultPrevented, false);
});
