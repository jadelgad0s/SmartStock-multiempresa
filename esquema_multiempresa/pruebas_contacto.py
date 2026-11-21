"""Identidad exclusiva, separación entre bases y contrato HTTPS del buzón Zoho."""
from datetime import timedelta
from io import StringIO
from types import SimpleNamespace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

import requests
from django.core import mail
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import connections
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.empresa import usar_empresa
from apps.usuarios.models import Rol, Usuario
from .buzon_contacto import sincronizar_buzon
from .forms import CuentaTecnicaForm
from .models import BuzonContacto, Empresa, MensajeContacto, NotaContacto, NotificacionSistema, RespuestaContacto
from .permisos import CONTACTO, CORREO_CONTACTO, SOPORTE_TECNICO, es_contacto_smartstock, es_personal_smartstock
from .zoho_contacto import ClienteZoho, ErrorZoho, cifrar_configuracion, configuracion_zoho, texto_correo


ZOHO = {'ZOHO_CONTACTO_CLIENT_ID': 'cliente-fixture', 'ZOHO_CONTACTO_CLIENT_SECRET': 'secreto-fixture',
        'ZOHO_CONTACTO_REFRESH_TOKEN': 'refresh-fixture', 'ZOHO_CONTACTO_DC': 'com'}


def respuesta_zoho(data, status=200):
    return SimpleNamespace(status_code=status, content=b'{}',
                           json=lambda: {'status': {'code': status}, 'data': data})


def cuentas_zoho(correo=CORREO_CONTACTO):
    return respuesta_zoho([{'accountId': '101', 'primaryEmailAddress': correo}])


def fila_zoho(numero='201'):
    return {'messageId': numero, 'folderId': '301', 'sender': 'Persona de prueba',
            'fromAddress': 'consulta@example.invalid', 'subject': 'Ayuda con acceso',
            'summary': 'Necesito orientación', 'hasAttachment': '1', 'receivedTime': '1795219200000'}


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
                   ZOHO_CONTACTO_CLIENT_ID='', ZOHO_CONTACTO_CLIENT_SECRET='', ZOHO_CONTACTO_REFRESH_TOKEN='')
class ContactoTests(TestCase):
    databases = {'central', 'ferreteria', 'repuestos'}
    clave = 'Solo-fixture-contacto-2026!'

    @classmethod
    def setUpTestData(cls):
        call_command('registrar_empresas_prueba', stdout=StringIO())
        cls.rol, _ = Rol.objects.using('central').get_or_create(codigo=CONTACTO, defaults={'nombre': 'Contacto', 'es_sistema': True})
        cls.contacto = Usuario.objects.db_manager('central').create_user(
            email=CORREO_CONTACTO, password=cls.clave, nombres='Contacto', apellidos='SmartStock', is_staff=True, rol=cls.rol)
        cls.root = Usuario.objects.db_manager('central').create_superuser(
            email='root@example.invalid', password=cls.clave, nombres='Superusuario')
        cls.soporte = Usuario.objects.db_manager('central').create_user(
            email='soporte@example.invalid', password=cls.clave, nombres='Soporte', is_staff=True,
            rol=Rol.objects.using('central').get(codigo=SOPORTE_TECNICO))
        cls.mensaje = MensajeContacto.objects.using('central').create(
            cuenta_zoho='101', mensaje_zoho='201', carpeta_zoho='301', asunto='Consulta de fixture',
            remitente_nombre='Persona', remitente_email='consulta@example.invalid', resumen='Resumen',
            contenido='Contenido del correo', contenido_cargado=True, tiene_adjuntos=True)

    def setUp(self):
        cache.clear()
        self.cliente = APIClient(enforce_csrf_checks=True, HTTP_HOST='127.0.0.1:8000')
        self.cliente.get('/')

    def entrar(self, usuario=None):
        usuario = usuario or self.contacto
        return self.cliente.post('/api/v1/auth/login-web/', {'email': usuario.email, 'password': self.clave},
                                 format='json', HTTP_X_CSRFTOKEN=self.cliente.cookies['csrftoken'].value)

    def post(self, ruta, datos, **headers):
        with self.captureOnCommitCallbacks(using='central', execute=True):
            return self.cliente.post(ruta, datos, HTTP_X_CSRFTOKEN=self.cliente.cookies['csrftoken'].value, **headers)

    @property
    def ruta(self):
        return f'/contacto/mensajes/{self.mensaje.pk}/'

    def test_login_contacto_abre_su_bandeja_y_no_administracion(self):
        self.assertEqual(self.entrar().data['data'], {'contacto': True, 'inicio': '/contacto/bandeja/'})
        panel = self.cliente.get('/contacto/bandeja/')
        self.assertContains(panel, 'Atención de SmartStock')
        self.assertContains(panel, 'Zoho')
        self.assertContains(panel, 'href="/contacto/mi-cuenta/" class="ss-sidebar-profile')
        for ruta in ('/sistema/', '/sistema/empresas/', '/sistema/cuentas/', '/sistema/configuracion/',
                     '/sistema/catalogo/', '/sistema/usuarios/', '/sistema/contacto/cuenta/'):
            self.assertNotContains(panel, f'href="{ruta}"')
            self.assertEqual(self.cliente.get(ruta).status_code, 403, ruta)
        self.assertRedirects(self.cliente.get('/'), '/contacto/bandeja/', fetch_redirect_response=False)

    def test_bandeja_exclusiva_no_abre_para_root_soporte_o_anonimo(self):
        self.assertEqual(self.cliente.get('/contacto/bandeja/').status_code, 302)
        for cuenta in (self.root, self.soporte):
            self.entrar(cuenta)
            for ruta in ('/contacto/bandeja/', self.ruta, '/contacto/mi-cuenta/'):
                self.assertEqual(self.cliente.get(ruta).status_code, 403)
            self.assertEqual(self.post('/contacto/sincronizar/', {}).status_code, 403)
        self.assertEqual(self.cliente.get('/sistema/contacto/cuenta/').status_code, 403)

    def test_contacto_no_es_asignable_en_formulario_general_ni_post_forzado(self):
        self.entrar(self.root)
        form = CuentaTecnicaForm(actor=self.root)
        self.assertNotIn(CONTACTO, dict(form.fields['perfil'].choices))
        respuesta = self.post('/sistema/cuentas/nueva/', {'email': 'otro@example.invalid', 'nombres': 'Otra',
            'apellidos': 'Persona', 'activo': 'on', 'perfil': CONTACTO, 'password1': self.clave, 'password2': self.clave})
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(Usuario.objects.using('central').filter(email='otro@example.invalid').exists())
        self.assertRedirects(self.cliente.get(f'/sistema/cuentas/{self.contacto.pk}/'), '/sistema/contacto/cuenta/', fetch_redirect_response=False)

    def test_modelo_rechaza_contacto_en_otro_correo_y_no_permite_reasignarlo(self):
        with self.assertRaises(ValidationError):
            Usuario.objects.db_manager('central').create_user(email='otro@example.invalid', nombres='Otra', is_staff=True, rol=self.rol)
        self.contacto.email = 'otro@example.invalid'
        with self.assertRaises(ValidationError):
            self.contacto.save(using='central')
        self.contacto.refresh_from_db(using='central')
        self.contacto.is_superuser = True
        with self.assertRaises(ValidationError):
            self.contacto.save(using='central')
        self.assertFalse(es_personal_smartstock(self.contacto))

    def test_apartado_exclusivo_crea_cuenta_fija_e_ignora_flags_correo_y_rol_forjados(self):
        # Se borra solamente la cuenta de la fixture; no contiene datos de empresas.
        from .admin_central import RecolectorCuentasCentrales
        recolector = RecolectorCuentasCentrales()
        recolector.collect([self.contacto])
        recolector.delete()
        self.entrar(self.root)
        datos = {'email': 'atacante@example.invalid', 'nombres': 'Atención', 'apellidos': 'SmartStock',
                 'activo': 'on', 'password1': self.clave, 'password2': self.clave,
                 'perfil': 'superusuario', 'is_superuser': 'on', 'is_staff': '', 'rol': self.soporte.rol_id}
        self.assertEqual(self.post('/sistema/contacto/cuenta/', datos).status_code, 302)
        cuenta = Usuario.objects.using('central').get(email=CORREO_CONTACTO)
        self.assertTrue(es_contacto_smartstock(cuenta))
        datos.update(password1='', password2='')
        self.assertEqual(self.post('/sistema/contacto/cuenta/', datos).status_code, 302)
        self.assertEqual(Usuario.objects.using('central').filter(rol=self.rol).count(), 1)

    def test_perfil_propio_conserva_identidad_estado_y_privilegios(self):
        self.entrar()
        respuesta = self.post('/contacto/mi-cuenta/', {'nombres': 'Atención', 'apellidos': 'Consultas',
            'email': 'otro@example.invalid', 'activo': '', 'is_superuser': 'on', 'perfil': 'superusuario',
            'telefono': '', 'password1': '', 'password2': ''})
        self.assertEqual(respuesta.status_code, 302)
        self.contacto.refresh_from_db(using='central')
        self.assertTrue(es_contacto_smartstock(self.contacto))
        self.assertEqual(self.contacto.nombres, 'Atención')
        self.assertContains(self.cliente.get('/contacto/bandeja/'), 'Atención de SmartStock')

    def test_suspender_contacto_invalida_la_sesion_y_el_login(self):
        self.entrar()
        Usuario.objects.using('central').filter(pk=self.contacto.pk).update(activo=False)
        self.assertEqual(self.cliente.get('/contacto/bandeja/').status_code, 403)
        self.assertEqual(self.entrar().status_code, 401)

    def test_no_se_reutiliza_correo_reservado_en_otra_empresa(self):
        empresa = Empresa.objects.get(codigo='la-fragua')
        with usar_empresa(empresa):
            Usuario.objects.create_user(email=CORREO_CONTACTO, password=self.clave, nombres='Cliente',
                                        rol=Rol.objects.create(codigo='operador', nombre='Operador'))
        Usuario.objects.using('central').filter(pk=self.contacto.pk).update(activo=False)
        self.assertEqual(self.entrar().status_code, 401)

    def test_campana_es_privada_tambien_para_contacto(self):
        propio = NotificacionSistema.objects.using('central').create(destinatario=self.contacto, titulo='Consulta', mensaje='Texto')
        ajeno = NotificacionSistema.objects.using('central').create(destinatario=self.root, titulo='Solo root', mensaje='Privado')
        self.entrar()
        datos = self.cliente.get('/sistema/notificaciones/').json()['data']
        self.assertEqual([item['id'] for item in datos['items']], [str(propio.pk)])
        self.assertEqual(self.post(f'/sistema/notificaciones/{ajeno.pk}/leer/', {}).status_code, 404)

    def test_seguimiento_notas_y_busqueda_sin_envios_y_con_escape(self):
        self.entrar()
        self.assertEqual(self.post(self.ruta, {'accion': 'seguimiento', 'version': 0, 'estado': 'seguimiento',
            'categoria': 'acceso', 'seguimiento': str(timezone.localdate())}).status_code, 302)
        self.assertEqual(self.post(self.ruta, {'accion': 'nota', 'texto': '<script>alert(1)</script> Llamar'}).status_code, 302)
        detalle = self.cliente.get(self.ruta)
        self.assertContains(detalle, '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(detalle, '<script>alert(1)</script>')
        self.assertEqual(NotaContacto.objects.using('central').count(), 1)
        self.assertEqual(len(self.cliente.get('/contacto/bandeja/?vista=seguimiento&vencidos=1').context['pagina']), 1)
        self.assertEqual(len(self.cliente.get('/contacto/bandeja/?search=no-existe').context['pagina']), 0)
        self.assertEqual(len(getattr(mail, 'outbox', [])), 0)

    def test_version_anterior_no_sobrescribe_seguimiento(self):
        self.entrar()
        MensajeContacto.objects.using('central').filter(pk=self.mensaje.pk).update(version=2, estado='resuelto')
        respuesta = self.post(self.ruta, {'accion': 'seguimiento', 'version': 0, 'estado': 'pendiente', 'categoria': 'general'})
        self.assertContains(respuesta, 'cambió en otra pestaña')
        self.mensaje.refresh_from_db(using='central')
        self.assertEqual(self.mensaje.estado, 'resuelto')

    def test_borrador_se_guarda_sin_enviar_y_no_se_sobrescribe_desde_otra_pestana(self):
        self.entrar()
        with patch('esquema_multiempresa.zoho_contacto.requests.request') as externo:
            self.assertEqual(self.post(self.ruta, {'accion': 'borrador', 'texto': 'Primera respuesta', 'version': 0}).status_code, 302)
            respuesta = self.post(self.ruta, {'accion': 'borrador', 'texto': 'Pestaña antigua', 'version': 0})
            self.assertContains(respuesta, 'Ya hay un borrador')
            self.assertEqual(RespuestaContacto.objects.using('central').get().texto, 'Primera respuesta')
            externo.assert_not_called()

    def test_cambios_y_sincronizacion_exigen_csrf(self):
        self.entrar()
        self.assertEqual(self.cliente.post(self.ruta, {'accion': 'nota', 'texto': 'Sin CSRF'}).status_code, 403)
        self.assertEqual(self.cliente.post('/contacto/sincronizar/').status_code, 403)
        self.assertEqual(self.cliente.get('/contacto/sincronizar/').status_code, 405)
        self.assertFalse(NotaContacto.objects.using('central').exists())

    def test_sin_conexion_no_inventa_correos_ni_simula_que_envio(self):
        self.entrar()
        with patch('esquema_multiempresa.zoho_contacto.requests.request') as externo:
            respuesta = self.post('/contacto/sincronizar/', {})
            self.assertEqual(respuesta.status_code, 302)
            self.assertContains(self.cliente.get(respuesta.url), 'aún no está conectado')
            self.assertFalse(NotificacionSistema.objects.using('central').exists())
            self.assertEqual(MensajeContacto.objects.using('central').count(), 1)
            externo.assert_not_called()

    @override_settings(**ZOHO)
    def test_sincroniza_metadatos_reales_sin_duplicar_ni_borrar_seguimiento(self):
        self.mensaje.estado = 'resuelto'
        self.mensaje.save(using='central')
        with patch('esquema_multiempresa.zoho_contacto.requests.post', return_value=SimpleNamespace(
                status_code=200, json=lambda: {'access_token': 'token-fixture'})), \
             patch('esquema_multiempresa.zoho_contacto.requests.request', side_effect=[
                cuentas_zoho(), respuesta_zoho([fila_zoho(), fila_zoho('202')]),
                cuentas_zoho(), respuesta_zoho([fila_zoho(), fila_zoho('202')])]) as externo:
            self.assertEqual(sincronizar_buzon(), 1)
            BuzonContacto.objects.using('central').update(ultima_consulta=timezone.now() - timedelta(minutes=1))
            self.assertEqual(sincronizar_buzon(), 0)
            self.assertEqual(externo.call_count, 4)
            self.assertEqual(externo.call_args_list[1].kwargs['params']['searchKey'], 'in:Inbox::groupResult:false')
        self.assertEqual(MensajeContacto.objects.using('central').count(), 2)
        self.mensaje.refresh_from_db(using='central')
        self.assertEqual(self.mensaje.estado, 'resuelto')
        self.assertEqual(NotificacionSistema.objects.using('central').filter(destinatario=self.contacto).count(), 1)

    @override_settings(**ZOHO)
    def test_actualizar_importa_correo_de_recibidos_recien_llegado_con_fecha_de_busqueda(self):
        """Una lista sin carpeta vacía no implica que Recibidos no tenga mensajes."""
        self.entrar()
        recibida = timezone.now() - timedelta(seconds=15)
        fila = fila_zoho('202')
        fila['subject'] = 'Prueba recién llegada a Recibidos'
        fila['receivedtime'] = str(int(recibida.timestamp() * 1000))
        del fila['receivedTime']

        def api(metodo, url, **opciones):
            self.assertEqual(metodo, 'GET')
            if url.endswith('/api/accounts'):
                return cuentas_zoho()
            if url.endswith('/messages/view'):
                return respuesta_zoho([])
            if url.endswith('/messages/search'):
                criterios = opciones['params']
                self.assertEqual(criterios['searchKey'], 'in:Inbox::groupResult:false')
                # Zoho omite los dos minutos más recientes cuando no se da un
                # límite explícito; la fecha actual debe incluir esta fixture.
                if criterios.get('receivedTime', 0) >= int(recibida.timestamp() * 1000):
                    return respuesta_zoho([fila])
                return respuesta_zoho([])
            self.fail('Se intentó consultar un recurso de otro buzón')

        with patch('esquema_multiempresa.zoho_contacto.requests.post', return_value=SimpleNamespace(
                status_code=200, json=lambda: {'access_token': 'token-fixture'})), \
             patch('esquema_multiempresa.zoho_contacto.requests.request', side_effect=api):
            resultado = self.post('/contacto/sincronizar/', {}, HTTP_ACCEPT='application/json')
            repetido = self.post('/contacto/sincronizar/', {}, HTTP_ACCEPT='application/json')
        self.assertEqual(resultado.status_code, 200)
        self.assertEqual(resultado.json()['nuevos'], 1)
        self.assertEqual(repetido.json()['nuevos'], 0)
        mensaje = MensajeContacto.objects.using('central').get(mensaje_zoho='202')
        self.assertLess(abs((mensaje.recibido_en - recibida).total_seconds()), .001)
        self.assertFalse(mensaje.contenido_cargado)
        self.assertContains(self.cliente.get('/contacto/bandeja/'), 'Prueba recién llegada a Recibidos')

    @override_settings(**ZOHO)
    def test_consulta_de_recibidos_conserva_paginacion_y_no_se_limita_a_sin_leer(self):
        leido, sin_leer = fila_zoho('202'), fila_zoho('203')
        leido['status'], sin_leer['status'] = 'read', 'unread'
        with patch('esquema_multiempresa.zoho_contacto.requests.request', side_effect=[
                cuentas_zoho(), respuesta_zoho([leido, sin_leer])]) as externo:
            cliente = ClienteZoho({'client_id':'fixture','client_secret':'fixture','refresh_token':'fixture','dc':'com'}, token='fixture')
            cuenta, filas = cliente.listar(101)
        self.assertEqual(cuenta, '101')
        self.assertEqual([fila['messageId'] for fila in filas], ['202', '203'])
        criterios = externo.call_args.kwargs['params']
        self.assertEqual((criterios['start'], criterios['limit']), (101, 100))
        self.assertNotIn('status', criterios)

    @override_settings(**ZOHO)
    def test_no_importa_otro_buzon_aunque_token_tenga_acceso(self):
        with patch('esquema_multiempresa.zoho_contacto.requests.post', return_value=SimpleNamespace(
                status_code=200, json=lambda: {'access_token': 'token-fixture'})), \
             patch('esquema_multiempresa.zoho_contacto.requests.request', return_value=cuentas_zoho('personal@example.invalid')) as externo:
            with self.assertRaisesMessage(ErrorZoho, 'no corresponde al buzón'):
                sincronizar_buzon()
            self.assertEqual(externo.call_count, 1)
        self.assertEqual(MensajeContacto.objects.using('central').count(), 1)
        self.assertIsNone(BuzonContacto.objects.using('central').get().bloqueo)

    @override_settings(**ZOHO)
    def test_lote_invalido_revierte_importacion_y_libera_bloqueo(self):
        from .zoho_contacto import ClienteZoho
        with patch.object(ClienteZoho, '__init__', return_value=None), patch.object(ClienteZoho, 'listar',
                return_value=('101', [fila_zoho('202'), fila_zoho('../invalid')])):
            with self.assertRaises(ErrorZoho):
                sincronizar_buzon()
        self.assertEqual(MensajeContacto.objects.using('central').count(), 1)
        self.assertFalse(NotificacionSistema.objects.using('central').exists())
        self.assertIsNone(BuzonContacto.objects.using('central').get().bloqueo)

    @override_settings(**ZOHO)
    def test_envio_usa_borrador_guardado_destino_fijo_y_no_se_repite(self):
        borrador = RespuestaContacto.objects.using('central').create(mensaje=self.mensaje, texto='Respuesta revisada')
        self.entrar()
        with patch('esquema_multiempresa.zoho_contacto.requests.post', return_value=SimpleNamespace(
                status_code=200, json=lambda: {'access_token': 'token-fixture'})), \
             patch('esquema_multiempresa.zoho_contacto.requests.request', side_effect=[
                cuentas_zoho(), respuesta_zoho({'messageId': '501'}), cuentas_zoho()]) as externo:
            datos = {'accion': 'enviar', 'respuesta': str(borrador.pk), 'version': 0,
                     'texto': 'Texto forjado', 'toAddress': 'otro@example.invalid', 'fromAddress': 'root@example.invalid'}
            self.assertEqual(self.post(self.ruta, datos).status_code, 302)
            repetido = self.post(self.ruta, datos)
            self.assertContains(repetido, 'ya fue enviado')
            enviados = [llamada for llamada in externo.call_args_list if llamada.args[0] == 'POST']
            self.assertEqual(len(enviados), 1)
            self.assertEqual(enviados[0].kwargs['json']['content'], 'Respuesta revisada')
            self.assertEqual(enviados[0].kwargs['json']['toAddress'], self.mensaje.remitente_email)
            self.assertEqual(enviados[0].kwargs['json']['fromAddress'], CORREO_CONTACTO)
            self.assertFalse(enviados[0].kwargs['allow_redirects'])
        borrador.refresh_from_db(using='central')
        self.assertEqual(borrador.estado, 'enviada')

    @override_settings(**ZOHO)
    def test_timeout_de_envio_no_lo_reintenta_y_exige_revision_manual(self):
        borrador = RespuestaContacto.objects.using('central').create(mensaje=self.mensaje, texto='Respuesta revisada')
        self.entrar()
        with patch('esquema_multiempresa.zoho_contacto.requests.post', return_value=SimpleNamespace(
                status_code=200, json=lambda: {'access_token': 'token-fixture'})), \
             patch('esquema_multiempresa.zoho_contacto.requests.request', side_effect=[cuentas_zoho(), requests.Timeout()]):
            self.assertContains(self.post(self.ruta, {'accion': 'enviar', 'respuesta': str(borrador.pk), 'version': 0}),
                                'Revisa Enviados en Zoho')
        borrador.refresh_from_db(using='central')
        self.assertEqual(borrador.estado, 'incierta')
        self.assertContains(self.post(self.ruta, {'accion': 'borrador', 'texto': 'Reintento', 'version': 0}), 'envío sin confirmar')
        self.assertEqual(self.post(self.ruta, {'accion': 'confirmar_no_enviada', 'respuesta': str(borrador.pk),
                                              'version': borrador.version}).status_code, 302)
        borrador.refresh_from_db(using='central')
        self.assertEqual(borrador.estado, 'rechazada')

    def test_tablas_y_roles_solo_en_central_y_borrado_de_cliente_no_afecta_buzon(self):
        for alias in ('ferreteria', 'repuestos'):
            tablas = connections[alias].introspection.table_names()
            self.assertNotIn('mensajes_contacto', tablas)
            self.assertNotIn('buzon_contacto', tablas)
            self.assertFalse(Rol.objects.using(alias).filter(codigo=CONTACTO).exists())
        with usar_empresa(Empresa.objects.get(codigo='la-fragua')):
            cuenta = Usuario.objects.create_user(pk=self.contacto.pk, email='cliente@example.invalid', nombres='Cliente')
            cuenta.delete()
        self.assertTrue(MensajeContacto.objects.using('central').filter(pk=self.mensaje.pk).exists())
        self.assertTrue(Usuario.objects.using('central').filter(pk=self.contacto.pk).exists())

    def test_html_de_correo_no_ejecuta_scripts_ni_carga_imagenes(self):
        contenido = texto_correo('<style>oculto</style><p>Hola <b>persona</b></p><script>alert(1)</script><img src="https://example.invalid/track">Texto')
        self.assertEqual(contenido, 'Hola persona\nTexto')
        self.assertNotIn('<', contenido)
        self.assertNotIn('alert', contenido)

    @override_settings(**ZOHO)
    def test_sincronizaciones_simultaneas_y_throttle_no_consultan_zoho(self):
        BuzonContacto.objects.using('central').create(bloqueo=uuid4(), iniciado_en=timezone.now())
        with patch('esquema_multiempresa.buzon_contacto.ClienteZoho') as cliente:
            with self.assertRaisesMessage(ErrorZoho, 'ya se está actualizando'):
                sincronizar_buzon()
            BuzonContacto.objects.using('central').update(bloqueo=None, ultima_consulta=timezone.now())
            self.assertEqual(sincronizar_buzon(), 0)
            cliente.assert_not_called()

    @override_settings(**ZOHO)
    def test_historial_consulta_siguiente_pagina_y_actualizar_reinicia_recientes(self):
        BuzonContacto.objects.using('central').create(siguiente_pagina=101)
        with patch('esquema_multiempresa.buzon_contacto.ClienteZoho') as cliente:
            cliente.return_value.listar.return_value = ('101', [fila_zoho('202')])
            self.assertEqual(sincronizar_buzon(anteriores=True), 1)
            cliente.return_value.listar.assert_called_once_with(101)
            buzon = BuzonContacto.objects.using('central').get()
            self.assertTrue(buzon.historial_completo)

    def test_recuperacion_incluye_contacto_sin_confundir_con_empresas(self):
        self.post('/recuperar-clave/', {'email': CORREO_CONTACTO})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [CORREO_CONTACTO])

    @override_settings(**ZOHO)
    def test_conexion_guarda_token_privado_preserva_env_y_no_envia_correo(self):
        with TemporaryDirectory() as carpeta, override_settings(BASE_DIR=Path(carpeta)), \
             patch('esquema_multiempresa.management.commands.conectar_zoho_contacto.getpass.getpass', return_value='codigo-fixture'), \
             patch('esquema_multiempresa.management.commands.conectar_zoho_contacto.requests.post', return_value=SimpleNamespace(
                 status_code=200, json=lambda: {'access_token':'access-fixture','refresh_token':'refresh-nuevo-fixture'})) as token, \
             patch('esquema_multiempresa.management.commands.conectar_zoho_contacto.requests.get', return_value=cuentas_zoho()):
            archivo = Path(carpeta) / '.env'
            archivo.write_text('SECRET_KEY=fixture-local\nZOHO_CONTACTO_REFRESH_TOKEN=anterior\n', encoding='utf-8')
            salida = StringIO()
            call_command('conectar_zoho_contacto', stdout=salida)
            self.assertEqual(archivo.read_text(), 'SECRET_KEY=fixture-local\nZOHO_CONTACTO_REFRESH_TOKEN=refresh-nuevo-fixture\n')
            self.assertNotIn('refresh-nuevo-fixture', salida.getvalue())
            self.assertEqual(token.call_args.kwargs['data']['grant_type'], 'authorization_code')
            self.assertFalse(token.call_args.kwargs['allow_redirects'])
            self.assertEqual(len(getattr(mail, 'outbox', [])), 0)

    @override_settings(**ZOHO)
    def test_conexion_a_otro_buzon_no_sobrescribe_configuracion(self):
        from django.core.management.base import CommandError
        with TemporaryDirectory() as carpeta, override_settings(BASE_DIR=Path(carpeta)), \
             patch('esquema_multiempresa.management.commands.conectar_zoho_contacto.getpass.getpass', return_value='codigo-fixture'), \
             patch('esquema_multiempresa.management.commands.conectar_zoho_contacto.requests.post', return_value=SimpleNamespace(
                 status_code=200, json=lambda: {'access_token':'access-fixture','refresh_token':'refresh-fixture'})), \
             patch('esquema_multiempresa.management.commands.conectar_zoho_contacto.requests.get', return_value=cuentas_zoho('otra@example.invalid')):
            archivo = Path(carpeta) / '.env'
            archivo.write_text('NO_CAMBIAR=fixture\n', encoding='utf-8')
            with self.assertRaises(CommandError):
                call_command('conectar_zoho_contacto', stdout=StringIO())
            self.assertEqual(archivo.read_text(), 'NO_CAMBIAR=fixture\n')

    def test_sin_primera_consulta_indicadores_desconocidos_y_un_solo_aviso(self):
        MensajeContacto.objects.using('central').all().delete()
        self.entrar()
        principal = self.cliente.get('/contacto/bandeja/')
        self.assertTrue(all(valor is None for _, valor, _ in principal.context['kpis']))
        self.assertContains(principal, 'Tu buzón está pendiente de conexión', count=1)
        self.assertNotContains(principal, 'No hay correos en esta vista')
        self.assertNotContains(principal, 'id="contacto-buscar"')
        self.assertNotContains(principal, 'id="contacto-actualizar"')
        otra = self.cliente.get('/contacto/bandeja/?vista=pendiente')
        self.assertNotContains(otra, 'class="ss-sistema-kpis ss-contacto-kpis"')
        self.assertContains(otra, 'ss-menu-contador')

    def test_buzon_consultado_vacio_muestra_cero_y_mensajes_por_vista(self):
        MensajeContacto.objects.using('central').all().delete()
        BuzonContacto.objects.using('central').create(ultima_consulta=timezone.now(), conexion_estado='conectado')
        self.entrar()
        principal = self.cliente.get('/contacto/bandeja/')
        self.assertTrue(all(valor == 0 for _, valor, _ in principal.context['kpis']))
        self.assertContains(principal, 'No hay correos importados')
        self.assertContains(principal, 'Zoho no devolvió correos de Recibidos')
        self.assertNotContains(principal, 'Tu bandeja no tiene correos')
        for vista, texto in [('sin-leer','Estás al día con tus correos'), ('pendiente','No tienes consultas pendientes'),
                             ('borradores','Aquí aparecerán las respuestas que guardes sin enviar.'),
                             ('enviados','Todavía no has enviado respuestas')]:
            self.assertContains(self.cliente.get('/contacto/bandeja/?vista=' + vista), texto)

    def test_enviados_muestra_solo_respuestas_confirmadas_con_busqueda(self):
        self.entrar()
        RespuestaContacto.objects.using('central').create(mensaje=self.mensaje, estado='enviada',
            texto='Respuesta realizada desde SmartStock', enviada_en=timezone.now())
        RespuestaContacto.objects.using('central').create(mensaje=self.mensaje, estado='incierta', texto='No mostrar sin confirmar')
        pagina = self.cliente.get('/contacto/bandeja/?vista=enviados')
        self.assertContains(pagina, 'Respuesta realizada desde SmartStock')
        self.assertNotContains(pagina, 'No mostrar sin confirmar')
        self.assertEqual(len(pagina.context['pagina']), 1)
        self.assertEqual(len(self.cliente.get('/contacto/bandeja/?vista=enviados&search=inexistente').context['pagina']), 0)

    def test_conexion_web_solo_para_superusuario_y_exige_csrf(self):
        for usuario in (self.contacto, self.soporte):
            self.entrar(usuario)
            self.assertEqual(self.cliente.get('/sistema/contacto/conexion/').status_code, 403)
            self.assertEqual(self.post('/sistema/contacto/conexion/', {'accion':'comprobar'}).status_code, 403)
        self.entrar(self.root)
        self.assertContains(self.cliente.get('/sistema/contacto/conexion/'), 'Autorizar y cargar correos')
        self.assertEqual(self.cliente.post('/sistema/contacto/conexion/', {'accion':'conectar'}).status_code, 403)

    def test_autorizar_desde_web_verifica_buzon_cifra_secretos_e_importa_correo(self):
        self.entrar(self.root)
        with patch('esquema_multiempresa.zoho_contacto.requests.post', return_value=SimpleNamespace(
                status_code=200, json=lambda: {'access_token':'access-web-fixture','refresh_token':'refresh-web-fixture'})), \
             patch('esquema_multiempresa.zoho_contacto.requests.request', side_effect=[
                cuentas_zoho(), respuesta_zoho([fila_zoho('202')])]):
            respuesta = self.post('/sistema/contacto/conexion/', {'accion':'conectar','centro':'com',
                'client_id':'client-web-fixture','client_secret':'secret-web-fixture','codigo':'code-web-fixture'})
        self.assertEqual(respuesta.status_code, 302)
        buzon = BuzonContacto.objects.using('central').get()
        self.assertEqual(buzon.conexion_estado, 'conectado')
        self.assertTrue(buzon.ultima_consulta)
        self.assertNotIn('secret-web-fixture', buzon.credenciales_cifradas)
        self.assertNotIn('refresh-web-fixture', buzon.credenciales_cifradas)
        self.assertEqual(configuracion_zoho()['refresh_token'], 'refresh-web-fixture')
        self.assertTrue(MensajeContacto.objects.using('central').filter(mensaje_zoho='202').exists())
        pagina = self.cliente.get('/sistema/contacto/conexion/')
        for secreto in ('secret-web-fixture','refresh-web-fixture','access-web-fixture','code-web-fixture',buzon.credenciales_cifradas):
            self.assertNotContains(pagina, secreto)

    def test_cuenta_zoho_incorrecta_no_guarda_credenciales_ni_renderiza_secretos(self):
        self.entrar(self.root)
        with patch('esquema_multiempresa.zoho_contacto.requests.post', return_value=SimpleNamespace(
                status_code=200, json=lambda: {'access_token':'access-web-fixture','refresh_token':'refresh-web-fixture'})), \
             patch('esquema_multiempresa.zoho_contacto.requests.request', return_value=cuentas_zoho('personal@example.invalid')):
            respuesta = self.post('/sistema/contacto/conexion/', {'accion':'conectar','centro':'com',
                'client_id':'client-web-fixture','client_secret':'secret-web-fixture','codigo':'code-web-fixture'})
        self.assertContains(respuesta, 'no corresponde al buzón')
        self.assertFalse(BuzonContacto.objects.using('central').exclude(credenciales_cifradas='').exists())
        self.assertNotContains(respuesta, 'secret-web-fixture')
        self.assertNotContains(respuesta, 'code-web-fixture')

    def test_actualizar_explica_autorizacion_pendiente_y_conserva_la_vista(self):
        self.entrar()
        respuesta = self.post('/contacto/sincronizar/', {'vista':'pendiente','search':'Consulta'})
        self.assertIn('vista=pendiente', respuesta.url)
        pagina = self.cliente.get(respuesta.url)
        self.assertContains(pagina, 'Cuenta de contacto → Conectar Zoho')
        self.assertFalse(NotificacionSistema.objects.using('central').exists())
        resultado = self.post('/contacto/sincronizar/', {}, HTTP_ACCEPT='application/json')
        self.assertEqual(resultado.status_code, 503)
        self.assertEqual(resultado.json()['codigo'], 'sin_configuracion')

    @override_settings(**ZOHO)
    def test_actualizacion_manual_no_reutiliza_consulta_automatica_reciente(self):
        self.entrar()
        BuzonContacto.objects.using('central').create(ultima_consulta=timezone.now())
        with patch('esquema_multiempresa.buzon_contacto.ClienteZoho') as cliente:
            cliente.return_value.listar.return_value = ('101',[fila_zoho('202')])
            respuesta = self.post('/contacto/sincronizar/', {}, HTTP_ACCEPT='application/json')
            cliente.return_value.listar.assert_called_once_with(1)
        self.assertEqual(respuesta.json()['nuevos'], 1)
        self.assertEqual(respuesta.json()['total'], 2)

    @override_settings(**ZOHO)
    def test_token_vencido_se_renueva_una_vez_en_lectura(self):
        with patch('esquema_multiempresa.zoho_contacto.requests.post', return_value=SimpleNamespace(
                status_code=200, json=lambda: {'access_token':'token-renovado'})) as renovar, \
             patch('esquema_multiempresa.zoho_contacto.requests.request', side_effect=[
                 respuesta_zoho({},401), cuentas_zoho()]):
            config = {'client_id':'cliente','client_secret':'secreto','refresh_token':'refresh','dc':'com'}
            self.assertEqual(ClienteZoho(config, token='token-vencido').comprobar_cuenta(), '101')
            renovar.assert_called_once()

    @override_settings(**ZOHO)
    def test_permisos_de_zoho_producen_diagnostico_claro_sin_datos_privados(self):
        with patch('esquema_multiempresa.zoho_contacto.requests.post', return_value=SimpleNamespace(
                status_code=200, json=lambda: {'access_token':'token-fixture'})), \
             patch('esquema_multiempresa.zoho_contacto.requests.request', side_effect=[
                 cuentas_zoho(), respuesta_zoho({},403)]):
            with self.assertRaisesMessage(ErrorZoho, 'no concedió permisos'):
                sincronizar_buzon(forzar=True)
        buzon = BuzonContacto.objects.using('central').get()
        self.assertEqual(buzon.conexion_estado, 'error')
        self.assertIn('no concedió permisos', buzon.ultimo_error)

    def test_cifrado_rechaza_otra_clave_y_admite_clave_anterior_autorizada(self):
        from django.conf import settings
        config = {'client_id':'cliente','client_secret':'secreto','refresh_token':'refresh','dc':'com'}
        anterior = settings.SECRET_KEY
        BuzonContacto.objects.using('central').create(credenciales_cifradas=cifrar_configuracion(config))
        with override_settings(SECRET_KEY='otra-clave-fixture', SECRET_KEY_FALLBACKS=[]):
            with self.assertRaisesMessage(ErrorZoho, 'autorización guardada'):
                configuracion_zoho()
        with override_settings(SECRET_KEY='otra-clave-fixture', SECRET_KEY_FALLBACKS=[anterior]):
            self.assertEqual(configuracion_zoho(), config)

    @override_settings(**ZOHO)
    def test_rechazo_explicito_de_envio_no_se_marca_como_confirmado_o_incierto(self):
        self.entrar()
        borrador = RespuestaContacto.objects.using('central').create(mensaje=self.mensaje, texto='Respuesta revisada')
        rechazo = SimpleNamespace(status_code=200,content=b'{}',json=lambda:{'status':{'code':403},'data':{}})
        with patch('esquema_multiempresa.zoho_contacto.requests.post', return_value=SimpleNamespace(
                status_code=200,json=lambda:{'access_token':'token-fixture'})), \
             patch('esquema_multiempresa.zoho_contacto.requests.request', side_effect=[cuentas_zoho(),rechazo]):
            respuesta = self.post(self.ruta, {'accion':'enviar','respuesta':str(borrador.pk),'version':0})
        self.assertContains(respuesta, 'no concedió permisos')
        borrador.refresh_from_db(using='central')
        self.assertEqual(borrador.estado,'rechazada')
        self.assertIsNone(borrador.enviada_en)
        self.assertFalse(NotificacionSistema.objects.using('central').exists())
