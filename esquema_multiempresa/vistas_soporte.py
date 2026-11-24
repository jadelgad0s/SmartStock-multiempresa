from smtplib import SMTPException

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.core.empresa import usar_empresa
from apps.core.models import Auditoria
from apps.usuarios.models import Rol, Usuario
from .autorizacion_soporte import (LECTURAS, acceso_para, atenciones_visibles, alcances_actuales,
    auditar_soporte, empresas_visibles, parametros_atencion)
from .cuentas_empresa import enviar_enlace, puede_invitar_inicial
from .forms_soporte import AtencionForm, FiltroAtencionesForm, InvitacionEmpresaForm, ResolucionForm, SolicitudAccesoForm
from .models import AccesoSoporte, AtencionSoporte
from .notificaciones import confirmar_guardado
from .permisos import es_administrador_plataforma, registrar_empresa_consultada, requiere_administrador_plataforma, requiere_personal
from .sistema import contexto_sistema, empresa_del_panel, paginar
from .soporte_operaciones import avisar_tecnico, revocar_accesos, solicitar_acceso


@requiere_personal
@require_GET
def atenciones_sistema(request):
    contexto = contexto_sistema(request, 'atenciones', 'Atenciones de soporte', resolver_empresa=False)
    consulta = atenciones_visibles(request.user)
    formulario = FiltroAtencionesForm(request.GET, actor=request.user)
    if formulario.is_valid():
        filtros = formulario.cleaned_data
        if filtros['search']:
            consulta = consulta.filter(asunto__icontains=filtros['search'])
        if filtros['empresa']:
            consulta = consulta.filter(empresa=filtros['empresa'])
        if filtros['estado']:
            consulta = consulta.filter(estado=filtros['estado'])
    else:
        consulta = consulta.none()
    contexto.update(
        formulario_filtros=formulario,
        filtros_atenciones_activos=any(request.GET.get(campo) for campo in formulario.fields),
        resumen_atenciones=consulta.aggregate(
            abiertas=Count('pk', filter=Q(estado='abierta')),
            cerradas=Count('pk', filter=Q(estado='cerrada')),
            sin_responsable=Count('pk', filter=Q(estado='abierta', tecnico__isnull=True))),
    )
    contexto['atenciones'] = list(paginar(request, contexto, consulta))
    return render(request, 'soporte/atenciones.html', contexto)


@requiere_personal
@require_http_methods(['GET', 'POST'])
def nueva_atencion(request):
    empresa = get_object_or_404(empresas_visibles(request.user), codigo=request.GET['empresa']) if request.GET.get('empresa') else None
    formulario = AtencionForm(request.POST or None, actor=request.user,
                             initial={'empresa': empresa, 'tecnico': request.user.pk})
    if request.method == 'POST' and formulario.is_valid():
        atencion = formulario.save(commit=False)
        atencion.save(using='central')
        auditar_soporte(request, atencion, 'CREATE', 'Atención creada: ' + atencion.motivo)
        avisar_tecnico(atencion, 'Atención asignada', atencion.asunto)
        confirmar_guardado(request, alias='central', titulo='Atención creada', mensaje='La atención quedó registrada.',
            link=reverse('sistema_atencion', args=[atencion.pk]), empresa=atencion.empresa)
        return redirect('sistema_atencion', atencion_id=atencion.pk)
    contexto = contexto_sistema(request, 'atenciones', 'Nueva atención de soporte')
    contexto.update(formulario=formulario, volver=reverse('sistema_atenciones'))
    return render(request, 'soporte/nueva_atencion.html', contexto)


@requiere_personal
@require_http_methods(['GET', 'POST'])
def detalle_atencion(request, atencion_id):
    atencion = get_object_or_404(atenciones_visibles(request.user), pk=atencion_id)
    acceso_form = SolicitudAccesoForm(request.POST if request.POST.get('accion') == 'solicitar' else None, actor=request.user)
    cierre = ResolucionForm(request.POST if request.POST.get('accion') == 'cerrar' else None)
    asignar = AtencionForm(request.POST if request.POST.get('accion') == 'asignar' else None, instance=atencion, actor=request.user)
    error = ''
    if request.method == 'POST':
        try:
            accion = request.POST.get('accion')
            if accion == 'solicitar' and acceso_form.is_valid():
                solicitar_acceso(request, atencion, acceso_form.cleaned_data)
            elif accion == 'cerrar' and cierre.is_valid():
                with transaction.atomic(using='central'):
                    actual = AtencionSoporte.objects.using('central').select_for_update().get(pk=atencion.pk)
                    if actual.estado != 'abierta' or not (es_administrador_plataforma(request.user) or actual.tecnico_id == request.user.pk):
                        raise PermissionDenied
                    actual.estado, actual.cerrada_en, actual.resolucion = 'cerrada', timezone.now(), cierre.cleaned_data['resolucion']
                    actual.save(using='central')
                    revocar_accesos(actual)
                    auditar_soporte(request, actual, 'UPDATE', 'Atención cerrada: ' + actual.resolucion,
                        operacion='Atención de soporte cerrada', cambios={'estado': {'antes': 'abierta', 'despues': 'cerrada'}})
            elif accion == 'asignar' and es_administrador_plataforma(request.user) and asignar.is_valid():
                with transaction.atomic(using='central'):
                    actual = AtencionSoporte.objects.using('central').select_for_update().get(pk=atencion.pk)
                    if actual.estado != 'abierta':
                        raise ValidationError('Esta atención ya está cerrada.')
                    nuevo_tecnico = asignar.cleaned_data['tecnico']
                    anterior = actual.tecnico_id
                    if actual.tecnico_id != getattr(nuevo_tecnico, 'pk', None):
                        revocar_accesos(actual)
                    actual.tecnico = asignar.cleaned_data['tecnico']
                    actual.save(using='central', update_fields=['tecnico'])
                    auditar_soporte(request, actual, 'UPDATE', 'Responsable de la atención actualizado',
                        cambios={'tecnico': {'antes': anterior, 'despues': actual.tecnico_id}})
                    avisar_tecnico(actual, 'Atención asignada', actual.asunto)
            elif accion == 'retirar':
                with transaction.atomic(using='central'):
                    actual = AtencionSoporte.objects.using('central').select_for_update().get(pk=atencion.pk)
                    if not (es_administrador_plataforma(request.user) or actual.tecnico_id == request.user.pk):
                        raise PermissionDenied
                    acceso = get_object_or_404(AccesoSoporte.objects.using('central'), pk=request.POST.get('acceso'), atencion=actual)
                    if acceso.estado not in ('pendiente', 'aprobado'):
                        raise ValidationError('Esta solicitud ya está resuelta.')
                    anterior = acceso.estado
                    acceso.estado = 'revocado'
                    acceso.save(using='central', update_fields=['estado'])
                    auditar_soporte(request, actual, 'UPDATE', f'Acceso {acceso.pk} retirado por el equipo',
                        operacion='Acceso de soporte retirado', cambios={'estado': {'antes': anterior, 'despues': 'revocado'}})
            else:
                accion = None
            if accion:
                confirmar_guardado(request, alias='central', titulo='Atención actualizada',
                    mensaje='Los cambios quedaron registrados.', link=reverse('sistema_atencion', args=[atencion.pk]), empresa=atencion.empresa)
                return redirect('sistema_atencion', atencion_id=atencion.pk)
        except (ValidationError, IntegrityError) as e:
            error = ' '.join(e.messages) if isinstance(e, ValidationError) else 'Ya existe una solicitud pendiente. Actualiza la atención.'
    atencion.refresh_from_db(using='central')
    # Una atención no es una autorización. Estos enlaces se calculan solo con
    # permisos aprobados y vigentes del usuario que está viendo la página.
    request._atencion_soporte = atencion
    enlaces = []
    for alcance, nombre in LECTURAS.items():
        if acceso_para(request, atencion.empresa, alcance, exigir=False):
            acceso = request._acceso_soporte
            if acceso.atencion_id != atencion.pk:
                continue
            ruta = 'sistema_' + ('sms' if alcance == 'sms' else alcance)
            enlaces.append((nombre, reverse(ruta) + f'?empresa={atencion.empresa.codigo}&atencion={atencion.pk}'))
    contexto = contexto_sistema(request, 'atenciones', 'Atención de soporte', atencion.empresa)
    contexto.update(atencion=atencion, solicitudes=list(atencion.accesos.select_related('tecnico').all()),
        formulario_acceso=acceso_form, formulario_cierre=cierre, formulario_asignacion=asignar,
        puede_solicitar=atencion.tecnico_id == request.user.pk and atencion.estado == 'abierta' and atencion.empresa.activa,
        enlaces_autorizados=enlaces, error_consulta=error,
        eventos=list(Auditoria.objects.using('central').filter(modelo='AtencionSoporte', objeto_id=str(atencion.pk)).order_by('-fecha_creacion')[:20]))
    registrar_empresa_consultada(request, atencion.empresa, 'fallida' if error else 'completada')
    return render(request, 'soporte/atencion.html', contexto)


@requiere_administrador_plataforma
@require_http_methods(['GET', 'POST'])
def invitar_administrador(request, codigo):
    empresa = empresa_del_panel(codigo, request)
    if not empresa.activa or not puede_invitar_inicial(empresa):
        raise PermissionDenied('La empresa ya tiene un administrador activo o su acceso está suspendido.')
    with usar_empresa(empresa):
        pendiente = Usuario.objects.filter(email__iexact=empresa.contacto_email).first()
        if pendiente and (pendiente.has_usable_password() or not pendiente.rol_id or pendiente.rol.codigo != 'administrador'):
            raise PermissionDenied('El contacto ya tiene una cuenta. Su rol debe gestionarlo la empresa.')
        formulario = InvitacionEmpresaForm(request.POST or None, empresa=empresa, instance=pendiente)
        if request.method == 'POST' and formulario.is_valid():
            with transaction.atomic(using=empresa.alias_bd):
                rol = get_object_or_404(Rol.objects.select_for_update(), codigo='administrador', activo=True)
                if not puede_invitar_inicial(empresa):
                    raise PermissionDenied('La empresa ya tiene un administrador activo.')
                usuario = formulario.save(commit=False)
                usuario.email = empresa.contacto_email.lower()
                usuario.rol, usuario.activo, usuario.is_staff, usuario.is_superuser = rol, True, False, False
                # Conservar el hash de una invitación pendiente: cambiarlo al
                # reenviar invalidaría el enlace anterior, incluso con throttle.
                if usuario._state.adding:
                    usuario.set_unusable_password()
                usuario.save(using=empresa.alias_bd)
            from apps.core.registro_auditoria import crear_evento
            crear_evento(alias='central', request=request, empresa=empresa, accion='CREATE', modelo='Empresa', objeto_id=empresa.pk,
                operacion='Cuenta de administrador inicial preparada',
                descripcion=f'Administrador inicial preparado para {empresa.contacto_email}; verificación del contacto confirmada por {request.user.email}')
            try:
                enviado = enviar_enlace(request, empresa, usuario)
                mensaje = 'Invitación enviada al contacto principal.' if enviado else 'Ya se envió un enlace recientemente. Espera dos minutos antes de reintentar.'
            except (SMTPException, OSError):
                formulario.add_error(None, 'La cuenta quedó preparada, pero no pudimos enviar el correo. Reintenta desde esta pantalla.')
            else:
                confirmar_guardado(request, alias='central', titulo='Administrador inicial', mensaje=mensaje,
                    link=reverse('sistema_ficha_empresa', args=[empresa.codigo]), empresa=empresa)
                return redirect('sistema_ficha_empresa', codigo=empresa.codigo)
    contexto = contexto_sistema(request, 'usuarios', 'Invitar administrador inicial', empresa)
    contexto.update(formulario=formulario, volver=reverse('sistema_ficha_empresa', args=[empresa.codigo]))
    registrar_empresa_consultada(request, empresa, 'completada')
    return render(request, 'sistema/formulario.html', contexto)


@requiere_personal
@require_POST
def recuperar_usuario_empresa(request, codigo, usuario_id):
    empresa = empresa_del_panel(codigo, request)
    acceso_para(request, empresa, 'recuperar_acceso')
    usuario = get_object_or_404(Usuario.objects.using(empresa.alias_bd), pk=usuario_id, activo=True, is_superuser=False, is_staff=False)
    auditar_soporte(request, request._atencion_soporte, 'UPDATE', f'Recuperación solicitada para usuario {usuario.pk}; correo de destino registrado',
        operacion='Recuperación de acceso solicitada', resultado='solicitada')
    try:
        enviado = enviar_enlace(request, empresa, usuario)
        mensaje = 'El enlace fue enviado al correo registrado del usuario.' if enviado else 'Ya se solicitó un enlace recientemente. Espera dos minutos.'
    except (SMTPException, OSError):
        mensaje = 'No pudimos enviar el correo de recuperación. Reintenta más tarde.'
    confirmar_guardado(request, alias='central', titulo='Recuperación de acceso', mensaje=mensaje,
        link=reverse('sistema_usuarios') + f'?empresa={empresa.codigo}', empresa=empresa)
    return redirect(reverse('sistema_usuarios') + f'?empresa={empresa.codigo}&atencion={request._atencion_soporte.pk}')
