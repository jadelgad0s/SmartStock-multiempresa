from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.db.migrations.recorder import MigrationRecorder


class Command(BaseCommand):
    help = 'Consulta qué tablas prevé Django en cada base y cuántas están presentes.'

    def handle(self, *args, **options):
        for alias in ('central', *settings.BASES_EMPRESA):
            conexion = connections[alias]
            previstas = set(conexion.introspection.django_table_names())
            previstas.add(MigrationRecorder.Migration._meta.db_table)
            with conexion.cursor() as cursor:
                cursor.execute('SELECT current_database()')
                nombre = cursor.fetchone()[0]
                if nombre != conexion.settings_dict['NAME']:
                    raise CommandError(f'El alias {alias} abrió una base inesperada ({nombre}).')
                existentes = set(conexion.introspection.table_names(cursor))

            presentes = len(previstas & existentes)
            self.stdout.write(f'{alias} -> {nombre} | {presentes} de {len(previstas)} tablas previstas presentes')
            self.stdout.write('  Previstas: ' + ', '.join(sorted(previstas)))
            sobrantes = existentes - previstas
            if sobrantes:
                self.stdout.write(self.style.WARNING('  Otras tablas presentes: ' + ', '.join(sorted(sobrantes))))
