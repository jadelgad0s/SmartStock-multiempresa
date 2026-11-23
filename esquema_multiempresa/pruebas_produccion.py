"""Publicación: configuración cerrada, HTTPS, sesiones y archivos por empresa."""
from io import StringIO
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from uuid import uuid4

from botocore.stub import Stubber
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured, SuspiciousFileOperation
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from apps.core.empresa import usar_empresa
from apps.productos.alertas_sms import callback_url
from apps.usuarios.models import Rol, Usuario
from .almacenamiento import ArchivosEmpresaS3
from .configuracion_produccion import bases_produccion, configuracion_publica, opciones_s3
from .models import Empresa
from .salud import SaludMiddleware


def entorno_prueba():
    return {
        'SS_CENTRAL_DATABASE_URL': 'postgresql://fixture:password-for-tests@fixture.neon.tech/central?sslmode=require',
        'SS_FERRETERIA_DATABASE_URL': 'postgresql://fixture:password-for-tests@fixture.neon.tech/fragua?sslmode=require',
        'SS_REPUESTOS_DATABASE_URL': 'postgresql://fixture:password-for-tests@fixture.neon.tech/motor?sslmode=require',
        'SS_S3_ENDPOINT_URL': 'https://storage.example.invalid',
        'SS_S3_BUCKET': 'bucket-de-pruebas',
        'SS_S3_ACCESS_KEY_ID': 'fixture-only-access-key',
        'SS_S3_SECRET_ACCESS_KEY': 'fixture-only-secret-key',
    }


def lector(valores):
    return lambda nombre, default='': valores.get(nombre, default)


class ConfiguracionPublicacionTests(SimpleTestCase):
    def test_perfil_real_recoge_estaticos_y_responde_detras_del_proxy_sin_conectar_proveedores(self):
        entorno = {**os.environ, **entorno_prueba(),
            'DJANGO_SETTINGS_MODULE': 'esquema_multiempresa.production',
            'SECRET_KEY': 'clave-sintetica-de-publicacion-solo-para-ci-0123456789-abcdefghijkl',
            'RENDER_EXTERNAL_HOSTNAME': 'smartstock-pruebas.onrender.com',
            'SS_DOMINIO_EMPRESAS': 'smartstockchile.cl', 'SS_HSTS_SECONDS': '0',
            'SMS_ALERTAS_ACTIVAS': 'False', 'DEBUG': 'True',
        }
        codigo = '''
import django
django.setup()
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.conf import settings
from django.core.files.storage import storages
from django.core.management import call_command
from django.test import Client, override_settings
assert settings.DEBUG is False
assert settings.SESSION_COOKIE_SECURE and settings.CSRF_COOKIE_SECURE
assert settings.SESSION_COOKIE_DOMAIN is None
assert settings.ROOT_URLCONF == 'esquema_multiempresa.urls'
assert settings.DATABASES['default']['ENGINE'] == 'django.db.backends.dummy'
with TemporaryDirectory() as raiz, override_settings(STATIC_ROOT=raiz):
    call_command('check', deploy=True, fail_level='ERROR', verbosity=0)
    call_command('collectstatic', interactive=False, verbosity=0)
    ruta = storages['staticfiles'].url('branding/smartstock-mark.png')
    assert ruta != '/static/branding/smartstock-mark.png'
    with patch('django.db.backends.base.base.BaseDatabaseWrapper.ensure_connection', side_effect=AssertionError('No debe abrir Neon')):
        cliente = Client()
        for host in settings.HOSTS_CENTRALES:
            assert cliente.get('/', HTTP_HOST=host, HTTP_X_FORWARDED_PROTO='https').status_code == 200
        for host in ('smartstock-pruebas.onrender.com', 'la-fragua.smartstockchile.cl'):
            assert cliente.get('/salud/', HTTP_HOST=host).status_code == 200
        respuesta = cliente.get(ruta, HTTP_HOST='smartstock-pruebas.onrender.com', HTTP_X_FORWARDED_PROTO='https')
        assert respuesta.status_code == 200
        assert b''.join(respuesta.streaming_content) == (settings.BASE_DIR / 'static/branding/smartstock-mark.png').read_bytes()
'''
        resultado = subprocess.run([sys.executable, '-c', codigo], env=entorno,
            cwd=Path(__file__).resolve().parent.parent, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90)
        self.assertEqual(resultado.returncode, 0, resultado.stdout[-6000:])

    def test_exige_tres_bases_independientes_y_conserva_las_urls_y_ssl(self):
        bases = bases_produccion(lector(entorno_prueba()))
        self.assertEqual(bases['default'], {})
        self.assertEqual([bases[a]['NAME'] for a in ('central', 'ferreteria', 'repuestos')],
                         ['central', 'fragua', 'motor'])
        for alias in ('central', 'ferreteria', 'repuestos'):
            self.assertEqual(bases[alias]['HOST'], 'fixture.neon.tech')
            self.assertEqual(bases[alias]['OPTIONS']['sslmode'], 'require')
            self.assertIn('pool', bases[alias]['OPTIONS'])

    def test_migraciones_utilizan_las_mismas_bases_directas_sin_pool(self):
        bases = bases_produccion(lector(entorno_prueba()), pool=False)
        self.assertEqual(bases['ferreteria']['NAME'], 'fragua')
        for alias in ('central', 'ferreteria', 'repuestos'):
            self.assertNotIn('pool', bases[alias]['OPTIONS'])
            self.assertNotIn('options', bases[alias]['OPTIONS'])

    def test_no_reutiliza_database_url_ni_credenciales_de_desarrollo(self):
        valores = entorno_prueba()
        del valores['SS_REPUESTOS_DATABASE_URL']
        valores['DATABASE_URL'] = valores['SS_CENTRAL_DATABASE_URL']
        with self.assertRaisesMessage(ImproperlyConfigured, 'SS_REPUESTOS_DATABASE_URL'):
            bases_produccion(lector(valores))

    def test_rechaza_urls_inseguras_repetidas_o_con_motor_equivocado_sin_mostrar_secretos(self):
        base = entorno_prueba()
        invalidas = [
            'postgresql://fixture:super-secret-fixture@localhost/prod?sslmode=require',
            'postgresql://fixture:super-secret-fixture@fixture.neon.tech/prod?sslmode=disable',
            'postgresql://fixture:super-secret-fixture@fixture-pooler.neon.tech/prod?sslmode=require',
            'mysql://fixture:super-secret-fixture@fixture.neon.tech/prod?sslmode=require',
            'postgresql://fixture:super-secret-fixture@[invalid/prod',
            base['SS_CENTRAL_DATABASE_URL'],
        ]
        for url in invalidas:
            with self.subTest(url=url), self.assertRaises(ImproperlyConfigured) as error:
                bases_produccion(lector({**base, 'SS_FERRETERIA_DATABASE_URL': url}))
            self.assertNotIn('super-secret-fixture', str(error.exception))
            self.assertNotIn('postgresql://', str(error.exception))

    def test_configura_hosts_centrales_y_tenants_sin_aceptar_origenes_arbitrarios(self):
        datos = configuracion_publica(lector({'RENDER_EXTERNAL_HOSTNAME': 'smartstock-pruebas.onrender.com'}))
        self.assertIn('www.smartstockchile.cl', datos['HOSTS_CENTRALES'])
        self.assertIn('smartstock-pruebas.onrender.com', datos['HOSTS_CENTRALES'])
        self.assertEqual(datos['CSRF_TRUSTED_ORIGINS'], [
            'https://smartstockchile.cl', 'https://www.smartstockchile.cl',
            'https://smartstock-pruebas.onrender.com',
        ])
        self.assertNotIn('*', datos['ALLOWED_HOSTS'])
        for host in ('http://example.cl', 'example.cl:8000', 'localhost', '.example.cl', 'example.cl/ruta'):
            with self.subTest(host=host), self.assertRaises(ImproperlyConfigured):
                configuracion_publica(lector({'SS_DOMINIO_EMPRESAS': host}))

    def test_storage_externo_exige_credenciales_y_https_y_mantiene_el_bucket_privado(self):
        opciones = opciones_s3(lector(entorno_prueba()))
        self.assertIsNone(opciones['default_acl'])
        self.assertFalse(opciones['file_overwrite'])
        self.assertIsNone(opciones['custom_domain'])
        for variable in ('SS_S3_BUCKET', 'SS_S3_ENDPOINT_URL', 'SS_S3_ACCESS_KEY_ID', 'SS_S3_SECRET_ACCESS_KEY'):
            valores = entorno_prueba()
            del valores[variable]
            with self.subTest(variable=variable), self.assertRaises(ImproperlyConfigured):
                opciones_s3(lector(valores))
        for endpoint in ('http://storage.example.invalid', 'https://usuario:clave@example.invalid',
                         'https://storage.example.invalid/bucket', 'https://storage.example.invalid/?token=secreto'):
            with self.subTest(endpoint=endpoint), self.assertRaises(ImproperlyConfigured):
                opciones_s3(lector({**entorno_prueba(), 'SS_S3_ENDPOINT_URL': endpoint}))

    @override_settings(ALLOWED_HOSTS=['.smartstockchile.cl', 'smartstock-pruebas.onrender.com'])
    def test_salud_no_depende_de_sesiones_ni_de_las_bases(self):
        def resto(request):
            raise AssertionError('La comprobación de vida no debe acceder al resto de la aplicación.')
        middleware = SaludMiddleware(resto)
        factory = RequestFactory()
        for host in ('smartstockchile.cl', 'la-fragua.smartstockchile.cl', 'smartstock-pruebas.onrender.com'):
            respuesta = middleware(factory.get('/salud/', HTTP_HOST=host))
            self.assertEqual(respuesta.status_code, 200)
            self.assertEqual(respuesta['Cache-Control'], 'no-store')
        self.assertEqual(middleware(factory.post('/salud/', HTTP_HOST='smartstockchile.cl')).status_code, 405)


@override_settings(BASES_EMPRESA=('ferreteria', 'repuestos'), MEDIA_URL='/media/')
class ArchivosExternosTests(SimpleTestCase):
    def test_la_misma_ruta_consulta_objetos_distintos_segun_la_empresa(self):
        with self.settings(SS_S3_STORAGE_OPTIONS=opciones_s3(lector(entorno_prueba()))):
            almacenamiento = ArchivosEmpresaS3()
            for alias in ('ferreteria', 'repuestos'):
                with usar_empresa(SimpleNamespace(alias_bd=alias)):
                    backend = almacenamiento.backend('productos/ficha.png')
                    with Stubber(backend.connection.meta.client) as stub:
                        stub.add_response('head_object', {'ContentLength': 3}, {
                            'Bucket': 'bucket-de-pruebas', 'Key': f'empresas/{alias}/productos/ficha.png',
                        })
                        self.assertTrue(almacenamiento.exists('productos/ficha.png'))
                        stub.assert_no_pending_responses()
                    self.assertEqual(almacenamiento.url('productos/ficha.png'), '/media/productos/ficha.png')
            self.assertIsNot(almacenamiento._backends['ferreteria'], almacenamiento._backends['repuestos'])

    def test_rechaza_contexto_central_alias_desconocido_y_rutas_fuera_del_prefijo(self):
        almacenamiento = ArchivosEmpresaS3()
        with self.assertRaises(ImproperlyConfigured):
            almacenamiento.exists('ficha.png')
        with usar_empresa(SimpleNamespace(alias_bd='central')), self.assertRaises(ImproperlyConfigured):
            almacenamiento.exists('ficha.png')
        for nombre in ('../repuestos/ficha.png', '/empresas/repuestos/ficha.png'):
            with usar_empresa(SimpleNamespace(alias_bd='ferreteria')), self.assertRaises(SuspiciousFileOperation):
                almacenamiento.url(nombre)


@override_settings(
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    DOMINIO_EMPRESAS='smartstockchile.cl',
    HOSTS_CENTRALES=('smartstockchile.cl', 'www.smartstockchile.cl', 'smartstock-pruebas.onrender.com'),
    ALLOWED_HOSTS=['.smartstockchile.cl', 'smartstock-pruebas.onrender.com'],
    SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO', 'https'),
    SECURE_SSL_REDIRECT=True, SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True,
    SMS_ORIGEN_POR_EMPRESA=True,
)
class AccesoPublicoTests(TestCase):
    databases = {'central', 'ferreteria', 'repuestos'}

    def setUp(self):
        cache.clear()

    @classmethod
    def setUpTestData(cls):
        call_command('registrar_empresas_prueba', stdout=StringIO())
        for empresa in Empresa.objects.all():
            call_command('seed_empresa', empresa.codigo, sin_admin=True, stdout=StringIO())
            with usar_empresa(empresa):
                Usuario.objects.create_user(email='cuenta@example.invalid', password='Fixture-clave-9',
                    nombres=empresa.nombre, rol=Rol.objects.get(codigo='administrador'))

    def test_entrega_https_desde_los_tres_hosts_centrales_y_conserva_cookies_por_host(self):
        for host in settings.HOSTS_CENTRALES:
            with self.subTest(host=host):
                portal = APIClient(enforce_csrf_checks=True, HTTP_HOST=host, HTTP_X_FORWARDED_PROTO='https')
                entrada = portal.get('/')
                self.assertEqual(entrada.status_code, 200)
                self.assertTrue(entrada.cookies['csrftoken']['secure'])
                respuesta = portal.post('/api/v1/auth/login-web/', {
                    'email': 'cuenta@example.invalid', 'password': 'Fixture-clave-9',
                }, format='json', HTTP_X_CSRFTOKEN=portal.cookies['csrftoken'].value,
                    HTTP_ORIGIN='https://' + host)
                self.assertEqual(respuesta.status_code, 200, respuesta.data)
                destino = next(d for d in respuesta.data['data']['destinos'] if 'la-fragua.' in d['url'])
                self.assertEqual(destino['url'], 'https://la-fragua.smartstockchile.cl/acceder/')
                cliente = APIClient(HTTP_HOST='la-fragua.smartstockchile.cl', HTTP_X_FORWARDED_PROTO='https')
                entrega = cliente.post('/acceder/', {'ticket': destino['ticket']}, HTTP_ORIGIN='https://' + host)
                self.assertEqual(entrega.status_code, 200)
                self.assertTrue(entrega.cookies['sessionid']['secure'])
                self.assertEqual(entrega.cookies['sessionid']['domain'], '')
                self.assertEqual(cliente.get('/dashboard/').status_code, 200)
                otro = APIClient(HTTP_HOST='punto-motor.smartstockchile.cl', HTTP_X_FORWARDED_PROTO='https')
                otro.cookies['sessionid'] = cliente.cookies['sessionid'].value
                self.assertEqual(otro.get('/dashboard/').status_code, 302)

    def test_host_desconocido_y_central_no_abren_inventario_y_http_redirige(self):
        cliente = APIClient(HTTP_HOST='smartstockchile.cl')
        respuesta = cliente.get('/')
        self.assertEqual(respuesta.status_code, 301)
        self.assertEqual(respuesta['Location'], 'https://smartstockchile.cl/')
        self.assertEqual(cliente.get('/api/v1/productos/', HTTP_X_FORWARDED_PROTO='https').status_code, 404)
        self.assertEqual(cliente.get('/', HTTP_HOST='desconocida.smartstockchile.cl',
                                     HTTP_X_FORWARDED_PROTO='https').status_code, 404)

    def test_callback_sms_usa_la_empresa_y_exige_contexto_operativo(self):
        identificador = uuid4()
        for empresa in Empresa.objects.all():
            with usar_empresa(empresa):
                self.assertEqual(callback_url(identificador),
                    f'https://{empresa.codigo}.smartstockchile.cl/api/v1/alertas-sms/twilio/estado/{identificador}/')
        with self.assertRaises(ImproperlyConfigured):
            callback_url(identificador)

    def test_archivo_privado_sigue_funcionando_en_local_y_directorios_no_se_publican(self):
        empresa = Empresa.objects.get(alias_bd='ferreteria')
        cliente = APIClient(HTTP_HOST='la-fragua.smartstockchile.cl', HTTP_X_FORWARDED_PROTO='https')
        with TemporaryDirectory() as raiz, self.settings(MEDIA_ROOT=raiz):
            with usar_empresa(empresa):
                usuario = Usuario.objects.get(email='cuenta@example.invalid')
                cliente.force_login(usuario)
                nombre = default_storage.save('productos/ficha.txt', ContentFile(b'archivo privado'))
            respuesta = cliente.get('/media/' + nombre)
            self.assertEqual(respuesta.status_code, 200)
            self.assertEqual(b''.join(respuesta.streaming_content), b'archivo privado')
            self.assertIn('no-store', respuesta['Cache-Control'])
            self.assertEqual(cliente.get('/media/productos/').status_code, 404)
            self.assertEqual(cliente.get('/media/productos/ficha.txt/otra').status_code, 404)
            anonimo = APIClient(HTTP_HOST='la-fragua.smartstockchile.cl', HTTP_X_FORWARDED_PROTO='https')
            self.assertEqual(anonimo.get('/media/' + nombre).status_code, 302)
