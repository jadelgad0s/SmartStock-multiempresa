"""Opciones comunes del servidor local multiempresa y de sus pruebas aisladas."""
from config.settings.base import MIDDLEWARE as MIDDLEWARE_BASE

DOMINIO_EMPRESAS = 'localhost'
ALLOWED_HOSTS = ['.localhost', '127.0.0.1', '[::1]']
MIDDLEWARE = list(MIDDLEWARE_BASE)
MIDDLEWARE.insert(MIDDLEWARE.index('django.contrib.sessions.middleware.SessionMiddleware'),
                  'esquema_multiempresa.acceso.EmpresaMiddleware')
ROOT_URLCONF = 'esquema_multiempresa.urls'
SESSION_ENGINE = 'esquema_multiempresa.recursos'
SESSION_COOKIE_DOMAIN = CSRF_COOKIE_DOMAIN = None
CORS_ALLOW_ALL_ORIGINS = False
CACHES = {'default': {
    'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    'KEY_FUNCTION': 'esquema_multiempresa.recursos.clave_cache',
}}
STORAGES = {
    'default': {'BACKEND': 'esquema_multiempresa.recursos.ArchivosEmpresa'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
# El ensayo de dos clientes no debe usar destinatarios ni hacer envíos reales de la instalación original.
SMS_ALERTAS_ACTIVAS = False
SMS_ALERTAS_DESTINATARIOS = []
