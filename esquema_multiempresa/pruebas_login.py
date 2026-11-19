"""El login común conserva la identidad y los permisos de cada base."""
import re
from datetime import timedelta
from io import StringIO
from urllib.parse import urlsplit
from unittest.mock import patch

from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.db import OperationalError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.empresa import usar_empresa
from apps.usuarios.models import Rol, Usuario
from .models import Empresa, TicketAcceso


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class LoginUnificadoTests(TestCase):
    databases = {'central', 'ferreteria', 'repuestos'}
    origen = 'http://127.0.0.1:8000'
    correo = 'admin@example.invalid'
    claves = {'ferreteria': 'Fragua-clave-de-fixture', 'repuestos': 'Motor-clave-de-fixture'}

    @classmethod
    def setUpTestData(cls):
        call_command('registrar_empresas_prueba', stdout=StringIO())
        for empresa in Empresa.objects.all():
            call_command('seed_empresa', empresa.codigo, sin_admin=True, stdout=StringIO())
            with usar_empresa(empresa):
                Usuario.objects.create_user(
                    pk=90, email=cls.correo, password=cls.claves[empresa.alias_bd],
                    nombres=empresa.nombre, rol=Rol.objects.get(codigo='administrador'),
                )
        Usuario.objects.db_manager('central').create_superuser(
            pk=90, email='tecnico@example.invalid', password='Tecnico-clave-de-fixture',
            nombres='Equipo', apellidos='SmartStock',
        )

    def setUp(self):
        cache.clear()
        self.portal = APIClient(enforce_csrf_checks=True, HTTP_HOST='127.0.0.1:8000')
        self.assertEqual(self.portal.get('/')['Referrer-Policy'], 'strict-origin')

    def ingresar(self, clave=None, correo=None):
        return self.portal.post('/api/v1/auth/login-web/', {
            'email': correo or self.correo, 'password': clave or self.claves['ferreteria'],
        }, format='json', HTTP_X_CSRFTOKEN=self.portal.cookies['csrftoken'].value)

    def recibir(self, destino, origen=None, host=None):
        cliente = APIClient(enforce_csrf_checks=True, HTTP_HOST=host or urlsplit(destino['url']).netloc)
        respuesta = cliente.post('/acceder/', {'ticket': destino['ticket']},
                                 HTTP_ORIGIN=origen or self.origen)
        return cliente, respuesta

    def test_mismo_correo_con_claves_distintas_abre_la_empresa_correspondiente(self):
        for alias, codigo in (('ferreteria', 'la-fragua'), ('repuestos', 'punto-motor')):
            with self.subTest(alias=alias):
                respuesta = self.ingresar(self.claves[alias])
                self.assertEqual(respuesta.status_code, 200, respuesta.data)
                destinos = respuesta.data['data']['destinos']
                self.assertEqual(len(destinos), 1)
                self.assertEqual(destinos[0]['url'], f'http://{codigo}.localhost:8000/acceder/')
                self.assertNotIn(self.claves[alias], respuesta.content.decode())
                cliente, entrega = self.recibir(destinos[0])
                self.assertEqual(entrega.status_code, 200)
                self.assertContains(entrega, 'datos-sesion')
                self.assertEqual(cliente.get('/dashboard/').status_code, 200)
                self.assertEqual(Usuario.objects.using(alias).get(pk=90).intentos_fallidos, 0)
        self.assertEqual(Usuario.objects.using('repuestos').get(pk=90).intentos_fallidos, 0)

    def test_usuario_de_empresa_no_abre_el_panel_tecnico_con_su_sesion(self):
        destino = self.ingresar().data['data']['destinos'][0]
        cliente, _ = self.recibir(destino)
        self.portal.cookies['sessionid'] = cliente.cookies['sessionid'].value
        self.assertEqual(self.portal.get('/sistema/').status_code, 302)
        self.assertNotEqual(cliente.get('/admin/').status_code, 200)

    def test_superusuario_central_abre_sistema_y_no_un_inventario(self):
        respuesta = self.ingresar('Tecnico-clave-de-fixture', 'tecnico@example.invalid')
        self.assertEqual(respuesta.data['data'], {'sistema': True, 'inicio': '/sistema/'})
        panel = self.portal.get('/sistema/')
        self.assertContains(panel, 'Administración de SmartStock')
        self.assertContains(self.portal.get('/sistema/empresas/'), 'Ferretería La Fragua')
        self.assertEqual(self.portal.get('/api/v1/productos/').status_code, 404)
        ajeno = APIClient(HTTP_HOST='la-fragua.localhost:8000')
        ajeno.cookies['sessionid'] = self.portal.cookies['sessionid'].value
        self.assertEqual(ajeno.get('/dashboard/').status_code, 302)

    def test_el_login_exige_csrf_y_clave_correcta(self):
        sin_csrf = APIClient(enforce_csrf_checks=True, HTTP_HOST='127.0.0.1:8000')
        self.assertEqual(sin_csrf.post('/api/v1/auth/login-web/', {
            'email': self.correo, 'password': self.claves['ferreteria'],
        }, format='json').status_code, 403)
        self.assertEqual(self.ingresar('incorrecta').status_code, 401)
        self.assertFalse(TicketAcceso.objects.exists())
        self.assertEqual(Usuario.objects.using('ferreteria').get(pk=90).intentos_fallidos, 1)
        self.assertEqual(Usuario.objects.using('repuestos').get(pk=90).intentos_fallidos, 1)

    def test_el_ticket_exige_origen_empresa_y_un_solo_uso(self):
        destino = self.ingresar().data['data']['destinos'][0]
        self.assertEqual(self.recibir(destino, origen='https://otro.example.invalid')[1].status_code, 403)
        self.assertEqual(self.recibir(destino, host='punto-motor.localhost:8000')[1].status_code, 403)
        self.assertEqual(self.recibir(destino)[1].status_code, 200)
        self.assertEqual(self.recibir(destino)[1].status_code, 403)

    def test_ticket_caducado_o_clave_modificada_exige_autenticarse_otra_vez(self):
        destino = self.ingresar().data['data']['destinos'][0]
        TicketAcceso.objects.filter(pk=destino['ticket']).update(fecha_expiracion=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.recibir(destino)[1].status_code, 403)
        destino = self.ingresar().data['data']['destinos'][0]
        usuario = Usuario.objects.using('ferreteria').get(pk=90)
        usuario.set_password('Nueva-clave-de-fixture')
        usuario.save(using='ferreteria')
        self.assertEqual(self.recibir(destino)[1].status_code, 403)

    def test_reasignar_la_base_de_una_empresa_invalida_sus_tickets(self):
        destino = self.ingresar().data['data']['destinos'][0]
        original = Usuario.objects.using('ferreteria').get(pk=90)
        Usuario.objects.using('repuestos').filter(pk=90).update(password=original.password)
        Empresa.objects.filter(alias_bd='repuestos').delete()
        Empresa.objects.filter(alias_bd='ferreteria').update(alias_bd='repuestos')
        self.assertEqual(self.recibir(destino)[1].status_code, 403)

    def test_bloqueo_o_desactivacion_de_usuario_rol_y_empresa_se_aplican_al_login(self):
        Usuario.objects.using('ferreteria').filter(pk=90).update(activo=False)
        self.assertEqual(self.ingresar().status_code, 401)
        Usuario.objects.using('ferreteria').filter(pk=90).update(activo=True, bloqueado_hasta=timezone.now() + timedelta(minutes=10))
        self.assertEqual(self.ingresar().status_code, 401)
        Usuario.objects.using('ferreteria').filter(pk=90).update(bloqueado_hasta=None)
        Rol.objects.using('ferreteria').filter(codigo='administrador').update(activo=False)
        self.assertEqual(self.ingresar().status_code, 401)
        Rol.objects.using('ferreteria').filter(codigo='administrador').update(activo=True)
        Empresa.objects.filter(alias_bd='ferreteria').update(activa=False)
        self.assertEqual(self.ingresar().status_code, 401)

    def test_si_las_mismas_credenciales_tienen_dos_accesos_solo_ofrece_esos_destinos(self):
        usuario = Usuario.objects.using('repuestos').get(pk=90)
        usuario.set_password(self.claves['ferreteria'])
        usuario.save(using='repuestos')
        respuesta = self.ingresar()
        destinos = respuesta.data['data']['destinos']
        self.assertEqual({d['nombre'] for d in destinos}, {'Ferretería La Fragua', 'Repuestos Punto Motor'})
        for destino in destinos:
            self.assertEqual(self.recibir(destino)[1].status_code, 200)

    def test_una_base_no_disponible_no_produce_una_redireccion_incompleta(self):
        with patch('esquema_multiempresa.login.empresas_disponibles', side_effect=OperationalError('sin base')):
            self.assertEqual(self.ingresar().status_code, 503)
        self.assertFalse(TicketAcceso.objects.exists())

    def test_recuperacion_desde_el_login_comun_envia_enlaces_de_cada_empresa(self):
        self.portal.get('/recuperar-clave/')
        respuesta = self.portal.post('/recuperar-clave/', {'email': self.correo},
                                      HTTP_X_CSRFTOKEN=self.portal.cookies['csrftoken'].value)
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(len(mail.outbox), 2)
        hosts = set()
        for correo in mail.outbox:
            enlace = re.search(r'http://[^\s]+/restablecer-clave/[^\s]+/', correo.body).group()
            url = urlsplit(enlace)
            hosts.add(url.netloc)
            cliente = APIClient(HTTP_HOST=url.netloc)
            self.assertEqual(cliente.get(url.path).status_code, 302)
        self.assertEqual(hosts, {'la-fragua.localhost:8000', 'punto-motor.localhost:8000'})

    def test_el_panel_crea_cuentas_tecnicas_y_conserva_la_sesion_de_la_otra_empresa(self):
        fragua, _ = self.recibir(self.ingresar().data['data']['destinos'][0])
        self.ingresar('Tecnico-clave-de-fixture', 'tecnico@example.invalid')
        self.portal.get('/sistema/configuracion/usuarios/usuario/add/')
        respuesta = self.portal.post('/sistema/configuracion/usuarios/usuario/add/', {
            'email': 'soporte@example.invalid', 'nombres': 'Soporte', 'apellidos': 'SmartStock',
            'password1': 'Clave-de-soporte-fixture-128', 'password2': 'Clave-de-soporte-fixture-128',
            'is_superuser': 'on',
        }, HTTP_X_CSRFTOKEN=self.portal.cookies['csrftoken'].value)
        self.assertEqual(respuesta.status_code, 302)
        nuevo = Usuario.objects.using('central').get(email='soporte@example.invalid')
        self.assertTrue(nuevo.is_superuser and nuevo.is_staff)
        self.assertIsNone(nuevo.rol_id)
        self.assertEqual(fragua.get('/dashboard/').status_code, 200)
