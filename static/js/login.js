document.addEventListener('DOMContentLoaded', () => {
  'use strict';
  const aviso = document.getElementById('alert-box');
  const mensaje = texto => { if (aviso) { aviso.textContent = texto; aviso.hidden = !texto; } };
  const transicion = window.SSAccesoTransicion;
  let epoca = 0;
  window.addEventListener('pagehide', () => { epoca++; transicion?.cancelar(); });
  const navegar = async (datos, accion) => {
    const intento = epoca;
    const continuar = transicion ? await transicion.mostrar(datos) : true;
    if (continuar && intento === epoca) accion();
  };
  const abrirSesion = async d => {
    if (!d || typeof d.access !== 'string' || !d.access || typeof d.refresh !== 'string' || !d.refresh || !Number.isSafeInteger(d.usuario?.id) || d.usuario.id < 1) throw new Error('La respuesta de inicio de sesión está incompleta. Inténtalo nuevamente.');
    try {
      localStorage.setItem('access_token', d.access);
      localStorage.setItem('refresh_token', d.refresh);
      localStorage.setItem('usuario', JSON.stringify(d.usuario));
    } catch (_) {
      for (const key of ['access_token', 'refresh_token', 'usuario']) { try { localStorage.removeItem(key); } catch (_) {} }
      throw new Error('No se pudo guardar la sesión. Revisa que tu navegador permita almacenamiento e inténtalo nuevamente.');
    }
    const campoClave = document.getElementById('password');
    if (campoClave) campoClave.value = '';
    await navegar({}, () => { window.location.href = /^\/[a-z-]+\/$/.test(d.inicio) ? d.inicio : '/'; });
  };
  const datosSesion = document.getElementById('datos-sesion');
  if (datosSesion) {
    const fallar = error => {
      transicion?.error(); mensaje(error.message); aviso?.focus();
      const volver = document.getElementById('ss-login-reintentar');
      if (volver) volver.hidden = false;
    };
    try {
      const datos = JSON.parse(datosSesion.textContent);
      datosSesion.remove();
      abrirSesion(datos).catch(fallar);
    } catch (error) { fallar(error); }
    window.addEventListener('pageshow', evento => {
      if (evento.persisted) { epoca++; fallar(new Error('Vuelve a iniciar sesión para continuar.')); }
    });
    return;
  }
  const form = document.getElementById('login-form');
  if (!form) return;
  const correo = document.getElementById('email'), clave = document.getElementById('password');
  const boton = document.getElementById('login-submit');
  const opciones = document.getElementById('opciones-acceso');
  let enviando = false, completado = false, navegando = false;
  const estado = () => {
    const ocupado = enviando || completado;
    boton.disabled = ocupado;
    boton.textContent = completado ? 'Abriendo SmartStock…' : enviando ? 'Iniciando sesión…' : 'Iniciar sesión';
    form.setAttribute('aria-busy', String(ocupado));
    correo.readOnly = ocupado; clave.readOnly = ocupado;
  };
  const validarDestino = destino => {
    let url;
    try { url = new URL(destino.url); } catch (_) { throw new Error('El acceso a la empresa no es válido. Inténtalo nuevamente.'); }
    const dominio = form.dataset.dominioEmpresas;
    const codigo = dominio && url.hostname.endsWith('.' + dominio) ? url.hostname.slice(0, -dominio.length - 1) : '';
    if (!/^[a-z0-9](?:[a-z0-9-]{0,58}[a-z0-9])?$/.test(codigo) || url.protocol !== window.location.protocol || url.port !== window.location.port || url.pathname !== '/acceder/' || url.search || url.hash || url.username || url.password || typeof destino.nombre !== 'string' || !destino.nombre.trim() || !/^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/.test(destino.ticket)) throw new Error('El acceso a la empresa no es válido. Inténtalo nuevamente.');
    return {...destino, url: url.href, nombre: destino.nombre.trim().slice(0, 160)};
  };
  const enviarDestino = async destino => {
    if (navegando) return;
    navegando = true;
    const entrega = document.createElement('form');
    entrega.method = 'post'; entrega.action = destino.url; entrega.hidden = true;
    entrega.dataset.ssEntregaAcceso = '';
    const ticket = document.createElement('input');
    ticket.type = 'hidden'; ticket.name = 'ticket'; ticket.value = destino.ticket;
    entrega.appendChild(ticket); document.body.appendChild(entrega);
    opciones?.querySelectorAll('button').forEach(b => { b.disabled = true; });
    try {
      await navegar(destino, () => entrega.submit());
    } catch (error) {
      navegando = false; entrega.remove();
      opciones?.querySelectorAll('button').forEach(b => { b.disabled = false; });
      throw error;
    }
  };
  document.getElementById('cambiar-cuenta')?.addEventListener('click', () => {
    epoca++; transicion?.restaurar(); navegando = false;
    opciones.hidden = true; form.hidden = false;
    document.getElementById('destinos-acceso').replaceChildren();
    completado = false; estado(); correo.focus();
  });
  [correo,clave].forEach(campo => campo.addEventListener('input', () => { if (!enviando) mensaje(''); }));
  form.addEventListener('submit', async evento => {
    evento.preventDefault();
    if (enviando || completado || !form.reportValidity()) return;
    const payload = {email:correo.value.trim(), password:clave.value};
    const intento = ++epoca;
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
      if (intento !== epoca) return;
      if (!respuesta.ok || !datos?.success) {
        const texto = respuesta.status === 401 ? 'No pudimos iniciar sesión. Revisa tu correo y contraseña o inténtalo más tarde.' : respuesta.status === 429 ? 'Has realizado varios intentos. Espera un momento antes de volver a ingresar.' :
          respuesta.status >= 500 ? 'No pudimos iniciar sesión en este momento. Inténtalo nuevamente.' : typeof datos?.mensaje === 'string' ? datos.mensaje : 'No se pudo iniciar sesión. Inténtalo nuevamente.';
        throw new Error(texto);
      }
      const d = datos.data;
      if (d?.sistema === true && d.inicio === '/sistema/') {
        completado = true; clave.value = '';
        await navegar({nombre: 'SmartStock'}, () => { window.location.href = d.inicio; });
      } else if (d?.contacto === true && d.inicio === '/contacto/bandeja/') {
        completado = true; clave.value = '';
        await navegar({nombre: 'Atención de SmartStock'}, () => { window.location.href = d.inicio; });
      } else if (Array.isArray(d?.destinos) && d.destinos.length) {
        const destinos = d.destinos.map(validarDestino);
        clave.value = ''; completado = true;
        if (destinos.length === 1) {
          await enviarDestino(destinos[0]);
        } else {
          const lista = document.getElementById('destinos-acceso');
          lista.replaceChildren();
          for (const destino of destinos) {
            const enlace = document.createElement('button');
            enlace.type = 'button'; enlace.className = 'btn btn-primary ss-auth-destino';
            const logo = document.createElement('img');
            logo.className = 'ss-auth-destino-logo'; logo.alt = ''; logo.width = 72; logo.height = 32;
            const rutaLogo = transicion?.logoSeguro(destino.logo);
            if (rutaLogo) { logo.src = rutaLogo; logo.onerror = () => { logo.hidden = true; }; enlace.appendChild(logo); }
            const nombre = document.createElement('span'); nombre.textContent = destino.nombre; enlace.appendChild(nombre);
            enlace.addEventListener('click', async () => {
              try { await enviarDestino(destino); }
              catch (error) { transicion?.error(); mensaje(error.message); aviso.focus(); }
            });
            lista.appendChild(enlace);
          }
          form.hidden = true; opciones.hidden = false;
        }
      } else {
        completado = true;
        await abrirSesion(d);
      }
    } catch (error) {
      if (intento !== epoca) return;
      transicion?.error(); completado = false; navegando = false;
      mensaje(error instanceof TypeError ? 'No se pudo conectar con SmartStock. Revisa tu conexión e inténtalo nuevamente.' : error.message);
      aviso.focus();
    } finally { if (intento === epoca) { enviando = false; estado(); } }
  });
  window.addEventListener('pageshow', evento => {
    if (evento.persisted) {
      epoca++; transicion?.restaurar();
      document.querySelectorAll('form[data-ss-entrega-acceso]').forEach(f => f.remove());
      enviando = false; completado = false; navegando = false; form.hidden = false;
      if (opciones) {
        opciones.hidden = true;
        opciones.querySelectorAll('button').forEach(b => { b.disabled = false; });
      }
      estado();
    }
  });
});
