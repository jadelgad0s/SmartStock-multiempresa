from django.conf import settings

from apps.core.empresa import empresa_actual


class RouterEsquema:
    apps_centrales = {'empresas', 'usuarios', 'auth', 'contenttypes', 'sessions', 'admin', 'core'}

    def allow_migrate(self, db, app_label, **hints):
        if db == 'central':
            return app_label in self.apps_centrales
        if app_label == 'empresas':
            return False
        return db in settings.BASES_EMPRESA

    def db_for_read(self, model, **hints):
        if model._meta.app_label == 'empresas':
            return 'central'
        empresa = empresa_actual()
        if empresa is not None:
            return empresa.alias_bd
        if model._meta.app_label in self.apps_centrales:
            return 'central'
        return None

    db_for_write = db_for_read
