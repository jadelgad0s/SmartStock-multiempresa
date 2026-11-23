const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const {JSDOM, VirtualConsole} = require('jsdom');
const codigo = readFileSync(path.resolve(__dirname, '../../static/js/navegacion.js'), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
const datos = {inicio:'/dashboard/', modulos:['/dashboard/','/productos/'], usuario:{id:90, nombre_completo:'Cliente de prueba', rol:'administrador'}};

async function pantalla(t, inicial, conToken=true) {
  const dom = new JSDOM(`<div id="ss-acceso-estado" hidden><p id="ss-acceso-texto"></p><button id="ss-acceso-reintentar"></button></div>
    <form id="ss-cerrar-sesion"><input name="refresh"></form><div class="ss-app-layout"><nav id="ss-navigation">
    <a data-ss-inicio></a><ul><li id="ss-enlace-inicio-bodega" hidden></li><li><a class="sidebar-item" href="/dashboard/">Inicio</a></li>
    <li id="no-permitido"><a class="sidebar-item" href="/admin/">Configuración</a></li></ul></nav></div>`,
    {url:'http://la-fragua.localhost/dashboard/',runScripts:'outside-only',virtualConsole:new VirtualConsole()});
  const w=dom.window, peticiones=[]; let cierres=0;
  t.after(()=>w.close());
  if (conToken) w.localStorage.setItem('access_token','token-fixture');
  if (inicial!==undefined) { const nodo=w.document.createElement('script');nodo.id='ss-navegacion-inicial';nodo.type='application/json';nodo.textContent=typeof inicial==='string'?inicial:JSON.stringify(inicial);w.document.body.append(nodo); }
  w.smartstockClearSession=()=>{cierres++;};w.document.querySelector('form').submit=()=>{};
  w.SmartStockCarga=(_,tarea)=>tarea();
  w.SmartStockReportes={json:url=>new Promise((resolve,reject)=>peticiones.push({url,resolve,reject}))};
  w.eval(codigo);await tick();
  return {w,peticiones,cierres:()=>cierres,panel:w.document.querySelector('.ss-app-layout')};
}

test('reutiliza la verificación del HTML de esta petición sin otra llamada HTTP', async t=>{
  const c=await pantalla(t,datos);
  assert.equal(c.peticiones.length,0);
  assert.equal(c.panel.hasAttribute('data-ss-autorizado'),true);
  assert.equal(JSON.parse(c.w.localStorage.getItem('usuario')).id,90);
  assert.equal(c.w.document.getElementById('no-permitido').hasAttribute('data-ss-menu-denegado'),true);
  assert.equal(c.w.document.querySelector('.sidebar-item[href="/dashboard/"]').getAttribute('aria-current'),'page');
});

for (const inicial of [undefined,'json inválido']) test(`sin verificación inicial válida consulta al servidor: ${inicial}`,async t=>{
  const c=await pantalla(t,inicial);
  assert.equal(c.peticiones.length,1);
  assert.equal(c.panel.hasAttribute('data-ss-autorizado'),false);
  c.peticiones[0].resolve({data:datos});await c.w.SmartStockNavegacion.lista;
  assert.equal(c.panel.hasAttribute('data-ss-autorizado'),true);
});

test('volver desde historial siempre consulta permisos actuales y bloquea un rol revocado',async t=>{
  const c=await pantalla(t,datos);
  c.w.dispatchEvent(new c.w.PageTransitionEvent('pageshow',{persisted:true}));await tick();
  assert.equal(c.peticiones.length,1);
  assert.equal(c.panel.hasAttribute('data-ss-autorizado'),false);
  c.peticiones[0].reject(Object.assign(new Error('Rol desactivado'),{status:403}));
  await c.w.SmartStockNavegacion.lista;
  assert.equal(c.panel.hasAttribute('data-ss-autorizado'),false);
  assert.match(c.w.document.getElementById('ss-acceso-texto').textContent,/rol activo/);
});

test('el HTML verificado no sustituye una sesión ausente ni reactiva un JWT vencido',async t=>{
  const sin=await pantalla(t,datos,false);assert.equal(sin.cierres(),1);assert.equal(sin.panel.hasAttribute('data-ss-autorizado'),false);
  const c=await pantalla(t,datos);
  c.w.dispatchEvent(new c.w.PageTransitionEvent('pageshow',{persisted:true}));await tick();
  c.peticiones[0].reject(Object.assign(new Error('Sesión vencida'),{status:401}));await c.w.SmartStockNavegacion.lista;
  assert.equal(c.cierres(),1);
  assert.equal(c.panel.hasAttribute('data-ss-autorizado'),false);
});
