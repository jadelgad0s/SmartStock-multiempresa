"""Catálogo local de regiones y comunas, obtenido de los CUT de SUBDERE."""
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path


def clave_nombre(valor):
    texto = unicodedata.normalize('NFKD', str(valor or '').strip().casefold())
    texto = ''.join(caracter for caracter in texto if not unicodedata.combining(caracter))
    return ' '.join(texto.replace('’', "'").split())


@lru_cache(maxsize=1)
def regiones_chile():
    ruta = Path(__file__).with_name('datos') / 'regiones_comunas.json'
    regiones = json.loads(ruta.read_text(encoding='utf-8'))['regiones']
    for region in regiones:
        region['comunas'].sort(key=lambda comuna: clave_nombre(comuna['nombre']))
    return regiones


def normalizar_region(valor):
    clave = re.sub(r'^region\s+', '', clave_nombre(valor))
    clave = re.sub(r'^(?:de|del)\s+', '', clave)
    alias = {'metropolitana': '13', 'rm': '13', 'aysen': '11', 'magallanes': '12', "o'higgins": '06'}
    codigo = alias.get(clave, clave)
    for region in regiones_chile():
        if codigo == region['codigo'] or clave == clave_nombre(region['nombre']):
            return region['nombre']
    return ''


def normalizar_comuna(valor, region):
    clave = clave_nombre(valor)
    for item in regiones_chile():
        if item['nombre'] == region:
            for comuna in item['comunas']:
                if clave in (comuna['codigo'], clave_nombre(comuna['nombre'])):
                    return comuna['nombre']
    return ''
