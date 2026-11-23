"""Datos explícitos de auditoría. Nunca se copian formularios ni credenciales."""
from datetime import date, datetime
from ipaddress import ip_address

from .empresa import empresa_actual
from .middleware import get_client_ip
from .models import Auditoria


PERFILES = {'superusuario': 'Superusuario técnico', 'administrador_plataforma': 'Administrador de plataforma',
            'soporte_tecnico': 'Soporte técnico', 'contacto': 'Contacto'}
MODULOS = {'Empresa': 'Empresas', 'Usuario': 'Usuarios', 'Rol': 'Roles', 'Producto': 'Catálogo',
           'Bodega': 'Bodegas', 'Movimiento': 'Movimientos', 'Transferencia': 'Transferencias',
           'Merma': 'Mermas y bajas', 'MensajeContacto': 'Buzón de contacto',
           'BuzonContacto': 'Buzón de contacto', 'AtencionSoporte': 'Atenciones de soporte',
           'EnvioAlertaSMS': 'Alertas SMS', 'Auditoria': 'Auditoría', 'Acceso': 'Accesos'}
ETIQUETAS = {
    'nombre': 'Nombre', 'codigo': 'Código', 'razon_social': 'Razón social', 'rut': 'RUT', 'rubro': 'Rubro',
    'contacto_nombre': 'Nombre de contacto', 'contacto_apellidos': 'Apellidos de contacto',
    'contacto_email': 'Correo de contacto', 'contacto_telefono': 'Teléfono de contacto',
    'direccion': 'Dirección', 'comuna': 'Comuna', 'region': 'Región', 'activa': 'Empresa activa',
    'nombres': 'Nombres', 'apellidos': 'Apellidos', 'email': 'Correo', 'telefono': 'Teléfono',
    'activo': 'Cuenta activa', 'perfil': 'Perfil', 'estado': 'Estado', 'tecnico': 'Responsable',
    'alcances': 'Permisos de soporte', 'expira_en': 'Vigencia del acceso', 'minutos': 'Duración en minutos',
    'categoria': 'Tipo de consulta', 'seguimiento': 'Próximo seguimiento', 'leido': 'Leído',
}
_ACTOR_ACTUAL = object()


def identidad(usuario):
    if usuario is None or not usuario.is_authenticated:
        return {}
    central = usuario._state.db == 'central'
    rol = usuario.rol if usuario.rol_id else None
    perfil = ('Superusuario técnico' if central else 'Administrador') if usuario.is_superuser else (
        PERFILES.get(rol.codigo, rol.nombre) if central and rol else rol.nombre if rol else 'Sin perfil')
    return {'id': str(usuario.pk), 'nombre': usuario.nombre_completo or usuario.email,
            'email': usuario.email, 'perfil': perfil, 'origen': 'smartstock' if central else 'empresa'}


def valor_seguro(valor):
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if valor is None or isinstance(valor, (bool, int, float)):
        return valor
    if isinstance(valor, (tuple, list)):
        return [valor_seguro(item) for item in valor[:30] if not isinstance(item, (dict, list, tuple))]
    return str(valor)[:1000]


def cambios_seguros(cambios):
    if not isinstance(cambios, dict):
        return {}
    return {campo: {'antes': valor_seguro(valores['antes']), 'despues': valor_seguro(valores['despues'])}
            for campo, valores in (cambios or {}).items()
            if campo in ETIQUETAS and isinstance(valores, dict) and 'antes' in valores and 'despues' in valores}


def estado_auditable(objeto):
    campos = {
        'Empresa': ('nombre', 'codigo', 'razon_social', 'rut', 'rubro', 'contacto_nombre', 'contacto_apellidos',
                    'contacto_email', 'contacto_telefono', 'direccion', 'comuna', 'region', 'activa'),
        'Usuario': ('nombres', 'apellidos', 'email', 'telefono', 'activo'),
        'MensajeContacto': ('estado', 'categoria', 'seguimiento', 'leido'),
    }.get(type(objeto).__name__, ())
    datos = {campo: valor_seguro(getattr(objeto, campo, '')) for campo in campos}
    if type(objeto).__name__ == 'Usuario':
        datos['perfil'] = identidad(objeto).get('perfil', '')
    return datos


def diferencias(antes, despues):
    return {campo: {'antes': antes.get(campo), 'despues': valor}
            for campo, valor in despues.items() if campo in ETIQUETAS and antes.get(campo) != valor}


def datos_registro(request=None, *, usuario=None, empresa=None, atencion=None, modulo='', operacion='',
                   resultado='completada', cambios=None):
    empresa = empresa or empresa_actual() or getattr(request, 'empresa', None)
    atencion = atencion or getattr(request, '_atencion_soporte', None)
    if atencion and empresa is None:
        empresa = atencion.empresa
    direccion = get_client_ip(request) if request else None
    try:
        direccion = str(ip_address(direccion)) if direccion else None
    except ValueError:
        direccion = None
    return {
        'actor': identidad(usuario), 'empresa_codigo': empresa.codigo if empresa else '',
        'empresa_nombre': empresa.nombre if empresa else '', 'atencion_id': atencion.pk if atencion else None,
        'modulo': modulo[:100], 'operacion': operacion[:120], 'resultado': resultado,
        'cambios': cambios_seguros(cambios), 'ip_address': direccion,
        'user_agent': request.META.get('HTTP_USER_AGENT', '')[:500] if request else '',
    }


def crear_evento(*, accion, modelo, objeto_id='', descripcion='', request=None, usuario=_ACTOR_ACTUAL,
                 alias=None, empresa=None, atencion=None, modulo='', operacion='', resultado='completada', cambios=None):
    if usuario is _ACTOR_ACTUAL:
        usuario = getattr(request, 'user', None)
    if usuario is not None and not usuario.is_authenticated:
        usuario = None
    alias = alias or Auditoria.objects.db
    datos = datos_registro(request, usuario=usuario, empresa=empresa, atencion=atencion,
                          modulo=modulo or MODULOS.get(modelo, modelo), operacion=operacion,
                          resultado=resultado, cambios=cambios)
    # Los identificadores de usuarios se repiten entre bases: no crear una FK cruzada.
    return Auditoria.objects.using(alias).create(
        usuario_id=usuario.pk if usuario and usuario._state.db == alias else None, accion=accion, modelo=modelo,
        objeto_id=str(objeto_id), descripcion=descripcion, **datos)
