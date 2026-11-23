"""Menos viajes a PostgreSQL, conexiones reutilizadas y contenido sin bloqueo."""
from copy import deepcopy
from datetime import timedelta
from threading import Thread
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.db import connections
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.empresa import usar_empresa
from apps.usuarios.models import Usuario
from . import pruebas_contacto as correo
from . import pruebas_soporte as soporte
from .conexiones import con_pool_neon
from .models import AccesoSoporte, AtencionSoporte, MensajeContacto
from .zoho_contacto import ErrorZoho


class ConfiguracionPoolTests(SimpleTestCase):
    def test_conserva_neon_y_ssl_y_no_modifica_la_configuracion_directa(self):
        base = {'default': {}, 'central': {'ENGINE': 'django.db.backends.postgresql',
            'NAME': 'central', 'HOST': 'endpoint-fixture.neon.tech', 'USER': 'fixture',
            'PASSWORD': 'solo-fixture', 'PORT': 5432, 'OPTIONS': {'sslmode': 'require', 'connect_timeout': 15}}}
        base['empresa'] = {**deepcopy(base['central']), 'NAME': 'empresa'}
        copia = deepcopy(base)
        resultado = con_pool_neon(base, ['central', 'empresa'])
        self.assertEqual(base, copia)
        self.assertNotIn('pool', base['central']['OPTIONS'])
        for alias in ('central', 'empresa'):
            for clave in ('ENGINE', 'HOST', 'PORT', 'NAME', 'USER', 'PASSWORD'):
                self.assertEqual(resultado[alias][clave], base[alias][clave])
            self.assertEqual(resultado[alias]['OPTIONS']['sslmode'], 'require')
            self.assertEqual(resultado[alias]['CONN_MAX_AGE'], 0)
            self.assertTrue(resultado[alias]['CONN_HEALTH_CHECKS'])
            self.assertEqual(resultado[alias]['OPTIONS']['pool']['min_size'], 0)
            self.assertEqual(resultado[alias]['OPTIONS']['pool']['max_size'], 4)
        self.assertIsNot(resultado['central']['OPTIONS']['pool'], resultado['empresa']['OPTIONS']['pool'])

    def test_rechaza_sustituir_neon_por_una_base_local(self):
        for motor, host in (('django.db.backends.sqlite3', ''), ('django.db.backends.postgresql', 'localhost'),
                            ('django.db.backends.postgresql', 'servidor-ajeno.invalid')):
            with self.subTest(motor=motor, host=host), self.assertRaises(ImproperlyConfigured):
                con_pool_neon({'central': {'ENGINE': motor, 'HOST': host}}, ['central'])


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ConsultasRendimientoTests(TestCase):
    databases = {'central', 'ferreteria', 'repuestos'}
    clave = soporte.PermisosSoporteTests.clave

    @classmethod
    def setUpTestData(cls):
        soporte.PermisosSoporteTests.setUpTestData.__func__(cls)

    def test_resumen_hace_una_consulta_por_empresa_y_conserva_los_indicadores(self):
        cliente = APIClient(HTTP_HOST='127.0.0.1:8000')
        cliente.force_login(self.raiz)
        with CaptureQueriesContext(connections['ferreteria']) as a, CaptureQueriesContext(connections['repuestos']) as b:
            respuesta = cliente.get('/sistema/')
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(len(a), 1)
        self.assertEqual(len(b), 1)
        for resumen in respuesta.context['resumen_empresas']:
            self.assertEqual(resumen['usuarios'], 2)
            self.assertTrue(resumen['administrador'])
            self.assertFalse(resumen['puede_invitar'])

    def test_permisos_se_entregan_con_el_html_y_se_revalidan_en_la_siguiente_pagina(self):
        cliente = APIClient(HTTP_HOST='la-fragua.localhost:8000')
        with usar_empresa(self.fragua):
            cliente.force_login(Usuario.objects.get(pk=90))
        respuesta = cliente.get('/dashboard/')
        self.assertContains(respuesta, 'id="ss-navegacion-inicial"')
        datos = respuesta.wsgi_request.navegacion_verificada
        self.assertEqual(datos['usuario']['id'], 90)
        self.assertIn('/dashboard/', datos['modulos'])
        self.assertIn('/soporte/', datos['modulos'])
        Usuario.objects.using('ferreteria').filter(pk=90).update(activo=False)
        self.assertEqual(cliente.get('/dashboard/').status_code, 302)
        central = APIClient(HTTP_HOST='127.0.0.1:8000')
        central.force_login(self.raiz)
        self.assertNotContains(central.get('/sistema/'), 'id="ss-navegacion-inicial"')

    def test_varios_enlaces_de_una_atencion_comparten_una_lectura_sin_conservarla_entre_peticiones(self):
        caso = AtencionSoporte.objects.using('central').create(empresa=self.fragua, tecnico=self.soporte,
            asunto='Revisión autorizada', motivo='Comprobar consultas autorizadas de prueba')
        ahora = timezone.now()
        acceso = AccesoSoporte.objects.using('central').create(atencion=caso, tecnico=self.soporte,
            alcances=list(soporte.LECTURAS), motivo='Lecturas solicitadas por el cliente', estado='aprobado',
            decidido_en=ahora, expira_en=ahora + timedelta(minutes=30), aprobador_id=90,
            aprobador_email='cliente@example.invalid')
        cliente = APIClient(HTTP_HOST='127.0.0.1:8000'); cliente.force_login(self.soporte)
        with CaptureQueriesContext(connections['central']) as consultas:
            pagina = cliente.get(f'/sistema/atenciones/{caso.pk}/')
        self.assertEqual(pagina.status_code, 200)
        vigentes = [q for q in consultas.captured_queries if 'FROM "accesos_soporte"' in q['sql'] and '"expira_en" >' in q['sql']]
        self.assertEqual(len(vigentes), 1)
        self.assertContains(pagina, 'href="/sistema/catalogo/')
        AccesoSoporte.objects.using('central').filter(pk=acceso.pk).update(estado='revocado')
        self.assertNotContains(cliente.get(f'/sistema/atenciones/{caso.pk}/'), 'href="/sistema/catalogo/')
        self.assertEqual(cliente.get('/sistema/catalogo/', {'empresa': 'la-fragua', 'atencion': str(caso.pk)}).status_code, 403)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
                   ZOHO_CONTACTO_CLIENT_ID='', ZOHO_CONTACTO_CLIENT_SECRET='', ZOHO_CONTACTO_REFRESH_TOKEN='')
class ContenidoIndependienteTests(TestCase):
    databases = {'central', 'ferreteria', 'repuestos'}
    clave = correo.ContactoTests.clave

    @classmethod
    def setUpTestData(cls):
        correo.ContactoTests.setUpTestData.__func__(cls)

    def setUp(self):
        self.cliente = APIClient(enforce_csrf_checks=True, HTTP_HOST='127.0.0.1:8000')
        self.cliente.force_login(self.contacto)
        self.ruta = f'/contacto/mensajes/{self.mensaje.pk}/'
        self.contenido = self.ruta + 'contenido/'
        self.cliente.get(self.ruta)

    def post(self):
        return self.cliente.post(self.contenido, {}, HTTP_X_CSRFTOKEN=self.cliente.cookies['csrftoken'].value)

    @override_settings(**correo.ZOHO)
    def test_html_se_muestra_sin_esperar_a_zoho_y_conserva_el_editor(self):
        MensajeContacto.objects.using('central').filter(pk=self.mensaje.pk).update(contenido='', contenido_cargado=False)
        with patch('esquema_multiempresa.contacto.ClienteZoho', side_effect=AssertionError('Zoho no debe bloquear HTML')):
            pagina = self.cliente.get(self.ruta)
        self.assertContains(pagina, 'id="contacto-contenido"')
        self.assertContains(pagina, 'data-contenido-texto>Resumen')
        self.assertContains(pagina, 'data-borrador-editor')
        self.assertContains(pagina, self.contenido)

    def test_contenido_guardado_se_consulta_sin_volver_a_zoho(self):
        with patch('esquema_multiempresa.contacto.ClienteZoho') as externo:
            respuesta = self.post()
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json()['data']['contenido'], 'Contenido del correo')
        self.assertIn('no-store', respuesta['Cache-Control'])
        externo.assert_not_called()

    @override_settings(**correo.ZOHO)
    def test_descarga_guarda_en_central_y_no_repite_la_descarga_al_reabrir(self):
        MensajeContacto.objects.using('central').filter(pk=self.mensaje.pk).update(contenido='', contenido_cargado=False)
        with patch('esquema_multiempresa.contacto.ClienteZoho') as externo:
            externo.return_value.contenido.return_value = 'Texto completo del correo'
            respuesta = self.post()
            self.assertEqual(respuesta.status_code, 200)
            self.assertEqual(self.post().json()['data']['contenido'], 'Texto completo del correo')
            externo.return_value.contenido.assert_called_once()
        self.mensaje.refresh_from_db(using='central')
        self.assertTrue(self.mensaje.contenido_cargado)
        self.assertEqual(self.mensaje.contenido, 'Texto completo del correo')
        self.assertEqual(respuesta.json()['data']['usuario_id'], self.contacto.pk)
        self.assertContains(self.cliente.get(self.ruta), 'Texto completo del correo')
        for alias in ('ferreteria', 'repuestos'):
            self.assertNotIn('mensajes_contacto', connections[alias].introspection.table_names())

    @override_settings(**correo.ZOHO)
    def test_error_de_zoho_permite_reintentar_y_no_marca_contenido_vacio_como_descargado(self):
        MensajeContacto.objects.using('central').filter(pk=self.mensaje.pk).update(contenido='', contenido_cargado=False)
        with patch('esquema_multiempresa.contacto.ClienteZoho') as externo:
            externo.return_value.contenido.side_effect = ErrorZoho('Zoho no respondió')
            respuesta = self.post()
        self.assertEqual(respuesta.status_code, 502)
        self.assertEqual(respuesta.json()['mensaje'], 'Zoho no respondió')
        self.mensaje.refresh_from_db(using='central')
        self.assertFalse(self.mensaje.contenido_cargado)
        self.assertContains(self.cliente.get(self.ruta), 'data-borrador-editor')

    def test_csrf_metodos_y_roles_tambien_protegen_el_contenido(self):
        self.assertEqual(self.cliente.get(self.contenido).status_code, 405)
        self.assertEqual(self.cliente.post(self.contenido, {}).status_code, 403)
        for usuario in (self.root, self.soporte):
            self.cliente.force_login(usuario)
            self.assertEqual(self.post().status_code, 403)
        cliente = APIClient(HTTP_HOST='la-fragua.localhost:8000')
        self.assertEqual(cliente.get(self.contenido).status_code, 404)

    def test_correo_guardado_tiene_presupuesto_de_consultas_y_no_descarga_remota(self):
        with CaptureQueriesContext(connections['central']) as consultas:
            respuesta = self.cliente.get(self.ruta)
        self.assertEqual(respuesta.status_code, 200)
        self.assertLessEqual(len(consultas), 9)
        con_buzon = [q for q in consultas.captured_queries if 'FROM "buzon_contacto"' in q['sql']]
        self.assertEqual(len(con_buzon), 1)


class ReutilizacionPostgresTests(TransactionTestCase):
    databases = {'central', 'repuestos'}

    def test_hilos_distintos_reutilizan_la_conexion_y_cada_alias_conserva_su_base(self):
        if connections['central'].vendor != 'postgresql':
            self.skipTest('Reutilización de conexiones comprobada con PostgreSQL real.')
        from django.db.backends.postgresql.base import DatabaseWrapper
        resultados, errores, wrappers = [], [], []

        def consultar(alias, origen):
            cfg = deepcopy(connections[origen].settings_dict)
            cfg['CONN_MAX_AGE'], cfg['CONN_HEALTH_CHECKS'] = 0, True
            cfg['OPTIONS']['pool'] = con_pool_neon({'x': {'ENGINE': 'django.db.backends.postgresql',
                'HOST': 'fixture.neon.tech'}}, ['x'])['x']['OPTIONS']['pool']
            conexion = DatabaseWrapper(cfg, alias=alias)
            wrappers.append(conexion)
            try:
                with conexion.cursor() as cursor:
                    cursor.execute('SELECT pg_backend_pid(), current_database()')
                    resultados.append((alias, *cursor.fetchone()))
            except Exception as error:
                errores.append(error)
            finally:
                conexion.close()

        try:
            for alias, origen in (('qa_pool_central', 'central'), ('qa_pool_central', 'central'), ('qa_pool_empresa', 'repuestos')):
                hilo = Thread(target=consultar, args=(alias, origen)); hilo.start(); hilo.join(timeout=20)
                self.assertFalse(hilo.is_alive(), 'La consulta al pool no debe bloquearse.')
            self.assertEqual(errores, [])
            self.assertEqual(resultados[0][1], resultados[1][1])
            self.assertEqual(resultados[0][2], connections['central'].settings_dict['NAME'])
            self.assertEqual(resultados[2][2], connections['repuestos'].settings_dict['NAME'])
            self.assertNotEqual(resultados[0][2], resultados[2][2])
            self.assertEqual(wrappers[0].pool.get_stats()['connections_num'], 1)
        finally:
            for conexion in wrappers:
                conexion.close_pool()
