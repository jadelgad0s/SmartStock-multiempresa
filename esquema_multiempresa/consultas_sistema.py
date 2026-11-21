"""Consultas del inventario desde una cuenta central, con empresa explícita."""
from types import SimpleNamespace
from urllib.parse import urlencode

from django.db import DatabaseError
from django.db.models import Q
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET
from rest_framework.exceptions import ValidationError

from apps.core.empresa import usar_empresa
from apps.productos.models import Bodega, DetalleTransferencia, EnvioAlertaSMS, Producto
from apps.productos.reportes import PlanReporte, filtrar_fechas, lectura_consistente
from apps.productos.stock import anotar_stock
from apps.productos.views_dashboard import datos_resumen_dashboard
from apps.productos.views_reportes import archivo_reporte, documento_reporte
from .forms import ConsultaInventarioForm
from .permisos import es_administrador_plataforma, requiere_personal
from .sistema import contexto_sistema, paginar, parametros_consulta
from .autorizacion_soporte import acceso_para, alcances_actuales, empresa_para_consulta, parametros_atencion, auditar_soporte


TITULOS = {'catalogo': 'Catálogo', 'bodegas': 'Bodegas', 'movimientos': 'Movimientos',
           'transferencias': 'Transferencias', 'mermas': 'Mermas y bajas', 'reportes': 'Reportes de inventario', 'sms': 'Alertas SMS'}


@requiere_personal
@require_GET
def inventario_sistema(request):
    empresa = empresa_para_consulta(request, 'inventario')
    contexto = contexto_sistema(request, 'inventario', 'Resumen de inventario', empresa)
    if empresa is not None:
        try:
            with usar_empresa(empresa), lectura_consistente():
                contexto['dashboard'] = datos_resumen_dashboard(SimpleNamespace(query_params=request.GET, user=request.user))
                dashboard = contexto['dashboard']
                contexto['hay_movimientos_periodo'] = any(dashboard['chart_entradas']) or any(dashboard['chart_salidas'])
        except ValidationError:
            contexto['error_consulta'] = 'Selecciona una bodega activa y un período de 7 o 30 días.'
        except DatabaseError:
            contexto['error_consulta'] = 'No pudimos consultar el inventario de esta empresa. Vuelve a intentarlo.'
    return render(request, 'sistema/inventario.html', contexto)


def tabla_catalogo(request, contexto, datos):
    consulta = Producto.objects.all()
    if datos.get('search'):
        consulta = consulta.filter(Q(sku__icontains=datos['search']) | Q(nombre__icontains=datos['search']))
    bodega = datos.get('bodega')
    consulta = anotar_stock(consulta, bodega.pk if bodega else None).order_by('nombre', 'id')
    contexto['columnas'] = ['SKU', 'Producto', 'Stock actual', 'Estado']
    empresa = contexto['empresa_seleccionada']
    contexto['filas'] = [{
        'celdas': [producto.sku, producto.nombre, producto.stock_calculado, 'Activo' if producto.activo else 'Inactivo'],
        'url': reverse('sistema_reportes') + '?' + urlencode({
            'empresa': empresa.codigo, 'informe': 'kardex', 'producto': producto.pk, **parametros_atencion(request),
            **({'bodega': bodega.pk} if bodega else {}),
        }), 'accion': 'Ver historial',
    } for producto in paginar(request, contexto, consulta)]
    if 'reportes' not in alcances_actuales(request):
        for fila in contexto['filas']:
            fila.pop('url', None)


def tabla_bodegas(request, contexto, datos):
    consulta = Bodega.objects.all()
    if datos.get('search'):
        consulta = consulta.filter(Q(nombre__icontains=datos['search']) | Q(direccion__icontains=datos['search']))
    contexto['columnas'] = ['Bodega', 'Dirección', 'Estado']
    contexto['filas'] = [{'celdas': [bodega.nombre, bodega.direccion, 'Activa' if bodega.activa else 'Inactiva']}
                         for bodega in paginar(request, contexto, consulta.order_by('nombre', 'id'))]


def tabla_transferencias(request, contexto, datos):
    consulta = DetalleTransferencia.objects.select_related(
        'producto', 'transferencia__bodega_origen', 'transferencia__bodega_destino', 'transferencia__usuario',
    )
    if datos.get('search'):
        consulta = consulta.filter(Q(producto__nombre__icontains=datos['search']) | Q(producto__sku__icontains=datos['search']))
    if datos.get('bodega'):
        consulta = consulta.filter(Q(transferencia__bodega_origen=datos['bodega']) | Q(transferencia__bodega_destino=datos['bodega']))
    consulta = filtrar_fechas(consulta, datos, 'transferencia__fecha_creacion').order_by('-transferencia__fecha_creacion', '-id')
    contexto['columnas'] = ['Fecha / hora', 'SKU', 'Producto', 'Origen', 'Destino', 'Unidades', 'Estado', 'Responsable']
    contexto['filas'] = [{'celdas': [
        timezone.localtime(detalle.transferencia.fecha_creacion).strftime('%d/%m/%Y %H:%M'),
        detalle.producto.sku, detalle.producto.nombre, detalle.transferencia.bodega_origen.nombre,
        detalle.transferencia.bodega_destino.nombre, detalle.cantidad,
        detalle.transferencia.get_estado_display(), detalle.transferencia.usuario.nombre_completo,
    ]} for detalle in paginar(request, contexto, consulta)]


def tabla_reporte(request, contexto, parametros):
    with lectura_consistente():
        plan = PlanReporte(parametros)
        pagina = list(paginar(request, contexto, plan.qs))
        contexto['meta_reporte'] = plan.metadatos()
        contexto['columnas'] = [columna['etiqueta'] for columna in plan.columnas]
        contexto['filas'] = [{'celdas': [fila[columna['campo']] for columna in plan.columnas]}
                             for fila in plan.filas(pagina, pagina=True)]


def tabla_sms(request, contexto, datos):
    consulta = EnvioAlertaSMS.objects.all()
    if datos.get('search'):
        consulta = consulta.filter(Q(sku__icontains=datos['search']) | Q(producto_nombre__icontains=datos['search']))
    if datos.get('bodega'):
        consulta = consulta.filter(bodega=datos['bodega'])
    consulta = filtrar_fechas(consulta, datos, 'fecha_creacion').order_by('-fecha_creacion', '-id')
    contexto['columnas'] = ['Fecha / hora', 'SKU', 'Producto', 'Bodega', 'Destinatario', 'Estado', 'Intentos']
    contexto['filas'] = [{'celdas': [
        timezone.localtime(envio.fecha_creacion).strftime('%d/%m/%Y %H:%M'), envio.sku,
        envio.producto_nombre, envio.bodega_nombre, '••••' + envio.destinatario[-4:], envio.get_estado_display(), envio.intentos,
    ]} for envio in paginar(request, contexto, consulta)]


@requiere_personal
@require_GET
def consulta_sistema(request, modulo):
    empresa = empresa_para_consulta(request, modulo)
    if request.GET.get('exportar'):
        if modulo != 'reportes' or not empresa or request.GET['exportar'] not in ('csv', 'pdf'):
            raise PermissionDenied
        acceso_para(request, empresa, 'exportar')
    contexto = contexto_sistema(request, modulo, TITULOS[modulo], empresa)
    if empresa is not None:
        try:
            with usar_empresa(empresa):
                parametros = parametros_consulta(request)
                if modulo in ('movimientos', 'mermas'):
                    parametros['informe'] = modulo
                elif modulo == 'reportes':
                    parametros.setdefault('informe', 'existencias')
                if modulo == 'reportes' and not parametros.get('bodega'):
                    primera = Bodega.objects.filter(activa=True).order_by('nombre', 'id').first()
                    if primera:
                        parametros['bodega'] = str(primera.pk)
                formulario = ConsultaInventarioForm(parametros, alias=empresa.alias_bd, reporte=modulo == 'reportes')
                if modulo in ('catalogo', 'bodegas'):
                    del formulario.fields['desde']
                    del formulario.fields['hasta']
                if modulo == 'bodegas':
                    del formulario.fields['bodega']
                contexto['formulario_consulta'] = formulario
                if formulario.is_valid():
                    if modulo == 'reportes' and request.GET.get('exportar') in ('csv', 'pdf'):
                        auditar_soporte(request, request._atencion_soporte, 'CONSULTA',
                            f'Exportación {request.GET["exportar"]}; reporte {parametros.get("informe")}')
                        exportador = archivo_reporte if request.GET['exportar'] == 'csv' else documento_reporte
                        return exportador(parametros, request.user.email, empresa.nombre)
                    consultas = {'catalogo': tabla_catalogo, 'bodegas': tabla_bodegas,
                                 'transferencias': tabla_transferencias, 'sms': tabla_sms}
                    if modulo in consultas:
                        consultas[modulo](request, contexto, formulario.cleaned_data)
                    else:
                        tabla_reporte(request, contexto, parametros)
                    contexto['hay_acciones'] = any(fila.get('url') for fila in contexto.get('filas', []))
        except ValidationError as error:
            detalles = error.detail.values() if isinstance(error.detail, dict) else error.detail
            contexto['error_consulta'] = ' '.join(
                ' '.join(str(mensaje) for mensaje in detalle) if isinstance(detalle, list) else str(detalle)
                for detalle in detalles
            )
        except DatabaseError:
            contexto.pop('formulario_consulta', None)
            contexto['error_consulta'] = 'No pudimos consultar esta empresa. Vuelve a intentarlo.'
    return render(request, 'sistema/consulta.html', contexto)
