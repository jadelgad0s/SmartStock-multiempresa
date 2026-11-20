document.addEventListener('DOMContentLoaded', () => {
  'use strict';
  const dialogo = document.getElementById('ss-carga');
  const textoCarga = document.getElementById('ss-carga-texto');
  document.querySelectorAll('form[data-ss-loading]').forEach(formulario => {
    formulario.addEventListener('submit', evento => {
      if (evento.submitter?.name === 'exportar') return;
      if (formulario.getAttribute('aria-busy') === 'true') {
        evento.preventDefault();
        return;
      }
      formulario.setAttribute('aria-busy', 'true');
      textoCarga.textContent = formulario.dataset.ssLoading;
      if (!dialogo.open) dialogo.showModal();
    });
  });
  window.addEventListener('pageshow', () => {
    document.querySelectorAll('form[aria-busy]').forEach(formulario => formulario.setAttribute('aria-busy', 'false'));
    if (dialogo.open) dialogo.close();
  });

  const contenido = document.getElementById('sistema-datos-dashboard');
  if (!contenido || typeof Chart !== 'function') return;
  const datos = JSON.parse(contenido.textContent);
  const movimientos = new Chart(document.getElementById('sistema-grafico-movimientos'), {
    type: 'line',
    data: {
      labels: datos.chart_labels,
      datasets: [
        {label: 'Entradas', data: datos.chart_entradas, borderColor: '#0f766e', backgroundColor: '#0f766e15', fill: true, tension: 0.15},
        {label: 'Salidas', data: datos.chart_salidas, borderColor: '#3979ff', borderDash: [5, 4], tension: 0.15},
      ],
    },
    options: {responsive: true, maintainAspectRatio: false, scales: {x: {ticks: {}}, y: {beginAtZero: true, ticks: {precision: 0}}}, plugins: {legend: {labels: {}}}},
  });
  new Chart(document.getElementById('sistema-grafico-estado'), {
    type: 'doughnut',
    data: {labels: ['Stock suficiente', 'Stock bajo', 'Agotados'], datasets: [{
      data: [datos.estado_inventario.suficiente, datos.estado_inventario.bajo, datos.estado_inventario.agotado],
      backgroundColor: ['#0f766e', '#d97706', '#dc3545'], borderWidth: 0,
    }]},
    options: {responsive: true, maintainAspectRatio: false, cutout: '72%', plugins: {legend: {display: false}}},
  });
  const actualizarColores = () => {
    const color = getComputedStyle(document.documentElement).getPropertyValue('--slate-600').trim();
    movimientos.options.scales.x.ticks.color = color;
    movimientos.options.scales.y.ticks.color = color;
    movimientos.options.plugins.legend.labels.color = color;
    movimientos.update('none');
  };
  actualizarColores();
  window.addEventListener('smartstock:themechange', actualizarColores);
});
