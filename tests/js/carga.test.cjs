const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const raiz = path.resolve(__dirname, '../..');
const plantilla = readFileSync(path.join(raiz, 'templates/base.html'), 'utf8');
const fuente = readFileSync(path.join(raiz, 'static/js/carga.js'), 'utf8');

function pantalla(t) {
    const dom = new JSDOM(plantilla.match(/<dialog id="ss-carga"[\s\S]*?<\/dialog>/)[0], {runScripts: 'outside-only'});
    const w = dom.window;
    t.after(() => w.close());
    const dialogo = w.document.getElementById('ss-carga');
    let aperturas = 0;
    dialogo.showModal = () => { dialogo.open = true; aperturas++; };
    dialogo.close = () => { dialogo.open = false; };
    const temporizadores = new Map();
    let secuencia = 0;
    w.setTimeout = fn => { temporizadores.set(++secuencia, fn); return secuencia; };
    w.clearTimeout = id => temporizadores.delete(id);
    w.eval(fuente);
    function pintar() {
        const pendientes = [...temporizadores.values()];
        temporizadores.clear();
        pendientes.forEach(fn => fn());
    }
    return {w, dialogo, pintar, aperturas: () => aperturas};
}

test('una respuesta rápida no abre el indicador', async t => {
    const c = pantalla(t);
    assert.equal(await c.w.SmartStockCarga('Cargando catálogo…', () => Promise.resolve('resultado')), 'resultado');
    c.pintar();
    assert.equal(c.aperturas(), 0);
});

test('la espera muestra un solo indicador y termina al resolver o rechazar la última solicitud', async t => {
    const c = pantalla(t);
    let resolver, rechazar;
    const carga = c.w.SmartStockCarga('Cargando movimientos…', () => new Promise(r => { resolver = r; }));
    const guardado = c.w.SmartStockCarga('Guardando producto…', () => new Promise((_, r) => { rechazar = r; }));
    c.pintar();
    assert.equal(c.dialogo.open, true);
    assert.equal(c.aperturas(), 1);
    assert.match(c.dialogo.textContent, /Guardando producto/);
    const cancelar = new c.w.Event('cancel', {cancelable: true});
    c.dialogo.dispatchEvent(cancelar);
    assert.equal(cancelar.defaultPrevented, true);
    rechazar(new Error('Error del servidor'));
    await assert.rejects(guardado, /Error del servidor/);
    assert.equal(c.dialogo.open, true);
    assert.match(c.dialogo.textContent, /Cargando movimientos/);
    resolver('lista');
    assert.equal(await carga, 'lista');
    assert.equal(c.dialogo.open, false);
});

test('un error de guardado cierra el indicador y permite un nuevo intento', async t => {
    const c = pantalla(t);
    let rechazar;
    const guardado = c.w.SmartStockCarga('Confirmando transferencia…', () => new Promise((_, r) => { rechazar = r; }));
    c.pintar();
    rechazar(new Error('Stock insuficiente'));
    await assert.rejects(guardado, /Stock insuficiente/);
    assert.equal(c.dialogo.open, false);
    assert.equal(await c.w.SmartStockCarga('Confirmando transferencia…', () => Promise.resolve('confirmada')), 'confirmada');
});
