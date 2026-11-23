"""Migraciones explícitas por alias con las mismas URLs directas, sin pool web."""
from .production import *  # noqa: F403
from .configuracion_produccion import bases_produccion

DATABASES = bases_produccion(config, pool=False)
