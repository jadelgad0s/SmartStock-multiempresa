"""Cliente acotado a un único buzón Zoho. No usa contraseñas de usuarios Django."""
import hashlib
import base64
import json
import re
from html import unescape
from html.parser import HTMLParser

import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .permisos import CORREO_CONTACTO
from .models import BuzonContacto


class ErrorZoho(Exception):
    """Mensaje apto para pantalla, sin cuerpos de respuestas ni secretos."""
    def __init__(self, mensaje, *, codigo='conexion'):
        super().__init__(mensaje)
        self.codigo = codigo


class EnvioIncierto(ErrorZoho):
    pass


_BUZON_NO_CARGADO = object()


def zoho_configurado(*, buzon=_BUZON_NO_CARGADO):
    guardada = (BuzonContacto.objects.using('central').exclude(credenciales_cifradas='').exists()
                if buzon is _BUZON_NO_CARGADO else bool(buzon and buzon.credenciales_cifradas))
    return bool(guardada
                or settings.ZOHO_CONTACTO_CLIENT_ID and settings.ZOHO_CONTACTO_CLIENT_SECRET
                and settings.ZOHO_CONTACTO_REFRESH_TOKEN)


def cifrador():
    claves = [settings.SECRET_KEY, *settings.SECRET_KEY_FALLBACKS]
    return MultiFernet([Fernet(base64.urlsafe_b64encode(HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None,
        info=b'smartstock-buzon-contacto-v1').derive(clave.encode()))) for clave in claves])


def cifrar_configuracion(datos):
    return cifrador().encrypt(json.dumps(datos).encode()).decode()


@sensitive_variables()
def configuracion_zoho(*, buzon=_BUZON_NO_CARGADO):
    cifrada = (BuzonContacto.objects.using('central').values_list('credenciales_cifradas', flat=True).first()
               if buzon is _BUZON_NO_CARGADO else buzon.credenciales_cifradas if buzon else '')
    if cifrada:
        try:
            datos = json.loads(cifrador().decrypt(cifrada.encode()))
            if not isinstance(datos, dict) or not all(isinstance(datos.get(campo), str) and datos[campo]
                    for campo in ('client_id', 'client_secret', 'refresh_token', 'dc')):
                raise ValueError
            return datos
        except (InvalidToken, ValueError, TypeError):
            raise ErrorZoho('La autorización guardada necesita renovarse. El superusuario debe volver a conectar Zoho.', codigo='autorizacion') from None
    return {'client_id': settings.ZOHO_CONTACTO_CLIENT_ID, 'client_secret': settings.ZOHO_CONTACTO_CLIENT_SECRET,
            'refresh_token': settings.ZOHO_CONTACTO_REFRESH_TOKEN, 'dc': settings.ZOHO_CONTACTO_DC}


def servidores(dc=None, *, buzon=_BUZON_NO_CARGADO):
    dc = dc or configuracion_zoho(buzon=buzon)['dc']
    # Nunca se acepta una URL arbitraria suministrada por una petición.
    if dc not in ('com', 'eu', 'in', 'com.au', 'jp'):
        raise ErrorZoho('Revisa el centro de datos de Zoho configurado para este buzón.', codigo='autorizacion')
    return f'https://accounts.zoho.{dc}', f'https://mail.zoho.{dc}'


def identificador(valor):
    valor = str(valor)
    if not re.fullmatch(r'[0-9]{1,40}', valor):
        raise ErrorZoho('Zoho devolvió una identificación de correo no válida.')
    return valor


class TextoCorreo(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.textos = []
        self.oculto = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'head'):
            self.oculto += 1
        if tag in ('br', 'p', 'div', 'li', 'tr') and not self.oculto:
            self.textos.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'head') and self.oculto:
            self.oculto -= 1
        elif tag in ('p', 'div', 'li', 'tr') and not self.oculto:
            self.textos.append('\n')

    def handle_data(self, data):
        if not self.oculto:
            self.textos.append(data)


def texto_correo(contenido):
    parser = TextoCorreo()
    parser.feed(str(contenido)[:500_000])
    return re.sub(r'\n[ \t]*\n[ \t]*\n+', '\n\n', ''.join(parser.textos)).strip()[:100_000]


def texto_cabecera(valor, limite):
    return re.sub(r'[\r\n\x00-\x1f\x7f]', ' ', unescape(str(valor or ''))).strip()[:limite]


@sensitive_variables()
def autorizar_codigo(*, centro, client_id, client_secret, codigo):
    accounts, _ = servidores(centro)
    try:
        respuesta = requests.post(accounts + '/oauth/v2/token', data={
            'grant_type': 'authorization_code', 'client_id': client_id,
            'client_secret': client_secret, 'code': codigo,
        }, timeout=(5, 15), allow_redirects=False)
        datos = respuesta.json()
        if respuesta.status_code != 200 or not all(isinstance(datos.get(campo), str) and datos[campo]
                for campo in ('access_token', 'refresh_token')):
            raise ValueError
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        raise ErrorZoho('Zoho no aceptó el código. Genera uno nuevo y comprueba el Client ID, Client Secret y centro de datos.', codigo='autorizacion') from None
    config = {'client_id': client_id, 'client_secret': client_secret, 'refresh_token': datos['refresh_token'], 'dc': centro}
    cliente = ClienteZoho(config, token=datos['access_token'])
    cliente.comprobar_cuenta()
    return config, cliente


class ClienteZoho:
    def __init__(self, configuracion=None, *, token=None):
        self.configuracion = configuracion or configuracion_zoho()
        if not all(self.configuracion.get(campo) for campo in ('client_id', 'client_secret', 'refresh_token')):
            raise ErrorZoho('Zoho Mail aún no está conectado. El superusuario debe abrir Cuenta de contacto → Conectar Zoho.', codigo='sin_configuracion')
        self.accounts, self.mail = servidores(self.configuracion['dc'])
        firma = hashlib.sha256((self.configuracion['client_id'] + ':' + self.configuracion['refresh_token']).encode()).hexdigest()
        self.cache_key = f'contacto-zoho-token:{self.configuracion["dc"]}:{firma}'
        self.token = token or cache.get(self.cache_key)
        if not self.token:
            self.renovar_token()
        self.cuenta = None

    @sensitive_variables()
    def renovar_token(self):
        try:
            respuesta = requests.post(self.accounts + '/oauth/v2/token', data={
                'grant_type': 'refresh_token', 'client_id': self.configuracion['client_id'],
                'client_secret': self.configuracion['client_secret'],
                'refresh_token': self.configuracion['refresh_token'],
            }, timeout=(5, 15), allow_redirects=False)
            datos = respuesta.json()
            token = datos.get('access_token') if respuesta.status_code == 200 else None
            if not isinstance(token, str) or not token:
                raise ValueError
        except (requests.RequestException, ValueError, AttributeError):
            raise ErrorZoho('Zoho no autorizó el buzón. El superusuario debe revisar el centro de datos o renovar la conexión.', codigo='autorizacion') from None
        self.token = token
        cache.set(self.cache_key, token, timeout=3000)

    @sensitive_variables()
    def pedir(self, metodo, ruta, *, params=None, datos=None, _renovado=False):
        try:
            respuesta = requests.request(metodo, self.mail + '/api' + ruta, params=params, json=datos,
                                         headers={'Authorization': 'Zoho-oauthtoken ' + self.token},
                                         timeout=(5, 20), allow_redirects=False)
        except requests.RequestException:
            if metodo == 'POST':
                raise EnvioIncierto('Zoho no confirmó el envío. Revisa Enviados en Zoho antes de volver a responder.') from None
            raise ErrorZoho('No pudimos conectar con Zoho. Revisa Internet e inténtalo nuevamente.', codigo='red') from None
        if respuesta.status_code == 401:
            cache.delete(self.cache_key)
            if metodo == 'GET' and not _renovado:
                self.renovar_token()
                return self.pedir(metodo, ruta, params=params, datos=datos, _renovado=True)
            raise ErrorZoho('La autorización de Zoho caducó o fue revocada. Solicita volver a conectar el buzón.', codigo='autorizacion')
        if respuesta.status_code == 403:
            raise ErrorZoho('Zoho no concedió permisos para esta operación. Autoriza lectura y creación de mensajes desde Cuenta de contacto.', codigo='permisos')
        if respuesta.status_code == 429:
            raise ErrorZoho('Zoho limitó temporalmente las consultas. Espera un minuto antes de reintentar.', codigo='limite')
        if respuesta.status_code >= 500 and metodo == 'POST':
            raise EnvioIncierto('Zoho no confirmó el envío. Revisa Enviados en Zoho antes de volver a responder.')
        try:
            if len(respuesta.content) > 2_000_000:
                raise ValueError
            payload = respuesta.json()
            codigo = int(payload['status']['code'])
            if codigo == 403:
                raise ErrorZoho('Zoho no concedió permisos para esta operación. Autoriza lectura y creación de mensajes desde Cuenta de contacto.', codigo='permisos')
            if codigo == 401:
                cache.delete(self.cache_key)
                raise ErrorZoho('La autorización de Zoho caducó o fue revocada. Solicita volver a conectar el buzón.', codigo='autorizacion')
            if codigo == 429:
                raise ErrorZoho('Zoho limitó temporalmente las consultas. Espera un minuto antes de reintentar.', codigo='limite')
            if 400 <= codigo < 500:
                raise ErrorZoho('Zoho rechazó la operación. Revisa los permisos o el correo original antes de reintentar.')
            if not 200 <= respuesta.status_code < 300 or not 200 <= codigo < 300:
                raise ValueError
            return payload['data']
        except (ValueError, TypeError, KeyError, AttributeError):
            if metodo == 'POST' and 200 <= respuesta.status_code < 300:
                raise EnvioIncierto('La respuesta de Zoho no permitió confirmar el envío. Revisa Enviados en Zoho.') from None
            raise ErrorZoho('Zoho rechazó la operación. Revisa los permisos y la conexión del buzón.') from None

    def comprobar_cuenta(self):
        if self.cuenta:
            return self.cuenta
        cuentas = self.pedir('GET', '/accounts')
        if not isinstance(cuentas, list):
            raise ErrorZoho('No pudimos identificar el buzón de contacto en Zoho.')
        for cuenta in cuentas:
            # Solo el buzón principal exacto: no se importan buzones personales
            # ni otras cuentas aunque el token OAuth tenga acceso a ellas.
            if isinstance(cuenta, dict) and str(cuenta.get('primaryEmailAddress') or cuenta.get('mailboxAddress') or '').lower() == CORREO_CONTACTO:
                self.cuenta = identificador(cuenta.get('accountId'))
                return self.cuenta
        raise ErrorZoho('La conexión no corresponde al buzón contacto@smartstockchile.cl.')

    def listar(self, inicio=1):
        cuenta = self.comprobar_cuenta()
        # /messages/view sin folderId no identifica la bandeja de entrada.
        # La búsqueda explícita usa el permiso messages.READ ya concedido;
        # no necesita acceso adicional para enumerar las carpetas del buzón.
        datos = self.pedir('GET', f'/accounts/{cuenta}/messages/search', params={
            'searchKey': 'in:Inbox::groupResult:false',
            'start': inicio, 'limit': 100, 'includeto': 'true',
            # Sin este parámetro Zoho omite por defecto los últimos dos minutos.
            'receivedTime': int(timezone.now().timestamp() * 1000),
        })
        if not isinstance(datos, list) or len(datos) > 100 or not all(isinstance(fila, dict) for fila in datos):
            raise ErrorZoho('No pudimos interpretar la lista de correos de Zoho.')
        return cuenta, datos

    def contenido(self, mensaje):
        cuenta = self.comprobar_cuenta()
        if cuenta != mensaje.cuenta_zoho:
            raise ErrorZoho('El correo no pertenece al buzón conectado.')
        carpeta, correo = identificador(mensaje.carpeta_zoho), identificador(mensaje.mensaje_zoho)
        contenido = self.pedir('GET', f'/accounts/{cuenta}/folders/{carpeta}/messages/{correo}/content',
                               params={'includeBlockContent': 'true'})
        if not isinstance(contenido, dict) or not isinstance(contenido.get('content'), str):
            raise ErrorZoho('No pudimos leer el contenido de este correo. Puedes abrirlo en Zoho.')
        return texto_correo(contenido['content'])

    def responder(self, mensaje, texto):
        cuenta = self.comprobar_cuenta()
        if cuenta != mensaje.cuenta_zoho:
            raise ErrorZoho('El correo no pertenece al buzón conectado.')
        resultado = self.pedir('POST', f'/accounts/{cuenta}/messages/{identificador(mensaje.mensaje_zoho)}', datos={
            'fromAddress': CORREO_CONTACTO, 'toAddress': mensaje.remitente_email,
            'subject': texto_cabecera('Re: ' + mensaje.asunto, 300), 'content': texto,
            'action': 'reply', 'mailFormat': 'plaintext', 'encoding': 'UTF-8', 'askReceipt': 'no',
        })
        if not isinstance(resultado, dict) or not resultado.get('messageId'):
            raise EnvioIncierto('Zoho no devolvió la identificación del envío. Revisa Enviados en Zoho.')
        try:
            return identificador(resultado['messageId'])
        except ErrorZoho:
            raise EnvioIncierto('Zoho no devolvió una identificación válida del envío. Revisa Enviados en Zoho.') from None
