"""Lotes operativos. Los llamadores bloquean producto, bodegas y stock en ese orden."""
from django.utils import timezone
from rest_framework.exceptions import APIException

from .models import DetalleLote, ExistenciaLote, Lote


class ConflictoLotes(APIException):
    status_code = 409
    default_detail = 'Las existencias por lote no coinciden con el stock. Revisa el inventario antes de operar.'
    default_code = 'conflicto_lotes'


def existencias_fifo(producto_id, bodega_id=None):
    # El saldo anterior se utiliza antes de las recepciones identificadas.
    consulta = ExistenciaLote.objects.filter(lote__producto_id=producto_id)
    if bodega_id is not None:
        consulta = consulta.filter(bodega_id=bodega_id)
    return consulta.select_related('lote').order_by('-lote__es_saldo_inicial', 'lote__fecha_recepcion', 'lote_id', 'bodega_id')


def preparar_lotes(producto, bodega, cantidad_stock):
    consulta = existencias_fifo(producto.pk, bodega.pk).select_for_update(of=('self',))
    filas = list(consulta.filter(cantidad__gt=0))
    if not filas and cantidad_stock > 0 and not consulta.exists():
        # Compatibilidad con saldos cargados directamente antes de usar lotes.
        # Una distribución existente, incluso agotada, nunca se reajusta aquí.
        lote = Lote.objects.create(producto=producto, cantidad_inicial=cantidad_stock,
                                   referencia='Saldo anterior sin desglose de recepción', es_saldo_inicial=True)
        filas = [ExistenciaLote.objects.create(lote=lote, bodega=bodega, cantidad=cantidad_stock)]
    if sum(fila.cantidad for fila in filas) != cantidad_stock:
        raise ConflictoLotes()
    return filas


def recibir_lote(producto, bodega, detalle, referencia='', costo_unitario=None):
    lote = Lote.objects.create(producto=producto, cantidad_inicial=detalle.cantidad,
                               fecha_recepcion=detalle.movimiento.fecha_creacion,
                               referencia=referencia, costo_unitario=costo_unitario)
    ExistenciaLote.objects.create(lote=lote, bodega=bodega, cantidad=detalle.cantidad)
    DetalleLote.objects.create(lote=lote, detalle_movimiento=detalle, cantidad=detalle.cantidad)
    return lote


def descontar_lotes(filas, cantidad, *, detalle=None, merma=None, lote_id=None):
    candidatas = [fila for fila in filas if fila.cantidad and (lote_id is None or fila.lote_id == lote_id)]
    if sum(fila.cantidad for fila in candidatas) < cantidad:
        raise ConflictoLotes('El lote seleccionado no tiene unidades suficientes en esta bodega.')
    pendientes = cantidad
    asignaciones = []
    for fila in candidatas:
        if not pendientes:
            break
        unidades = min(pendientes, fila.cantidad)
        fila.cantidad -= unidades
        fila.save(update_fields=['cantidad', 'fecha_modificacion'])
        asignaciones.append(DetalleLote.objects.create(lote=fila.lote, cantidad=unidades,
                                                       detalle_movimiento=detalle, merma=merma))
        pendientes -= unidades
    return asignaciones


def recibir_transferencia(asignaciones, bodega, detalle):
    for asignacion in asignaciones:
        fila, _ = ExistenciaLote.objects.get_or_create(lote=asignacion.lote, bodega=bodega)
        fila.cantidad += asignacion.cantidad
        fila.save(update_fields=['cantidad', 'fecha_modificacion'])
        DetalleLote.objects.create(lote=asignacion.lote, detalle_movimiento=detalle,
                                  cantidad=asignacion.cantidad)


def datos_lote(lote):
    return {
        'lote_id': lote.pk, 'codigo': lote.codigo, 'referencia': lote.referencia,
        'fecha_recepcion': None if lote.es_saldo_inicial else timezone.localtime(lote.fecha_recepcion).isoformat(),
        'es_saldo_inicial': lote.es_saldo_inicial,
        'costo_unitario': str(lote.costo_unitario) if lote.costo_unitario is not None else None,
    }


def datos_asignaciones(asignaciones):
    return [{**datos_lote(item.lote), 'cantidad': item.cantidad,
             'costo_total': str(item.lote.costo_unitario * item.cantidad) if item.lote.costo_unitario is not None else None}
            for item in asignaciones]
