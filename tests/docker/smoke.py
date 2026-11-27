"""Comprobación HTTP del entorno Compose y de sus volúmenes tras recrearlo."""
import binascii
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import re
import struct
import sys
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener
from uuid import uuid4
import zlib


def variables_locales():
    variables = {}
    for linea in Path('.env.docker.local').read_text().splitlines():
        if linea.strip() and not linea.lstrip().startswith('#'):
            clave, valor = linea.split('=', 1)
            variables[clave.strip()] = valor.strip().strip('"\'')
    return variables


configuracion = variables_locales()
password = os.environ.get('SS_DOCKER_DEMO_PASSWORD', configuracion['SS_DOCKER_DEMO_PASSWORD'])
puerto = os.environ.get('SMARTSTOCK_PORT', configuracion.get('SMARTSTOCK_PORT', '8000'))
BASE = f'http://127.0.0.1:{puerto}'


def solicitar(opener, host, ruta, *, datos=None, token=None, tipo='application/json'):
    headers = {'Host': f'{host}:{puerto}', 'Origin': f'http://{host}:{puerto}'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    if datos is not None:
        headers['Content-Type'] = tipo
    request = Request(BASE + ruta, data=datos, headers=headers)
    with opener.open(request, timeout=20) as response:
        return response.read()


def iniciar_sesion(host, correo):
    cookies = CookieJar()
    opener = build_opener(HTTPCookieProcessor(cookies))
    solicitar(opener, host, '/')
    csrf = next(cookie.value for cookie in cookies if cookie.name == 'csrftoken')
    request = Request(BASE + '/api/v1/auth/login-web/',
        data=json.dumps({'email': correo, 'password': password}).encode(),
        headers={'Host': f'{host}:{puerto}', 'Origin': f'http://{host}:{puerto}',
                 'Content-Type': 'application/json', 'X-CSRFToken': csrf})
    with opener.open(request, timeout=20) as response:
        login = json.loads(response.read())
    assert login['success'], 'El acceso fue rechazado'
    return opener, login['data']


def imagen_png(color):
    def bloque(tipo, datos):
        return struct.pack('!I', len(datos)) + tipo + datos + struct.pack('!I', binascii.crc32(tipo + datos) & 0xffffffff)
    cabecera = struct.pack('!IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
    return b'\x89PNG\r\n\x1a\n' + bloque(b'IHDR', cabecera) + bloque(b'IDAT', zlib.compress(b'\x00' + color)) + bloque(b'IEND', b'')


def crear_producto(opener, host, token, nombre, imagen):
    limite = uuid4().hex
    partes = []
    for clave, valor in {'sku': 'DOCKER-001', 'nombre': nombre, 'precio_referencia': '2500.00'}.items():
        partes.append(f'--{limite}\r\nContent-Disposition: form-data; name="{clave}"\r\n\r\n{valor}\r\n'.encode())
    partes.extend([
        f'--{limite}\r\nContent-Disposition: form-data; name="imagen"; filename="prueba.png"\r\nContent-Type: image/png\r\n\r\n'.encode(),
        imagen, f'\r\n--{limite}--\r\n'.encode(),
    ])
    resultado = json.loads(solicitar(opener, host, '/api/v1/productos/', datos=b''.join(partes),
                                   token=token, tipo='multipart/form-data; boundary=' + limite))
    assert resultado['success'], 'El producto no se creó'


def main():
    crear = len(sys.argv) > 1 and sys.argv[1] == 'crear'
    tecnico, _ = iniciar_sesion('localhost', 'tecnico@smartstock.test')
    panel = solicitar(tecnico, 'localhost', '/sistema/').decode()
    assert 'Resumen de SmartStock' in panel or 'Resumen general' in panel
    assert 'Ferretería La Fragua' in panel and 'Repuestos Punto Motor' in panel
    scripts = re.findall(r'src="(/static/[^"?]+)', panel)
    assert scripts, 'Faltan los archivos estáticos'
    assert solicitar(tecnico, 'localhost', scripts[0])
    sesiones = {}
    for codigo, correo, color in (
        ('la-fragua', 'admin.lafragua@smartstock.test', b'\xcc\x33\x00'),
        ('punto-motor', 'admin.puntomotor@smartstock.test', b'\x00\x33\xcc'),
    ):
        host = codigo + '.localhost'
        opener, login = iniciar_sesion(host, correo)
        token = login['access']
        sesiones[codigo] = (opener, token)
        nombre = 'Demostración ' + codigo
        imagen = imagen_png(color)
        if crear:
            crear_producto(opener, host, token, nombre, imagen)
        respuesta = json.loads(solicitar(opener, host, '/api/v1/productos/?search=DOCKER-001', token=token))
        assert respuesta['count'] == 1, 'El producto debe existir una sola vez'
        producto = respuesta['results'][0]
        assert producto['nombre'] == nombre, 'Se mezclaron los catálogos'
        detalle = json.loads(solicitar(opener, host, f"/api/v1/productos/{producto['id']}/", token=token))
        producto = detalle.get('data', detalle)
        ruta = urlsplit(producto['imagen']).path
        assert ruta.startswith('/media/'), 'La imagen debe servirse por la ruta privada'
        assert solicitar(opener, host, ruta) == imagen, 'La imagen debe persistir en su propia empresa'
    opener, _ = sesiones['punto-motor']
    try:
        solicitar(opener, 'punto-motor.localhost', '/api/v1/productos/', token=sesiones['la-fragua'][1])
    except HTTPError as error:
        assert error.code == 401, 'El token de otra empresa debe ser rechazado'
    else:
        raise AssertionError('Se aceptó un token de otra empresa')
    print('Accesos, estáticos, catálogos independientes e imágenes persistentes comprobados.')


if __name__ == '__main__':
    main()
