from django.conf import settings


class RouterEsquema:
    def allow_migrate(self, db, app_label, **hints):
        if app_label == 'empresas':
            return db == 'central'
        return db in settings.BASES_EMPRESA

    def db_for_read(self, model, **hints):
        if model._meta.app_label == 'empresas':
            return 'central'
        return None

    db_for_write = db_for_read
