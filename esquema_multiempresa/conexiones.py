"""Reutiliza conexiones a Neon; no sustituye ni replica las bases de datos."""
from copy import deepcopy

from django.core.exceptions import ImproperlyConfigured


def con_pool_neon(bases, aliases):
    resultado = deepcopy(bases)
    for alias in aliases:
        conexion = resultado[alias]
        if conexion['ENGINE'] != 'django.db.backends.postgresql' or not conexion.get('HOST', '').endswith('.neon.tech'):
            raise ImproperlyConfigured('El servidor multiempresa necesita las conexiones PostgreSQL de Neon configuradas.')
        # Django devuelve la conexión al pool al terminar cada petición, incluso
        # cuando runserver atiende la siguiente desde un hilo diferente.
        conexion['CONN_MAX_AGE'] = 0
        conexion['CONN_HEALTH_CHECKS'] = True
        conexion.setdefault('OPTIONS', {})['pool'] = {
            'min_size': 0, 'max_size': 4, 'timeout': 15,
            'max_idle': 60, 'max_lifetime': 600, 'reconnect_timeout': 15,
        }
    return resultado
