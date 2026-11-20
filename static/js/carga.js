/* Indicador compartido para las solicitudes que el usuario espera en pantalla. */
(() => {
    'use strict';
    const dialogo = document.getElementById('ss-carga');
    if (typeof dialogo?.showModal !== 'function') return;
    const texto = document.getElementById('ss-carga-texto');
    const pendientes = new Map();
    let temporizador = null;
    dialogo.addEventListener('cancel', evento => evento.preventDefault());

    function actualizar() {
        if (!pendientes.size) {
            clearTimeout(temporizador);
            temporizador = null;
            if (dialogo.open) dialogo.close();
            return;
        }
        texto.textContent = [...pendientes.values()].at(-1);
        if (!dialogo.open && temporizador === null) {
            // Evitar el destello cuando la respuesta llega en el siguiente pintado.
            temporizador = setTimeout(() => {
                temporizador = null;
                dialogo.showModal();
            }, 120);
        }
    }

    window.SmartStockCarga = async (mensaje, tarea) => {
        const solicitud = Symbol();
        pendientes.set(solicitud, mensaje);
        actualizar();
        try {
            return await tarea();
        } finally {
            pendientes.delete(solicitud);
            actualizar();
        }
    };
})();
