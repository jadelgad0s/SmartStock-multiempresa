"""Cambios de estado auditados. Ningún miembro del equipo aprueba su propio acceso."""
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.core.empresa import usar_empresa
from apps.productos.models import Notificacion
from apps.usuarios.models import Usuario
from .autorizacion_soporte import ALCANCES, EXTRAS_GESTION, auditar_soporte, usuario_empresa_administrador
from .models import AccesoSoporte, AtencionSoporte, NotificacionSistema
from .permisos import es_administrador_plataforma, es_personal_smartstock


def avisar_tecnico(atencion, titulo, mensaje):
    if atencion.tecnico_id:
        NotificacionSistema.objects.using('central').create(destinatario_id=atencion.tecnico_id,
            titulo=titulo, mensaje=mensaje, empresa_nombre=atencion.empresa.nombre,
            link=reverse('sistema_atencion', args=[atencion.pk], urlconf='esquema_multiempresa.urls_central'))


def avisar_empresa(atencion):
    with usar_empresa(atencion.empresa):
        administradores = Usuario.objects.filter(activo=True, rol__codigo='administrador', rol__activo=True)
        Notificacion.objects.bulk_create([Notificacion(usuario_destino=u, titulo='Solicitud de acceso de SmartStock',
            mensaje=f'{atencion.asunto}: revisa los permisos y la duración antes de autorizar.', link='/soporte/')
            for u in administradores])


def revocar_accesos(atencion):
    return AccesoSoporte.objects.using('central').filter(atencion=atencion, estado__in=['pendiente', 'aprobado']).update(estado='revocado')


def solicitar_acceso(request, atencion, datos):
    with transaction.atomic(using='central'):
        atencion = AtencionSoporte.objects.using('central').select_for_update(of=('self',)).select_related('empresa', 'tecnico', 'tecnico__rol').get(pk=atencion.pk)
        if (atencion.estado != 'abierta' or not atencion.empresa.activa or atencion.tecnico_id != request.user.pk
                or not es_personal_smartstock(atencion.tecnico)):
            raise PermissionDenied('La atención debe estar abierta, activa y asignada a tu cuenta.')
        alcances = datos['alcances']
        if (not alcances or any(k not in ALCANCES for k in alcances)
                or set(alcances) & EXTRAS_GESTION and not es_administrador_plataforma(request.user)):
            raise PermissionDenied('Los permisos solicitados no corresponden a tu perfil.')
        if atencion.accesos.filter(estado='pendiente').exists():
            raise ValidationError('Ya hay una solicitud pendiente. Espera su decisión o retírala antes de solicitar otra.')
        acceso = AccesoSoporte.objects.using('central').create(atencion=atencion, tecnico=request.user,
            alcances=list(dict.fromkeys(alcances)), minutos=datos['minutos'], motivo=datos['motivo'])
        auditar_soporte(request, atencion, 'CREATE', f'Acceso solicitado {acceso.pk}; permisos: {", ".join(acceso.alcances)}; {acceso.minutos} minutos; motivo: {acceso.motivo}',
            operacion='Acceso de soporte solicitado', resultado='solicitada')
        transaction.on_commit(lambda: avisar_empresa(atencion), using='central', robust=True)
    return acceso


def decidir_acceso(request, acceso_id, accion):
    if not usuario_empresa_administrador(request):
        raise PermissionDenied
    # La empresa se obtiene del host y la sesión, nunca de campos POST.
    base = AccesoSoporte.objects.using('central').filter(pk=acceso_id, atencion__empresa=request.empresa).first()
    if base is None:
        raise PermissionDenied('Esta solicitud no pertenece a tu empresa.')
    with transaction.atomic(using='central'):
        atencion = AtencionSoporte.objects.using('central').select_for_update(of=('self',)).select_related('empresa', 'tecnico', 'tecnico__rol').get(pk=base.atencion_id)
        acceso = AccesoSoporte.objects.using('central').select_for_update().get(pk=acceso_id)
        estado_anterior = acceso.estado
        reemplazados = 0
        if accion == 'revocar':
            if acceso.estado not in ('pendiente', 'aprobado'):
                raise ValidationError('Este acceso ya no puede revocarse.')
            acceso.estado = 'revocado'
        else:
            if accion not in ('aprobar', 'rechazar') or acceso.estado != 'pendiente':
                raise ValidationError('Esta solicitud ya fue resuelta. Actualiza la página.')
            if (atencion.estado != 'abierta' or not atencion.empresa.activa or atencion.tecnico_id != acceso.tecnico_id
                    or not atencion.tecnico or not es_personal_smartstock(atencion.tecnico)):
                raise ValidationError('La atención cambió o su responsable ya no tiene acceso al equipo.')
            if set(acceso.alcances) & EXTRAS_GESTION and not es_administrador_plataforma(atencion.tecnico):
                raise ValidationError('El perfil actual del responsable no permite esos permisos.')
            acceso.estado = 'aprobado' if accion == 'aprobar' else 'rechazado'
            acceso.decidido_en = timezone.now()
            acceso.aprobador_id, acceso.aprobador_email = request.user.pk, request.user.email
            if accion == 'aprobar':
                acceso.expira_en = acceso.decidido_en + timedelta(minutes=acceso.minutos)
                # Una atención mantiene una sola autorización efectiva. Así,
                # revocar la actual no deja lecturas habilitadas por una vieja.
                reemplazados = AccesoSoporte.objects.using('central').filter(
                    atencion=atencion, estado='aprobado').exclude(pk=acceso.pk).update(estado='revocado')
        acceso.save(using='central')
        detalle = f'Acceso {acceso.pk}: {acceso.estado}; permisos: {", ".join(acceso.alcances)}'
        if reemplazados:
            detalle += f'; {reemplazados} autorizaciones anteriores de esta atención revocadas'
        auditar_soporte(request, atencion, 'UPDATE', detalle,
            operacion={'aprobar': 'Acceso de soporte aprobado', 'rechazar': 'Acceso de soporte rechazado',
                       'revocar': 'Acceso de soporte revocado'}[accion],
            cambios={'estado': {'antes': estado_anterior, 'despues': acceso.estado}})
        transaction.on_commit(lambda: avisar_tecnico(atencion, 'Permisos de soporte actualizados',
            f'{atencion.empresa.nombre}: solicitud {acceso.get_estado_display().lower()}.'), using='central', robust=True)
    return acceso
