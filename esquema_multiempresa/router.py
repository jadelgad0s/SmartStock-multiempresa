from django.conf import settings

from apps.core.empresa import empresa_actual


class RouterEsquema:
    def allow_migrate(self, db, app_label, **hints):
        if app_label == 'empresas':
            return db == 'central'
        return db in settings.BASES_EMPRESA

    def db_for_read(self, model, **hints):
        if model._meta.app_label == 'empresas':
            return 'central'
        empresa = empresa_actual()
        return empresa.alias_bd if empresa is not None else None

    db_for_write = db_for_read
