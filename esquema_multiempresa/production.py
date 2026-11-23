"""Servidor multiempresa de producción: Neon y archivos privados externos."""
from decouple import config, Csv
from django.core.exceptions import ImproperlyConfigured

from config.settings.base import *  # noqa: F403
from .configuracion_web import *  # noqa: F403
from .configuracion_produccion import bases_produccion, configuracion_publica, opciones_s3

DEBUG = False
if len(SECRET_KEY) < 50 or SECRET_KEY.startswith('django-insecure-'):
    raise ImproperlyConfigured('Configura un SECRET_KEY privado de al menos 50 caracteres para producción.')
INSTALLED_APPS = [*INSTALLED_APPS, 'esquema_multiempresa.apps.EmpresasConfig']
DATABASE_ROUTERS = ['esquema_multiempresa.router.RouterEsquema']
BASES_EMPRESA = ('ferreteria', 'repuestos')
DATABASES = bases_produccion(config)
globals().update(configuracion_publica(config))

MIDDLEWARE = list(MIDDLEWARE)
MIDDLEWARE.insert(MIDDLEWARE.index('django.middleware.security.SecurityMiddleware') + 1,
                  'whitenoise.middleware.WhiteNoiseMiddleware')
MIDDLEWARE.insert(MIDDLEWARE.index('esquema_multiempresa.acceso.EmpresaMiddleware'),
                  'esquema_multiempresa.salud.SaludMiddleware')

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = True
SECURE_REDIRECT_EXEMPT = [r'^salud/$']
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = CSRF_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_DOMAIN = CSRF_COOKIE_DOMAIN = None
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
# HSTS se activa después de comprobar todos los dominios y sus certificados.
SECURE_HSTS_SECONDS = config('SS_HSTS_SECONDS', default=0, cast=int)
if SECURE_HSTS_SECONDS < 0:
    raise ImproperlyConfigured('SS_HSTS_SECONDS no puede ser negativo.')
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_PRELOAD = False
SECRET_KEY_FALLBACKS = config('SECRET_KEY_FALLBACKS', default='', cast=Csv())

STATIC_URL = '/static/'
MEDIA_URL = '/media/'
SS_S3_STORAGE_OPTIONS = opciones_s3(config)
STORAGES = {
    'default': {'BACKEND': 'esquema_multiempresa.almacenamiento.ArchivosEmpresaS3'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}

EMAIL_BACKEND = 'apps.usuarios.email_backends.ResendEmailBackend'
RESEND_API_KEY = config('RESEND_API_KEY', default='')
SMS_ALERTAS_ACTIVAS = config('SMS_ALERTAS_ACTIVAS', default=False, cast=bool)
SMS_ALERTAS_DESTINATARIOS = config('SMS_ALERTAS_DESTINATARIOS', default='', cast=Csv())
SMS_ORIGEN_POR_EMPRESA = True
WSGI_APPLICATION = 'esquema_multiempresa.wsgi.application'
