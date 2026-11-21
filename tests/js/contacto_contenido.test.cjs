const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const codigo=readFileSync(path.resolve(__dirname,'../../static/js/contacto_contenido.js'),'utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const datos=(contenido='Texto completo',extra={})=>({success:true,data:{usuario_id:1,mensaje_id:7,contenido,...extra}});

async function pantalla(t,config={}) {
  const dom=new JSDOM(`<form id="ss-cerrar-sesion"><input name="csrfmiddlewaretoken" value="csrf-fixture"></form>
    <textarea id="editor">Borrador sin guardar</textarea>${config.sinNodo?'':`<section id="contacto-contenido" data-url="/contacto/mensajes/7/contenido/" data-usuario="1" data-mensaje="7" data-conectado="${config.desconectado?'0':'1'}">
    <p data-contenido-estado></p><div data-contenido-texto>Resumen</div><p data-contenido-error hidden></p><button data-contenido-reintentar hidden>Reintentar</button></section>`}`,
    {url:'http://localhost/contacto/mensajes/7/',runScripts:'outside-only',pretendToBeVisual:true});
  t.after(()=>dom.window.close());
  const w=dom.window, peticiones=[], tiempos=[];
  w.SmartStockCarga=()=>{throw new Error('El contenido no debe bloquear la página');};
  w.setTimeout=(fn,ms)=>{tiempos.push({fn,ms});return tiempos.length;};w.clearTimeout=()=>{};
  w.fetch=(url,opciones)=>new Promise((resolve,reject)=>{peticiones.push({url,opciones,resolve,reject});opciones.signal.addEventListener('abort',()=>reject(new w.DOMException('Cancelado','AbortError')));});
  w.eval(codigo);await tick();
  const el=selector=>w.document.querySelector(selector);
  const responder=async(i,data=datos(),ok=true)=>{peticiones[i].resolve({ok,status:ok?200:502,json:async()=>data});await tick();};
  return {w,peticiones,tiempos,el,responder};
}

test('solicita el cuerpo con sesión y CSRF dejando disponibles el editor y la página',async t=>{
  const c=await pantalla(t);
  assert.equal(c.peticiones.length,1);assert.equal(c.peticiones[0].url,'/contacto/mensajes/7/contenido/');
  assert.equal(c.peticiones[0].opciones.method,'POST');assert.equal(c.peticiones[0].opciones.credentials,'same-origin');
  assert.equal(c.peticiones[0].opciones.headers['X-CSRFToken'],'csrf-fixture');
  assert.equal(c.el('#editor').disabled,false);
  c.el('#editor').value='Respuesta en preparación';
  await c.responder(0);
  assert.equal(c.el('[data-contenido-texto]').textContent,'Texto completo');
  assert.equal(c.el('#editor').value,'Respuesta en preparación');
  assert.equal(c.el('#contacto-contenido').getAttribute('aria-busy'),'false');
});

test('presenta el contenido como texto, sin ejecutar HTML ni hacer una segunda descarga',async t=>{
  const c=await pantalla(t);await c.responder(0,datos('<img src=x onerror=alert(1)>'));
  assert.equal(c.el('[data-contenido-texto] img'),null);
  assert.match(c.el('[data-contenido-texto]').textContent,/<img/);
  c.el('button').click();await tick();assert.equal(c.peticiones.length,1);
});

test('un error conserva el resumen y reintentar evita peticiones duplicadas',async t=>{
  const c=await pantalla(t);await c.responder(0,{success:false,mensaje:'Zoho no respondió'},false);
  assert.equal(c.el('[data-contenido-texto]').textContent,'Resumen');
  assert.match(c.el('[data-contenido-error]').textContent,/Zoho no respondió/);
  c.el('button').click();c.el('button').click();assert.equal(c.peticiones.length,2);
  await c.responder(1);assert.equal(c.el('[data-contenido-error]').hidden,true);
});

test('un cambio de sesión no presenta el contenido devuelto de otro usuario',async t=>{
  const c=await pantalla(t);await c.responder(0,datos('Contenido privado',{usuario_id:2}));
  assert.equal(c.el('[data-contenido-texto]').textContent,'Resumen');
  assert.match(c.el('[data-contenido-error]').textContent,/sesión cambió/);
  c.el('button').click();assert.equal(c.peticiones.length,1);
});

test('agotarse el tiempo permite reintentar sin un indicador que bloquee la página',async t=>{
  const c=await pantalla(t);assert.equal(c.tiempos[0].ms,45000);c.tiempos[0].fn();await tick();
  assert.match(c.el('[data-contenido-error]').textContent,/tardó demasiado/);
  assert.equal(c.el('button').hidden,false);assert.equal(c.el('#editor').disabled,false);
});

for(const config of [{sinNodo:true},{desconectado:true}]) test(`sin contenido pendiente o conexión no consulta: ${JSON.stringify(config)}`,async t=>{
  const c=await pantalla(t,config);assert.equal(c.peticiones.length,0);
});
