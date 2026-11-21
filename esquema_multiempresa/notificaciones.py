"""Confirmación de guardados y campana privada de cada cuenta del equipo."""
import json
from functools import wraps
from uuid import uuid4

from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .models import NotificacionSistema
from .permisos import es_cuenta_interna


def confirmar_guardado(request, *, alias, titulo, mensaje, link, empresa=None):
    identificador = uuid4()
    # El commit de una empresa ocurre en su propia base. El aviso se crea
    # después, en la central y sin una FK hacia un usuario de ese cliente.
    transaction.on_commit(lambda: NotificacionSistema.objects.using('central').create(
        id=identificador, destinatario_id=request.user.pk, titulo=titulo, mensaje=mensaje,
        empresa_nombre=empresa.nombre if empresa else '', link=link,
    ), using=alias, robust=True)
    # Esta confirmación sigue disponible si falla el historial de avisos
    # después del commit. No se presenta un guardado confirmado como fallido.
    messages.success(request, json.dumps({
        'id': str(identificador), 'titulo': titulo, 'mensaje': mensaje,
    }, ensure_ascii=False), extra_tags='ss-confirmacion')


def confirmaciones_para_pagina(request):
    confirmaciones = []
    for mensaje in messages.get_messages(request):
        if 'ss-confirmacion' in mensaje.extra_tags.split():
            confirmaciones.append(json.loads(str(mensaje)))
        else:
            confirmaciones.append({'id': str(uuid4()), 'titulo': 'SmartStock', 'mensaje': str(mensaje)})
    return confirmaciones


def respuesta(data=None, mensaje='', status=200):
    return JsonResponse({'success': status < 400, 'data': data, 'mensaje': mensaje}, status=status)


def solo_personal(vista):
    @never_cache
    @wraps(vista)
    def protegida(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return respuesta(mensaje='Inicia sesión para consultar tus notificaciones.', status=401)
        if not es_cuenta_interna(request.user):
            return respuesta(mensaje='Esta cuenta no tiene acceso al panel de SmartStock.', status=403)
        return vista(request, *args, **kwargs)
    return protegida


@solo_personal
@require_GET
def listar_notificaciones(request):
    corte = timezone.now()
    propias = NotificacionSistema.objects.using('central').filter(destinatario_id=request.user.pk, fecha_creacion__lte=corte)
    pendientes = propias.filter(leida=False)
    consulta = propias if request.GET.get('historial') == '1' else pendientes
    items = [{
        'id': str(aviso.pk), 'titulo': aviso.titulo, 'mensaje': aviso.mensaje,
        'empresa': aviso.empresa_nombre, 'link': aviso.link, 'leida': aviso.leida,
        'fecha': timezone.localtime(aviso.fecha_creacion).strftime('%d/%m/%Y %H:%M'),
    } for aviso in consulta[:20]]
    return respuesta({'usuario_id': request.user.pk, 'total': pendientes.count(), 'items': items, 'hasta': corte.isoformat()})


@solo_personal
@require_POST
def leer_notificacion(request, identificador):
    propias = NotificacionSistema.objects.using('central').filter(pk=identificador, destinatario_id=request.user.pk)
    if not propias.exists():
        return respuesta(mensaje='No se encontró la notificación.', status=404)
    return respuesta({'actualizadas': propias.filter(leida=False).update(leida=True)})


@solo_personal
@require_POST
def leer_todas(request):
    try:
        datos = json.loads(request.body or '{}') if request.content_type == 'application/json' else request.POST
        valor = datos.get('hasta')
        if valor is not None and (not isinstance(valor, str) or not valor):
            raise ValueError
        corte = parse_datetime(valor) if valor is not None else timezone.now()
        if corte is None or timezone.is_naive(corte):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        return respuesta(mensaje='No se pudo validar la selección de notificaciones. Vuelve a abrir la campana.', status=400)
    cantidad = NotificacionSistema.objects.using('central').filter(
        destinatario_id=request.user.pk, leida=False, fecha_creacion__lte=corte,
    ).update(leida=True)
    return respuesta({'actualizadas': cantidad})
