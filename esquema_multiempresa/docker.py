"""Instalación local multiempresa con PostgreSQL e imágenes en volúmenes de Docker."""
from decouple import config

from config.settings.base import *  # noqa: F403
from .configuracion_web import *  # noqa: F403

DOCKER_LOCAL_DEMO = True
DEBUG = False
INSTALLED_APPS = [*INSTALLED_APPS, 'esquema_multiempresa.apps.EmpresasConfig']
DATABASE_ROUTERS = ['esquema_multiempresa.router.RouterEsquema']
BASES_EMPRESA = ('ferreteria', 'repuestos')

DATABASES = {'default': {}}
for alias, nombre in (
    ('central', 'smartstock_central'),
    ('ferreteria', 'ferreteria_la_fragua'),
    ('repuestos', 'repuestos_punto_motor'),
):
    DATABASES[alias] = {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': nombre,
        'USER': config('SS_DOCKER_DB_USER', default='smartstock'),
        'PASSWORD': config('SS_DOCKER_DB_PASSWORD'),
        'HOST': config('SS_DOCKER_DB_HOST', default='db'),
        'PORT': config('SS_DOCKER_DB_PORT', default='5432'),
        'CONN_MAX_AGE': 0,
        'OPTIONS': {'connect_timeout': 10},
    }

MIDDLEWARE.insert(MIDDLEWARE.index('django.middleware.security.SecurityMiddleware') + 1,
                  'whitenoise.middleware.WhiteNoiseMiddleware')
MIDDLEWARE.insert(0, 'esquema_multiempresa.salud.SaludMiddleware')
STATIC_URL = '/static/'
MEDIA_URL = '/media/'
STORAGES['staticfiles'] = {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'}
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
WSGI_APPLICATION = 'esquema_multiempresa.wsgi.application'
