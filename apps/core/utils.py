"""
Utilidades comunes del sistema.
"""
from .middleware import get_current_user, get_current_request
from .registro_auditoria import crear_evento


def registrar_auditoria(accion, modelo, objeto_id='', descripcion='', usuario_override=None):
    """
    Registra una acción en el log de auditoría.

    Args:
        accion: Tipo de acción (CREATE, UPDATE, DEACTIVATE, REACTIVATE, DELETE, LOGIN, etc.)
        modelo: Nombre del modelo afectado
        objeto_id: ID del objeto sobre el que se realizó la acción
        descripcion: Descripción libre del evento
    """
    request = get_current_request()
    usuario = usuario_override if usuario_override else get_current_user()

    crear_evento(
        usuario=usuario,
        accion=accion,
        modelo=modelo,
        objeto_id=str(objeto_id),
        descripcion=descripcion,
        request=request,
        resultado='fallida' if accion == 'LOGIN_FAILED' else 'completada',
    )

