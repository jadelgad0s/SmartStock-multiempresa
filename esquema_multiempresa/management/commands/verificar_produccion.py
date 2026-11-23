"""Comprueba las conexiones del despliegue sin modificar registros de inventario."""
import os
from uuid import uuid4

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from apps.core.empresa import usar_empresa
from esquema_multiempresa.models import Empresa


class Command(BaseCommand):
    help = 'Verifica las tres bases de producción y, opcionalmente, archivos privados por empresa.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--probar-archivos', action='store_true',
            help='Escribe, lee y elimina un archivo temporal distinto en cada empresa.',
        )

    def handle(self, *args, **options):
        if os.environ.get('DJANGO_SETTINGS_MODULE') != 'esquema_multiempresa.production':
            raise CommandError('Usa --settings=esquema_multiempresa.production.')
        try:
            for alias in ('central', *settings.BASES_EMPRESA):
                try:
                    with connections[alias].cursor() as cursor:
                        cursor.execute('SELECT current_database()')
                        nombre = cursor.fetchone()[0]
                    if nombre != settings.DATABASES[alias]['NAME']:
                        raise ValueError('La base recibida no coincide.')
                except Exception as exc:
                    raise CommandError(
                        f'No se pudo verificar la base {alias} ({type(exc).__name__}).'
                    ) from None
                self.stdout.write(f'Base {alias}: conexión verificada.')
            if options['probar_archivos']:
                self.probar_archivos()
        finally:
            connections.close_all()
        self.stdout.write(self.style.SUCCESS('Verificación de producción completada.'))

    def probar_archivos(self):
        ruta = f'verificacion-produccion/{uuid4().hex}.txt'
        escritos = []
        fallo = None
        try:
            for alias in settings.BASES_EMPRESA:
                empresa = Empresa.objects.using('central').get(alias_bd=alias)
                contenido = f'Prueba temporal de almacenamiento: {alias}.'.encode()
                with usar_empresa(empresa):
                    nombre = default_storage.save(ruta, ContentFile(contenido))
                escritos.append((empresa, nombre, contenido))
                if nombre != ruta:
                    raise ValueError('El archivo de prueba no conserva su ruta.')
            # El mismo nombre relativo debe conservar contenido diferente en cada empresa.
            for empresa, nombre, contenido in escritos:
                with usar_empresa(empresa):
                    with default_storage.open(nombre, 'rb') as archivo:
                        if archivo.read() != contenido:
                            raise ValueError('El contenido no corresponde a la empresa.')
                self.stdout.write(f'Archivos {empresa.alias_bd}: escritura y lectura verificadas.')
        except Exception as exc:
            fallo = f'No se pudo verificar el almacenamiento ({type(exc).__name__}).'
        finally:
            for empresa, nombre, _ in escritos:
                try:
                    with usar_empresa(empresa):
                        default_storage.delete(nombre)
                        if default_storage.exists(nombre):
                            raise ValueError('El archivo temporal sigue presente.')
                except Exception as exc:
                    fallo = fallo or f'No se pudo retirar un archivo temporal ({type(exc).__name__}).'
        if fallo:
            raise CommandError(fallo) from None
        self.stdout.write('Archivos temporales eliminados; separación por empresa verificada.')
