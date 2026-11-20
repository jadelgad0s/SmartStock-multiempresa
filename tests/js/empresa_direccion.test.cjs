const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');

const codigo = readFileSync(path.resolve(__dirname, '../../static/js/empresa_direccion.js'), 'utf8');
const datos = [
  {nombre: 'Metropolitana de Santiago', comunas: [{nombre: 'Providencia'}, {nombre: 'Ñuñoa'}]},
  {nombre: 'Maule', comunas: [{nombre: 'Talca'}, {nombre: 'Curicó'}]},
];

async function pantalla(t, opciones = {}) {
  const dom = new JSDOM(`<form><select name="region" id="id_region">
    <option value="">Selecciona una región</option>
    <option>Metropolitana de Santiago</option><option>Maule</option>
    </select><select name="comuna" id="id_comuna"><option value="">Selecciona una comuna</option><option>Providencia</option></select>
    <div id="id_comuna_helptext"></div></form>`, {runScripts: 'outside-only'});
  t.after(() => dom.window.close());
  const {window} = dom;
  const region = window.document.getElementById('id_region');
  const comuna = window.document.getElementById('id_comuna');
  if (opciones.comuna && !Array.from(comuna.options).some(item => item.value === opciones.comuna)) {
    comuna.add(new window.Option(opciones.comuna, opciones.comuna));
  }
  region.value = opciones.region || '';
  comuna.value = opciones.comuna || '';
  region.dataset.ssRegionesComunas = opciones.json || JSON.stringify(opciones.datos || datos);
  region.dataset.ssComunaNombre = 'comuna';
  window.eval(codigo);
  await new Promise(resolve => setImmediate(resolve));
  const elegir = valor => {
    region.value = valor;
    region.dispatchEvent(new window.Event('change', {bubbles: true}));
  };
  return {window, region, comuna, elegir};
}

test('seleccionar región carga sus comunas y retira la comuna de la región anterior', async t => {
  const {comuna, elegir} = await pantalla(t);
  assert.equal(comuna.disabled, true);
  elegir('Maule');
  assert.equal(comuna.disabled, false);
  assert.deepEqual(Array.from(comuna.options, opcion => opcion.value), ['', 'Talca', 'Curicó']);
  comuna.value = 'Talca';
  elegir('Metropolitana de Santiago');
  assert.equal(comuna.value, '');
  assert.deepEqual(Array.from(comuna.options, opcion => opcion.value), ['', 'Providencia', 'Ñuñoa']);
  elegir('');
  assert.equal(comuna.disabled, true);
  assert.equal(comuna.value, '');
});

test('editar y volver por historial conservan las selecciones válidas y actualizan las comunas', async t => {
  const {window, region, comuna} = await pantalla(t, {region: 'Metropolitana de Santiago', comuna: 'Providencia'});
  assert.equal(comuna.value, 'Providencia');
  window.dispatchEvent(new window.PageTransitionEvent('pageshow', {persisted: true}));
  assert.equal(comuna.value, 'Providencia');
  region.value = 'Maule';
  window.dispatchEvent(new window.PageTransitionEvent('pageshow', {persisted: true}));
  assert.equal(comuna.value, '');
  assert.deepEqual(Array.from(comuna.options, opcion => opcion.value), ['', 'Talca', 'Curicó']);
});

test('un valor anterior sin región se conserva y sus textos no se interpretan como HTML', async t => {
  const anterior = '<img src=x onerror="window.ejecutado=true">';
  const {window, comuna, elegir} = await pantalla(t, {comuna: anterior, datos: [...datos, {nombre: '', anterior: true, comunas: [{nombre: anterior, anterior: true}]}]});
  assert.equal(comuna.disabled, false);
  assert.equal(comuna.value, anterior);
  assert.equal(comuna.options[1].text, anterior + ' (valor anterior)');
  assert.equal(window.document.querySelector('img'), null);
  assert.equal(window.ejecutado, undefined);
  elegir('Maule');
  assert.equal(comuna.options.length, 3);
  assert.equal(comuna.value, '');
});

test('un catálogo ilegible conserva las opciones del servidor para poder corregir y reenviar', async t => {
  const {comuna} = await pantalla(t, {json: '{', region: 'Metropolitana de Santiago', comuna: 'Providencia'});
  assert.equal(comuna.disabled, false);
  assert.equal(comuna.value, 'Providencia');
  assert.equal(comuna.options.length, 2);
});
