from functools import wraps

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.views.decorators.cache import never_cache

from apps.core.models import Auditoria


ADMINISTRADOR_PLATAFORMA = 'administrador_plataforma'
SOPORTE_TECNICO = 'soporte_tecnico'
PERFILES_EQUIPO = {
    'superusuario': 'Superusuario técnico',
    ADMINISTRADOR_PLATAFORMA: 'Administrador de plataforma',
    SOPORTE_TECNICO: 'Soporte técnico',
}


def es_personal_smartstock(usuario):
    if not (usuario.is_authenticated and usuario.activo and usuario.is_staff
            and usuario._state.db == 'central'):
        return False
    return bool(usuario.is_superuser or (
        usuario.rol_id and usuario.rol.activo
        and usuario.rol.codigo in (ADMINISTRADOR_PLATAFORMA, SOPORTE_TECNICO)
    ))


def es_superusuario_smartstock(usuario):
    return es_personal_smartstock(usuario) and usuario.is_superuser


def es_administrador_plataforma(usuario):
    return es_personal_smartstock(usuario) and (
        usuario.is_superuser or usuario.rol.codigo == ADMINISTRADOR_PLATAFORMA
    )


def perfil_personal(usuario):
    if usuario.is_superuser:
        return 'superusuario'
    return usuario.rol.codigo if usuario.rol_id else ''


def nombre_perfil_personal(usuario):
    return PERFILES_EQUIPO.get(perfil_personal(usuario), 'Sin perfil habilitado')


def registrar_empresa_consultada(request, empresa):
    consultas = getattr(request, '_empresas_consultadas', {})
    consultas[empresa.pk] = empresa
    request._empresas_consultadas = consultas


def auditar_consultas(request, respuesta):
    if request.method != 'GET' or respuesta.status_code >= 400:
        return
    consultas = getattr(request, '_empresas_consultadas', {})
    Auditoria.objects.using('central').bulk_create([
        Auditoria(
            usuario=request.user, accion='CONSULTA', modelo='Empresa', objeto_id=str(empresa.pk),
            descripcion=(f'SmartStock · {request.user.email} · Solicitud de consulta de '
                         f'{getattr(request, "_modulo_consultado", "empresa")} · {empresa.nombre} ({empresa.codigo})'),
            ip_address=request.META.get('REMOTE_ADDR'),
        ) for empresa in consultas.values()
    ])


def requiere(comprobar):
    def decorar(vista):
        @never_cache
        @wraps(vista)
        def protegida(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('login_page')
            if not comprobar(request.user):
                raise PermissionDenied
            respuesta = vista(request, *args, **kwargs)
            auditar_consultas(request, respuesta)
            return respuesta
        return protegida
    return decorar


requiere_personal = requiere(es_personal_smartstock)
requiere_administrador_plataforma = requiere(es_administrador_plataforma)
requiere_superusuario = requiere(es_superusuario_smartstock)
