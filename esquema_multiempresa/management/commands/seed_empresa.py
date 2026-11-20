from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from apps.core.empresa import usar_empresa
from esquema_multiempresa.acceso import empresa_activa


class Command(BaseCommand):
    help = 'Prepara los permisos, roles y administrador de negocio de una empresa de pruebas.'

    def add_arguments(self, parser):
        parser.add_argument('codigo', help='Código de empresa registrado en la central.')
        parser.add_argument('--sin-admin', action='store_true', help='Crea solo permisos y roles.')

    def handle(self, *args, **options):
        empresa = empresa_activa(options['codigo'])
        if empresa is None:
            raise CommandError('Empresa inactiva, desconocida o sin una base configurada.')
        self.stdout.write(f'{empresa.nombre} ({empresa.alias_bd})')
        with usar_empresa(empresa):
            call_command('seed', sin_admin=options['sin_admin'], stdout=self.stdout, stderr=self.stderr)
