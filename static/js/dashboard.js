/* Inventario por bodega: datos reales, estados visibles y consultas sin respuestas atrasadas. */
document.addEventListener('DOMContentLoaded', async () => {
    'use strict';
    if (window.SmartStockNavegacion && !await window.SmartStockNavegacion.lista) return;
    let token = localStorage.getItem('access_token');
    if (!token) { window.location.replace('/'); return; }
    let sesion;
    try { sesion = JSON.parse(localStorage.getItem('usuario') || '{}') || {}; } catch (_) { sesion = {}; }
    const el = id => document.getElementById(id);
    const conCarga = window.SmartStockCarga || ((_, tarea) => tarea());
    const nodo = (tag, clase, texto) => {
        const n = document.createElement(tag);
        if (clase) n.className = clase;
        if (texto !== undefined) n.textContent = String(texto ?? '');
        return n;
    };
    const numero = n => Number(n).toLocaleString('es-CL');
    const aviso = (id, texto) => { el(id).textContent = texto || ''; el(id).hidden = !texto; };
    const entero = n => Number.isSafeInteger(n) && n >= 0;
    function fecha(valor, completa = true) {
        if (!valor || Number.isNaN(new Date(valor).getTime())) return '—';
        const p = Object.fromEntries(new Intl.DateTimeFormat('es-CL', {
            timeZone: 'America/Santiago', year: 'numeric', month: '2-digit', day: '2-digit',
            hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
        }).formatToParts(new Date(valor)).map(x => [x.type, x.value]));
        return p.day + '/' + p.month + '/' + p.year + (completa ? ' ' + p.hour + ':' + p.minute + ':' + p.second : '');
    }
    const nombre = sesion.nombre_completo || 'Usuario';
    el('user-name').textContent = nombre;
    el('user-role').textContent = sesion.rol_nombre || 'Sin rol';
    el('dashboard-avatar').textContent = nombre.split(/\s+/).filter(Boolean).map(n => n[0]).slice(0, 2).join('').toUpperCase();
    let renovacion = null;
    async function renovar() {
        if (!renovacion) renovacion = (async () => {
            const refresh = localStorage.getItem('refresh_token');
            if (!refresh) return false;
            const res = await fetch('/api/v1/auth/refresh/', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({refresh})});
            if (res.status >= 500) throw new Error('No se pudo renovar la sesión. Vuelve a intentarlo.');
            if (!res.ok) return false;
            const json = await res.json(), datos = json.data || json;
            if (!datos.access) return false;
            token = datos.access; localStorage.setItem('access_token', token);
            if (datos.refresh) localStorage.setItem('refresh_token', datos.refresh);
            return true;
        })().finally(() => { renovacion = null; });
        return renovacion;
    }
    async function api(url) {
        const usado = token;
        const enviar = () => fetch(url, {headers: {Authorization: 'Bearer ' + token}, cache: 'no-store'});
        let res;
        try {
            res = await enviar();
            if (res.status === 401) {
                if (token !== usado || await renovar()) res = await enviar();
                else {
                    window.smartstockClearSession(); window.location.replace('/');
                    throw new Error('La sesión expiró. Vuelve a iniciar sesión.');
                }
            }
        } catch (error) { throw new Error(error.message === 'Failed to fetch' ? 'No se pudo conectar con el servidor. Vuelve a intentarlo.' : error.message || 'No se pudo conectar con el servidor.'); }
        let datos;
        try { datos = await res.json(); } catch (_) { throw new Error('No se pudo leer la respuesta del servidor. Vuelve a intentarlo.'); }
        if (!res.ok || !datos || datos.success === false) {
            const error = new Error(res.status === 403 ? 'Tu cuenta no tiene acceso a esta información.' : datos?.mensaje || datos?.detail || 'No se pudo cargar la información. Vuelve a intentarlo.');
            error.status = res.status; throw error;
        }
        return datos;
    }
    let chartLineInstance = null, chartDoughnutInstance = null, chartComparacion = null;
    const datosVolumen = el('dashboardDatosGrafico').closest('details');
    function destruirGraficos() {
        chartLineInstance?.destroy(); chartDoughnutInstance?.destroy();
        chartLineInstance = chartDoughnutInstance = null;
    }
    function colores() {
        const oscuro = document.documentElement.getAttribute('data-bs-theme') === 'dark';
        return {texto: oscuro ? '#c4d0e0' : '#475569', rejilla: oscuro ? 'rgba(196,208,224,.18)' : 'rgba(71,85,105,.15)', entrada: oscuro ? '#5eead4' : '#0f766e', salida: oscuro ? '#93c5fd' : '#2563eb'};
    }
    function temaGraficos() {
        const c = colores();
        [chartLineInstance, chartDoughnutInstance, chartComparacion].forEach(g => {
            if (!g) return;
            if (g.options.plugins?.legend?.labels) g.options.plugins.legend.labels.color = c.texto;
            Object.values(g.options.scales || {}).forEach(e => {
                e.ticks = {...e.ticks, color: c.texto}; e.grid = {...e.grid, color: c.rejilla};
                if (e.title) e.title.color = c.texto;
            });
            if (g === chartLineInstance || g === chartComparacion) {
                g.data.datasets[0].borderColor = c.entrada; g.data.datasets[1].borderColor = c.salida;
            }
            g.update('none');
        });
    }
    window.addEventListener('smartstock:themechange', temaGraficos);
    function graficoLineas(canvas, etiquetas, series) {
        const c = colores(), reducir = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
        return new Chart(canvas.getContext('2d'), {
            type: 'line',
            data: {
                labels: etiquetas,
                datasets: series.map(serie => ({tension: 0, borderWidth: 2, pointRadius: etiquetas.length === 30 ? 1 : 3, ...serie})),
            },
            options: {
                responsive: true, maintainAspectRatio: false, animation: reducir ? false : {duration: 200},
                plugins: {
                    legend: {position: 'top', labels: {color: c.texto, usePointStyle: true}},
                    tooltip: {callbacks: {label: ctx => ctx.dataset.label + ': ' + numero(ctx.parsed.y) + ' unid.'}},
                },
                scales: {
                    y: {beginAtZero: true, title: {display: true, text: 'Unidades', color: c.texto}, ticks: {precision: 0, color: c.texto}, grid: {color: c.rejilla}},
                    x: {ticks: {color: c.texto, maxTicksLimit: 7}, grid: {display: false}},
                },
            },
        });
    }
    function graficos(info) {
        destruirGraficos();
        const hayMovimientos = [...info.chart_entradas, ...info.chart_salidas].some(n => n !== 0);
        const hayProductos = info.estado_inventario.total > 0;
        const disponible = typeof Chart !== 'undefined';
        el('lineChart').hidden = !hayMovimientos || !disponible;
        el('doughnutChart').hidden = !hayProductos || !disponible;
        el('dashboardSinMovimientos').hidden = hayMovimientos;
        el('dashboardSinProductos').hidden = hayProductos;
        el('dashboardCentroEstado').hidden = !hayProductos;
        el('dashboardChartError').hidden = disponible || !hayMovimientos;
        el('dashboardDatosGrafico').replaceChildren(...info.chart_fechas.map((dia, i) => {
            const f = nodo('tr'); f.append(nodo('td', '', dia.split('-').reverse().join('/')), nodo('td', '', numero(info.chart_entradas[i])), nodo('td', '', numero(info.chart_salidas[i]))); return f;
        }));
        if (!disponible) { datosVolumen.open = true; return; }
        const c = colores(), reducir = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
        try {
            if (hayMovimientos) chartLineInstance = graficoLineas(el('lineChart'), info.chart_labels, [
                {label: 'Entradas', data: info.chart_entradas, borderColor: c.entrada, backgroundColor: 'rgba(15,118,110,.07)', fill: true},
                {label: 'Salidas', data: info.chart_salidas, borderColor: c.salida, borderDash: [5, 4]},
            ]);
            if (hayProductos) chartDoughnutInstance = new Chart(el('doughnutChart').getContext('2d'), {
                type: 'doughnut',
                data: {labels: ['Stock suficiente', 'Stock bajo', 'Agotados'], datasets: [{data: [info.estado_inventario.suficiente, info.estado_inventario.bajo, info.estado_inventario.agotado], backgroundColor: ['#0f766e', '#d97706', '#dc3545'], borderWidth: 0}]},
                options: {responsive: true, maintainAspectRatio: false, cutout: '76%', animation: reducir ? false : {duration: 200}, plugins: {legend: {display: false}, tooltip: {callbacks: {label: ctx => ctx.label + ': ' + numero(ctx.parsed) + ' productos'}}}},
            });
        } catch (_) {
            destruirGraficos(); el('lineChart').hidden = el('doughnutChart').hidden = true;
            el('dashboardChartError').hidden = false; datosVolumen.open = true;
        }
    }

    const bodegaComparacion = el('compararBodega'), botonComparar = el('compararEnviar');
    let versionComparacion = 0;
    function invalidarComparacion() {
        ++versionComparacion;
        chartComparacion?.destroy();
        chartComparacion = null;
        el('compararResultados').hidden = true;
        aviso('compararEstado', '');
        aviso('compararError', '');
        botonComparar.disabled = !bodegaComparacion.value;
    }
    function cargarBodegasComparacion(bodegas, predeterminada) {
        const anterior = bodegaComparacion.value;
        bodegaComparacion.replaceChildren(...bodegas.map(bodega => new Option(bodega.etiqueta || bodega.nombre, String(bodega.id))));
        if (bodegas.some(bodega => String(bodega.id) === anterior)) bodegaComparacion.value = anterior;
        else if (predeterminada) bodegaComparacion.value = String(predeterminada.id);
        else bodegaComparacion.append(new Option('Sin bodegas activas', ''));
        bodegaComparacion.disabled = !bodegas.length;
        if (anterior !== bodegaComparacion.value) invalidarComparacion();
    }
    function validarComparacion(info, filtros) {
        const coincide = info?.dias === Number(filtros.dias) && String(info.bodega?.id) === filtros.bodega;
        const fechas = coincide && Array.isArray(info.fechas) && info.fechas.length === info.dias
            && info.fechas.every(dia => typeof dia === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(dia));
        const serie = (producto, sku) => typeof producto?.sku === 'string' && producto.sku.toUpperCase() === sku
            && typeof producto.nombre === 'string' && Number.isSafeInteger(producto.stock_actual)
            && Array.isArray(producto.salidas) && producto.salidas.length === info.dias && producto.salidas.every(entero)
            && producto.total_salidas === producto.salidas.reduce((total, unidades) => total + unidades, 0);
        if (!fechas || !Array.isArray(info.productos) || info.productos.length !== 2 ||
            !serie(info.productos[0], filtros.sku_a) || !serie(info.productos[1], filtros.sku_b)) {
            throw new Error('La comparación tiene un formato inválido. Vuelve a intentarlo.');
        }
    }
    function resumenComparacion(producto) {
        const tarjeta = nodo('div', 'ss-dash-compare-product');
        const datos = nodo('dl');
        for (const [titulo, valor] of [['Salidas del período', producto.total_salidas], ['Stock actual', producto.stock_actual]]) {
            const campo = nodo('div');
            campo.append(nodo('dt', '', titulo), nodo('dd', '', numero(valor) + ' unid.'));
            datos.append(campo);
        }
        tarjeta.append(nodo('strong', '', producto.sku), nodo('div', 'ss-dash-subtle', producto.nombre + (producto.activo ? '' : ' · Inactivo')), datos);
        return tarjeta;
    }
    function pintarComparacion(info) {
        const [a, b] = info.productos;
        const fechaPeriodo = dia => dia.split('-').reverse().join('/');
        el('compararPeriodo').textContent = info.bodega.nombre + ' · ' + fechaPeriodo(info.fechas[0]) + ' al ' +
            fechaPeriodo(info.fechas.at(-1)) + ' · America/Santiago';
        el('compararTotales').replaceChildren(resumenComparacion(a), resumenComparacion(b));
        el('compararColumnaA').textContent = a.sku;
        el('compararColumnaB').textContent = b.sku;
        el('compararFilas').replaceChildren(...info.fechas.map((dia, indice) => {
            const fila = nodo('tr');
            fila.append(nodo('td', '', fechaPeriodo(dia)), nodo('td', '', numero(a.salidas[indice])), nodo('td', '', numero(b.salidas[indice])));
            return fila;
        }));

        const contenedor = el('compararContenedorGrafico');
        const c = colores();
        el('compararResultados').hidden = contenedor.hidden = false;
        if (typeof Chart !== 'undefined') {
            try {
                chartComparacion = graficoLineas(el('compararGrafico'), info.fechas.map(dia => fechaPeriodo(dia).slice(0, 5)), [
                    {label: a.sku, data: a.salidas, borderColor: c.entrada},
                    {label: b.sku, data: b.salidas, borderColor: c.salida, borderDash: [5, 4], pointStyle: 'rectRot'},
                ]);
            } catch (_) { chartComparacion = null; }
        }
        contenedor.hidden = !chartComparacion;
        el('compararGraficoError').hidden = Boolean(chartComparacion);
        el('compararDatos').open = !chartComparacion;
    }
    function selectorComparacion(id) {
        const campo = el(id);
        const boton = campo.parentElement.querySelector('[data-bs-toggle="dropdown"]');
        const menu = el(boton.getAttribute('aria-controls'));
        const lista = menu.querySelector('.ss-dash-picker-list');
        const estado = menu.querySelector('[data-estado]');
        const paginas = menu.querySelector('.ss-dash-picker-pages');
        const anterior = menu.querySelector('[data-anterior]');
        const siguiente = menu.querySelector('[data-siguiente]');
        const reintentar = menu.querySelector('[data-reintentar]');
        const Dropdown = window.bootstrap?.Dropdown;
        boton.disabled = !Dropdown;
        const desplegable = () => Dropdown.getOrCreateInstance(boton);
        const abierto = () => boton.getAttribute('aria-expanded') === 'true';
        const cerrar = () => Dropdown?.getInstance(boton)?.hide();
        let timer, version = 0, pagina = 1, seleccion = null;
        const elegido = () => seleccion?.etiqueta === campo.value ? seleccion.sku : '';
        const busqueda = () => elegido() ? '' : campo.value.trim();

        function cancelarCarga() {
            clearTimeout(timer);
            return ++version;
        }
        function prepararLista() {
            lista.replaceChildren();
            paginas.hidden = reintentar.hidden = true;
            estado.hidden = false;
            estado.textContent = 'Cargando productos…';
        }
        function opcion(producto) {
            const control = nodo('button', 'dropdown-item', producto.nombre);
            control.type = 'button';
            control.append(nodo('span', 'ss-dash-picker-sku', producto.sku + (producto.activo ? '' : ' · Inactivo')));
            if (producto.sku === elegido()) {
                control.classList.add('active');
                control.setAttribute('aria-current', 'true');
            }
            control.addEventListener('click', () => {
                seleccion = {sku: producto.sku, etiqueta: producto.nombre + ' · ' + producto.sku};
                campo.value = campo.title = seleccion.etiqueta;
                invalidarComparacion();
                cerrar();
                boton.focus({preventScroll: true});
            });
            return control;
        }
        async function cargar(nuevaPagina = 1, enfocar = false) {
            const solicitud = cancelarCarga();
            pagina = nuevaPagina;
            prepararLista();
            const parametros = new URLSearchParams({page: pagina});
            const termino = busqueda();
            if (termino) parametros.set('search', termino);
            try {
                const datos = await api('/api/v1/productos/?' + parametros);
                if (solicitud !== version) return;
                if (!Array.isArray(datos.results)) throw new Error('No se pudo leer la lista de productos.');
                lista.replaceChildren(...datos.results.map(opcion));
                lista.scrollTop = 0;
                estado.textContent = datos.results.length ? '' : 'No se encontraron productos.';
                estado.hidden = Boolean(datos.results.length);
                anterior.disabled = !datos.previous;
                siguiente.disabled = !datos.next;
                menu.querySelector('[data-pagina]').textContent = 'Página ' + pagina;
                paginas.hidden = anterior.disabled && siguiente.disabled;
                if (enfocar) lista.firstElementChild?.focus({preventScroll: true});
            } catch (error) {
                if (solicitud !== version) return;
                if (error.status === 404 && pagina > 1) return cargar(1, enfocar);
                estado.textContent = error.message;
                reintentar.hidden = false;
                if (enfocar) reintentar.focus({preventScroll: true});
            }
            desplegable().update();
        }
        function buscar() {
            if (!busqueda()) return cargar();
            cancelarCarga();
            prepararLista();
            timer = setTimeout(() => cargar(), 300);
            desplegable().update();
        }

        boton.addEventListener('shown.bs.dropdown', buscar);
        boton.addEventListener('hidden.bs.dropdown', cancelarCarga);
        anterior.addEventListener('click', e => cargar(pagina - 1, e.detail === 0));
        siguiente.addEventListener('click', e => cargar(pagina + 1, e.detail === 0));
        reintentar.addEventListener('click', e => cargar(pagina, e.detail === 0));
        campo.addEventListener('input', () => {
            seleccion = null;
            campo.removeAttribute('title');
            invalidarComparacion();
            if (abierto()) buscar();
            else if (Dropdown && busqueda()) {
                desplegable().show();
                campo.focus({preventScroll: true});
            }
        });
        campo.addEventListener('keydown', evento => {
            if (evento.key === 'Escape' && abierto()) {
                evento.preventDefault();
                cerrar();
            } else if (evento.key === 'ArrowDown' && Dropdown) {
                evento.preventDefault();
                desplegable().show();
                (lista.firstElementChild || boton).focus({preventScroll: true});
            }
        });
        return {sku: () => (elegido() || campo.value.trim()).toUpperCase(), cerrar};
    }
    const productoA = selectorComparacion('compararSkuA'), productoB = selectorComparacion('compararSkuB');
    bodegaComparacion.addEventListener('change', invalidarComparacion);
    el('compararDias').addEventListener('change', invalidarComparacion);
    el('formCompararProductos').addEventListener('submit', async evento => {
        evento.preventDefault();
        if (botonComparar.disabled) return;
        const filtros = {
            sku_a: productoA.sku(), sku_b: productoB.sku(),
            bodega: bodegaComparacion.value, dias: el('compararDias').value,
        };
        invalidarComparacion();
        if (!filtros.sku_a || !filtros.sku_b || filtros.sku_a === filtros.sku_b) {
            aviso('compararError', 'Elige dos SKU distintos para comparar.');
            return;
        }
        productoA.cerrar(); productoB.cerrar();
        const version = versionComparacion;
        botonComparar.disabled = true;
        aviso('compararEstado', 'Cargando comparación…');
        try {
            const datos = await api('/api/v1/productos/dashboard-comparacion/?' + new URLSearchParams(filtros));
            if (version !== versionComparacion) return;
            validarComparacion(datos.data, filtros);
            pintarComparacion(datos.data);
            aviso('compararEstado', datos.data.productos.every(producto => !producto.total_salidas)
                ? 'Ambos productos registran 0 salidas operativas en el período.' : '');
        } catch (error) {
            if (version === versionComparacion) {
                aviso('compararEstado', '');
                aviso('compararError', error.message);
            }
        } finally {
            if (version === versionComparacion) botonComparar.disabled = false;
        }
    });

    function enlaceProducto(sku, texto, bodega) {
        const a = nodo('a', 'ss-dash-product-link', texto), params = new URLSearchParams({q: sku});
        if (bodega) params.set('bodega', String(bodega));
        a.href = '/productos/?' + params; a.title = texto; return a;
    }
    function alerta(a) {
        const item = nodo('li', 'ss-dash-alert-item');
        const agotado = a.estado === 'agotado';
        const cabecera = nodo('div', 'ss-dash-alert-identity');
        cabecera.append(enlaceProducto(a.sku, a.producto, a.bodega_id), nodo('span', 'ss-dash-subtle', 'SKU: ' + a.sku));
        const tag = nodo('span', 'ss-dash-badge ' + (agotado ? 'ss-dash-badge-out' : 'ss-dash-badge-low'), agotado ? 'Agotado' : 'Stock bajo');
        const stock = nodo('p', 'ss-dash-alert-stock', 'Stock: ' + numero(a.stock) + ' unid. · Mínimo: ' + numero(a.minimo));
        item.append(cabecera, tag, stock, nodo('span', 'ss-dash-subtle ss-dash-alert-warehouse', a.bodega));
        return item;
    }
    function recientes(items) {
        const tabla = el('tabla-recientes');
        if (!items.length) { const tr = nodo('tr'), td = nodo('td', 'ss-dash-empty', 'No hay movimientos registrados en esta bodega.'); td.colSpan = 5; tr.append(td); tabla.replaceChildren(tr); return; }
        tabla.replaceChildren(...items.map(item => {
            const tr = nodo('tr', 'ss-dash-movement'), date = nodo('td', 'ss-dash-movement-date');
            const fechaLocal = fecha(item.fecha_iso), partes = fechaLocal.split(' ');
            date.append(nodo('span', '', partes[0]), nodo('span', 'ss-dash-subtle', partes[1] || ''));
            const producto = nodo('td', 'ss-dash-movement-product');
            const nombreProducto = nodo('strong', '', item.producto); nombreProducto.title = item.producto;
            producto.append(nombreProducto, nodo('span', 'ss-dash-subtle', 'SKU: ' + item.sku));
            const detalle = nodo('button', 'ss-dash-text-link', 'Ver detalle'); detalle.type = 'button'; detalle.dataset.detalle = String(item.id); detalle.setAttribute('aria-label', 'Ver detalle del movimiento de ' + item.producto); producto.append(detalle);
            const tipo = nodo('td', 'ss-dash-movement-type'), entrada = item.tipo === 'ENTRADA';
            tipo.append(nodo('span', 'ss-dash-badge ' + (entrada ? 'ss-dash-badge-in' : 'ss-dash-badge-out'), entrada ? 'Entrada' : 'Salida'));
            const cantidad = nodo('td', 'ss-dash-movement-quantity', numero(item.cantidad) + ' unid.');
            const operador = nodo('td', 'ss-dash-movement-user', item.usuario);
            tr.append(date, producto, tipo, cantidad, operador); return tr;
        }));
    }
    function aplicarPermisos(p = {}) {
        el('dashboardRegistrar').hidden = p.registrar_movimiento !== true;
        [['menu-auditoria', 'auditoria'], ['menu-usuarios', 'usuarios'], ['menu-config', 'configuracion']].forEach(([id, permiso]) => { el(id).hidden = p[permiso] !== true; });
        el('menu-sistema-title').hidden = !p.usuarios && !p.configuracion;
    }
    let version = 0, cargando = false, ultimo = null, bodegaActual = null;
    function limpiar() {
        ultimo = null; bodegaActual = null; destruirGraficos();
        ['kpi-stock', 'kpi-entradas', 'kpi-salidas', 'kpi-alertas', 'dashboardTotalProductos', 'dashboardSuficiente', 'dashboardBajo', 'dashboardAgotado'].forEach(id => { el(id).textContent = '—'; });
        el('dashboardKpiAlertas').classList.remove('ss-dash-kpi-danger', 'ss-dash-kpi-ok');
        el('dashboardAlertaNota').textContent = 'Consultando stock...';
        el('dashboardVerAlertas').disabled = true;
        el('lista-alertas').replaceChildren(); el('dashboardResumenAlertas').textContent = 'Cargando alertas...';
        el('dashboardDatosGrafico').replaceChildren(); el('dashboardPeriodo').textContent = 'Cargando período...';
        ['lineChart', 'doughnutChart', 'dashboardCentroEstado', 'dashboardSinProductos', 'dashboardSinMovimientos', 'dashboardChartError'].forEach(id => { el(id).hidden = true; });
        const tr = nodo('tr'), td = nodo('td', 'ss-dash-empty', 'Cargando movimientos...'); td.colSpan = 5; tr.append(td); el('tabla-recientes').replaceChildren(tr);
    }
    function validar(info) {
        const e = info?.estado_inventario;
        const invalido = () => { throw new Error('El resumen tiene un formato inválido. Vuelve a intentarlo.'); };
        if (!info || !e) invalido();
        const estadosValidos = ['total', 'suficiente', 'bajo', 'agotado'].every(k => entero(e[k]))
            && e.total === e.suficiente + e.bajo + e.agotado;
        const indicadoresValidos = Number.isSafeInteger(info.kpi_stock) && entero(info.kpi_entradas) && entero(info.kpi_salidas);
        const fechaDia = valor => typeof valor === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(valor);
        const fechasValidas = ['desde', 'hasta'].every(k => fechaDia(info[k]))
            && info.actualizado && !Number.isNaN(new Date(info.actualizado).getTime());
        const seriesValidas = [7, 30].includes(info.dias)
            && ['chart_labels', 'chart_fechas', 'chart_entradas', 'chart_salidas'].every(k => Array.isArray(info[k]) && info[k].length === info.dias)
            && info.chart_fechas.every(fechaDia) && [...info.chart_entradas, ...info.chart_salidas].every(entero);
        const listasValidas = ['bodegas', 'recientes', 'alertas'].every(k => Array.isArray(info[k]));
        if (!estadosValidos || !indicadoresValidos || !fechasValidas || !seriesValidas || !listasValidas) invalido();
    }
    function pintar(info) {
        validar(info); const e = info.estado_inventario;
        el('dashboardBodega').replaceChildren(...info.bodegas.map(b => new Option(b.etiqueta || b.nombre, String(b.id))));
        if (info.bodega) el('dashboardBodega').value = String(info.bodega.id);
        else el('dashboardBodega').append(new Option('Sin bodegas activas', ''));
        el('dashboardBodega').disabled = !info.bodegas.length;
        cargarBodegasComparacion(info.bodegas, info.bodega);
        el('dashboardDias').value = String(info.dias); bodegaActual = info.bodega;
        el('dashboardScope').textContent = info.bodega ? info.bodega.nombre + ' · Productos activos · America/Santiago.' : 'No hay bodegas activas para consultar.';
        el('dashboardSinProductos').textContent = info.bodega ? 'No hay productos activos para evaluar.' : 'No hay bodegas activas para evaluar.';
        [['kpi-stock', info.kpi_stock], ['kpi-entradas', info.kpi_entradas], ['kpi-salidas', info.kpi_salidas], ['kpi-alertas', e.agotado], ['dashboardTotalProductos', e.total], ['dashboardSuficiente', e.suficiente], ['dashboardBajo', e.bajo], ['dashboardAgotado', e.agotado]].forEach(([id, n]) => { el(id).textContent = numero(n); });
        el('dashboardKpiAlertas').classList.toggle('ss-dash-kpi-danger', e.agotado > 0);
        el('dashboardKpiAlertas').classList.toggle('ss-dash-kpi-ok', e.agotado === 0 && Boolean(info.bodega));
        el('dashboardAlertaNota').textContent = !info.bodega ? 'Sin bodega disponible' : e.agotado ? 'Requieren reposición' : 'Sin productos agotados';
        el('dashboardPeriodo').textContent = info.desde.split('-').reverse().join('/') + ' al ' + info.hasta.split('-').reverse().join('/') + ' · Unidades por día';
        el('doughnutChart').setAttribute('aria-label', e.total + ' productos: ' + e.suficiente + ' con stock suficiente, ' + e.bajo + ' con stock bajo y ' + e.agotado + ' agotados.');
        graficos(info); recientes(info.recientes);
        const totalAlertas = e.agotado + e.bajo;
        el('dashboardResumenAlertas').textContent = !info.bodega ? 'Sin bodega disponible.' : totalAlertas ? numero(e.agotado) + ' agotados · ' + numero(e.bajo) + ' con stock bajo.' : e.total ? 'Sin productos agotados ni con stock bajo.' : 'No hay productos activos para evaluar.';
        el('lista-alertas').replaceChildren(...info.alertas.map(alerta));
        el('dashboardVerAlertas').textContent = totalAlertas ? 'Ver todas (' + numero(totalAlertas) + ')' : 'Ver todas →';
        el('dashboardVerAlertas').disabled = !totalAlertas;
        aplicarPermisos(info.permisos); ultimo = info.actualizado;
        el('dashboardActualizado').textContent = 'Última actualización: ' + fecha(ultimo);
    }
    async function cargar({reset = false} = {}) {
        const miVersion = ++version; cargando = true;
        const params = new URLSearchParams({dias: el('dashboardDias').value});
        if (el('dashboardBodega').value) params.set('bodega', el('dashboardBodega').value);
        if (reset) limpiar();
        el('dashboardContenido').setAttribute('aria-busy', 'true'); el('dashboardContenido').classList.add('ss-dash-loading');
        el('dashboardActualizar').disabled = true; el('dashboardActualizar').textContent = 'Actualizando...';
        el('dashboardActualizado').textContent = ultimo ? 'Actualizando · Última consulta: ' + fecha(ultimo) : 'Cargando resumen...'; aviso('dashboardError', '');
        try {
            const json = await api('/api/v1/productos/dashboard-resumen/?' + params);
            if (miVersion !== version) return;
            pintar(json.data);
        } catch (error) {
            if (miVersion !== version) return;
            if (error.status === 403) { limpiar(); aplicarPermisos(); cargarBodegasComparacion([], null); }
            aviso('dashboardError', error.message + ' Usa «Actualizar» para reintentar.');
            el('dashboardActualizado').textContent = ultimo ? 'Datos sin actualizar · Última consulta: ' + fecha(ultimo) : 'No se pudo cargar el resumen.';
            if (!ultimo) {
                el('dashboardResumenAlertas').textContent = 'Alertas no disponibles.'; el('dashboardAlertaNota').textContent = 'Datos no disponibles';
                el('dashboardPeriodo').textContent = 'No se pudo consultar el período.';
                el('dashboardSinProductos').textContent = 'Estado del inventario no disponible.'; el('dashboardSinProductos').hidden = false;
                const tr = nodo('tr'), td = nodo('td', 'ss-dash-empty', 'Movimientos no disponibles. Usa «Actualizar» para reintentar.'); td.colSpan = 5; tr.append(td); el('tabla-recientes').replaceChildren(tr);
            }
        } finally {
            if (miVersion === version) {
                cargando = false; el('dashboardContenido').setAttribute('aria-busy', 'false'); el('dashboardContenido').classList.remove('ss-dash-loading');
                el('dashboardActualizar').disabled = false; el('dashboardActualizar').textContent = 'Actualizar';
            }
        }
    }
    el('dashboardActualizar').addEventListener('click', () => { if (!cargando) conCarga('Actualizando resumen…', cargar); });
    el('dashboardBodega').addEventListener('change', () => cargar({reset: true}));
    el('dashboardDias').addEventListener('change', () => cargar({reset: true}));
    document.addEventListener('visibilitychange', () => { if (!document.hidden && !cargando) cargar(); });
    window.addEventListener('pageshow', e => { if (e.persisted && !cargando) cargar(); });
    el('dashboardSearchForm').addEventListener('submit', e => {
        e.preventDefault(); const q = el('dashBuscador').value.trim();
        if (q) window.location.assign('/productos/?q=' + encodeURIComponent(q));
    });

    const modalDetalle = el('modalDashboardDetalle'); let detalleVersion = 0, origenDetalle;
    el('tabla-recientes').addEventListener('click', async e => {
        const boton = e.target.closest('button[data-detalle]'); if (!boton) return;
        const v = ++detalleVersion; origenDetalle = boton;
        el('dashboardDetalleDatos').replaceChildren(); aviso('dashboardDetalleEstado', 'Cargando movimiento...');
        bootstrap.Modal.getOrCreateInstance(modalDetalle).show();
        try {
            const json = await api('/api/v1/productos/movimientos/' + encodeURIComponent(boton.dataset.detalle) + '/');
            if (v !== detalleVersion) return;
            const d = json.data;
            el('dashboardDetalleDatos').replaceChildren(...[
                ['Producto', d.producto], ['SKU', d.sku], ['Fecha / hora', fecha(d.fecha_iso)], ['Tipo', d.tipo === 'ENTRADA' ? 'Entrada' : 'Salida'], ['Cantidad', numero(d.cantidad) + ' unid.'], ['Operador', d.usuario], ['Bodega', d.bodega], ['Referencia', d.documento_referencia || 'Sin referencia'], ['ID movimiento', '#' + d.movimiento_id],
            ].flatMap(([nombre, valor]) => [nodo('dt', '', nombre), nodo('dd', '', valor)]));
            aviso('dashboardDetalleEstado', '');
        } catch (error) { if (v === detalleVersion) aviso('dashboardDetalleEstado', error.message); }
    });
    modalDetalle.addEventListener('hide.bs.modal', () => { detalleVersion++; });
    modalDetalle.addEventListener('hidden.bs.modal', () => { if (origenDetalle?.isConnected) origenDetalle.focus(); });

    const modalAlertas = el('modalDashboardAlertas');
    let alertasVersion = 0, paginaAlertas = 1, bodegaAlertas = null, timerBusqueda;
    function prepararAlertas() {
        el('dashboardListaAlertas').replaceChildren(); el('dashboardListaAlertas').setAttribute('aria-busy', 'true');
        el('dashboardPaginasAlertas').replaceChildren(); el('dashboardContadorAlertas').textContent = 'Cargando productos...';
        aviso('dashboardErrorAlertas', ''); el('dashboardReintentarAlertas').hidden = true;
    }
    function paginarAlertas(paginas) {
        const nav = el('dashboardPaginasAlertas'); nav.replaceChildren(); if (paginas <= 1) return;
        const ul = nodo('ul', 'pagination');
        const agregar = (texto, n, disabled, actual = false) => {
            const li = nodo('li', 'page-item' + (disabled ? ' disabled' : '') + (actual ? ' active' : ''));
            const b = nodo('button', 'page-link', texto); b.type = 'button'; b.disabled = disabled || actual; b.dataset.page = String(n);
            b.setAttribute('aria-label', texto === 'Anterior' ? 'Página anterior' : texto === 'Siguiente' ? 'Página siguiente' : 'Ir a página ' + n);
            if (actual) b.setAttribute('aria-current', 'page'); li.append(b); ul.append(li);
        };
        agregar('Anterior', paginaAlertas - 1, paginaAlertas === 1);
        const numeros = new Set([1, paginas]);
        for (let n = Math.max(1, paginaAlertas - 1); n <= Math.min(paginas, paginaAlertas + 1); n++) numeros.add(n);
        let previo = 0;
        [...numeros].sort((a, b) => a - b).forEach(n => { if (previo && n > previo + 1) ul.append(nodo('li', 'ss-dash-ellipsis', '…')); agregar(String(n), n, false, n === paginaAlertas); previo = n; });
        agregar('Siguiente', paginaAlertas + 1, paginaAlertas === paginas); nav.append(ul);
    }
    async function cargarAlertas({ultima = false, enfocar = false} = {}) {
        clearTimeout(timerBusqueda); if (!bodegaAlertas) return;
        const v = ++alertasVersion; prepararAlertas();
        const params = new URLSearchParams({bodega: String(bodegaAlertas.id), page: ultima ? 'last' : String(paginaAlertas)});
        if (el('dashboardBuscarAlerta').value.trim()) params.set('search', el('dashboardBuscarAlerta').value.trim());
        if (el('dashboardEstadoAlerta').value) params.set('estado', el('dashboardEstadoAlerta').value);
        try {
            const json = await api('/api/v1/productos/dashboard-alertas/?' + params);
            if (v !== alertasVersion) return;
            if (!entero(json.count) || !Array.isArray(json.results)) throw new Error('No se pudo leer la lista de alertas.');
            const paginas = Math.ceil(json.count / 25); if (ultima) paginaAlertas = Math.max(1, paginas);
            el('dashboardListaAlertas').replaceChildren(...json.results.map(alerta));
            const primero = (paginaAlertas - 1) * 25 + 1;
            el('dashboardContadorAlertas').textContent = json.count ? 'Mostrando ' + primero + '–' + (primero + json.results.length - 1) + ' de ' + json.count + ' productos' : 'No hay productos que coincidan con estos filtros.';
            paginarAlertas(paginas);
            if (enfocar) { const destino = el('dashboardPaginasAlertas').querySelector('[aria-current="page"]'); if (destino) { destino.disabled = false; destino.focus(); destino.disabled = true; } }
        } catch (error) {
            if (v !== alertasVersion) return;
            if (error.status === 404 && paginaAlertas > 1 && !ultima) return cargarAlertas({ultima: true, enfocar});
            aviso('dashboardErrorAlertas', error.message); el('dashboardContadorAlertas').textContent = 'Lista no disponible.'; el('dashboardReintentarAlertas').hidden = false;
        } finally { if (v === alertasVersion) el('dashboardListaAlertas').setAttribute('aria-busy', 'false'); }
    }
    el('dashboardVerAlertas').addEventListener('click', () => {
        if (!bodegaActual) return;
        bodegaAlertas = {...bodegaActual}; paginaAlertas = 1;
        el('dashboardBuscarAlerta').value = ''; el('dashboardEstadoAlerta').value = '';
        el('dashboardAlertasBodega').textContent = bodegaAlertas.nombre + ' · Productos activos';
        bootstrap.Modal.getOrCreateInstance(modalAlertas).show(); cargarAlertas();
    });
    modalAlertas.addEventListener('hide.bs.modal', () => { alertasVersion++; clearTimeout(timerBusqueda); bodegaAlertas = null; });
    modalAlertas.addEventListener('hidden.bs.modal', () => el('dashboardVerAlertas').focus());
    el('dashboardBuscarAlerta').addEventListener('input', () => { alertasVersion++; paginaAlertas = 1; clearTimeout(timerBusqueda); prepararAlertas(); timerBusqueda = setTimeout(() => cargarAlertas(), 300); });
    el('dashboardEstadoAlerta').addEventListener('change', () => { paginaAlertas = 1; cargarAlertas(); });
    el('dashboardReintentarAlertas').addEventListener('click', () => cargarAlertas());
    el('dashboardPaginasAlertas').addEventListener('click', e => { const b = e.target.closest('button[data-page]'); if (b && !b.disabled) { paginaAlertas = Number(b.dataset.page); cargarAlertas({enfocar: true}); } });
    limpiar();
    conCarga('Cargando resumen de inventario…', cargar);
});
