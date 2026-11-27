"""Preparación repetible del entorno local de Docker."""
from io import StringIO
from secrets import token_urlsafe
from decouple import config

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.empresa import usar_empresa
from apps.usuarios.models import Rol, Usuario
from esquema_multiempresa.models import Empresa


class Command(BaseCommand):
    help = 'Aplica migraciones y crea las cuentas iniciales del entorno Docker local.'

    def handle(self, *args, **options):
        if not getattr(settings, 'DOCKER_LOCAL_DEMO', False):
            raise CommandError('Utiliza este comando con esquema_multiempresa.docker.')
        for alias in ('central', *settings.BASES_EMPRESA):
            call_command('migrate', database=alias, interactive=False, stdout=self.stdout)
        call_command('registrar_empresas_prueba', stdout=self.stdout)
        self.crear_cuenta('central', 'tecnico@smartstock.test', 'Técnico', superusuario=True)
        cuentas = (
            ('la-fragua', 'admin.lafragua@smartstock.test', 'Administración La Fragua'),
            ('punto-motor', 'admin.puntomotor@smartstock.test', 'Administración Punto Motor'),
        )
        for codigo, email, nombre in cuentas:
            empresa = Empresa.objects.using('central').get(codigo=codigo)
            with usar_empresa(empresa):
                if not Rol.objects.filter(codigo='administrador').exists():
                    call_command('seed_empresa', codigo, sin_admin=True, stdout=StringIO())
                self.crear_cuenta(empresa.alias_bd, email, nombre)
        self.stdout.write(self.style.SUCCESS('Entorno Docker multiempresa preparado.'))

    def crear_cuenta(self, alias, email, nombre, superusuario=False):
        consulta = Usuario.objects.db_manager(alias)
        with transaction.atomic(using=alias):
            # La preparación inicial respeta las cuentas que ya tiene cada base.
            existentes = consulta.filter(is_superuser=True) if superusuario else consulta.all()
            if existentes.exists():
                return
            password = config('SS_DOCKER_DEMO_PASSWORD', default='') or token_urlsafe(18)
            datos = {'email': email, 'password': password, 'nombres': nombre, 'apellidos': 'Demo'}
            if superusuario:
                consulta.create_superuser(**datos)
            else:
                consulta.create_user(**datos, rol=Rol.objects.using(alias).get(codigo='administrador'))
        self.stdout.write(f'Cuenta inicial de {alias} creada · {email}')
        if not config('SS_DOCKER_DEMO_PASSWORD', default=''):
            self.stdout.write(f'Contraseña inicial · {password}')
