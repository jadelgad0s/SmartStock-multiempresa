"""Consulta paginada de lotes dentro de la empresa autenticada."""
from rest_framework import serializers
from rest_framework.pagination import PageNumberPagination

from .fifo import datos_lote, existencias_fifo


class FiltrosLotesSerializer(serializers.Serializer):
    bodega = serializers.IntegerField(min_value=1, required=False)
    incluir_agotados = serializers.BooleanField(default=False)


def consultar_lotes(producto_id, request):
    filtros = FiltrosLotesSerializer(data=request.query_params)
    filtros.is_valid(raise_exception=True)
    datos = filtros.validated_data
    qs = existencias_fifo(producto_id, datos.get('bodega')).select_related('bodega')
    if not datos['incluir_agotados']:
        qs = qs.filter(cantidad__gt=0)
    paginador = PageNumberPagination()
    paginador.page_size = 25
    pagina = paginador.paginate_queryset(qs, request)
    return paginador.get_paginated_response([
        {**datos_lote(fila.lote), 'cantidad': fila.cantidad,
         'bodega_id': fila.bodega_id, 'bodega': fila.bodega.nombre} for fila in pagina
    ])
