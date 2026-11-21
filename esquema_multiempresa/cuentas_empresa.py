"""Invitaciones y recuperación: el enlace solo llega al correo del titular."""
import hashlib
from smtplib import SMTPException

from django.core.cache import cache
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from apps.core.empresa import usar_empresa
from apps.usuarios.models import Usuario
from apps.usuarios.tokens import token_recuperacion
from apps.usuarios.views_recuperacion import RecuperacionClaveForm
from .acceso import direccion_empresa


def hay_administrador(empresa):
    return Usuario.objects.using(empresa.alias_bd).filter(activo=True, rol__codigo='administrador', rol__activo=True).exclude(
        password__startswith='!').exclude(password='').exists()


def puede_invitar_inicial(empresa):
    # La habilitación inicial no sustituye la recuperación de una cuenta ya
    # utilizada, aunque su administrador esté suspendido o haya cambiado de rol.
    return not Usuario.objects.using(empresa.alias_bd).exclude(password__startswith='!').exclude(password='').exists()


def enviar_enlace(request, empresa, usuario):
    """No devuelve el token ni lo registra en auditoría o notificaciones."""
    with usar_empresa(empresa):
        llave = 'enlace-soporte:' + hashlib.sha256(f'{empresa.pk}:{usuario.pk}'.encode()).hexdigest()
        if not cache.add(llave, True, timeout=120):
            return False
        try:
            origen = direccion_empresa(request, empresa)
            protocolo, dominio = origen.split('://', 1)
            contexto = {'email': usuario.email, 'domain': dominio, 'protocol': protocolo,
                'uid': urlsafe_base64_encode(force_bytes(usuario.pk)), 'token': token_recuperacion.make_token(usuario),
                'user': usuario, 'empresa': empresa, 'invitacion': not usuario.has_usable_password()}
            RecuperacionClaveForm().send_mail('soporte/asunto_acceso.txt', 'soporte/correo_acceso.txt',
                contexto, None, usuario.email, html_email_template_name='soporte/correo_acceso.html')
        except (SMTPException, OSError):
            cache.delete(llave)
            raise
        return True
