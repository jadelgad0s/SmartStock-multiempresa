/* La marca aparece después de validar el acceso. La navegación espera el pintado,
   sin imponer una duración mínima ni depender de que termine la animación. */
(() => {
  'use strict';
  const panel = document.getElementById('ss-acceso-transicion');
  const contenido = document.getElementById('ss-login-contenido');
  const imagen = document.getElementById('ss-acceso-logo');
  const titulo = document.getElementById('ss-acceso-titulo');
  const descripcion = document.getElementById('ss-acceso-descripcion');
  const indicador = document.getElementById('ss-acceso-indicador');
  const region = panel?.closest('.ss-auth-form');
  const logoInicial = imagen?.src || '';
  let cancelarPintado;

  const logoSeguro = valor => {
    if (typeof valor !== 'string' || !valor || !panel) return logoInicial;
    try {
      const base = new URL(panel.dataset.marcaBase, location.href);
      const url = new URL(valor, location.href);
      return url.origin === base.origin && url.pathname.startsWith(base.pathname)
        && !url.username && !url.password && !url.search && !url.hash ? url.href : logoInicial;
    } catch (_) { return logoInicial; }
  };
  const cancelar = () => cancelarPintado?.();
  const restaurar = () => {
    cancelar();
    if (panel) panel.hidden = true;
    if (contenido) contenido.hidden = false;
    region?.classList.remove('ss-auth-en-transicion');
    if (contenido) region?.setAttribute('aria-labelledby', 'titulo-acceso');
  };
  const mostrar = (datos = {}) => {
    cancelar();
    if (!panel) return Promise.resolve(true);
    const nombre = typeof datos.nombre === 'string' && datos.nombre.trim()
      ? datos.nombre.trim().slice(0, 160) : panel.dataset.nombre || 'SmartStock';
    imagen.hidden = false;
    imagen.onerror = () => {
      if (imagen.src !== logoInicial) imagen.src = logoInicial;
      else imagen.hidden = true;
    };
    imagen.src = logoSeguro(datos.logo);
    imagen.alt = 'Logo de ' + nombre;
    titulo.textContent = 'Abriendo ' + nombre + '…';
    descripcion.textContent = 'Estamos preparando tu sesión.';
    indicador.hidden = false;
    if (contenido) contenido.hidden = true;
    panel.hidden = false;
    region?.classList.add('ss-auth-en-transicion');
    region?.setAttribute('aria-labelledby', 'ss-acceso-titulo');
    titulo.focus({preventScroll: true});

    return new Promise(resolve => {
      let terminado = false;
      const fotogramas = [];
      const terminar = continuar => {
        if (terminado) return;
        terminado = true;
        clearTimeout(limite);
        fotogramas.forEach(id => window.cancelAnimationFrame?.(id));
        cancelarPintado = undefined;
        resolve(continuar);
      };
      // En una pestaña oculta requestAnimationFrame puede estar suspendido.
      const limite = setTimeout(() => terminar(true), 100);
      cancelarPintado = () => terminar(false);
      if (typeof window.requestAnimationFrame === 'function') {
        fotogramas.push(window.requestAnimationFrame(() => {
          fotogramas.push(window.requestAnimationFrame(() => terminar(true)));
        }));
      }
    });
  };
  const error = () => {
    if (contenido) { restaurar(); return; }
    cancelar();
    if (panel) {
      panel.hidden = false;
      titulo.textContent = 'No pudimos abrir tu sesión';
      descripcion.textContent = 'Vuelve a iniciar sesión para continuar.';
      indicador.hidden = true;
    }
  };
  window.SSAccesoTransicion = {mostrar, restaurar, cancelar, error, logoSeguro};
})();
