document.addEventListener('DOMContentLoaded', () => {
  'use strict';
  const aviso = document.getElementById('alert-box');
  const mensaje = texto => { aviso.textContent = texto; aviso.hidden = !texto; };
  const abrirSesion = d => {
    if (!d || typeof d.access !== 'string' || !d.access || typeof d.refresh !== 'string' || !d.refresh || !Number.isSafeInteger(d.usuario?.id) || d.usuario.id < 1) throw new Error('La respuesta de inicio de sesión está incompleta. Inténtalo nuevamente.');
    try {
      localStorage.setItem('access_token', d.access);
      localStorage.setItem('refresh_token', d.refresh);
      localStorage.setItem('usuario', JSON.stringify(d.usuario));
    } catch (_) {
      for (const key of ['access_token', 'refresh_token', 'usuario']) { try { localStorage.removeItem(key); } catch (_) {} }
      throw new Error('No se pudo guardar la sesión. Revisa que tu navegador permita almacenamiento e inténtalo nuevamente.');
    }
    window.location.href = /^\/[a-z-]+\/$/.test(d.inicio) ? d.inicio : '/';
  };
  const datosSesion = document.getElementById('datos-sesion');
  if (datosSesion) {
    try { abrirSesion(JSON.parse(datosSesion.textContent)); }
    catch (error) { mensaje(error.message); aviso.focus(); }
    return;
  }
  const form = document.getElementById('login-form');
  if (!form) return;
  const correo = document.getElementById('email'), clave = document.getElementById('password');
  const boton = document.getElementById('login-submit');
  const opciones = document.getElementById('opciones-acceso');
  let enviando = false, completado = false;
  const estado = () => {
    const ocupado = enviando || completado;
    boton.disabled = ocupado;
    boton.textContent = completado ? 'Abriendo SmartStock…' : enviando ? 'Iniciando sesión…' : 'Iniciar sesión';
    form.setAttribute('aria-busy', String(ocupado));
    correo.readOnly = ocupado; clave.readOnly = ocupado;
  };
  const enviarDestino = destino => {
    const url = new URL(destino.url);
    const dominio = form.dataset.dominioEmpresas;
    if (!dominio || !url.hostname.endsWith('.' + dominio) || url.protocol !== window.location.protocol || url.pathname !== '/acceder/' || url.search || url.hash || url.username || url.password || !/^[a-f0-9-]{36}$/.test(destino.ticket)) throw new Error('El acceso a la empresa no es válido. Inténtalo nuevamente.');
    const entrega = document.createElement('form');
    entrega.method = 'post'; entrega.action = url.href; entrega.hidden = true;
    const ticket = document.createElement('input');
    ticket.type = 'hidden'; ticket.name = 'ticket'; ticket.value = destino.ticket;
    entrega.appendChild(ticket); document.body.appendChild(entrega);
    opciones?.querySelectorAll('button').forEach(b => { b.disabled = true; });
    entrega.submit();
  };
  document.getElementById('cambiar-cuenta')?.addEventListener('click', () => {
    opciones.hidden = true; form.hidden = false;
    completado = false; estado(); correo.focus();
  });
  [correo,clave].forEach(campo => campo.addEventListener('input', () => { if (!enviando) mensaje(''); }));
  form.addEventListener('submit', async evento => {
    evento.preventDefault();
    if (enviando || completado || !form.reportValidity()) return;
    const payload = {email:correo.value.trim(), password:clave.value};
    enviando = true; estado(); mensaje('');
    try {
      const csrf = new FormData(form).get('csrfmiddlewaretoken');
      const respuesta = await fetch(form.action, {
        method: 'POST', cache: 'no-store',
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf},
        body: JSON.stringify(payload),
      });
      let datos;
      try { datos = await respuesta.json(); }
      catch (_) { throw new Error('El servidor no respondió como esperábamos. Inténtalo nuevamente.'); }
      if (!respuesta.ok || !datos?.success) {
        const texto = respuesta.status === 401 ? 'No pudimos iniciar sesión. Revisa tu correo y contraseña o inténtalo más tarde.' : respuesta.status === 429 ? 'Has realizado varios intentos. Espera un momento antes de volver a ingresar.' :
          respuesta.status >= 500 ? 'No pudimos iniciar sesión en este momento. Inténtalo nuevamente.' : typeof datos?.mensaje === 'string' ? datos.mensaje : 'No se pudo iniciar sesión. Inténtalo nuevamente.';
        throw new Error(texto);
      }
      const d = datos.data;
      if (d?.sistema === true && d.inicio === '/sistema/') {
        completado = true;
        window.location.href = d.inicio;
      } else if (Array.isArray(d?.destinos) && d.destinos.length) {
        clave.value = '';
        if (d.destinos.length === 1) {
          enviarDestino(d.destinos[0]);
        } else {
          const lista = document.getElementById('destinos-acceso');
          lista.replaceChildren();
          for (const destino of d.destinos) {
            const enlace = document.createElement('button');
            enlace.type = 'button'; enlace.className = 'btn btn-primary';
            enlace.textContent = destino.nombre;
            enlace.addEventListener('click', () => {
              try { enviarDestino(destino); }
              catch (error) { mensaje(error.message); aviso.focus(); }
            });
            lista.appendChild(enlace);
          }
          form.hidden = true; opciones.hidden = false;
        }
        completado = true;
      } else {
        abrirSesion(d);
        completado = true;
      }
    } catch (error) {
      mensaje(error instanceof TypeError ? 'No se pudo conectar con SmartStock. Revisa tu conexión e inténtalo nuevamente.' : error.message);
      aviso.focus();
    } finally { enviando = false; estado(); }
  });
  window.addEventListener('pageshow', evento => {
    if (evento.persisted) {
      enviando = false; completado = false; form.hidden = false;
      if (opciones) {
        opciones.hidden = true;
        opciones.querySelectorAll('button').forEach(b => { b.disabled = false; });
      }
      estado();
    }
  });
});
