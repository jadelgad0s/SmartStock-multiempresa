"""Servidor local para las empresas registradas en la rama Neon de pruebas."""
from .migracion import *  # noqa: F403
from .configuracion_web import *  # noqa: F403
from .conexiones import con_pool_neon

DATABASES = con_pool_neon(DATABASES, ('central', *BASES_EMPRESA))

# La central guarda las cuentas técnicas, sesiones y accesos de un solo uso.
