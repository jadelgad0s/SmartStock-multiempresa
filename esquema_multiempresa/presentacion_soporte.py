"""Presentación del flujo de soporte a partir de sus estados y eventos existentes."""
from django.utils import timezone

from .permisos import es_personal_smartstock


def situacion_atencion(atencion, solicitudes):
    solicitudes = list(solicitudes)
    pendiente = next((s for s in solicitudes if s.estado == 'pendiente'), None)
    vigente = next((s for s in solicitudes if s.estado == 'aprobado' and s.expira_en
        and s.expira_en > timezone.now() and s.tecnico_id == atencion.tecnico_id), None)
    if (atencion.estado != 'abierta' or not atencion.empresa.activa
            or not atencion.tecnico or not es_personal_smartstock(atencion.tecnico)):
        vigente = None
    codigo, etiqueta, tono, paso = 'sin_solicitud', 'Sin autorización solicitada', 'neutro', 0
    mensaje = 'Solicita los permisos necesarios para comenzar la revisión.'
    if atencion.estado == 'cerrada':
        codigo, etiqueta, paso = 'finalizada', 'Accesos finalizados', 3
        mensaje = 'La atención está finalizada y sus accesos fueron retirados.'
    elif not atencion.empresa.activa:
        codigo, etiqueta, tono = 'suspendida', 'Empresa inactiva', 'aviso'
        mensaje = 'La empresa está inactiva. Sus datos no están disponibles para consultas de soporte.'
    elif not atencion.tecnico or not es_personal_smartstock(atencion.tecnico):
        codigo, etiqueta, tono = 'sin_responsable', 'Sin responsable habilitado', 'aviso'
        mensaje = 'Asigna una cuenta del equipo habilitada para continuar con la atención.'
    elif vigente:
        codigo, etiqueta, tono, paso = 'autorizado', 'Acceso autorizado', 'correcto', 2
        mensaje = 'El responsable puede realizar las consultas autorizadas y registrar el resultado al finalizar.'
        if pendiente:
            mensaje += ' La empresa también tiene una nueva solicitud pendiente de decisión.'
    elif pendiente:
        codigo, etiqueta, tono, paso = 'pendiente', 'Pendiente de autorización', 'aviso', 1
        mensaje = 'Espera la decisión del administrador de la empresa sobre los permisos solicitados.'
    elif solicitudes:
        ultima = solicitudes[0]
        codigo = 'vencido' if ultima.estado == 'aprobado' else ultima.estado
        etiqueta = {'vencido': 'Acceso vencido', 'rechazado': 'Solicitud rechazada',
                    'revocado': 'Acceso revocado'}.get(codigo, ultima.estado_visible)
        tono = 'aviso' if codigo == 'rechazado' else 'neutro'
        mensaje = 'Puedes solicitar una nueva autorización si necesitas continuar la revisión.'
    actuales = [s for s in solicitudes if s is pendiente or s is vigente] if atencion.estado == 'abierta' else []
    return {'codigo': codigo, 'etiqueta': etiqueta, 'tono': tono, 'mensaje': mensaje, 'paso': paso,
            'vigente': vigente, 'pendiente': pendiente, 'actuales': actuales,
            'historicas': [s for s in solicitudes if s not in actuales],
            'pasos': [{'nombre': nombre, 'actual': i == paso, 'completo': i < paso or atencion.estado == 'cerrada'}
                      for i, nombre in enumerate(('Solicitar acceso', 'Autorización de la empresa', 'Revisión', 'Finalizar'))]}


TITULOS_EVENTOS = {
    'Atención creada': 'Atención creada', 'Consulta del cliente': 'Consulta recibida de la empresa',
    'Acceso de soporte solicitado': 'Permisos solicitados',
    'Acceso de soporte aprobado': 'Autorización aprobada',
    'Acceso de soporte rechazado': 'Autorización rechazada',
    'Acceso de soporte revocado': 'Acceso revocado por la empresa',
    'Acceso de soporte retirado': 'Solicitud o acceso retirado',
    'Responsable de la atención actualizado': 'Responsable actualizado',
    'Atención de soporte cerrada': 'Atención finalizada',
    'Atención finalizada por el administrador de la empresa.': 'Atención finalizada por la empresa',
}


def presentar_evento_soporte(evento):
    actor = evento.actor if isinstance(evento.actor, dict) else {}
    persona = actor.get('nombre') or actor.get('email')
    if not persona and evento.usuario_id:
        persona = evento.usuario.nombre_completo or evento.usuario.email
    titulo = TITULOS_EVENTOS.get(evento.operacion)
    if not titulo:
        if evento.accion == 'CONSULTA':
            titulo = {'completada': 'Consulta realizada', 'denegada': 'Consulta denegada',
                      'fallida': 'Consulta no completada'}.get(evento.resultado, 'Consulta registrada')
        else:
            titulo = {'CREATE': 'Creación registrada', 'UPDATE': 'Atención actualizada',
                      'ACCESS_DENIED': 'Acceso denegado'}.get(evento.accion, 'Evento registrado')
    return {'evento': evento, 'titulo': titulo, 'persona': persona or 'Persona no identificada'}
