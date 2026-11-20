document.addEventListener('DOMContentLoaded', () => {
  'use strict';
  const dialogo = document.getElementById('ss-carga');
  const textoCarga = document.getElementById('ss-carga-texto');
  let navegando = false;
  const cargarPagina = mensaje => {
    navegando = true;
    if (!dialogo || !textoCarga) return;
    textoCarga.textContent = mensaje;
    if (!dialogo.open && typeof dialogo.showModal === 'function') dialogo.showModal();
  };
  const salida = document.getElementById('ss-cerrar-sesion');
  if (salida) salida.dataset.ssLoading = 'Cerrando sesión…';
  document.querySelectorAll('form[data-ss-loading]').forEach(formulario => {
    formulario.addEventListener('submit', evento => {
      if (evento.defaultPrevented || evento.submitter?.name === 'exportar') return;
      if (navegando || formulario.getAttribute('aria-busy') === 'true' || !formulario.checkValidity()) {
        evento.preventDefault();
        return;
      }
      formulario.setAttribute('aria-busy', 'true');
      cargarPagina(formulario.dataset.ssLoading);
    });
  });
  document.querySelector('.ss-sistema')?.addEventListener('click', evento => {
    const enlace = evento.target.closest('a[href]');
    if (!enlace || evento.defaultPrevented || evento.button !== 0 || evento.ctrlKey || evento.metaKey || evento.shiftKey || evento.altKey
        || enlace.hasAttribute('download') || (enlace.target && enlace.target !== '_self')) return;
    const url = new URL(enlace.href, window.location.href);
    if (url.origin !== window.location.origin || !(/^\/(sistema|contacto)\//).test(url.pathname)
        || (url.pathname === window.location.pathname && url.search === window.location.search)) return;
    if (navegando) { evento.preventDefault(); return; }
    cargarPagina('Cargando ' + (enlace.textContent.trim() || 'SmartStock') + '…');
  });
  window.addEventListener('pageshow', () => {
    navegando = false;
    document.querySelectorAll('form[aria-busy]').forEach(formulario => formulario.setAttribute('aria-busy', 'false'));
    if (dialogo?.open) dialogo.close();
  });

  const contenido = document.getElementById('sistema-datos-dashboard');
  if (!contenido || typeof Chart !== 'function') return;
  const datos = JSON.parse(contenido.textContent);
  const lienzoMovimientos = document.getElementById('sistema-grafico-movimientos');
  const lienzoEstado = document.getElementById('sistema-grafico-estado');
  const movimientos = lienzoMovimientos ? new Chart(lienzoMovimientos, {
    type: 'line',
    data: {
      labels: datos.chart_labels,
      datasets: [
        {label: 'Entradas', data: datos.chart_entradas, borderColor: '#0f766e', backgroundColor: '#0f766e15', fill: true, tension: 0.15},
        {label: 'Salidas', data: datos.chart_salidas, borderColor: '#3979ff', borderDash: [5, 4], tension: 0.15},
      ],
    },
    options: {responsive: true, maintainAspectRatio: false, scales: {x: {ticks: {}}, y: {beginAtZero: true, ticks: {precision: 0}}}, plugins: {legend: {labels: {}}}},
  }) : null;
  if (lienzoEstado) new Chart(lienzoEstado, {
    type: 'doughnut',
    data: {labels: ['Stock suficiente', 'Stock bajo', 'Agotados'], datasets: [{
      data: [datos.estado_inventario.suficiente, datos.estado_inventario.bajo, datos.estado_inventario.agotado],
      backgroundColor: ['#0f766e', '#d97706', '#dc3545'], borderWidth: 0,
    }]},
    options: {responsive: true, maintainAspectRatio: false, cutout: '72%', plugins: {legend: {display: false}}},
  });
  const actualizarColores = () => {
    if (!movimientos) return;
    const color = getComputedStyle(document.documentElement).getPropertyValue('--slate-600').trim();
    movimientos.options.scales.x.ticks.color = color;
    movimientos.options.scales.y.ticks.color = color;
    movimientos.options.plugins.legend.labels.color = color;
    movimientos.update('none');
  };
  actualizarColores();
  window.addEventListener('smartstock:themechange', actualizarColores);
});
