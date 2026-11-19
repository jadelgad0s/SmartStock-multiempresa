"""Acceso por credenciales y entrega de sesión en la empresa correspondiente."""
import logging
from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.db import DatabaseError
from django.http.request import split_domain_port
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_POST
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.core.empresa import transaccion_operativa, usar_empresa
from apps.core.responses import error_response, success_response
from apps.usuarios.models import Usuario
from apps.usuarios.navegacion import cuenta_habilitada, puede_acceder_admin
from apps.usuarios.serializers import CustomTokenObtainPairSerializer
from apps.usuarios.views_auth import abrir_sesion_web, auditar_login
from .acceso import direccion_empresa
from .models import Empresa, TicketAcceso


logger = logging.getLogger(__name__)


class Credenciales(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(trim_whitespace=False, max_length=4096)


class LimiteAcceso(AnonRateThrottle):
    scope = 'acceso_central'
    rate = '20/min'


def empresas_disponibles():
    return Empresa.objects.filter(activa=True, alias_bd__in=settings.BASES_EMPRESA).order_by('nombre')


@never_cache
def login_central(request):
    if puede_acceder_admin(request.user):
        return redirect('sistema_admin:index')
    respuesta = render(request, 'login.html', {'dominio_empresas': settings.DOMINIO_EMPRESAS})
    # El POST entre direcciones conserva el origen que valida el pase de acceso.
    respuesta['Referrer-Policy'] = 'strict-origin'
    return respuesta


def coincide(usuario, clave):
    return usuario.check_password(clave) and cuenta_habilitada(usuario) and not usuario.esta_bloqueado()


def huella_acceso(usuario, empresa):
    identidad = f'{empresa.pk}:{empresa.alias_bd}:{usuario.get_session_auth_hash()}'
    return salted_hmac('smartstock-acceso-empresa', identidad, algorithm='sha256').hexdigest()


@method_decorator([never_cache, csrf_protect, sensitive_post_parameters('password')], name='dispatch')
class LoginCentralView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [LimiteAcceso]

    def post(self, request):
        formulario = Credenciales(data=request.data)
        if not formulario.is_valid():
            return error_response('Revisa tu correo y contraseña.', status_code=400)
        correo = formulario.validated_data['email'].lower()
        clave = formulario.validated_data['password']
        intentos = []

        try:
            tecnicos = Usuario.objects.using('central').filter(
                email__iexact=correo, is_superuser=True, is_staff=True,
            )
            for usuario in tecnicos:
                if coincide(usuario, clave):
                    usuario.resetear_intentos()
                    abrir_sesion_web(request._request, usuario)
                    auditar_login(usuario)
                    return success_response(data={'sistema': True, 'inicio': '/sistema/'})
                intentos.append((None, usuario))

            accesos = []
            for empresa in empresas_disponibles():
                with usar_empresa(empresa):
                    usuarios = list(Usuario.objects.select_related('rol').filter(email__iexact=correo))
                    if not usuarios:
                        # Consume el coste del hash también para los correos desconocidos.
                        Usuario().set_password(clave)
                    for usuario in usuarios:
                        if coincide(usuario, clave):
                            accesos.append((empresa, usuario))
                        else:
                            intentos.append((empresa, usuario))

            if not accesos:
                for empresa, usuario in intentos:
                    if usuario.activo and not usuario.esta_bloqueado():
                        with usar_empresa(empresa):
                            usuario.registrar_intento_fallido()
                return error_response('Credenciales incorrectas o cuenta no disponible.', status_code=401)

            ahora = timezone.now()
            TicketAcceso.objects.filter(fecha_expiracion__lte=ahora).delete()
            destinos = []
            for empresa, usuario in accesos:
                ticket = TicketAcceso.objects.create(
                    empresa=empresa, usuario_id=usuario.pk,
                    huella_clave=huella_acceso(usuario, empresa),
                    origen=request.build_absolute_uri('/').rstrip('/'),
                    fecha_expiracion=ahora + timedelta(minutes=2),
                )
                destinos.append({
                    'nombre': empresa.nombre,
                    'url': direccion_empresa(request, empresa) + '/acceder/',
                    'ticket': str(ticket.pk),
                })
            return success_response(data={'destinos': destinos})
        except DatabaseError:
            logger.exception('No se pudo consultar el acceso multiempresa.')
            return error_response('No pudimos iniciar sesión en este momento. Inténtalo nuevamente.', status_code=503)


@never_cache
@require_POST
@csrf_exempt
@sensitive_post_parameters('ticket')
def completar_acceso(request):
    """El POST viene del login central, con origen exacto y un ticket de un uso."""
    _, puerto = split_domain_port(request.get_host())
    central = settings.DOMINIO_EMPRESAS + (f':{puerto}' if puerto else '')

    def rechazado():
        return render(request, 'empresas/completar_acceso.html', {
            'error_acceso': 'Este acceso caducó o ya se utilizó. Inicia sesión nuevamente.',
            'entrada_central': f'{request.scheme}://{central}/',
        }, status=403)

    try:
        identificador = UUID(request.POST.get('ticket', ''))
    except (ValueError, TypeError, AttributeError):
        return rechazado()
    ticket = TicketAcceso.objects.filter(
        pk=identificador, empresa=request.empresa,
        fecha_expiracion__gt=timezone.now(),
    ).first()
    if ticket is None or request.headers.get('Origin') != ticket.origen:
        return rechazado()
    usuario = Usuario.objects.select_related('rol').filter(pk=ticket.usuario_id).first()
    if (usuario is None or not cuenta_habilitada(usuario) or usuario.esta_bloqueado()
            or not constant_time_compare(huella_acceso(usuario, request.empresa), ticket.huella_clave)):
        return rechazado()
    consumidos, _ = TicketAcceso.objects.filter(
        pk=ticket.pk, fecha_expiracion__gt=timezone.now(),
    ).delete()
    if consumidos != 1:
        return rechazado()
    with transaccion_operativa():
        usuario.resetear_intentos()
        datos = CustomTokenObtainPairSerializer.datos_sesion(usuario)
        abrir_sesion_web(request, usuario)
        auditar_login(usuario)
    respuesta = render(request, 'empresas/completar_acceso.html', {'datos_sesion': datos})
    respuesta['Referrer-Policy'] = 'no-referrer'
    return respuesta
