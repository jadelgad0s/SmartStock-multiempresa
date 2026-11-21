/* Campana del panel interno: sesión y CSRF, independiente de los JWT de empresas. */
document.addEventListener('DOMContentLoaded', () => {
  'use strict';
  const raiz = document.getElementById('sistema-notificaciones');
  if (!raiz) return;
  const elemento = id => document.getElementById('sistema-' + id);
  const boton = elemento('notificaciones-boton'), panel = elemento('notificaciones-panel');
  const contador = elemento('notificaciones-total'), lista = elemento('notificaciones-lista');
  const leer = elemento('notificaciones-leer'), historial = elemento('notificaciones-historial');
  const error = elemento('notificaciones-error'), aviso = elemento('confirmacion');
  const usuario = Number(raiz.dataset.usuario);
  const csrf = () => document.querySelector('#ss-cerrar-sesion input[name="csrfmiddlewaretoken"]')?.value || '';
  const texto = (tipo, contenido) => {
    const nodo = document.createElement(tipo);
    nodo.textContent = String(contenido || '');
    return nodo;
  };
  let anteriores = false, total = 0, hasta = '', ocupado = false, secuencia = 0, firma = '';
  let sesionValida = true, temporizadorAviso;
  const mostrarError = mensaje => { error.textContent = mensaje; error.hidden = !mensaje; };
  const controles = () => {
    leer.disabled = ocupado || !sesionValida || !total;
    historial.disabled = ocupado || !sesionValida;
    lista.querySelectorAll('button').forEach(item => { item.disabled = ocupado || !sesionValida; });
  };
  const ubicar = () => raiz.style.setProperty('--ss-avisos-top', Math.ceil(boton.getBoundingClientRect().bottom + 8) + 'px');
  function cerrar(devolverFoco = false) {
    panel.hidden = true;
    boton.setAttribute('aria-expanded', 'false');
    if (devolverFoco) boton.focus();
  }
  function rutaSegura(link) {
    try {
      const url = new URL(link, window.location.origin);
      const permitida = ['/sistema/usuarios/', '/sistema/cuentas/', '/sistema/mi-cuenta/', '/sistema/contacto/cuenta/', '/sistema/contacto/conexion/', '/contacto/mi-cuenta/', '/contacto/bandeja/'].includes(url.pathname)
        || /^\/sistema\/empresas\/[a-z0-9-]+\/$/.test(url.pathname)
        || /^\/contacto\/mensajes\/\d+\/$/.test(url.pathname);
      return url.origin === window.location.origin && permitida ? url.pathname + url.search : null;
    } catch (_) { return null; }
  }
  const estadoContador = () => {
    contador.hidden = !total;
    contador.textContent = total > 99 ? '99+' : String(total);
    boton.setAttribute('aria-label', total ? `Notificaciones: ${total} sin leer` : 'Sin notificaciones nuevas');
    boton.querySelector('i').className = total ? 'fa-solid fa-bell' : 'fa-regular fa-bell';
  };
  async function pedir(url, opciones) {
    const controlador = new AbortController();
    const limite = setTimeout(() => controlador.abort(), 15000);
    try { return await fetch(url, {...opciones, signal: controlador.signal}); }
    finally { clearTimeout(limite); }
  }

  async function cargar() {
    if (ocupado || !sesionValida) return;
    const turno = ++secuencia;
    try {
      const url = raiz.dataset.url + (anteriores ? '?historial=1' : '');
      const respuesta = await pedir(url, {credentials: 'same-origin', cache: 'no-store', headers: {Accept: 'application/json'}});
      if (!respuesta.ok) throw new Error('No se pudieron consultar las notificaciones. Abre la campana para reintentar.');
      const {data} = await respuesta.json();
      if (turno !== secuencia) return;
      if (data?.usuario_id !== usuario) {
        sesionValida = false; total = 0; firma = ''; lista.replaceChildren(); estadoContador(); controles();
        throw new Error('La sesión cambió. Recarga esta página para consultar tus notificaciones.');
      }
      if (!Number.isSafeInteger(data.total) || data.total < 0 || !Array.isArray(data.items) || typeof data.hasta !== 'string') {
        throw new Error('No se pudieron interpretar las notificaciones. Vuelve a intentarlo.');
      }
      total = data.total; hasta = data.hasta; mostrarError(''); estadoContador(); controles();
      const items = data.items.filter(item => typeof item?.id === 'string' && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(item.id));
      const nuevaFirma = JSON.stringify([anteriores, items]);
      if (nuevaFirma === firma) return;
      firma = nuevaFirma;
      const foco = lista.contains(document.activeElement) ? document.activeElement.dataset.aviso : null;
      lista.replaceChildren();
      if (!items.length) {
        const vacio = texto('li', anteriores ? 'No tienes notificaciones.' : 'No tienes notificaciones nuevas.');
        vacio.className = 'ss-sistema-avisos-vacio'; lista.append(vacio);
      }
      for (const item of items) {
        const fila = document.createElement('li'), tarjeta = document.createElement('button');
        tarjeta.type = 'button'; tarjeta.className = 'ss-sistema-aviso'; tarjeta.dataset.aviso = item.id;
        tarjeta.dataset.leida = String(item.leida === true);
        tarjeta.append(texto('strong', item.titulo), texto('span', item.mensaje));
        if (item.empresa) tarjeta.append(texto('small', item.empresa));
        tarjeta.append(texto('small', item.fecha));
        tarjeta.addEventListener('click', () => cambiar(async () => {
          if (!item.leida) await enviar(raiz.dataset.url + encodeURIComponent(item.id) + '/leer/');
        }).then(correcto => {
          if (!correcto) return;
          const ruta = rutaSegura(item.link);
          if (ruta) window.location.assign(ruta);
        }));
        fila.append(tarjeta); lista.append(fila);
      }
      controles();
      if (foco) (Array.from(lista.querySelectorAll('button')).find(item => item.dataset.aviso === foco) || panel).focus();
    } catch (fallo) {
      if (turno === secuencia) {
        mostrarError(fallo.name === 'AbortError' ? 'La consulta tardó demasiado. Abre la campana para reintentar.'
          : fallo.message || 'No se pudieron cargar las notificaciones. Vuelve a intentarlo.');
        if (!firma) {
          const vacio = texto('li', 'Consulta de notificaciones no disponible.');
          vacio.className = 'ss-sistema-avisos-vacio'; lista.replaceChildren(vacio);
        }
      }
    }
  }

  async function enviar(url, datos = {}) {
    const respuesta = await pedir(url, {
      method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf()},
      body: JSON.stringify(datos),
    });
    if (!respuesta.ok) throw new Error('No se pudo marcar la notificación como leída. Vuelve a intentarlo.');
  }
  async function cambiar(tarea) {
    if (ocupado || !sesionValida) return false;
    ocupado = true; ++secuencia; controles(); mostrarError('');
    let completado = false;
    try {
      if (typeof window.SmartStockCarga === 'function') await window.SmartStockCarga('Actualizando notificaciones…', tarea);
      else await tarea();
      completado = true; return true;
    } catch (_) { mostrarError('No se pudo confirmar la lectura. Vuelve a intentarlo.'); return false; }
    finally { ocupado = false; controles(); if (completado) cargar(); }
  }
  leer.addEventListener('click', () => {
    if (total && hasta) cambiar(() => enviar(raiz.dataset.leerTodas, {hasta}));
  });
  historial.addEventListener('click', () => {
    if (ocupado) return;
    anteriores = !anteriores;
    historial.textContent = anteriores ? 'Ver sin leer' : 'Ver anteriores'; cargar();
  });
  boton.addEventListener('click', () => {
    if (!panel.hidden) { cerrar(); return; }
    aviso.hidden = true; ubicar(); panel.hidden = false; boton.setAttribute('aria-expanded', 'true');
    panel.focus(); cargar();
  });
  document.addEventListener('click', evento => { if (!raiz.contains(evento.target)) cerrar(); });
  document.addEventListener('keydown', evento => { if (evento.key === 'Escape' && !panel.hidden) cerrar(true); });
  window.addEventListener('resize', () => { if (!panel.hidden) ubicar(); });
  window.addEventListener('scroll', () => cerrar());

  // Solo la confirmación que entrega el guardado muestra un aviso. El sondeo
  // de la campana nunca vuelve a anunciar una operación ya confirmada.
  const clave = 'ss-sistema-confirmaciones:' + usuario;
  let vistos = new Set();
  try { vistos = new Set(JSON.parse(sessionStorage.getItem(clave) || '[]')); } catch (_) {}
  let confirmaciones = [];
  try { confirmaciones = JSON.parse(elemento('confirmaciones')?.textContent || '[]'); } catch (_) {}
  if (!Array.isArray(confirmaciones)) confirmaciones = [];
  const nuevas = confirmaciones.filter(item => item && typeof item.id === 'string' && !vistos.has(item.id));
  if (nuevas.length) {
    elemento('confirmacion-titulo').textContent = nuevas.length === 1 ? nuevas[0].titulo : 'Operaciones completadas';
    elemento('confirmacion-texto').textContent = nuevas.map(item => item.mensaje).join('\n');
    aviso.hidden = false;
    nuevas.forEach(item => vistos.add(item.id));
    try { sessionStorage.setItem(clave, JSON.stringify([...vistos].slice(-100))); } catch (_) {}
    temporizadorAviso = setTimeout(() => { aviso.hidden = true; }, 6000);
  }
  elemento('confirmacion-cerrar').addEventListener('click', () => { clearTimeout(temporizadorAviso); aviso.hidden = true; });
  window.addEventListener('pageshow', evento => {
    if (evento.persisted) { aviso.hidden = true; cerrar(); cargar(); }
  });
  const intervalo = setInterval(() => { if (!document.hidden) cargar(); }, 10000);
  window.addEventListener('pagehide', evento => { if (!evento.persisted) clearInterval(intervalo); });
  window.addEventListener('focus', () => { if (!document.hidden) cargar(); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) cargar(); });
  cargar();
});
