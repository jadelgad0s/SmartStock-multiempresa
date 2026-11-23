"""Atención de consultas: permisos exclusivos, sin acceso a las bases de empresas."""
from datetime import timedelta
from uuid import UUID

from django.contrib.auth import update_session_auth_hash
from django.conf import settings
from django.core.paginator import Paginator
from django.db import IntegrityError, connections, transaction
from django.db.models import Count, F, Max, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables

from apps.usuarios.models import Usuario
from apps.core.registro_auditoria import crear_evento, diferencias, estado_auditable
from .buzon_contacto import enviar_respuesta, sincronizar_buzon
from .forms import CuentaContactoForm
from .forms_contacto import BorradorForm, ConexionZohoForm, NotaForm, SeguimientoForm
from .models import BuzonContacto, MensajeContacto, NotaContacto, RespuestaContacto
from .notificaciones import confirmar_guardado, confirmaciones_para_pagina
from .permisos import CORREO_CONTACTO, requiere_contacto, requiere_superusuario
from .sistema import auditar_gestion, contexto_sistema
from .zoho_contacto import ClienteZoho, ErrorZoho, autorizar_codigo, cifrar_configuracion, servidores, zoho_configurado


VISTAS = [('todos', 'Bandeja de entrada', 'inbox'), ('sin-leer', 'Sin leer', 'envelope'),
          ('pendiente', 'Pendientes', 'clock'), ('seguimiento', 'En seguimiento', 'comments'),
          ('resuelto', 'Resueltos', 'check'), ('borradores', 'Borradores', 'pen-to-square'),
          ('enviados', 'Enviados', 'paper-plane')]


def datos_bandeja():
    hoy = timezone.localdate()
    datos = MensajeContacto.objects.using('central').aggregate(
        todos=Count('pk'), ultimo_id=Max('pk'),
        sin_leer=Count('pk', filter=Q(leido=False)), pendiente=Count('pk', filter=Q(estado='pendiente')),
        en_seguimiento=Count('pk', filter=Q(estado='seguimiento')), resuelto=Count('pk', filter=Q(estado='resuelto')),
        vencidos=Count('pk', filter=~Q(estado='resuelto') & Q(seguimiento__lte=hoy)))
    datos['sin-leer'] = datos.pop('sin_leer')
    datos['seguimiento'] = datos.pop('en_seguimiento')
    datos.update(RespuestaContacto.objects.using('central').aggregate(
        borradores=Count('pk', filter=Q(estado='borrador')),
        enviados=Count('pk', filter=Q(estado='enviada'))))
    return datos


def contexto_contacto(request, titulo, vista='todos'):
    buzon = BuzonContacto.objects.using('central').filter(pk=1).first()
    datos = datos_bandeja()
    conocidos = bool(datos['todos'] or buzon and buzon.ultima_consulta)
    contexto = {
        'titulo': titulo, 'modulo': 'mi_cuenta' if vista == 'mi_cuenta' else vista,
        'identidad_panel': 'Atención de SmartStock', 'perfil_personal': 'Contacto',
        'inicio_panel': reverse('contacto_bandeja'), 'perfil_panel': reverse('contacto_mi_cuenta'),
        'confirmaciones': confirmaciones_para_pagina(request),
        'zoho_configurado': zoho_configurado(buzon=buzon),
        'buzon': buzon, 'datos_disponibles': conocidos, 'contadores': datos,
        'secciones_menu': [{'nombre': 'Atención', 'enlaces': [
            {'nombre': nombre, 'icono': icono, 'activo': clave == vista,
             'mostrar_contador': True, 'contador': datos[clave] if conocidos else None,
             'url': reverse('contacto_bandeja') + (f'?vista={clave}' if clave != 'todos' else '')}
            for clave, nombre, icono in VISTAS]}],
    }
    try:
        contexto['zoho_url'] = servidores(buzon=buzon)[1] + '/'
    except ErrorZoho:
        contexto['zoho_url'] = 'https://mail.zoho.com/'
    return contexto


@requiere_superusuario
@require_http_methods(['GET', 'POST'])
@sensitive_post_parameters('client_secret', 'codigo')
@sensitive_variables()
def conexion_contacto(request):
    accion = request.POST.get('accion') if request.method == 'POST' else None
    formulario = ConexionZohoForm(request.POST if accion == 'conectar' else None, initial={'centro': settings.ZOHO_CONTACTO_DC})
    error_conexion = ''
    if request.method == 'POST':
        try:
            if accion == 'conectar' and formulario.is_valid():
                config, cliente = autorizar_codigo(**formulario.cleaned_data)
                with transaction.atomic(using='central'):
                    buzon, _ = BuzonContacto.objects.using('central').get_or_create(pk=1)
                    if buzon.cuenta_zoho and buzon.cuenta_zoho != cliente.cuenta:
                        raise ErrorZoho('El buzón de Zoho cambió de identificación. Revisa la migración de sus correos antes de reemplazarlo.')
                    buzon.credenciales_cifradas = cifrar_configuracion(config)
                    buzon.save(using='central', update_fields=['credenciales_cifradas'])
                nuevos = sincronizar_buzon(forzar=True, cliente=cliente)
            elif accion == 'comprobar':
                nuevos = sincronizar_buzon(forzar=True)
            else:
                nuevos = None
            if nuevos is not None:
                auditar_gestion(request, 'central', 'UPDATE', 'BuzonContacto', BuzonContacto(pk=1), 'Conexión de contacto comprobada')
                confirmar_guardado(request, alias='central', titulo='Buzón conectado',
                    mensaje=f'Zoho respondió correctamente. Se incorporaron {nuevos} correo(s).',
                    link=reverse('sistema_conexion_contacto'))
                return redirect('sistema_conexion_contacto')
        except ErrorZoho as error:
            if accion == 'conectar':
                formulario.add_error(None, str(error))
            else:
                error_conexion = str(error)
    contexto = contexto_sistema(request, 'contacto', 'Conexión del buzón de contacto')
    contexto.update(formulario=formulario, buzon=BuzonContacto.objects.using('central').filter(pk=1).first(),
                     zoho_configurado=zoho_configurado(), error_consulta=error_conexion)
    return render(request, 'contacto/conexion.html', contexto)


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
                antes = estado_auditable(Usuario.objects.using('central').select_for_update(of=('self',)).select_related('rol').get(pk=cuenta.pk)) if not nueva else {}
                guardada = formulario.save()
                auditar_gestion(request, 'central', 'CREATE' if nueva else 'UPDATE', 'Usuario', guardada,
                    'Cuenta exclusiva de contacto actualizada', cambios=diferencias(antes, estado_auditable(guardada)))
        except IntegrityError:
            formulario.add_error(None, 'La cuenta de contacto ya existe. Recarga esta página para editarla.')
        else:
            if propia:
                update_session_auth_hash(request, guardada)
            confirmar_guardado(request, alias='central', titulo='Cuenta de contacto guardada',
                               mensaje='Los datos de la cuenta de contacto se guardaron correctamente.', link=destino)
            return redirect(destino)
    contexto.update(formulario=formulario, propia=propia,
                    volver=reverse('contacto_bandeja' if propia else 'sistema_cuentas'))
    if 'zoho_configurado' not in contexto:
        contexto['zoho_configurado'] = zoho_configurado()
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
    elif vista == 'enviados':
        consulta = RespuestaContacto.objects.using('central').filter(estado='enviada').select_related('mensaje').order_by('-enviada_en', '-creada_en')
    texto = request.GET.get('search', '').strip()[:200]
    if texto:
        if vista == 'enviados':
            consulta = consulta.filter(Q(mensaje__asunto__icontains=texto) | Q(mensaje__remitente_email__icontains=texto) | Q(texto__icontains=texto))
        else:
            consulta = consulta.filter(Q(asunto__icontains=texto) | Q(remitente_email__icontains=texto)
                                       | Q(remitente_nombre__icontains=texto) | Q(resumen__icontains=texto))
    hoy = timezone.localdate()
    if request.GET.get('vencidos') == '1' and vista != 'enviados':
        consulta = consulta.exclude(estado='resuelto').filter(seguimiento__lte=hoy)
    filtros = request.GET.copy()
    filtros.pop('page', None)
    contexto.update(
        pagina=Paginator(consulta, 25).get_page(request.GET.get('page')), filtros_pagina=filtros.urlencode(),
        vista=vista, busqueda=texto, hoy=hoy,
        error_consulta=request.session.pop('contacto_error_sync', ''),
        kpis=[(etiqueta, contexto['contadores'][clave] if contexto['datos_disponibles'] else None, clave)
              for etiqueta, clave in [('Sin leer', 'sin-leer'), ('Pendientes', 'pendiente'),
                                     ('En seguimiento', 'seguimiento'), ('Seguimientos para hoy', 'vencidos')]],
    )
    return render(request, 'contacto/bandeja.html', contexto)


@requiere_contacto
@require_POST
def sincronizar(request):
    from urllib.parse import urlencode
    filtros = {clave: request.POST[clave][:200] for clave in ('vista', 'search', 'vencidos') if request.POST.get(clave)}
    destino = reverse('contacto_bandeja') + ('?' + urlencode(filtros) if filtros else '')
    try:
        nuevos = sincronizar_buzon(anteriores=request.POST.get('anteriores') == '1',
                                   forzar=request.POST.get('automatico') != '1')
    except ErrorZoho as error:
        if request.headers.get('Accept') == 'application/json':
            return JsonResponse({'success': False, 'codigo': error.codigo, 'mensaje': str(error)},
                                status=409 if error.codigo == 'ocupado' else 503)
        request.session['contacto_error_sync'] = str(error)
        return redirect(destino)
    if request.headers.get('Accept') == 'application/json':
        buzon = BuzonContacto.objects.using('central').get(pk=1)
        datos = datos_bandeja()
        return JsonResponse({'success': True, 'usuario_id': request.user.pk, 'nuevos': nuevos,
            'total': datos['todos'], 'ultimo_id': datos['ultimo_id'],
            'ultima_consulta': buzon.ultima_consulta.isoformat() if buzon.ultima_consulta else None})
    confirmar_guardado(request, alias='central', titulo='Bandeja consultada',
                       mensaje=f'{nuevos} correo(s) incorporado(s).', link=reverse('contacto_bandeja'))
    return redirect(destino)


def confirmar_accion(request, mensaje, titulo, texto, *, cambios=None):
    auditar_gestion(request, 'central', 'UPDATE', 'MensajeContacto', mensaje, titulo, cambios=cambios)
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
    antes_seguimiento = estado_auditable(mensaje)
    error = ''
    seguimiento = SeguimientoForm(instance=mensaje)
    nota = NotaForm()
    respuesta_form = None
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
                    return confirmar_accion(request, mensaje, 'Seguimiento actualizado', 'La consulta quedó actualizada.',
                        cambios=diferencias(antes_seguimiento, estado_auditable(mensaje)))
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
            crear_evento(alias='central', request=request, accion='UPDATE', modelo='MensajeContacto',
                objeto_id=mensaje.pk, operacion='Acción de correo no completada', resultado='fallida',
                descripcion='La operación del buzón no pudo completarse. No se registra el texto del correo.')
    # La página se muestra sin esperar a Zoho. Su contenido se solicita aparte
    # y queda guardado en la misma base central de Neon.
    if request.method == 'GET' and not mensaje.leido:
        MensajeContacto.objects.using('central').filter(pk=mensaje.pk).update(leido=True)
        mensaje.leido = True
    elif request.method == 'POST':
        mensaje.refresh_from_db(using='central')
    respuestas = list(mensaje.respuestas.all())
    borrador = next((r for r in respuestas if r.estado == 'borrador'), None)
    if respuesta_form is None:
        respuesta_form = BorradorForm(initial={'texto': borrador.texto if borrador else '',
            'version': borrador.version if borrador else 0, 'borrador': borrador.pk if borrador else None})
    contexto = contexto_contacto(request, mensaje.asunto or 'Sin asunto')
    contexto.update(mensaje=mensaje, seguimiento_form=seguimiento, nota_form=nota, respuesta_form=respuesta_form,
                    respuestas=respuestas, borrador=borrador,
                    notas=list(mensaje.notas.all()), error_consulta=error,
                    sin_confirmar=any(r.estado in ('enviando', 'incierta') for r in respuestas),
                    corte_revision=timezone.now() - timedelta(minutes=3))
    return render(request, 'contacto/mensaje.html', contexto)


@requiere_contacto
@require_POST
def contenido_mensaje(request, mensaje_id):
    mensaje = get_object_or_404(MensajeContacto.objects.using('central'), pk=mensaje_id)
    if not mensaje.contenido_cargado:
        try:
            from .zoho_contacto import configuracion_zoho
            configuracion = configuracion_zoho()
            conexion = connections['central']
            # Zoho puede tardar: devolver la conexión al pool durante la espera
            # deja capacidad para navegar por el resto de SmartStock.
            if conexion.settings_dict['OPTIONS'].get('pool') and not conexion.in_atomic_block:
                conexion.close()
            contenido = ClienteZoho(configuracion).contenido(mensaje)
        except ErrorZoho as error:
            return JsonResponse({'success': False, 'mensaje': str(error)}, status=502)
        actualizados = MensajeContacto.objects.using('central').filter(pk=mensaje.pk, contenido_cargado=False).update(
            contenido=contenido, contenido_cargado=True)
        if actualizados:
            mensaje.contenido = contenido
        else:
            mensaje.refresh_from_db(using='central', fields=['contenido'])
    return JsonResponse({'success': True, 'data': {'usuario_id': request.user.pk,
        'mensaje_id': mensaje.pk, 'contenido': mensaje.contenido}})
