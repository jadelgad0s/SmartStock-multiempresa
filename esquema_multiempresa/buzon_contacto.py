"""Importación y envío con deduplicación y control de peticiones simultáneas."""
from datetime import datetime, timedelta, timezone as tz
from email.utils import parseaddr
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import F, Q
from django.urls import reverse
from django.utils import timezone

from apps.usuarios.models import Usuario
from .models import BuzonContacto, MensajeContacto, NotificacionSistema, RespuestaContacto
from .permisos import CONTACTO, CORREO_CONTACTO
from .zoho_contacto import ClienteZoho, EnvioIncierto, ErrorZoho, identificador, texto_cabecera, texto_correo


def importar_fila(cuenta, fila):
    correo, carpeta = identificador(fila.get('messageId')), identificador(fila.get('folderId'))
    remitente = parseaddr(texto_cabecera(fila.get('fromAddress'), 500))[1].lower()
    try:
        validate_email(remitente)
    except ValidationError:
        remitente = ''  # Visible pero no respondible; nunca inventar un destino.
    try:
        fecha = datetime.fromtimestamp(int(fila['receivedTime']) / 1000, tz=tz.utc)
    except (KeyError, ValueError, TypeError, OverflowError, OSError):
        raise ErrorZoho('Zoho devolvió un correo sin fecha válida. No se completó esta consulta.') from None
    mensaje, nuevo = MensajeContacto.objects.using('central').get_or_create(
        cuenta_zoho=cuenta, mensaje_zoho=correo,
        defaults={'carpeta_zoho': carpeta, 'remitente_nombre': texto_cabecera(fila.get('sender'), 200),
                  'remitente_email': remitente, 'asunto': texto_cabecera(fila.get('subject'), 300),
                  'resumen': texto_correo(fila.get('summary', ''))[:1000], 'recibido_en': fecha,
                  'tiene_adjuntos': str(fila.get('hasAttachment', '0')).lower() in ('1', 'true')},
    )
    if not nuevo and mensaje.carpeta_zoho != carpeta:
        MensajeContacto.objects.using('central').filter(pk=mensaje.pk).update(carpeta_zoho=carpeta)
    return nuevo


def sincronizar_buzon(*, anteriores=False, forzar=False, cliente=None):
    buzon, _ = BuzonContacto.objects.using('central').get_or_create(pk=1)
    ahora, token = timezone.now(), uuid4()
    if not forzar and not anteriores and buzon.ultima_consulta and buzon.ultima_consulta > ahora - timedelta(seconds=30):
        return 0
    disponibles = BuzonContacto.objects.using('central').filter(pk=1).filter(
        Q(bloqueo__isnull=True) | Q(iniciado_en__lt=ahora - timedelta(minutes=3)))
    if not disponibles.update(bloqueo=token, iniciado_en=ahora):
        raise ErrorZoho('La bandeja ya se está actualizando. Espera un momento.', codigo='ocupado')
    try:
        cliente = cliente or ClienteZoho()
        inicio = buzon.siguiente_pagina if anteriores else 1
        if anteriores and buzon.historial_completo:
            return 0
        cuenta, filas = cliente.listar(inicio)
        if buzon.cuenta_zoho and cuenta != buzon.cuenta_zoho:
            raise ErrorZoho('El buzón conectado cambió. Solicita revisar la conexión antes de importar correos.')
        with transaction.atomic(using='central'):
            nuevos = sum(importar_fila(cuenta, fila) for fila in filas)
            if anteriores or not buzon.ultima_consulta or nuevos >= 100:
                siguiente = inicio + len(filas)
                completo = len(filas) < 100
            else:
                # La consulta automática de recientes no reinicia el avance
                # por el archivo. Los nuevos correos desplazan ese índice.
                siguiente = max(buzon.siguiente_pagina + nuevos, len(filas) + 1)
                completo = buzon.historial_completo or len(filas) < 100
            BuzonContacto.objects.using('central').filter(pk=1, bloqueo=token).update(
                cuenta_zoho=cuenta, ultima_consulta=ahora, siguiente_pagina=siguiente,
                historial_completo=completo, conexion_estado='conectado', ultimo_error='', comprobado_en=timezone.now())
            destinatario = Usuario.objects.using('central').filter(
                email=CORREO_CONTACTO, rol__codigo=CONTACTO, rol__activo=True,
                is_staff=True, is_superuser=False, activo=True).first()
            if nuevos and destinatario:
                NotificacionSistema.objects.using('central').create(
                    destinatario=destinatario, titulo='Correos recibidos',
                    mensaje=f'{nuevos} correo(s) incorporado(s) a la bandeja de contacto.',
                    link=reverse('contacto_bandeja', urlconf='esquema_multiempresa.urls_central'))
        return nuevos
    except ErrorZoho as error:
        BuzonContacto.objects.using('central').filter(pk=1, bloqueo=token).update(
            conexion_estado='pendiente' if error.codigo == 'sin_configuracion' else 'error',
            ultimo_error=str(error)[:400], comprobado_en=timezone.now())
        raise
    finally:
        BuzonContacto.objects.using('central').filter(pk=1, bloqueo=token).update(bloqueo=None, iniciado_en=None)


def enviar_respuesta(respuesta, version):
    """Un borrador guardado se envía una sola vez; los fallos ambiguos no se reintentan."""
    cliente = ClienteZoho()
    cliente.comprobar_cuenta()  # La autorización puede fallar sin iniciar un envío.
    try:
        validate_email(respuesta.mensaje.remitente_email)
    except ValidationError:
        raise ErrorZoho('El remitente de este correo no tiene una dirección válida para responder.') from None
    with transaction.atomic(using='central'):
        MensajeContacto.objects.using('central').select_for_update().get(pk=respuesta.mensaje_id)
        if RespuestaContacto.objects.using('central').filter(
                mensaje_id=respuesta.mensaje_id, estado__in=('enviando', 'incierta')).exists():
            raise ErrorZoho('Hay un envío sin confirmar. Revísalo en Zoho antes de responder.')
        reclamadas = RespuestaContacto.objects.using('central').filter(
            pk=respuesta.pk, estado='borrador', version=version).update(
            estado='enviando', iniciado_en=timezone.now(), version=version + 1)
    if not reclamadas:
        raise ErrorZoho('Este borrador cambió o ya fue enviado. Recarga el correo antes de continuar.')
    try:
        mensaje_zoho = cliente.responder(respuesta.mensaje, respuesta.texto)
    except EnvioIncierto:
        RespuestaContacto.objects.using('central').filter(pk=respuesta.pk).update(estado='incierta')
        raise
    except ErrorZoho:
        RespuestaContacto.objects.using('central').filter(pk=respuesta.pk).update(estado='rechazada')
        raise
    with transaction.atomic(using='central'):
        RespuestaContacto.objects.using('central').filter(pk=respuesta.pk).update(
            estado='enviada', enviada_en=timezone.now(), mensaje_zoho=mensaje_zoho)
        MensajeContacto.objects.using('central').filter(pk=respuesta.mensaje_id, estado='pendiente').update(
            estado='seguimiento', version=F('version') + 1)
    return mensaje_zoho
