"""Perfil para aplicar explícitamente las migraciones en las tres bases de prueba."""

from copy import deepcopy

from .settings import *  # noqa: F403

# local_settings ya ha validado la URL directa de la rama y la base central.
# Se conserva la configuración de lectura del perfil original para otras comprobaciones.
DATABASES = deepcopy(DATABASES)
for alias in ('central', *BASES_EMPRESA):
    opciones = DATABASES[alias]['OPTIONS']
    if opciones.get('options') == '-c default_transaction_read_only=on':
        del opciones['options']
