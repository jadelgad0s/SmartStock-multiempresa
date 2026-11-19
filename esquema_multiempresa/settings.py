"""Perfil de consulta del esquema para la rama pruebas-multiempresa."""

from local_settings import *  # noqa: F403

INSTALLED_APPS = [*INSTALLED_APPS, 'esquema_multiempresa.apps.EmpresasConfig']
DATABASE_ROUTERS = ['esquema_multiempresa.router.RouterEsquema']
BASES_EMPRESA = ('ferreteria', 'repuestos')
