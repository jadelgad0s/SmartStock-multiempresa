"""Archivos privados en S3 con un prefijo independiente por empresa."""
from threading import RLock

from botocore.config import Config
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files.storage import Storage
from django.core.files.utils import validate_file_name
from django.utils.encoding import filepath_to_uri
from storages.backends.s3 import S3Storage

from apps.core.empresa import empresa_actual


class ArchivosEmpresaS3(Storage):
    def __init__(self):
        self._backends = {}
        self._lock = RLock()

    def backend(self, name):
        validate_file_name(name, allow_relative_path=True)
        empresa = empresa_actual()
        if empresa is None or empresa.alias_bd not in settings.BASES_EMPRESA:
            raise ImproperlyConfigured('Selecciona una empresa para acceder a sus archivos.')
        alias = empresa.alias_bd
        with self._lock:
            if alias not in self._backends:
                self._backends[alias] = S3Storage(
                    **settings.SS_S3_STORAGE_OPTIONS, location=f'empresas/{alias}',
                    client_config=Config(signature_version='s3v4', s3={'addressing_style': 'path'},
                        connect_timeout=5, read_timeout=15,
                        retries={'mode': 'standard', 'total_max_attempts': 2}),
                )
            return self._backends[alias]

    def _open(self, name, mode='rb'):
        return self.backend(name).open(name, mode)

    def _save(self, name, content):
        return self.backend(name).save(name, content)

    def exists(self, name):
        return self.backend(name).exists(name)

    def delete(self, name):
        return self.backend(name).delete(name)

    def size(self, name):
        return self.backend(name).size(name)

    def url(self, name):
        self.backend(name)
        # El navegador usa la ruta autenticada de su empresa; el bucket es privado.
        return settings.MEDIA_URL.rstrip('/') + '/' + filepath_to_uri(name)
