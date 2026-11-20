"""Atención de consultas: permisos exclusivos, sin acceso a las bases de empresas."""
from datetime import timedelta
from uuid import UUID

from django.contrib.auth import update_session_auth_hash
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.usuarios.models import Usuario
from .buzon_contacto import enviar_respuesta, sincronizar_buzon
from .forms import CuentaContactoForm
from .forms_contacto import BorradorForm, NotaForm, SeguimientoForm
from .models import BuzonContacto, MensajeContacto, NotaContacto, RespuestaContacto
from .notificaciones import confirmar_guardado, confirmaciones_para_pagina
from .permisos import CORREO_CONTACTO, requiere_contacto, requiere_superusuario
from .sistema import auditar_gestion, contexto_sistema
from .zoho_contacto import ClienteZoho, ErrorZoho, servidores, zoho_configurado


VISTAS = [('todos', 'Bandeja de entrada', 'inbox'), ('sin-leer', 'Sin leer', 'envelope'),
          ('pendiente', 'Pendientes', 'clock'), ('seguimiento', 'En seguimiento', 'comments'),
          ('resuelto', 'Resueltos', 'check'), ('borradores', 'Borradores', 'pen-to-square')]


def contexto_contacto(request, titulo, vista='todos'):
    contexto = {
        'titulo': titulo, 'modulo': 'mi_cuenta' if vista == 'mi_cuenta' else vista,
        'identidad_panel': 'Atención de SmartStock', 'perfil_personal': 'Contacto',
        'inicio_panel': reverse('contacto_bandeja'), 'perfil_panel': reverse('contacto_mi_cuenta'),
        'confirmaciones': confirmaciones_para_pagina(request),
        'zoho_configurado': zoho_configurado(),
        'secciones_menu': [{'nombre': 'Atención', 'enlaces': [
            {'nombre': nombre, 'icono': icono, 'activo': clave == vista,
             'url': reverse('contacto_bandeja') + (f'?vista={clave}' if clave != 'todos' else '')}
            for clave, nombre, icono in VISTAS]}],
    }
    try:
        contexto['zoho_url'] = servidores()[1] + '/'
    except ErrorZoho:
        contexto['zoho_url'] = 'https://mail.zoho.com/'
    return contexto


@requiere_superusuario
@require_http_methods(['GET', 'POST'])
def cuenta_contacto(request):
    cuentas = Usuario.objects.using('central').filter(email__iexact=CORREO_CONTACTO)
    contexto = contexto_sistema(request, 'contacto', 'Cuenta de contacto')
    if cuentas.count() > 1:
        contexto['error_consulta'] = 'Hay variantes del correo de contacto en la central. Unifica esas cuentas antes de habilitar el acceso.'
        return render(request, 'contacto/cuenta.html', contexto)
    return formulario_contacto(request, cuentas.first() or Usuario(), propia=False, contexto=contexto)


@requiere_contacto
@require_http_methods(['GET', 'POST'])
def mi_cuenta_contacto(request):
    return formulario_contacto(request, request.user, propia=True,
                               contexto=contexto_contacto(request, 'Mi cuenta', 'mi_cuenta'))


def formulario_contacto(request, cuenta, *, propia, contexto):
    nueva = cuenta._state.adding
    formulario = CuentaContactoForm(request.POST or None, instance=cuenta, propia=propia)
    destino = reverse('contacto_mi_cuenta' if propia else 'sistema_cuenta_contacto')
    if request.method == 'POST' and formulario.is_valid():
        try:
            with transaction.atomic(using='central'):
                guardada = formulario.save()
                auditar_gestion(request, 'central', 'CREATE' if nueva else 'UPDATE', 'Usuario', guardada,
                                'Cuenta exclusiva de contacto actualizada')
        except IntegrityError:
            formulario.add_error(None, 'La cuenta de contacto ya existe. Recarga esta página para editarla.')
        else:
            if propia:
                update_session_auth_hash(request, guardada)
            confirmar_guardado(request, alias='central', titulo='Cuenta de contacto guardada',
                               mensaje='Los datos de la cuenta de contacto se guardaron correctamente.', link=destino)
            return redirect(destino)
    contexto.update(formulario=formulario, propia=propia,
                    zoho_configurado=zoho_configurado(),
                    volver=reverse('contacto_bandeja' if propia else 'sistema_cuentas'))
    return render(request, 'contacto/cuenta.html', contexto)


@requiere_contacto
@require_GET
def bandeja(request):
    vista = request.GET.get('vista', 'todos')
    if vista not in dict((clave, nombre) for clave, nombre, _ in VISTAS):
        vista = 'todos'
    contexto = contexto_contacto(request, dict((c, n) for c, n, _ in VISTAS)[vista], vista)
    todos = MensajeContacto.objects.using('central').all()
    consulta = todos
    if vista in ('pendiente', 'seguimiento', 'resuelto'):
        consulta = consulta.filter(estado=vista)
    elif vista == 'sin-leer':
        consulta = consulta.filter(leido=False)
    elif vista == 'borradores':
        consulta = consulta.filter(respuestas__estado='borrador')
    texto = request.GET.get('search', '').strip()[:200]
    if texto:
        consulta = consulta.filter(Q(asunto__icontains=texto) | Q(remitente_email__icontains=texto)
                                   | Q(remitente_nombre__icontains=texto) | Q(resumen__icontains=texto))
    hoy = timezone.localdate()
    if request.GET.get('vencidos') == '1':
        consulta = consulta.exclude(estado='resuelto').filter(seguimiento__lte=hoy)
    filtros = request.GET.copy()
    filtros.pop('page', None)
    contexto.update(
        pagina=Paginator(consulta, 25).get_page(request.GET.get('page')), filtros_pagina=filtros.urlencode(),
        vista=vista, busqueda=texto, hoy=hoy, buzon=BuzonContacto.objects.using('central').filter(pk=1).first(),
        kpis=[('Sin leer', todos.filter(leido=False).count(), 'sin-leer'),
              ('Pendientes', todos.filter(estado='pendiente').count(), 'pendiente'),
              ('En seguimiento', todos.filter(estado='seguimiento').count(), 'seguimiento'),
              ('Seguimientos para hoy', todos.exclude(estado='resuelto').filter(seguimiento__lte=hoy).count(), 'vencidos')],
    )
    return render(request, 'contacto/bandeja.html', contexto)


@requiere_contacto
@require_POST
def sincronizar(request):
    try:
        nuevos = sincronizar_buzon(anteriores=request.POST.get('anteriores') == '1')
    except ErrorZoho as error:
        if request.headers.get('Accept') == 'application/json':
            return JsonResponse({'success': False, 'mensaje': str(error)}, status=503)
        contexto = contexto_contacto(request, 'No pudimos actualizar la bandeja')
        contexto['error_consulta'] = str(error)
        return render(request, 'contacto/error.html', contexto, status=503)
    if request.headers.get('Accept') == 'application/json':
        return JsonResponse({'success': True, 'nuevos': nuevos})
    confirmar_guardado(request, alias='central', titulo='Bandeja consultada',
                       mensaje=f'{nuevos} correo(s) incorporado(s).', link=reverse('contacto_bandeja'))
    return redirect('contacto_bandeja')


def confirmar_accion(request, mensaje, titulo, texto):
    auditar_gestion(request, 'central', 'UPDATE', 'MensajeContacto', mensaje, titulo)
    confirmar_guardado(request, alias='central', titulo=titulo, mensaje=texto,
                       link=reverse('contacto_mensaje', args=[mensaje.pk]))
    return redirect('contacto_mensaje', mensaje_id=mensaje.pk)


def guardar_borrador(mensaje, formulario):
    datos = formulario.cleaned_data
    with transaction.atomic(using='central'):
        MensajeContacto.objects.using('central').select_for_update().get(pk=mensaje.pk)
        if mensaje.respuestas.filter(estado__in=('enviando', 'incierta')).exists():
            raise ErrorZoho('Hay un envío sin confirmar. Revísalo en Zoho antes de preparar otra respuesta.')
        if datos['borrador']:
            actualizado = RespuestaContacto.objects.using('central').filter(
                pk=datos['borrador'], mensaje=mensaje, estado='borrador', version=datos['version']).update(
                texto=datos['texto'], version=F('version') + 1)
            if not actualizado:
                raise ErrorZoho('El borrador cambió en otra pestaña. Recarga para no sobrescribirlo.')
        else:
            try:
                with transaction.atomic(using='central'):
                    RespuestaContacto.objects.using('central').create(mensaje=mensaje, texto=datos['texto'])
            except IntegrityError:
                raise ErrorZoho('Ya hay un borrador para este correo. Recarga para revisarlo.') from None


@requiere_contacto
@require_http_methods(['GET', 'POST'])
def detalle_mensaje(request, mensaje_id):
    mensaje = get_object_or_404(MensajeContacto.objects.using('central'), pk=mensaje_id)
    error = ''
    seguimiento = SeguimientoForm(instance=mensaje)
    nota = NotaForm()
    borrador = mensaje.respuestas.filter(estado='borrador').first()
    respuesta_form = BorradorForm(initial={
        'texto': borrador.texto if borrador else '', 'version': borrador.version if borrador else 0,
        'borrador': borrador.pk if borrador else None})
    if request.method == 'POST':
        accion = request.POST.get('accion')
        try:
            if accion == 'seguimiento':
                seguimiento = SeguimientoForm(request.POST, instance=mensaje)
                if seguimiento.is_valid():
                    datos = seguimiento.cleaned_data
                    if not MensajeContacto.objects.using('central').filter(pk=mensaje.pk, version=datos['version']).update(
                            estado=datos['estado'], categoria=datos['categoria'], seguimiento=datos['seguimiento'], version=F('version') + 1):
                        raise ErrorZoho('El seguimiento cambió en otra pestaña. Recarga antes de guardar.')
                    return confirmar_accion(request, mensaje, 'Seguimiento actualizado', 'La consulta quedó actualizada.')
            elif accion == 'nota':
                nota = NotaForm(request.POST)
                if nota.is_valid():
                    NotaContacto.objects.using('central').create(mensaje=mensaje, texto=nota.cleaned_data['texto'])
                    return confirmar_accion(request, mensaje, 'Nota guardada', 'La nota interna quedó registrada.')
            elif accion == 'borrador':
                respuesta_form = BorradorForm(request.POST)
                if respuesta_form.is_valid():
                    guardar_borrador(mensaje, respuesta_form)
                    return confirmar_accion(request, mensaje, 'Borrador guardado', 'Revisa la respuesta antes de enviarla.')
            elif accion in ('enviar', 'confirmar_enviada', 'confirmar_no_enviada'):
                try:
                    identificador = UUID(request.POST.get('respuesta', ''))
                    version = int(request.POST.get('version', ''))
                except (ValueError, TypeError):
                    raise ErrorZoho('La respuesta no es válida. Recarga el correo.') from None
                respuesta = get_object_or_404(RespuestaContacto.objects.using('central').select_related('mensaje'),
                                              pk=identificador, mensaje=mensaje)
                if accion == 'enviar':
                    enviar_respuesta(respuesta, version)
                    return confirmar_accion(request, mensaje, 'Respuesta enviada', 'Zoho confirmó el envío de tu respuesta.')
                posibles = RespuestaContacto.objects.using('central').filter(pk=respuesta.pk, version=version).filter(
                    Q(estado='incierta') | Q(estado='enviando', iniciado_en__lt=timezone.now() - timedelta(minutes=3)))
                if not posibles.update(estado='enviada' if accion == 'confirmar_enviada' else 'rechazada',
                                       enviada_en=timezone.now() if accion == 'confirmar_enviada' else None, version=F('version') + 1):
                    raise ErrorZoho('El envío no está pendiente de revisión o todavía está en curso.')
                return confirmar_accion(request, mensaje, 'Envío revisado', 'Se registró el resultado que comprobaste en Zoho.')
            elif accion == 'no_leido':
                MensajeContacto.objects.using('central').filter(pk=mensaje.pk).update(leido=False)
                return redirect('contacto_bandeja')
            else:
                raise ErrorZoho('La acción solicitada no es válida.')
        except ErrorZoho as fallo:
            error = str(fallo)
    if not mensaje.contenido_cargado and zoho_configurado():
        try:
            contenido = ClienteZoho().contenido(mensaje)
            MensajeContacto.objects.using('central').filter(pk=mensaje.pk).update(contenido=contenido, contenido_cargado=True)
        except ErrorZoho as fallo:
            error = error or str(fallo)
    if request.method == 'GET':
        MensajeContacto.objects.using('central').filter(pk=mensaje.pk).update(leido=True)
    mensaje.refresh_from_db(using='central')
    contexto = contexto_contacto(request, mensaje.asunto or 'Sin asunto')
    contexto.update(mensaje=mensaje, seguimiento_form=seguimiento, nota_form=nota, respuesta_form=respuesta_form,
                    respuestas=list(mensaje.respuestas.all()), borrador=mensaje.respuestas.filter(estado='borrador').first(),
                    notas=list(mensaje.notas.all()), error_consulta=error,
                    sin_confirmar=mensaje.respuestas.filter(estado__in=('enviando', 'incierta')).exists(),
                    corte_revision=timezone.now() - timedelta(minutes=3))
    return render(request, 'contacto/mensaje.html', contexto)
