from django.core.management.base import BaseCommand, CommandError

from esquema_multiempresa.buzon_contacto import sincronizar_buzon
from esquema_multiempresa.zoho_contacto import ErrorZoho


class Command(BaseCommand):
    help = 'Consulta el buzón de contacto conectado a Zoho, sin enviar correos.'

    def add_arguments(self, parser):
        parser.add_argument('--anteriores', action='store_true', help='Carga el siguiente lote de correos anteriores.')

    def handle(self, *args, **opciones):
        try:
            nuevos = sincronizar_buzon(anteriores=opciones['anteriores'])
        except ErrorZoho as error:
            raise CommandError(str(error)) from None
        self.stdout.write(self.style.SUCCESS(f'Bandeja consultada: {nuevos} correo(s) incorporado(s).'))
