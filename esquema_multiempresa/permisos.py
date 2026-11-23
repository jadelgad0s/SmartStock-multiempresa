from functools import wraps

from django.core.exceptions import PermissionDenied
from django.db import DatabaseError
from django.shortcuts import redirect
from django.views.decorators.cache import never_cache

from apps.core.models import Auditoria
from apps.core.registro_auditoria import crear_evento, datos_registro


ADMINISTRADOR_PLATAFORMA = 'administrador_plataforma'
SOPORTE_TECNICO = 'soporte_tecnico'
CONTACTO = 'contacto'
CORREO_CONTACTO = 'contacto@smartstockchile.cl'
PERFILES_EQUIPO = {
    'superusuario': 'Superusuario técnico',
    ADMINISTRADOR_PLATAFORMA: 'Administrador de plataforma',
    SOPORTE_TECNICO: 'Soporte técnico',
}


def es_personal_smartstock(usuario):
    if not (usuario.is_authenticated and usuario.activo and usuario.is_staff
            and usuario._state.db == 'central'):
        return False
    # La identidad reservada nunca obtiene acceso al inventario o a la
    # administración por un cambio accidental de rol o de flags.
    if usuario.email.lower() == CORREO_CONTACTO or usuario.rol_id and usuario.rol.codigo == CONTACTO:
        return False
    return bool(usuario.is_superuser or (
        usuario.rol_id and usuario.rol.activo
        and usuario.rol.codigo in (ADMINISTRADOR_PLATAFORMA, SOPORTE_TECNICO)
    ))


def es_contacto_smartstock(usuario):
    return bool(usuario.is_authenticated and usuario.activo and usuario.is_staff
                and not usuario.is_superuser and usuario._state.db == 'central'
                and usuario.email == CORREO_CONTACTO and usuario.rol_id
                and usuario.rol.activo and usuario.rol.codigo == CONTACTO)


def es_cuenta_interna(usuario):
    return es_personal_smartstock(usuario) or es_contacto_smartstock(usuario)


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
    if perfil_personal(usuario) == CONTACTO:
        return 'Contacto'
    return PERFILES_EQUIPO.get(perfil_personal(usuario), 'Sin perfil habilitado')


def registrar_empresa_consultada(request, empresa, resultado=None):
    consultas = getattr(request, '_empresas_consultadas', {})
    consultas[empresa.pk] = empresa
    request._empresas_consultadas = consultas
    if resultado:
        resultados = getattr(request, '_resultados_consulta', {})
        # Crear el contexto después de una lectura no borra su resultado.
        # Tampoco una lectura posterior oculta un fallo parcial de la ficha.
        if resultados.get(empresa.pk) not in ('fallida', 'denegada'):
            resultados[empresa.pk] = resultado
        request._resultados_consulta = resultados


def auditar_consultas(request, respuesta=None, resultado=None):
    if request.method != 'GET':
        return
    consultas = getattr(request, '_empresas_consultadas', {})
    resultados = getattr(request, '_resultados_consulta', {})
    if respuesta is not None:
        if respuesta.status_code >= 400:
            resultado = 'denegada' if respuesta.status_code == 403 else 'fallida'
        elif (respuesta.status_code >= 300 or respuesta.streaming
              or not getattr(respuesta, 'is_rendered', True)):
            # Ni una redirección ni el inicio de un flujo confirman su final.
            resultado = 'solicitada'
    descripciones = {'completada': 'Consulta completada de ', 'fallida': 'Consulta fallida de ',
                     'denegada': 'Consulta denegada de ', 'solicitada': 'Solicitud de consulta de '}
    registros = []
    for empresa in consultas.values():
        final = resultado or resultados.get(empresa.pk, 'solicitada')
        registros.append(Auditoria(
            usuario=request.user, accion='CONSULTA', modelo='Empresa', objeto_id=str(empresa.pk),
            descripcion=(f'SmartStock · {request.user.email} · {descripciones[final]}'
                         f'{getattr(request, "_modulo_consultado", "empresa")} · {empresa.nombre} ({empresa.codigo})'
                         + (f' · Atención {request._atencion_soporte.pk} · Motivo: {getattr(request, "_acceso_soporte", request._atencion_soporte).motivo}'
                            if getattr(request, '_atencion_soporte', None) else ''))[:2000],
            **datos_registro(request, usuario=request.user, empresa=empresa,
                modulo=getattr(request, '_modulo_consultado', 'Empresas'),
                operacion='Consulta de ' + getattr(request, '_modulo_consultado', 'empresa'),
                resultado=final),
        ))
    Auditoria.objects.using('central').bulk_create(registros)


def requiere(comprobar):
    def decorar(vista):
        @never_cache
        @wraps(vista)
        def protegida(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('login_page')
            try:
                if not comprobar(request.user):
                    raise PermissionDenied
                respuesta = vista(request, *args, **kwargs)
            except PermissionDenied:
                # Solo identidad autenticada; no incorporar parámetros ni credenciales.
                try:
                    crear_evento(alias='central', request=request, accion='ACCESS_DENIED', modelo='Acceso',
                        operacion='Acceso denegado', resultado='denegada',
                        descripcion='La cuenta no tenía permiso vigente para esta acción.')
                    auditar_consultas(request, resultado='denegada')
                except DatabaseError:
                    pass  # La falta de registro nunca convierte una denegación en acceso.
                raise
            except Exception:
                try:
                    auditar_consultas(request, resultado='fallida')
                except DatabaseError:
                    pass  # Conservar el error original si tampoco responde la auditoría.
                raise
            auditar_consultas(request, respuesta)
            return respuesta
        return protegida
    return decorar


requiere_personal = requiere(es_personal_smartstock)
requiere_administrador_plataforma = requiere(es_administrador_plataforma)
requiere_superusuario = requiere(es_superusuario_smartstock)
requiere_contacto = requiere(es_contacto_smartstock)
