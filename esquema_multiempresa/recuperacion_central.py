from django.db import DatabaseError

from apps.core.empresa import empresa_actual, usar_empresa
from apps.usuarios.views_recuperacion import RecuperacionClaveForm, SolicitarRecuperacionView
from .acceso import direccion_empresa
from .login import empresas_disponibles, logger
from .permisos import es_personal_smartstock


class RecuperacionCentralForm(RecuperacionClaveForm):
    def get_users(self, email):
        usuarios = super().get_users(email)
        if empresa_actual() is None:
            return (usuario for usuario in usuarios if es_personal_smartstock(usuario))
        return usuarios

    def save(self, **kwargs):
        request = kwargs['request']
        for empresa in [None, *empresas_disponibles()]:
            opciones = dict(kwargs)
            opciones['domain_override'] = (
                direccion_empresa(request, empresa).split('://', 1)[1]
                if empresa is not None else request.get_host()
            )
            try:
                with usar_empresa(empresa):
                    super().save(**opciones)
            except DatabaseError:
                logger.exception('Una base de acceso no estuvo disponible para recuperar la clave.')


class SolicitarRecuperacionCentralView(SolicitarRecuperacionView):
    form_class = RecuperacionCentralForm
