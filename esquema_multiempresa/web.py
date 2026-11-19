"""Servidor local para las empresas registradas en la rama Neon de pruebas."""
from .migracion import *  # noqa: F403
from .settings import DATABASES as BASES_LECTURA
from .configuracion_web import *  # noqa: F403

# El directorio central se consulta en cada petición. Las escrituras pertenecen a la empresa.
DATABASES = {**DATABASES, 'central': BASES_LECTURA['central']}
