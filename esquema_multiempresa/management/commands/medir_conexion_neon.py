"""Diagnóstico de red y reutilización, sin leer ni modificar registros."""
from statistics import median
from time import perf_counter

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connections


class Command(BaseCommand):
    help = 'Mide la conexión a Neon con SELECT 1, sin modificar datos ni mostrar credenciales.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--repeticiones', type=int, default=5)

    def handle(self, *args, **options):
        repeticiones = options['repeticiones']
        if not 2 <= repeticiones <= 10:
            raise CommandError('Usa entre 2 y 10 repeticiones.')
        aliases = ('central', *getattr(settings, 'BASES_EMPRESA', ()))
        for alias in aliases:
            cfg = settings.DATABASES.get(alias, {})
            if cfg.get('ENGINE') != 'django.db.backends.postgresql' or not cfg.get('HOST', '').endswith('.neon.tech'):
                raise CommandError('Ejecuta con --settings=esquema_multiempresa.web y las conexiones de Neon configuradas.')
        self.stdout.write('Medición desde este equipo. Solo se ejecutan SELECT; las bases continúan en Neon.')
        for alias in aliases:
            conexion = connections[alias]
            try:
                inicio = perf_counter()
                with conexion.cursor() as cursor:
                    cursor.execute('SELECT current_database()')
                    if cursor.fetchone()[0] != conexion.settings_dict['NAME']:
                        raise CommandError(f'{alias}: la conexión abrió una base diferente a la configurada.')
                primera = (perf_counter() - inicio) * 1000
                conexion.close()
                muestras = []
                for _ in range(repeticiones):
                    inicio = perf_counter()
                    with conexion.cursor() as cursor:
                        cursor.execute('SELECT 1')
                        cursor.fetchone()
                    muestras.append((perf_counter() - inicio) * 1000)
                    conexion.close()
                modo = 'pool de conexiones a Neon' if conexion.settings_dict['OPTIONS'].get('pool') else 'conexión directa a Neon'
                self.stdout.write(f'{alias}: primera {primera:.0f} ms; siguientes mediana {median(muestras):.0f} ms; {modo}.')
            except DatabaseError:
                raise CommandError(f'No pudimos medir {alias}. Revisa la conexión a Neon y vuelve a intentarlo.') from None
            finally:
                conexion.close()
                if conexion.settings_dict['OPTIONS'].get('pool'):
                    conexion.close_pool()
