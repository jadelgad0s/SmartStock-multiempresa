"""Configuración de publicación validada sin abrir conexiones ni mostrar secretos."""
import re
from urllib.parse import urlsplit

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

from .conexiones import con_pool_neon


VARIABLES_BASES = {
    'central': 'SS_CENTRAL_DATABASE_URL',
    'ferreteria': 'SS_FERRETERIA_DATABASE_URL',
    'repuestos': 'SS_REPUESTOS_DATABASE_URL',
}


def requerido(leer, nombre):
    valor = leer(nombre, default='').strip()
    if not valor:
        raise ImproperlyConfigured(f'Falta configurar {nombre}.')
    return valor


def host_publico(valor):
    valor = valor.lower()
    if (len(valor) > 253 or '.' not in valor or
            not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', p)
                    for p in valor.split('.')) or valor.endswith('.localhost')):
        raise ImproperlyConfigured('Configura un dominio público, sin protocolo, puerto ni rutas.')
    return valor


def bases_produccion(leer, *, pool=True):
    bases = {'default': {}}
    destinos = set()
    for alias, variable in VARIABLES_BASES.items():
        url = requerido(leer, variable)
        try:
            base = dj_database_url.parse(url, conn_max_age=0)
            host = base.get('HOST', '').lower()
            opciones = base.setdefault('OPTIONS', {})
            valido = (base['ENGINE'] == 'django.db.backends.postgresql'
                and host.endswith('.neon.tech') and '-pooler.' not in host
                and base.get('NAME') and base.get('USER') and base.get('PASSWORD')
                and opciones.get('sslmode') in ('require', 'verify-ca', 'verify-full'))
        except (ValueError, TypeError, KeyError):
            valido = False
        if not valido:
            raise ImproperlyConfigured(f'Revisa {variable}: se requiere una URL directa de Neon con SSL.') from None
        identidad = (host, str(base.get('PORT') or '5432'), base['NAME'])
        if identidad in destinos:
            raise ImproperlyConfigured('La central y cada empresa deben usar bases distintas.')
        destinos.add(identidad)
        opciones['connect_timeout'] = 15
        bases[alias] = base
    return con_pool_neon(bases, VARIABLES_BASES) if pool else bases


def configuracion_publica(leer):
    dominio = host_publico(leer('SS_DOMINIO_EMPRESAS', default='smartstockchile.cl').strip())
    centrales = [dominio, 'www.' + dominio]
    render = leer('RENDER_EXTERNAL_HOSTNAME', default='').strip()
    if render:
        render = host_publico(render)
        if not render.endswith('.onrender.com'):
            raise ImproperlyConfigured('RENDER_EXTERNAL_HOSTNAME debe ser el host asignado por Render.')
        centrales.append(render)
    return {
        'DOMINIO_EMPRESAS': dominio,
        'HOSTS_CENTRALES': tuple(centrales),
        'ALLOWED_HOSTS': ['.' + dominio, *([render] if render else [])],
        'CSRF_TRUSTED_ORIGINS': ['https://' + h for h in centrales],
    }


def opciones_s3(leer):
    endpoint = requerido(leer, 'SS_S3_ENDPOINT_URL')
    try:
        url = urlsplit(endpoint)
        valido = (url.scheme == 'https' and url.hostname and not url.username
                  and not url.password and url.path in ('', '/') and not url.query and not url.fragment)
        url.port
    except ValueError:
        valido = False
    if not valido:
        raise ImproperlyConfigured('SS_S3_ENDPOINT_URL debe ser un origen HTTPS, sin credenciales ni rutas.')
    bucket = requerido(leer, 'SS_S3_BUCKET')
    if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', bucket):
        raise ImproperlyConfigured('Revisa el nombre de SS_S3_BUCKET.')
    return {
        'bucket_name': bucket,
        'endpoint_url': endpoint.rstrip('/'),
        'access_key': requerido(leer, 'SS_S3_ACCESS_KEY_ID'),
        'secret_key': requerido(leer, 'SS_S3_SECRET_ACCESS_KEY'),
        'region_name': leer('SS_S3_REGION', default='us-east-1'),
        'default_acl': None,
        'file_overwrite': False,
        'querystring_auth': True,
        'custom_domain': None,
        'addressing_style': 'path',
        'signature_version': 's3v4',
        'max_memory_size': 2 * 1024 * 1024,
    }
