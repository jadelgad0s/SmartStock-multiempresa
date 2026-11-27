/* Representación de las asignaciones FIFO y las existencias por lote. */
(() => {
    'use strict';
    function celda(texto, encabezado = false) {
        const elemento = document.createElement(encabezado ? 'th' : 'td');
        elemento.textContent = texto;
        if (encabezado) elemento.scope = 'col';
        return elemento;
    }
    const numero = n => Number(n).toLocaleString('es-CL');
    const costo = n => n === null || n === undefined ? 'Sin registrar' : Number(n).toLocaleString('es-CL', {style: 'currency', currency: 'CLP', maximumFractionDigits: 2});
    function mostrar(contenedor, filas, mostrarBodega = false) {
        if (!contenedor) return;
        contenedor.replaceChildren();
        if (!filas?.length) {
            const texto = document.createElement('p');
            texto.className = 'small text-muted mb-0';
            texto.textContent = 'Sin lotes registrados para esta consulta. Los movimientos anteriores conservan su historial original.';
            contenedor.append(texto);
            return;
        }
        const tabla = document.createElement('table');
        tabla.className = 'table table-sm align-middle small';
        const titulo = document.createElement('caption');
        titulo.textContent = mostrarBodega ? 'Existencias ordenadas por prioridad FIFO' : 'Lotes incluidos en la operación';
        const cabecera = document.createElement('thead'), titulos = document.createElement('tr');
        ['Lote / referencia', 'Recepción', ...(mostrarBodega ? ['Bodega'] : []), 'Unidades', 'Costo unitario'].forEach(texto => titulos.append(celda(texto, true)));
        cabecera.append(titulos);
        const cuerpo = document.createElement('tbody');
        for (const fila of filas) {
            const tr = document.createElement('tr');
            const fecha = fila.es_saldo_inicial ? 'Saldo anterior' : new Date(fila.fecha_recepcion).toLocaleString('es-CL');
            tr.append(celda(fila.codigo + (fila.referencia ? ' · ' + fila.referencia : '')), celda(fecha));
            if (mostrarBodega) tr.append(celda(fila.bodega));
            tr.append(celda(numero(fila.cantidad)), celda(costo(fila.costo_unitario)));
            cuerpo.append(tr);
        }
        tabla.append(titulo, cabecera, cuerpo);
        contenedor.append(tabla);
    }
    window.SmartStockLotes = {mostrar};
})();
