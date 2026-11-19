from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from esquema_multiempresa.models import Empresa


class Command(BaseCommand):
    help = 'Registra las dos empresas de la prueba en el directorio central.'

    def handle(self, *args, **options):
        empresas = (
            ('la-fragua', 'Ferretería La Fragua', 'ferreteria'),
            ('punto-motor', 'Repuestos Punto Motor', 'repuestos'),
        )
        try:
            with transaction.atomic(using='central'):
                for codigo, nombre, alias in empresas:
                    empresa, _ = Empresa.objects.using('central').get_or_create(
                        codigo=codigo, defaults={'nombre': nombre, 'alias_bd': alias},
                    )
                    if empresa.alias_bd != alias:
                        raise CommandError(f'El código {codigo} ya está asociado a otra base.')
        except IntegrityError as exc:
            raise CommandError('Una de las bases ya está asignada a otra empresa. Revisa el directorio.') from exc
        self.stdout.write(self.style.SUCCESS('Directorio de las dos empresas de prueba comprobado.'))
