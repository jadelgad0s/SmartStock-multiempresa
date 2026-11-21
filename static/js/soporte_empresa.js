document.addEventListener('DOMContentLoaded', async () => {
  'use strict';
  const datos = await window.SmartStockNavegacion?.lista;
  if (!datos?.usuario) return;
  document.querySelectorAll('#ss-navigation .sidebar-item').forEach(enlace => {
    enlace.classList.toggle('active', enlace.getAttribute('aria-current') === 'page');
  });
  const el = id => document.getElementById(id);
  if (el('user-name')) el('user-name').textContent = datos.usuario.nombre_completo || datos.usuario.email;
  if (el('user-role')) el('user-role').textContent = datos.usuario.rol_nombre || 'Administrador';
  const nombre = datos.usuario.nombre_completo || datos.usuario.email || 'U';
  if (el('dashboard-avatar')) el('dashboard-avatar').textContent = nombre.split(/\s+/).filter(Boolean).map(n => n[0]).slice(0, 2).join('').toUpperCase();
});
