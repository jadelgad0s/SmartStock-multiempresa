/* Descarga el cuerpo sin bloquear el menú, los borradores ni la página. */
document.addEventListener('DOMContentLoaded', () => {
  'use strict';
  const raiz = document.getElementById('contacto-contenido');
  if (!raiz || raiz.dataset.conectado !== '1') return;
  const estado = raiz.querySelector('[data-contenido-estado]');
  const texto = raiz.querySelector('[data-contenido-texto]');
  const error = raiz.querySelector('[data-contenido-error]');
  const boton = raiz.querySelector('[data-contenido-reintentar]');
  let ocupado = false, cargado = false, controlador = null, abandonando = false, sesionValida = true, pendiente = false;
  async function cargar() {
    if (ocupado || cargado || abandonando || !sesionValida) return;
    ocupado = true; boton.disabled = true; error.hidden = true;
    raiz.setAttribute('aria-busy', 'true');
    estado.textContent = 'Cargando contenido del correo…';
    controlador = new AbortController();
    const limite = setTimeout(() => controlador.abort(), 45000);
    try {
      const url = new URL(raiz.dataset.url, window.location.origin);
      if (url.origin !== window.location.origin || !/^\/contacto\/mensajes\/\d+\/contenido\/$/.test(url.pathname)) {
        throw new Error('Recarga la página para consultar este correo.');
      }
      const respuesta = await fetch(url.pathname, {method: 'POST', credentials: 'same-origin', cache: 'no-store',
        signal: controlador.signal, headers: {Accept: 'application/json',
          'X-CSRFToken': document.querySelector('#ss-cerrar-sesion input[name="csrfmiddlewaretoken"]')?.value || ''}});
      if (respuesta.redirected || respuesta.status === 401 || respuesta.status === 403) {
        sesionValida = false;
        throw new Error('Tu sesión ya no tiene acceso al correo. Vuelve a iniciar sesión.');
      }
      let datos;
      try { datos = await respuesta.json(); } catch (_) { throw new Error('No pudimos leer la respuesta. Reintenta el contenido del correo.'); }
      if (!respuesta.ok || !datos.success) throw new Error(datos.mensaje || 'No pudimos cargar el contenido del correo.');
      if (datos.data?.usuario_id !== Number(raiz.dataset.usuario) || datos.data?.mensaje_id !== Number(raiz.dataset.mensaje)) {
        sesionValida = false;
        throw new Error('La sesión cambió. Recarga la página para consultar este correo.');
      }
      if (typeof datos.data.contenido !== 'string') throw new Error('No pudimos interpretar el contenido del correo.');
      if (abandonando) return;
      texto.textContent = datos.data.contenido || 'Este correo no contiene texto.';
      estado.textContent = 'Contenido del correo cargado.';
      cargado = true; boton.hidden = true;
    } catch (fallo) {
      if (abandonando) return;
      estado.textContent = 'Se muestra el resumen del correo.';
      error.textContent = fallo.name === 'AbortError' ? 'Zoho tardó demasiado. Puedes reintentar el contenido.'
        : fallo instanceof TypeError ? 'No pudimos conectar. Reintenta el contenido del correo.'
        : fallo.message || 'No pudimos cargar el contenido del correo.';
      error.hidden = false; boton.hidden = !sesionValida;
    } finally {
      clearTimeout(limite); ocupado = false; boton.disabled = false;
      raiz.setAttribute('aria-busy', 'false');
      if (pendiente && !abandonando) { pendiente = false; cargar(); }
    }
  }
  boton.addEventListener('click', cargar);
  window.addEventListener('pagehide', () => { abandonando = true; controlador?.abort(); });
  window.addEventListener('pageshow', evento => { if (evento.persisted) { abandonando = false; if (ocupado) pendiente = true; else cargar(); } });
  cargar();
});
