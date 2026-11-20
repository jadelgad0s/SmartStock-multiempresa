from django.apps import AppConfig


class EmpresasConfig(AppConfig):
    name = 'esquema_multiempresa'
    label = 'empresas'
    verbose_name = 'Empresas de SmartStock'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        from . import identidad_contacto  # noqa: F401
