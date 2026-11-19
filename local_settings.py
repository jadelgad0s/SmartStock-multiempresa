"""Conexiones de lectura a la rama pruebas-multiempresa de SmartStock."""

from pathlib import Path

import dj_database_url
from decouple import RepositoryEnv
from django.core.exceptions import ImproperlyConfigured
from django.db import connections

from config.settings.development import *  # noqa: F403


_BASES = {
    'central': 'smartstock_central',
    'ferreteria': 'ferreteria_la_fragua',
    'repuestos': 'repuestos_punto_motor',
}
_HOST_PRUEBAS = 'ep-super-art-b5mcjw76.c-7.us-east-2.aws.neon.tech'


def _conexiones_de_prueba():
    archivo = Path(__file__).with_name('.env.multiempresa.local')
    try:
        url = RepositoryEnv(archivo)['SS_PRUEBAS_CENTRAL_URL']
        central = dj_database_url.parse(url)
    except (OSError, KeyError, ValueError):
        raise ImproperlyConfigured(
            'Revisa SS_PRUEBAS_CENTRAL_URL en .env.multiempresa.local junto a manage.py.'
        ) from None

    if (central['ENGINE'], central['HOST'], central['NAME']) != (
        'django.db.backends.postgresql', _HOST_PRUEBAS, _BASES['central']
    ):
        raise ImproperlyConfigured(
            'Copia la URL directa de smartstock_central en la rama pruebas-multiempresa.'
        )

    opciones = central.setdefault('OPTIONS', {})
    if opciones.get('sslmode') not in ('require', 'verify-ca', 'verify-full'):
        raise ImproperlyConfigured('Copia la URL completa de Neon, incluidos sus parámetros SSL.')
    opciones['connect_timeout'] = 15
    opciones['options'] = '-c default_transaction_read_only=on'

    # Solo se usan los tres alias explícitos durante esta comprobación.
    bases = {'default': {}}
    for alias, nombre in _BASES.items():
        bases[alias] = {**central, 'NAME': nombre, 'OPTIONS': opciones.copy()}
    return bases


DATABASES = _conexiones_de_prueba()


def comprobar_conexiones():
    """Pregunta a PostgreSQL qué base abrió cada alias de Django."""
    for alias, esperado in _BASES.items():
        conexion = connections[alias]
        try:
            with conexion.cursor() as cursor:
                cursor.execute('SELECT current_database()')
                actual = cursor.fetchone()[0]
            if actual != esperado:
                raise RuntimeError(f'{alias} abrió {actual}. Se esperaba {esperado}.')
            print(f'{alias} -> {actual}')
        finally:
            conexion.close()
