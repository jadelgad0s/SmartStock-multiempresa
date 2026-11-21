"""Autorizaciones por empresa, atención y técnico. Se comprueban en cada petición."""
from uuid import UUID

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Auditoria
from .models import AccesoSoporte, AtencionSoporte, Empresa
from .permisos import es_administrador_plataforma, es_personal_smartstock


LECTURAS = {
    'inventario': 'Consultar resumen de inventario', 'catalogo': 'Consultar catálogo y stock',
    'bodegas': 'Consultar bodegas', 'movimientos': 'Consultar movimientos',
    'transferencias': 'Consultar transferencias', 'mermas': 'Consultar mermas y bajas',
    'reportes': 'Consultar reportes', 'sms': 'Diagnosticar alertas SMS (destinatarios ocultos)',
    'auditoria': 'Consultar auditoría de la empresa', 'usuarios': 'Consultar usuarios y estado de acceso',
}
ALCANCES = {**LECTURAS, 'recuperar_acceso': 'Enviar recuperación al correo actual del usuario',
            'gestionar_usuarios': 'Crear, editar, asignar roles y suspender usuarios de la empresa',
            'exportar': 'Exportar reportes CSV o PDF'}
EXTRAS_GESTION = {'gestionar_usuarios', 'exportar'}


def empresas_visibles(usuario):
    empresas = Empresa.objects.using('central').filter(alias_bd__in=settings.BASES_EMPRESA)
    if es_administrador_plataforma(usuario):
        return empresas
    return empresas.filter(atenciones_soporte__tecnico_id=usuario.pk, atenciones_soporte__estado='abierta').distinct()


def atenciones_visibles(usuario):
    consulta = AtencionSoporte.objects.using('central').select_related('empresa', 'tecnico', 'tecnico__rol')
    return consulta if es_administrador_plataforma(usuario) else consulta.filter(tecnico_id=usuario.pk)


def auditar_soporte(request, atencion, accion, detalle):
    cliente = getattr(request, 'empresa', None)
    actor = request.user
    Auditoria.objects.using('central').create(
        usuario_id=actor.pk if cliente is None else None, accion=accion, modelo='AtencionSoporte', objeto_id=str(atencion.pk),
        descripcion=(f'Soporte · {actor.email} · Empresa {atencion.empresa.codigo} · '
                     f'Atención {atencion.pk} · {detalle}')[:2000],
        ip_address=request.META.get('REMOTE_ADDR'))


def accesos_vigentes(usuario, empresa=None):
    if not es_personal_smartstock(usuario):
        return AccesoSoporte.objects.using('central').none()
    consulta = AccesoSoporte.objects.using('central').filter(
        tecnico_id=usuario.pk, atencion__tecnico_id=usuario.pk, estado='aprobado',
        expira_en__gt=timezone.now(), atencion__estado='abierta', atencion__empresa__activa=True,
        atencion__empresa__alias_bd__in=settings.BASES_EMPRESA).select_related('atencion', 'atencion__empresa')
    return consulta.filter(atencion__empresa=empresa) if empresa else consulta


def acceso_para(request, empresa, alcance, *, exigir=True):
    if alcance in EXTRAS_GESTION and not es_administrador_plataforma(request.user):
        if exigir:
            raise PermissionDenied('Tu perfil no permite esta acción.')
        return None
    consulta = accesos_vigentes(request.user, empresa)
    codigo = request.GET.get('atencion') or request.POST.get('atencion')
    if not codigo and getattr(request, '_atencion_soporte', None):
        codigo = str(request._atencion_soporte.pk)
    if codigo:
        try:
            codigo = UUID(codigo)
        except (ValueError, AttributeError, TypeError):
            raise PermissionDenied('Selecciona una atención válida.') from None
        consulta = consulta.filter(atencion_id=codigo)
    for acceso in consulta:
        if isinstance(acceso.alcances, list) and alcance in acceso.alcances:
            request._acceso_soporte = acceso
            request._atencion_soporte = acceso.atencion
            return acceso
    if exigir:
        raise PermissionDenied('Necesitas autorización vigente del administrador de esta empresa para esta consulta.')
    return None


def alcances_actuales(request):
    acceso = getattr(request, '_acceso_soporte', None)
    if acceso is None or not acceso.vigente:
        return set()
    alcances = {valor for valor in acceso.alcances if isinstance(valor, str) and valor in ALCANCES} if isinstance(acceso.alcances, list) else set()
    if not es_administrador_plataforma(request.user):
        alcances -= EXTRAS_GESTION
    return alcances


def empresa_para_consulta(request, alcance):
    codigo = request.GET.get('empresa')
    if not codigo:
        return None
    empresa = get_object_or_404(empresas_visibles(request.user), codigo=codigo)
    acceso_para(request, empresa, alcance)
    return empresa


def parametros_atencion(request):
    acceso = getattr(request, '_acceso_soporte', None)
    return {'atencion': str(acceso.atencion_id)} if acceso else {}


def enlace_atencion(atencion):
    return reverse('sistema_atencion', args=[atencion.pk], urlconf='esquema_multiempresa.urls_central')


def usuario_empresa_administrador(request):
    usuario = request.user
    empresa = getattr(request, 'empresa', None)
    return bool(empresa and empresa.activa and usuario.is_authenticated and usuario.activo
                and usuario._state.db == empresa.alias_bd and (usuario.is_superuser or usuario.rol_id
                and usuario.rol.activo and usuario.rol.codigo == 'administrador'))
