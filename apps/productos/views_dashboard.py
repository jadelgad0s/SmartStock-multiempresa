"""Resumen de inventario por bodega y alertas calculadas sobre productos activos."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from django.views.decorators.cache import never_cache
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.pagination import PageNumberPagination

from apps.core.responses import error_response, success_response
from apps.usuarios.navegacion import es_administrador, puede_acceder_admin
from apps.usuarios.permissions import EsAdministrador, EsEncargadoOAdmin
from .bodegas import datos_bodega, opciones_bodegas
from .models import Bodega, DetalleMovimiento, Producto
from .reportes import ID_MAXIMO, lectura_consistente
from .stock import AGOTADO, BAJO, anotar_stock
from .views_movimientos import datos_movimiento

ZONA = ZoneInfo('America/Santiago')
PERIODOS_DASHBOARD = ('7', '30')


class FiltrosDashboardSerializer(serializers.Serializer):
    bodega = serializers.IntegerField(min_value=1, required=False)
    dias = serializers.ChoiceField(choices=PERIODOS_DASHBOARD, default='7')
    search = serializers.CharField(max_length=200, required=False, allow_blank=True)
    estado = serializers.ChoiceField(choices=('', 'agotado', 'bajo'), default='')


class FiltrosComparacionSerializer(serializers.Serializer):
    bodega = serializers.IntegerField(min_value=1, max_value=ID_MAXIMO)
    dias = serializers.ChoiceField(choices=PERIODOS_DASHBOARD, default='30')
    sku_a = serializers.CharField(max_length=50)
    sku_b = serializers.CharField(max_length=50)

    def validate(self, datos):
        datos['sku_a'] = datos['sku_a'].upper()
        datos['sku_b'] = datos['sku_b'].upper()
        if datos['sku_a'] == datos['sku_b']:
            raise serializers.ValidationError('Elige dos productos distintos.')
        return datos


class AlertasDashboardPagination(PageNumberPagination):
    page_size = 25


def contexto_dashboard(request):
    filtros = FiltrosDashboardSerializer(data=request.query_params)
    filtros.is_valid(raise_exception=True)
    opciones = opciones_bodegas()
    datos = filtros.validated_data
    if 'bodega' in datos:
        bodega = next((b for b in opciones if b['id'] == datos['bodega']), None)
        if bodega is None:
            raise serializers.ValidationError({'bodega': 'Selecciona una bodega activa.'})
    else:
        bodega = next((b for b in opciones if b['nombre'] == 'Bodega Central'), opciones[0] if opciones else None)
    return datos, opciones, bodega


def productos_dashboard(bodega):
    """Un producto = una categoría, incluso sin fila de stock en esta bodega.

    Sumamos filas antiguas duplicadas de stock y usamos el mayor mínimo
    configurado. Las subconsultas evitan multiplicar cantidades al unir ambas
    tablas; no requieren modificar el esquema existente.
    """
    return anotar_stock(Producto.objects.filter(activo=True), bodega['id'])


def consulta_alertas(bodega, datos):
    qs = productos_dashboard(bodega)
    estado = datos.get('estado')
    qs = qs.filter(AGOTADO if estado == 'agotado' else BAJO if estado == 'bajo' else AGOTADO | BAJO)
    if datos.get('search'):
        qs = qs.filter(Q(nombre__icontains=datos['search']) | Q(sku__icontains=datos['search']))
    # Agotados primero; nombre e ID hacen estable el recorrido de las páginas.
    return qs.order_by('stock_calculado', 'nombre', 'id')


def datos_alerta(producto, bodega):
    return {
        'producto_id': producto.pk, 'producto': producto.nombre, 'sku': producto.sku,
        'stock': producto.stock_calculado, 'minimo': max(0, producto.minimo_calculado),
        'estado': 'agotado' if producto.stock_calculado <= 0 else 'bajo',
        'bodega_id': bodega['id'], 'bodega': bodega['nombre'],
    }


def permisos_dashboard(usuario):
    administrador = es_administrador(usuario)
    puede_registrar = usuario.is_superuser or bool(usuario.rol_id and usuario.rol.permisos.filter(codigo__in=('registrar_entrada', 'registrar_salida')).exists())
    return {
        'registrar_movimiento': puede_registrar,
        'auditoria': administrador, 'usuarios': administrador,
        'configuracion': puede_acceder_admin(usuario),
    }


def fechas_dashboard(ahora, dias):
    hoy = timezone.localtime(ahora, ZONA).date()
    inicio = hoy - timedelta(days=dias - 1)
    return [inicio + timedelta(days=i) for i in range(dias)]


def movimientos_por_dia(movimientos, fechas):
    # Las medianoches locales también delimitan días de 23 o 25 horas.
    return movimientos.filter(
        movimiento__fecha_creacion__gte=datetime.combine(fechas[0], time.min, tzinfo=ZONA),
        movimiento__fecha_creacion__lt=datetime.combine(fechas[-1] + timedelta(days=1), time.min, tzinfo=ZONA),
    ).annotate(dia=TruncDate('movimiento__fecha_creacion', tzinfo=ZONA))


@never_cache
@api_view(['GET'])
@permission_classes([EsAdministrador])
def resumen_dashboard(request):
    datos, bodegas, bodega = contexto_dashboard(request)
    ahora = timezone.now()
    dias = int(datos['dias'])
    fechas = fechas_dashboard(ahora, dias)
    inicio, hoy = fechas[0], fechas[-1]
    estados = {'total': 0, 'suficiente': 0, 'bajo': 0, 'agotado': 0}
    stock_total, recientes, alertas, por_fecha = 0, [], [], {}
    if bodega:
        resumen = productos_dashboard(bodega).aggregate(
            stock=Sum('stock_calculado'), total=Count('pk'),
            agotado=Count('pk', filter=AGOTADO), bajo=Count('pk', filter=BAJO),
        )
        stock_total = resumen['stock'] or 0
        estados.update({k: resumen[k] for k in ('total', 'agotado', 'bajo')})
        estados['suficiente'] = estados['total'] - estados['agotado'] - estados['bajo']
        movimientos = DetalleMovimiento.objects.filter(movimiento__bodega_id=bodega['id'])
        serie = movimientos_por_dia(movimientos, fechas).values('dia').annotate(
            entradas=Sum('cantidad', filter=Q(movimiento__tipo__operacion='+')),
            salidas=Sum('cantidad', filter=Q(movimiento__tipo__operacion='-')),
        ).order_by('dia')
        por_fecha = {item['dia']: item for item in serie}
        ultimos = movimientos.select_related('movimiento__tipo', 'movimiento__usuario', 'movimiento__bodega', 'producto').order_by('-movimiento__fecha_creacion', '-id')[:5]
        for detalle in ultimos:
            item = datos_movimiento(detalle)
            item['id_trx'] = f"#TRX-{detalle.movimiento_id}"  # Compatibilidad del resumen anterior.
            item['iniciales'] = ''.join(n[0] for n in item['usuario'].split())[:2].upper() or 'U'
            recientes.append(item)
        alertas = [datos_alerta(p, bodega) for p in consulta_alertas(bodega, {})[:5]]
    entradas = [por_fecha.get(fecha, {}).get('entradas') or 0 for fecha in fechas]
    salidas = [por_fecha.get(fecha, {}).get('salidas') or 0 for fecha in fechas]
    return success_response(data={
        'bodega': bodega, 'bodegas': bodegas, 'dias': dias,
        'actualizado': timezone.localtime(ahora, ZONA).isoformat(), 'zona_horaria': str(ZONA),
        'desde': inicio.isoformat(), 'hasta': hoy.isoformat(),
        'kpi_stock': stock_total, 'kpi_entradas': entradas[-1], 'kpi_salidas': salidas[-1],
        'kpi_alertas': estados['agotado'], 'kpi_bajo': estados['bajo'],
        'estado_inventario': estados, 'recientes': recientes, 'alertas': alertas,
        'chart_labels': [fecha.strftime('%d/%m') if fecha != hoy else 'Hoy' for fecha in fechas],
        'chart_fechas': [fecha.isoformat() for fecha in fechas],
        'chart_entradas': entradas, 'chart_salidas': salidas,
        'permisos': permisos_dashboard(request.user),
    })


@never_cache
@api_view(['GET'])
@permission_classes([EsAdministrador])
def comparar_productos_dashboard(request):
    filtros = FiltrosComparacionSerializer(data=request.query_params)
    filtros.is_valid(raise_exception=True)
    datos = filtros.validated_data
    skus = (datos['sku_a'], datos['sku_b'])
    dias = int(datos['dias'])
    fechas = fechas_dashboard(timezone.now(), dias)

    with lectura_consistente():
        bodega = Bodega.objects.filter(pk=datos['bodega'], activa=True).first()
        if bodega is None:
            return error_response('Selecciona una bodega activa.')

        candidatos = Producto.objects.filter(Q(sku__iexact=skus[0]) | Q(sku__iexact=skus[1]))
        filas = list(anotar_stock(candidatos, bodega.pk).values('id', 'sku', 'nombre', 'activo', 'stock_calculado'))
        por_sku = {fila['sku'].upper(): fila for fila in filas}
        if len(por_sku) != len(filas):
            return error_response('Un SKU coincide con más de un producto. Revisa el catálogo.')
        for sku in skus:
            if sku not in por_sku:
                return error_response(f'No se encontró el SKU {sku}. Escribe el SKU completo o elígelo en las sugerencias.')

        salidas = DetalleMovimiento.objects.filter(
            producto_id__in=[fila['id'] for fila in filas],
            movimiento__bodega=bodega,
            movimiento__tipo__nombre__iexact='SALIDA',
            movimiento__tipo__operacion='-',
        )
        agrupadas = movimientos_por_dia(salidas, fechas).values('producto_id', 'dia').annotate(unidades=Sum('cantidad'))
        unidades_por_dia = {(fila['producto_id'], fila['dia']): fila['unidades'] for fila in agrupadas}
        productos = []
        for sku in skus:
            producto = por_sku[sku]
            serie = [unidades_por_dia.get((producto['id'], dia), 0) for dia in fechas]
            productos.append({
                'sku': producto['sku'], 'nombre': producto['nombre'], 'activo': producto['activo'],
                'salidas': serie, 'total_salidas': sum(serie), 'stock_actual': producto['stock_calculado'],
            })

        return success_response(data={
            'bodega': datos_bodega(bodega), 'dias': dias, 'zona_horaria': str(ZONA),
            'fechas': [dia.isoformat() for dia in fechas], 'productos': productos,
        })


@never_cache
@api_view(['GET'])
@permission_classes([EsAdministrador])
def alertas_dashboard(request):
    datos, _, bodega = contexto_dashboard(request)
    if bodega is None:
        return error_response('No hay bodegas activas para consultar.')
    paginador = AlertasDashboardPagination()
    pagina = paginador.paginate_queryset(consulta_alertas(bodega, datos), request)
    respuesta = paginador.get_paginated_response([datos_alerta(p, bodega) for p in pagina])
    respuesta.data['bodega'] = bodega
    return respuesta


@never_cache
@api_view(['GET'])
@permission_classes([EsEncargadoOAdmin])
def inicio_bodega(request):
    _, bodegas, bodega = contexto_dashboard(request)
    conteos = {'bajo': 0, 'agotado': 0}
    alertas = []
    if bodega:
        conteos = productos_dashboard(bodega).aggregate(
            bajo=Count('pk', filter=BAJO),
            agotado=Count('pk', filter=AGOTADO),
        )
        alertas = [datos_alerta(producto, bodega) for producto in consulta_alertas(bodega, {})[:8]]
    return success_response(data={
        'bodegas': bodegas, 'bodega': bodega, 'conteos': conteos, 'alertas': alertas,
    })
