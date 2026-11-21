/* Consulta solo en la bandeja visible; nunca recarga una respuesta en edición. */
document.addEventListener('DOMContentLoaded', () => {
  'use strict';
  const editor = document.querySelector('[data-borrador-editor] textarea');
  const enviar = document.querySelector('[data-respuesta-enviar]');
  if (editor && enviar) {
    const original = editor.value, bloqueado = enviar.disabled;
    const ayuda = document.getElementById('contacto-enviar-ayuda');
    const textoAyuda = ayuda.textContent;
    editor.addEventListener('input', () => {
      const cambios = editor.value !== original;
      enviar.disabled = bloqueado || cambios;
      ayuda.textContent = cambios ? 'Guarda los cambios del borrador antes de enviar la respuesta.' : textoAyuda;
    });
  }
  const raiz = document.getElementById('contacto-sync');
  if (!raiz) return;
  const estado = document.getElementById('contacto-sync-estado');
  const nuevos = document.getElementById('contacto-sync-nuevos');
  const usuario = Number(raiz.dataset.usuario);
  let ocupado = false, sesionValida = true;
  const consultar = async () => {
    if (ocupado || !sesionValida || document.hidden || !nuevos.hidden) return;
    ocupado = true;
    const controlador = new AbortController();
    const limite = setTimeout(() => controlador.abort(), 45000);
    try {
      const csrf = document.querySelector('#ss-cerrar-sesion input[name="csrfmiddlewaretoken"]')?.value;
      const respuesta = await fetch(raiz.dataset.url, {method:'POST', credentials:'same-origin', cache:'no-store',
        headers:{Accept:'application/json', 'X-CSRFToken':csrf || '', 'Content-Type':'application/x-www-form-urlencoded'},
        body:'automatico=1', signal:controlador.signal});
      let datos;
      try { datos = await respuesta.json(); } catch (_) { throw new Error('No pudimos consultar Zoho. Reintenta con Actualizar bandeja.'); }
      if (!respuesta.ok || !datos.success) throw new Error(typeof datos.mensaje === 'string' ? datos.mensaje : 'No pudimos consultar Zoho. Reintenta con Actualizar bandeja.');
      if (!Number.isSafeInteger(usuario) || datos.usuario_id !== usuario) {
        sesionValida = false;
        throw new Error('La sesión cambió. Recarga la página antes de actualizar la bandeja.');
      }
      if (!Number.isSafeInteger(datos.nuevos) || datos.nuevos < 0 || !Number.isSafeInteger(datos.total) || datos.total < 0) throw new Error('No pudimos interpretar la respuesta de Zoho. Inténtalo nuevamente.');
      raiz.dataset.error = 'false';
      const fecha = datos.ultima_consulta ? new Date(datos.ultima_consulta) : null;
      estado.textContent = fecha && !Number.isNaN(fecha.getTime()) ? 'Bandeja consultada: ' + fecha.toLocaleTimeString('es-CL', {hour:'2-digit',minute:'2-digit'}) : 'Consulta completada.';
      const cambio = datos.total !== Number(raiz.dataset.total) || (datos.ultimo_id || 0) !== Number(raiz.dataset.ultimo);
      const primera = raiz.dataset.consultado === '0' && datos.ultima_consulta;
      if (datos.nuevos || cambio || primera) {
        estado.textContent = datos.nuevos || cambio ? 'Hay correos nuevos en tu bandeja.' : 'Zoho respondió correctamente. Actualiza la vista para ver los resultados.';
        nuevos.hidden = false;
      }
    } catch (error) {
      raiz.dataset.error = 'true';
      estado.textContent = error?.name === 'AbortError' ? 'La consulta a Zoho tardó demasiado. Reintenta con Actualizar bandeja.' : error?.name === 'TypeError' ? 'No pudimos conectar con SmartStock. Revisa Internet e inténtalo nuevamente.' : error?.message || 'No pudimos consultar Zoho. Reintenta con Actualizar bandeja.';
    }
    finally { clearTimeout(limite); ocupado = false; }
  };
  consultar();
  window.setInterval(consultar, 60000);
});
