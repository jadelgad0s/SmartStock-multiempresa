"""Regresiones del acceso web con dos empresas que reutilizan IDs, correo y SKU."""
from io import StringIO
from tempfile import TemporaryDirectory
from uuid import uuid4

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase, override_settings
from rest_framework.test import APIClient

from apps.core.empresa import empresa_actual, transaccion_operativa, usar_empresa
from apps.core.models import Auditoria
from apps.productos.models import Bodega, Producto, StockBodega
from apps.usuarios.models import Rol, Usuario
from apps.usuarios.tokens import token_recuperacion
from .models import Empresa


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class AccesoPorEmpresaTests(TestCase):
    databases = {'central', 'ferreteria', 'repuestos'}
    correo = 'inventario@example.invalid'
    clave = 'Clave-solo-para-fixtures'

    @classmethod
    def setUpTestData(cls):
        call_command('registrar_empresas_prueba', stdout=StringIO())
        cls.fragua = Empresa.objects.get(codigo='la-fragua')
        cls.motor = Empresa.objects.get(codigo='punto-motor')
        for empresa, cantidad in ((cls.fragua, 15), (cls.motor, 4)):
            call_command('seed_empresa', empresa.codigo, sin_admin=True, stdout=StringIO())
            with usar_empresa(empresa):
                Usuario.objects.create_user(
                    pk=90, email=cls.correo, password=cls.clave, nombres=empresa.nombre,
                    rol=Rol.objects.get(codigo='administrador'),
                )
                bodega = Bodega.objects.create(pk=1, nombre='Bodega Central')
                producto = Producto.objects.create(pk=10, sku='QA-UNO', nombre=empresa.nombre)
                Producto.objects.create(pk=11, sku='QA-DOS', nombre='Otro artículo')
                StockBodega.objects.create(producto=producto, bodega=bodega, cantidad_total=cantidad)

    def cliente(self, empresa):
        return APIClient(enforce_csrf_checks=True, HTTP_HOST=f'{empresa.codigo}.localhost')

    def ingresar(self, empresa):
        cliente = self.cliente(empresa)
        self.assertContains(cliente.get('/'), empresa.nombre)
        respuesta = cliente.post('/api/v1/auth/login-web/', {'email': self.correo, 'password': self.clave},
                                 format='json', HTTP_X_CSRFTOKEN=cliente.cookies['csrftoken'].value)
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        tokens = respuesta.data['data']
        cliente.credentials(HTTP_AUTHORIZATION='Bearer ' + tokens['access'])
        return cliente, tokens

    def test_directorio_repetible_respeta_empresas_y_esquema_fisico(self):
        Empresa.objects.filter(pk=self.motor.pk).update(activa=False)
        call_command('registrar_empresas_prueba', stdout=StringIO())
        self.assertEqual(Empresa.objects.count(), 2)
        self.assertFalse(Empresa.objects.get(pk=self.motor.pk).activa)
        with self.assertRaises(CommandError):
            call_command('seed_empresa', self.motor.codigo, stdout=StringIO())
        tablas_centrales = set(connections['central'].introspection.table_names())
        self.assertTrue({'empresas', 'tickets_acceso', 'usuarios', 'django_session', 'notificaciones_sistema'} <= tablas_centrales)
        self.assertFalse({'productos', 'bodegas', 'stock_bodega'} & tablas_centrales)
        tablas_a = set(connections['ferreteria'].introspection.table_names())
        self.assertNotIn('empresas', tablas_a)
        self.assertNotIn('tickets_acceso', tablas_a)
        self.assertNotIn('notificaciones_sistema', tablas_a)
        self.assertTrue({'usuarios', 'productos', 'stock_bodega', 'django_session'} <= tablas_a)
        self.assertEqual(tablas_a, set(connections['repuestos'].introspection.table_names()))

    def test_portal_muestra_login_y_solo_admite_empresas_activas_configuradas(self):
        portal = APIClient(HTTP_HOST='127.0.0.1:8000')
        self.assertContains(portal.get('/'), 'Correo electrónico')
        self.assertNotContains(portal.get('/'), 'Código de empresa')
        self.assertEqual(portal.get('/', {'empresa': 'la-fragua'}).status_code, 200)
        self.assertEqual(portal.get('/api/v1/productos/').status_code, 404)
        Empresa.objects.create(codigo='ajena', nombre='Sin base de negocio', alias_bd='central')
        for codigo in ('ajena', 'desconocida'):
            with self.subTest(codigo=codigo):
                self.assertEqual(portal.get('/', HTTP_HOST=codigo + '.localhost').status_code, 404)
        Empresa.objects.filter(pk=self.fragua.pk).update(activa=False)
        self.assertEqual(portal.get('/', HTTP_HOST='la-fragua.localhost').status_code, 404)

    def test_marca_de_empresa_en_todos_los_modulos_no_se_cambia_por_parametros(self):
        rutas = ('dashboard', 'productos', 'bodegas', 'ubicaciones', 'reportes', 'movimientos',
                 'transferencias', 'mermas', 'auditoria', 'usuarios', 'alertas-sms', 'soporte')
        for propia, ajena in ((self.fragua, self.motor), (self.motor, self.fragua)):
            cliente, _ = self.ingresar(propia)
            for ruta in rutas:
                with self.subTest(empresa=propia.codigo, ruta=ruta):
                    respuesta = cliente.get(f'/{ruta}/', {'empresa': ajena.codigo})
                    self.assertContains(respuesta, f'/static/branding/empresas/{propia.codigo}.png')
                    self.assertContains(respuesta, f'alt="Logo de {propia.nombre}"')
                    self.assertNotContains(respuesta, f'/static/branding/empresas/{ajena.codigo}.png')
                    self.assertNotContains(respuesta, 'branding/smartstock-mark.png')

    def test_acceso_y_recuperacion_muestran_solo_la_marca_del_host(self):
        for propia, ajena in ((self.fragua, self.motor), (self.motor, self.fragua)):
            cliente = self.cliente(propia)
            for ruta in ('/', '/recuperar-clave/'):
                with self.subTest(empresa=propia.codigo, ruta=ruta):
                    respuesta = cliente.get(ruta, {'empresa': ajena.codigo})
                    self.assertContains(respuesta, f'/static/branding/empresas/{propia.codigo}.png')
                    self.assertNotContains(respuesta, f'/static/branding/empresas/{ajena.codigo}.png')
                    self.assertContains(respuesta, f'<p class="ss-auth-company">{propia.nombre}</p>', html=True)
                    if propia.codigo == 'la-fragua':
                        self.assertContains(respuesta, 'ss-auth-layout ss-auth-la-fragua')
                    else:
                        self.assertNotContains(respuesta, 'ss-auth-layout ss-auth-la-fragua')
        portal = APIClient(HTTP_HOST='127.0.0.1:8000')
        for ruta in ('/', '/recuperar-clave/'):
            respuesta = portal.get(ruta, {'empresa': self.fragua.codigo})
            self.assertContains(respuesta, 'branding/smartstock-mark.png')
            self.assertNotContains(respuesta, 'branding/empresas/')
            self.assertNotContains(respuesta, '<p class="ss-auth-company">')
            self.assertNotContains(respuesta, 'ss-auth-layout ss-auth-la-fragua')

    def test_empresa_sin_logo_propio_tiene_alternativa_sin_consultas_extra(self):
        request = RequestFactory().get('/dashboard/')
        request.empresa = Empresa(codigo='otra-empresa', nombre='Otra empresa')
        with self.assertNumQueries(0, using='central'):
            marca = render_to_string('componentes/marca_aplicacion.html', request=request)
        self.assertIn('Otra empresa', marca)
        self.assertNotIn('branding/empresas/', marca)
        self.assertIn('branding/smartstock-mark.png', marca)

    def test_un_usuario_exclusivo_ingresa_solo_en_su_empresa(self):
        with usar_empresa(self.fragua):
            Usuario.objects.create_user(email='solo-fragua@example.invalid', password=self.clave,
                                        rol=Rol.objects.get(codigo='operador'))
        datos = {'email': 'solo-fragua@example.invalid', 'password': self.clave}
        self.assertEqual(self.cliente(self.motor).post('/api/v1/auth/login/', datos, format='json').status_code, 401)
        respuesta = self.cliente(self.fragua).post('/api/v1/auth/login/', datos, format='json')
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.data['data']['usuario']['email'], datos['email'])

    def test_tokens_y_sesion_quedan_vinculados_a_la_empresa(self):
        fragua, tokens = self.ingresar(self.fragua)
        motor = self.cliente(self.motor)
        motor.credentials(HTTP_AUTHORIZATION='Bearer ' + tokens['access'])
        self.assertEqual(motor.get('/api/v1/auth/me/').status_code, 401)
        self.assertEqual(motor.post('/api/v1/auth/refresh/', {'refresh': tokens['refresh']},
                                   format='json').status_code, 401)
        self.assertEqual(fragua.get('/api/v1/auth/me/').status_code, 200)
        self.assertEqual(fragua.post('/api/v1/auth/refresh/', {'refresh': tokens['refresh']},
                                    format='json').status_code, 200)
        motor.credentials()
        motor.cookies['sessionid'] = fragua.cookies['sessionid'].value
        self.assertRedirects(motor.get('/dashboard/'), '/', fetch_redirect_response=False)
        self.assertContains(fragua.get('/dashboard/'), 'Comparar productos')
        self.assertNotEqual(fragua.get('/admin/').status_code, 200)
        Empresa.objects.filter(pk=self.fragua.pk).update(activa=False)
        self.assertEqual(fragua.get('/dashboard/').status_code, 404)

    def test_movimiento_kardex_y_comparacion_con_el_mismo_sku_en_dos_bases(self):
        fragua, _ = self.ingresar(self.fragua)
        motor, _ = self.ingresar(self.motor)
        salida = fragua.post('/api/v1/productos/registrar-movimiento/', {
            'producto_id': 10, 'bodega_id': 1, 'tipo_movimiento': 'SALIDA', 'cantidad': 3,
        }, format='json')
        self.assertEqual(salida.status_code, 201, salida.data)
        self.assertEqual(salida.data['data']['stock_restante'], 12)
        for cliente, empresa, cantidad, salidas in ((fragua, self.fragua, 12, 3), (motor, self.motor, 4, 0)):
            with self.subTest(empresa=empresa.codigo):
                comparacion = cliente.get('/api/v1/productos/dashboard-comparacion/', {
                    'sku_a': 'QA-UNO', 'sku_b': 'QA-DOS', 'bodega': 1, 'dias': 30,
                })
                self.assertEqual(comparacion.status_code, 200, comparacion.data)
                sku = comparacion.data['data']['productos'][0]
                self.assertEqual((sku['nombre'], sku['stock_actual'], sku['total_salidas']),
                                 (empresa.nombre, cantidad, salidas))
                kardex = cliente.get('/api/v1/reportes/consulta/', {'informe': 'kardex', 'producto': 10, 'bodega': 1})
                self.assertEqual(kardex.status_code, 200, kardex.data)
                self.assertEqual([fila['saldo'] for fila in kardex.data['results']], [12] if salidas else [])

    def test_traslado_y_detalle_desde_el_kardex_pertenecen_a_la_empresa(self):
        for empresa in (self.fragua, self.motor):
            with usar_empresa(empresa):
                Bodega.objects.create(pk=2, nombre='Bodega de destino')
        fragua, _ = self.ingresar(self.fragua)
        motor, _ = self.ingresar(self.motor)
        ruta = '/api/v1/productos/transferencias/'
        traslado = fragua.post(ruta, {'bodega_origen_id': 1, 'bodega_destino_id': 2, 'producto_id': 10,
                                      'cantidad': 2, 'solicitud_id': str(uuid4())}, format='json')
        self.assertEqual(traslado.status_code, 201, traslado.data)
        filtros = {'informe': 'kardex', 'producto': 10, 'bodega': 2}
        historial = fragua.get('/api/v1/reportes/consulta/', filtros)
        self.assertEqual(historial.status_code, 200, historial.data)
        fila = historial.data['results'][0]
        self.assertEqual(fila['saldo'], 2)
        detalle = f"{ruta}{fila['transferencia_id']}/"
        self.assertEqual(fragua.get(detalle).status_code, 200)
        self.assertEqual(motor.get(detalle).status_code, 404)
        self.assertEqual(motor.get('/api/v1/reportes/consulta/', filtros).data['count'], 0)
        self.assertEqual(StockBodega.objects.using('repuestos').get().cantidad_total, 4)

    def test_descarga_de_auditoria_mantiene_la_base_durante_la_lectura_diferida(self):
        for empresa in (self.fragua, self.motor):
            with usar_empresa(empresa):
                Auditoria.objects.create(accion='CREATE', modelo='Producto', descripcion='Evento ' + empresa.codigo)
        fragua, _ = self.ingresar(self.fragua)
        motor, _ = self.ingresar(self.motor)
        descarga_a = fragua.get('/api/v1/auditoria/exportar/')
        descarga_b = motor.get('/api/v1/auditoria/exportar/')
        self.assertIsNone(empresa_actual())
        for descarga, propia, ajena in ((descarga_b, self.motor, self.fragua), (descarga_a, self.fragua, self.motor)):
            self.assertEqual(descarga.status_code, 200)
            csv = b''.join(descarga.streaming_content).decode('utf-8-sig')
            self.assertIn('Evento ' + propia.codigo, csv)
            self.assertNotIn('Evento ' + ajena.codigo, csv)

    def test_un_error_revierte_solo_la_transaccion_de_la_empresa_y_restaura_el_contexto(self):
        with usar_empresa(self.motor):
            StockBodega.objects.update(cantidad_total=5)
            with self.assertRaises(RuntimeError), usar_empresa(self.fragua), transaccion_operativa():
                StockBodega.objects.update(cantidad_total=0)
                raise RuntimeError('cancelar esta operación')
            self.assertEqual(StockBodega.objects.get().cantidad_total, 5)
        self.assertIsNone(empresa_actual())
        self.assertEqual(StockBodega.objects.using('ferreteria').get().cantidad_total, 15)

    def test_recuperacion_cache_y_archivos_mismo_nombre_son_independientes(self):
        with TemporaryDirectory() as directorio, self.settings(MEDIA_ROOT=directorio):
            with usar_empresa(self.fragua):
                usuario = Usuario.objects.get(pk=90)
                token = token_recuperacion.make_token(usuario)
                cache.set('producto:10', self.fragua.codigo)
                archivo = default_storage.save('productos/ficha.txt', ContentFile(b'fragua'))
            with usar_empresa(self.motor):
                self.assertFalse(token_recuperacion.check_token(usuario, token))
                self.assertIsNone(cache.get('producto:10'))
                self.assertFalse(default_storage.exists(archivo))
                self.assertEqual(default_storage.save(archivo, ContentFile(b'motor')), archivo)
            for empresa, esperado in ((self.fragua, b'fragua'), (self.motor, b'motor')):
                cliente, _ = self.ingresar(empresa)
                respuesta = cliente.get('/media/' + archivo)
                self.assertEqual(b''.join(respuesta.streaming_content), esperado)
            with usar_empresa(self.fragua):
                self.assertEqual(cache.get('producto:10'), self.fragua.codigo)
                self.assertTrue(token_recuperacion.check_token(usuario, token))
