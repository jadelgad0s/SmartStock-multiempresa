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
  let ocupado = false;
  const consultar = async () => {
    if (ocupado || document.hidden || !nuevos.hidden) return;
    ocupado = true;
    const controlador = new AbortController();
    const limite = setTimeout(() => controlador.abort(), 45000);
    try {
      const csrf = document.querySelector('#ss-cerrar-sesion input[name="csrfmiddlewaretoken"]')?.value;
      const respuesta = await fetch(raiz.dataset.url, {method:'POST', credentials:'same-origin', cache:'no-store',
        headers:{Accept:'application/json', 'X-CSRFToken':csrf || ''}, signal:controlador.signal});
      if (!respuesta.ok) throw new Error();
      const datos = await respuesta.json();
      if (!datos.success || !Number.isSafeInteger(datos.nuevos) || datos.nuevos < 0) throw new Error();
      estado.textContent = 'Bandeja consultada: ' + new Date().toLocaleTimeString('es-CL', {hour:'2-digit',minute:'2-digit'});
      if (datos.nuevos) {
        estado.textContent = 'Hay correos nuevos en tu bandeja.';
        nuevos.hidden = false;
      }
    } catch (_) { estado.textContent = 'No pudimos consultar correos nuevos. Puedes reintentar con Actualizar bandeja.'; }
    finally { clearTimeout(limite); ocupado = false; }
  };
  consultar();
  window.setInterval(consultar, 60000);
});
