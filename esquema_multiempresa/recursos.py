from pathlib import Path

from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore as SesionBase
from django.core.cache.backends.base import default_key_func
from django.core.exceptions import ImproperlyConfigured
from django.core.files.storage import FileSystemStorage

from apps.core.empresa import empresa_actual, identidad_empresa


def clave_cache(key, key_prefix, version):
    return default_key_func(key, f'{key_prefix}:{identidad_empresa()}', version)


class SessionStore(SesionBase):
    @property
    def key_salt(self):
        return f'{super().key_salt}:{identidad_empresa()}'


class ArchivosEmpresa(FileSystemStorage):
    @property
    def location(self):
        empresa = empresa_actual()
        if empresa is None:
            raise ImproperlyConfigured('Selecciona una empresa para acceder a sus archivos.')
        return str(Path(settings.MEDIA_ROOT).resolve() / empresa.alias_bd)
