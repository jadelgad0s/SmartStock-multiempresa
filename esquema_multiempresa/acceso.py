"""Selecciona el acceso central o la empresa antes de abrir la sesión."""
import re

from django.conf import settings
from django.http import Http404
from django.http.request import split_domain_port

from apps.core.empresa import usar_empresa
from .models import Empresa


def empresa_activa(codigo):
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,58}[a-z0-9])?', codigo):
        return None
    return Empresa.objects.filter(codigo=codigo, activa=True, alias_bd__in=settings.BASES_EMPRESA).first()


def direccion_empresa(request, empresa):
    _, puerto = split_domain_port(request.get_host())
    host = f'{empresa.codigo}.{settings.DOMINIO_EMPRESAS}'
    if puerto:
        host = f'{host}:{puerto}'
    return f'{request.scheme}://{host}'


class EmpresaMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host, _ = split_domain_port(request.get_host())
        dominio = settings.DOMINIO_EMPRESAS
        centrales = getattr(settings, 'HOSTS_CENTRALES', (dominio, '127.0.0.1', '[::1]'))
        if host in centrales:
            request.empresa = None
            request.urlconf = 'esquema_multiempresa.urls_central'
            with usar_empresa(None):
                return self.get_response(request)
        sufijo = '.' + dominio
        empresa = empresa_activa(host[:-len(sufijo)]) if host.endswith(sufijo) else None
        if empresa is None:
            raise Http404('Empresa no disponible.')
        request.empresa = empresa
        with usar_empresa(empresa):
            return self.get_response(request)
