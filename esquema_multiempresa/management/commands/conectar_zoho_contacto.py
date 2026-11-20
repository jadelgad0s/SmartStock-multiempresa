"""Canje local de un código Self Client; no imprime tokens ni envía correos."""
import getpass
import os
from pathlib import Path
import re
import tempfile

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from esquema_multiempresa.permisos import CORREO_CONTACTO
from esquema_multiempresa.zoho_contacto import ErrorZoho, servidores


class Command(BaseCommand):
    help = 'Guarda privadamente en .env el token de conexión del buzón exclusivo de contacto.'
    requires_system_checks = []

    def handle(self, *args, **options):
        if not settings.ZOHO_CONTACTO_CLIENT_ID or not settings.ZOHO_CONTACTO_CLIENT_SECRET:
            raise CommandError('Completa ZOHO_CONTACTO_CLIENT_ID y ZOHO_CONTACTO_CLIENT_SECRET en .env antes de conectar.')
        try:
            accounts, mail = servidores()
        except ErrorZoho as error:
            raise CommandError(str(error)) from None
        codigo = getpass.getpass('Código de autorización Self Client de Zoho (oculto): ').strip()
        if not codigo:
            raise CommandError('No se ingresó un código de autorización.')
        try:
            respuesta = requests.post(accounts + '/oauth/v2/token', data={
                'grant_type': 'authorization_code', 'client_id': settings.ZOHO_CONTACTO_CLIENT_ID,
                'client_secret': settings.ZOHO_CONTACTO_CLIENT_SECRET, 'code': codigo,
            }, timeout=(5, 20), allow_redirects=False)
            datos = respuesta.json()
            refresh, access = datos.get('refresh_token'), datos.get('access_token')
            if respuesta.status_code != 200 or not isinstance(refresh, str) or not re.fullmatch(r'[A-Za-z0-9._:-]+', refresh) or not isinstance(access, str):
                raise ValueError
            comprobacion = requests.get(mail + '/api/accounts', headers={'Authorization': 'Zoho-oauthtoken ' + access},
                                        timeout=(5, 20), allow_redirects=False)
            cuentas = comprobacion.json().get('data')
            if comprobacion.status_code != 200 or not isinstance(cuentas, list) or not any(
                    isinstance(cuenta, dict) and str(cuenta.get('primaryEmailAddress') or cuenta.get('mailboxAddress') or '').lower() == CORREO_CONTACTO
                    for cuenta in cuentas):
                raise ValueError
        except (requests.RequestException, ValueError, TypeError, AttributeError):
            raise CommandError('Zoho no autorizó el buzón de contacto. Revisa la cuenta, el centro de datos, los permisos y la vigencia del código.') from None
        destino = Path(settings.BASE_DIR) / '.env'
        temporal = None
        try:
            contenido = destino.read_text(encoding='utf-8') if destino.exists() else ''
            linea = 'ZOHO_CONTACTO_REFRESH_TOKEN=' + refresh
            patron = r'(?m)^\s*ZOHO_CONTACTO_REFRESH_TOKEN\s*=.*$'
            contenido = re.sub(patron, linea, contenido) if re.search(patron, contenido) else contenido.rstrip('\n') + '\n' + linea + '\n'
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=destino.parent, delete=False) as archivo:
                temporal = Path(archivo.name)
                archivo.write(contenido)
                archivo.flush()
                os.fsync(archivo.fileno())
            os.replace(temporal, destino)
        except OSError:
            raise CommandError('No pudimos guardar la conexión en .env. Revisa los permisos de esa carpeta.') from None
        finally:
            if temporal and temporal.exists():
                temporal.unlink()
        self.stdout.write(self.style.SUCCESS('Conexión del buzón de contacto guardada en .env. Reinicia el servidor. No se enviaron correos.'))
