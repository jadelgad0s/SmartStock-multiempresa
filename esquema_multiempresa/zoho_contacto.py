"""Cliente acotado a un único buzón Zoho. No usa contraseñas de usuarios Django."""
import hashlib
import re
from html import unescape
from html.parser import HTMLParser

import requests
from django.conf import settings
from django.core.cache import cache

from .permisos import CORREO_CONTACTO


class ErrorZoho(Exception):
    """Mensaje apto para pantalla, sin cuerpos de respuestas ni secretos."""


class EnvioIncierto(ErrorZoho):
    pass


def zoho_configurado():
    return bool(settings.ZOHO_CONTACTO_CLIENT_ID and settings.ZOHO_CONTACTO_CLIENT_SECRET
                and settings.ZOHO_CONTACTO_REFRESH_TOKEN)


def servidores():
    dc = settings.ZOHO_CONTACTO_DC
    # Nunca se acepta una URL arbitraria suministrada por una petición.
    if dc not in ('com', 'eu', 'in', 'com.au', 'jp'):
        raise ErrorZoho('Revisa el centro de datos de Zoho configurado para este buzón.')
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


class ClienteZoho:
    def __init__(self):
        if not zoho_configurado():
            raise ErrorZoho('Zoho Mail aún no está conectado. Solicita la conexión al superusuario de SmartStock.')
        self.accounts, self.mail = servidores()
        firma = hashlib.sha256((settings.ZOHO_CONTACTO_CLIENT_ID + ':' + settings.ZOHO_CONTACTO_REFRESH_TOKEN).encode()).hexdigest()
        self.cache_key = f'contacto-zoho-token:{settings.ZOHO_CONTACTO_DC}:{firma}'
        self.token = cache.get(self.cache_key)
        if not self.token:
            self.renovar_token()
        self.cuenta = None

    def renovar_token(self):
        try:
            respuesta = requests.post(self.accounts + '/oauth/v2/token', data={
                'grant_type': 'refresh_token', 'client_id': settings.ZOHO_CONTACTO_CLIENT_ID,
                'client_secret': settings.ZOHO_CONTACTO_CLIENT_SECRET,
                'refresh_token': settings.ZOHO_CONTACTO_REFRESH_TOKEN,
            }, timeout=(5, 15), allow_redirects=False)
            datos = respuesta.json()
            token = datos.get('access_token') if respuesta.status_code == 200 else None
            if not isinstance(token, str) or not token:
                raise ValueError
        except (requests.RequestException, ValueError, AttributeError):
            raise ErrorZoho('No se pudo autorizar el buzón en Zoho. Solicita revisar la conexión.') from None
        self.token = token
        cache.set(self.cache_key, token, timeout=3000)

    def pedir(self, metodo, ruta, *, params=None, datos=None):
        try:
            respuesta = requests.request(metodo, self.mail + '/api' + ruta, params=params, json=datos,
                                         headers={'Authorization': 'Zoho-oauthtoken ' + self.token},
                                         timeout=(5, 20), allow_redirects=False)
        except requests.RequestException:
            if metodo == 'POST':
                raise EnvioIncierto('Zoho no confirmó el envío. Revisa Enviados en Zoho antes de volver a responder.') from None
            raise ErrorZoho('No pudimos consultar Zoho. Inténtalo nuevamente más tarde.') from None
        if respuesta.status_code == 401:
            cache.delete(self.cache_key)
        if respuesta.status_code >= 500 and metodo == 'POST':
            raise EnvioIncierto('Zoho no confirmó el envío. Revisa Enviados en Zoho antes de volver a responder.')
        try:
            if len(respuesta.content) > 2_000_000:
                raise ValueError
            payload = respuesta.json()
            if not 200 <= respuesta.status_code < 300 or not 200 <= int(payload['status']['code']) < 300:
                raise ValueError
            return payload['data']
        except (ValueError, TypeError, KeyError):
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
        datos = self.pedir('GET', f'/accounts/{cuenta}/messages/view', params={
            'start': inicio, 'limit': 100, 'status': 'all', 'sortBy': 'date', 'sortorder': 'false',
            'includesent': 'false', 'includearchive': 'true', 'threadedMails': 'false', 'includeto': 'true',
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
