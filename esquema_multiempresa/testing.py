"""Bases desechables para probar dos empresas sin la URL ni las credenciales de Neon."""
from copy import deepcopy
from config.settings.testing import *  # noqa: F403
from .configuracion_web import *  # noqa: F403

INSTALLED_APPS = [*INSTALLED_APPS, 'esquema_multiempresa.apps.EmpresasConfig']
DATABASE_ROUTERS = ['esquema_multiempresa.router.RouterEsquema']
BASES_EMPRESA = ('ferreteria', 'repuestos')
plantilla = DATABASES['default']
DATABASES = {'default': {}}
for alias in ('central', *BASES_EMPRESA):
    db = deepcopy(plantilla)
    if db['ENGINE'] == 'django.db.backends.postgresql':
        db['NAME'] = f'smartstock_qa_{alias}'
    db['TEST'] = {'DEPENDENCIES': []}
    DATABASES[alias] = db
