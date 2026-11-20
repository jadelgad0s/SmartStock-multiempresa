/* Listas dependientes de dirección para la ficha de empresa y Django Admin. */
(() => {
  'use strict';
  const iniciar = () => {
    document.querySelectorAll('select[data-ss-regiones-comunas]').forEach(region => {
      const comuna = region.form?.elements.namedItem(region.dataset.ssComunaNombre);
      if (!comuna || region.dataset.ssDireccionLista === 'true') return;
      let regiones;
      try {
        regiones = JSON.parse(region.dataset.ssRegionesComunas);
      } catch (_) {
        return; // Conserva las opciones y validaciones que entrega el servidor.
      }
      const actualizar = conservar => {
        const anterior = conservar ? comuna.value : '';
        const seleccionada = regiones.find(item => item.nombre === region.value);
        const opciones = seleccionada?.comunas || [];
        const placeholder = new Option(opciones.length ? 'Selecciona una comuna' : 'Selecciona una región primero', '');
        comuna.replaceChildren(placeholder, ...opciones.map(item => new Option(
          item.nombre + (item.anterior ? ' (valor anterior)' : ''), item.nombre,
        )));
        comuna.value = opciones.some(item => item.nombre === anterior) ? anterior : '';
        comuna.disabled = opciones.length === 0;
        const ayuda = document.getElementById(comuna.id + '_helptext');
        if (ayuda) {
          ayuda.setAttribute('aria-live', 'polite');
          ayuda.textContent = opciones.length ? 'Selecciona una comuna de la región indicada.' : 'Selecciona una región para ver sus comunas.';
        }
      };
      region.dataset.ssDireccionLista = 'true';
      region.addEventListener('change', () => actualizar(false));
      window.addEventListener('pageshow', () => actualizar(true));
      actualizar(true);
    });
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', iniciar);
  else iniciar();
})();
