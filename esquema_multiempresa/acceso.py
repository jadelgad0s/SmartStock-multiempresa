"""Resuelve el subdominio antes de que Django abra la sesión del usuario."""
import re

from django.conf import settings
from django.http import Http404, HttpResponseNotAllowed, HttpResponseRedirect
from django.http.request import split_domain_port
from django.shortcuts import render
from django.views.decorators.cache import never_cache

from apps.core.empresa import usar_empresa
from .models import Empresa


def empresa_activa(codigo):
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,58}[a-z0-9])?', codigo):
        return None
    return Empresa.objects.filter(codigo=codigo, activa=True, alias_bd__in=settings.BASES_EMPRESA).first()


@never_cache
def entrada(request, puerto):
    if request.path_info != '/':
        raise Http404
    if request.method not in ('GET', 'HEAD'):
        return HttpResponseNotAllowed(['GET', 'HEAD'])
    codigo = request.GET.get('empresa', '').strip().lower()
    if codigo:
        empresa = empresa_activa(codigo)
        if empresa is not None:
            host = f'{empresa.codigo}.{settings.DOMINIO_EMPRESAS}'
            if puerto:
                host = f'{host}:{puerto}'
            return HttpResponseRedirect(f'{request.scheme}://{host}/')
    return render(request, 'empresas/entrada.html', {'codigo': codigo}, status=404 if codigo else 200)


class EmpresaMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host, puerto = split_domain_port(request.get_host())
        dominio = settings.DOMINIO_EMPRESAS
        if host in (dominio, '127.0.0.1', '[::1]'):
            return entrada(request, puerto)
        sufijo = '.' + dominio
        empresa = empresa_activa(host[:-len(sufijo)]) if host.endswith(sufijo) else None
        if empresa is None:
            raise Http404('Empresa no disponible.')
        request.empresa = empresa
        with usar_empresa(empresa):
            return self.get_response(request)
