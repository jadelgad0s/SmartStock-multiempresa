"""Permisos del panel central, consultas por empresa y gestión sin cruces de IDs."""
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.cache import cache
from django.core.management import call_command
from django.db import OperationalError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.empresa import empresa_actual, usar_empresa
from apps.core.models import Auditoria
from apps.productos.models import Bodega, Producto, StockBodega
from apps.usuarios.models import Rol, Sesion, Usuario
from .models import Empresa


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class PanelSmartStockTests(TestCase):
    databases = {'central', 'ferreteria', 'repuestos'}
    clave = 'Cuenta-fixture-que-cumple-2026!'

    @classmethod
    def setUpTestData(cls):
        call_command('registrar_empresas_prueba', stdout=StringIO())
        cls.fragua = Empresa.objects.get(codigo='la-fragua')
        cls.motor = Empresa.objects.get(codigo='punto-motor')
        for empresa, cantidad in ((cls.fragua, 15), (cls.motor, 4)):
            call_command('seed_empresa', empresa.codigo, sin_admin=True, stdout=StringIO())
            with usar_empresa(empresa):
                Usuario.objects.create_user(pk=90, email='cliente@example.invalid', password=cls.clave,
                                            nombres=empresa.nombre, rol=Rol.objects.get(codigo='administrador'))
                producto = Producto.objects.create(pk=10, sku='QA-001', nombre=empresa.nombre)
                bodega = Bodega.objects.create(pk=1, nombre='Bodega Central', direccion='Dirección de prueba')
                StockBodega.objects.create(producto=producto, bodega=bodega, cantidad_total=cantidad)
        cls.superusuario = Usuario.objects.db_manager('central').create_superuser(
            pk=90, email='superusuario@example.invalid', password=cls.clave, nombres='Javier', apellidos='Prueba')
        cls.tecnico = Usuario.objects.db_manager('central').create_user(
            pk=91, email='tecnico@example.invalid', password=cls.clave, nombres='Soporte', is_staff=True)

    def setUp(self):
        cache.clear()
        self.cliente = APIClient(enforce_csrf_checks=True, HTTP_HOST='127.0.0.1:8000')

    def entrar(self, usuario=None):
        usuario = usuario or self.tecnico
        self.cliente.get('/')
        respuesta = self.cliente.post('/api/v1/auth/login-web/', {'email': usuario.email, 'password': self.clave},
                                      format='json', HTTP_X_CSRFTOKEN=self.cliente.cookies['csrftoken'].value)
        self.assertEqual(respuesta.status_code, 200, respuesta.data)
        self.assertEqual(respuesta.data['data']['inicio'], '/sistema/')

    def guardar(self, ruta, datos):
        self.cliente.get(ruta)
        return self.cliente.post(ruta, datos, HTTP_X_CSRFTOKEN=self.cliente.cookies['csrftoken'].value)

    def datos_cuenta(self, **cambios):
        return {'email': 'nueva@example.invalid', 'nombres': 'Nueva', 'apellidos': 'Cuenta',
                'telefono': '', 'activo': 'on', 'password1': self.clave, 'password2': self.clave, **cambios}

    def test_tecnico_ingresa_sin_rol_de_negocio_y_recibe_panel_smartstock(self):
        self.entrar()
        panel = self.cliente.get('/sistema/')
        self.assertContains(panel, 'ss-app-layout')
        for modulo in ('Empresas', 'Usuarios de empresas', 'Cuentas técnicas', 'Auditoría', 'Catálogo', 'Transferencias'):
            self.assertContains(panel, modulo)
        self.assertNotContains(panel, 'href="/sistema/configuracion/"')
        self.assertNotContains(panel, 'id="content-main"')
        self.assertRedirects(self.cliente.get('/'), '/sistema/', fetch_redirect_response=False)

    def test_configuracion_y_urls_directas_exigen_superusuario(self):
        self.entrar()
        for ruta in ('/admin/', '/sistema/configuracion/', '/sistema/configuracion/empresas/empresa/',
                     '/sistema/configuracion/usuarios/usuario/add/', '/sistema/configuracion/login/'):
            self.assertEqual(self.cliente.get(ruta).status_code, 403, ruta)
        self.entrar(self.superusuario)
        self.assertContains(self.cliente.get('/sistema/'), 'href="/sistema/configuracion/"')
        self.assertEqual(self.cliente.get('/sistema/configuracion/').status_code, 200)

    def test_anonimo_y_usuario_de_empresa_no_acceden_al_panel_central(self):
        self.assertEqual(self.cliente.get('/sistema/usuarios/').status_code, 302)
        ajeno = APIClient(HTTP_HOST='la-fragua.localhost:8000')
        with usar_empresa(self.fragua):
            ajeno.force_login(Usuario.objects.get(pk=90))
        self.assertEqual(ajeno.get('/sistema/').status_code, 404)
        self.cliente.cookies['sessionid'] = ajeno.cookies['sessionid'].value
        self.assertEqual(self.cliente.get('/sistema/').status_code, 302)

    def test_cuenta_desactivada_o_sin_acceso_tecnico_pierde_el_panel(self):
        self.entrar()
        Usuario.objects.using('central').filter(pk=self.tecnico.pk).update(activo=False)
        self.assertEqual(self.cliente.get('/sistema/').status_code, 403)
        Usuario.objects.using('central').filter(pk=self.tecnico.pk).update(activo=True, is_staff=False)
        self.assertEqual(self.cliente.get('/sistema/empresas/').status_code, 403)

    def test_modulos_consultan_la_empresa_elegida_con_ids_repetidos(self):
        self.entrar()
        for codigo, nombre, ajena, stock in (('la-fragua', self.fragua.nombre, self.motor.nombre, 15),
                                            ('punto-motor', self.motor.nombre, self.fragua.nombre, 4)):
            panel = self.cliente.get('/sistema/inventario/', {'empresa': codigo})
            self.assertEqual(panel.status_code, 200)
            self.assertEqual(panel.context['dashboard']['kpi_stock'], stock)
            catalogo = self.cliente.get('/sistema/catalogo/', {'empresa': codigo})
            self.assertEqual(catalogo.status_code, 200)
            self.assertEqual(catalogo.context['filas'][0]['celdas'][1:3], [nombre, stock])
            for ruta in ('usuarios', 'bodegas', 'reportes', 'movimientos', 'transferencias', 'mermas', 'auditoria', 'alertas-sms'):
                self.assertEqual(self.cliente.get('/sistema/' + ruta + '/', {'empresa': codigo}).status_code, 200)
        self.assertIsNone(empresa_actual())

    def test_crear_y_editar_usuario_afecta_solo_a_la_empresa_de_la_url(self):
        self.entrar()
        rol = Rol.objects.using('ferreteria').get(codigo='operador')
        respuesta = self.guardar('/sistema/empresas/la-fragua/usuarios/nuevo/', self.datos_cuenta(rol=str(rol.pk)))
        self.assertEqual(respuesta.status_code, 302)
        usuario = Usuario.objects.using('ferreteria').get(email='nueva@example.invalid')
        self.assertFalse(Usuario.objects.using('repuestos').filter(email=usuario.email).exists())
        self.assertFalse(Usuario.objects.using('central').filter(email=usuario.email).exists())
        self.assertTrue(usuario.check_password(self.clave))
        evento = Auditoria.objects.using('ferreteria').latest('id')
        self.assertIsNone(evento.usuario_id)
        self.assertIn(self.tecnico.email, evento.descripcion)
        self.assertFalse(Auditoria.objects.using('repuestos').exists())

    def test_no_se_puede_elegir_otra_base_o_promover_cuentas_mediante_post(self):
        self.entrar()
        rol = Rol.objects.using('ferreteria').get(codigo='operador')
        datos = self.datos_cuenta(rol=str(rol.pk), empresa='punto-motor', alias_bd='repuestos', is_superuser='on', is_staff='on')
        self.assertEqual(self.guardar('/sistema/empresas/la-fragua/usuarios/nuevo/', datos).status_code, 302)
        usuario = Usuario.objects.using('ferreteria').get(email='nueva@example.invalid')
        self.assertFalse(usuario.is_superuser or usuario.is_staff)
        self.assertFalse(Usuario.objects.using('repuestos').filter(email=usuario.email).exists())

    def test_editar_id_repetido_no_modifica_otra_empresa_ni_al_superusuario_central(self):
        self.entrar()
        rol = Rol.objects.using('ferreteria').get(codigo='administrador')
        ruta = '/sistema/empresas/la-fragua/usuarios/90/'
        datos = self.datos_cuenta(email='cliente@example.invalid', nombres='Nombre actualizado', rol=str(rol.pk),
                                 password1='', password2='', activo='')
        self.assertEqual(self.guardar(ruta, datos).status_code, 302)
        usuario = Usuario.objects.using('ferreteria').get(pk=90)
        self.assertEqual(usuario.nombres, 'Nombre actualizado')
        self.assertFalse(usuario.activo)
        self.assertTrue(usuario.check_password(self.clave))
        self.assertEqual(Usuario.objects.using('repuestos').get(pk=90).nombres, self.motor.nombre)
        self.assertEqual(Usuario.objects.using('central').get(pk=90).email, self.superusuario.email)
        self.assertEqual(Auditoria.objects.using('ferreteria').latest('id').accion, 'DEACTIVATE')

    def test_crear_tecnico_no_otorga_superusuario_y_no_permite_editar_un_superusuario(self):
        self.entrar()
        datos = self.datos_cuenta(perfil='superusuario', is_superuser='on')
        self.assertEqual(self.guardar('/sistema/cuentas/nueva/', datos).status_code, 302)
        nuevo = Usuario.objects.using('central').get(email='nueva@example.invalid')
        self.assertTrue(nuevo.is_staff)
        self.assertFalse(nuevo.is_superuser)
        self.assertIsNone(nuevo.rol_id)
        ruta = f'/sistema/cuentas/{self.superusuario.pk}/'
        self.assertEqual(self.cliente.get(ruta).status_code, 403)
        self.assertEqual(self.guardar(ruta, self.datos_cuenta()).status_code, 403)

    def test_superusuario_puede_crear_otro_superusuario_desde_el_panel(self):
        self.entrar(self.superusuario)
        self.assertEqual(self.guardar('/sistema/cuentas/nueva/', self.datos_cuenta(perfil='superusuario')).status_code, 302)
        self.assertTrue(Usuario.objects.using('central').get(email='nueva@example.invalid').is_superuser)

    def test_cambiar_la_clave_propia_conserva_la_sesion_y_no_desactiva_la_cuenta(self):
        self.entrar()
        ruta = f'/sistema/cuentas/{self.tecnico.pk}/'
        datos = self.datos_cuenta(email=self.tecnico.email, activo='', password1='Otra-clave-para-fixture-2626!', password2='Otra-clave-para-fixture-2626!')
        self.assertEqual(self.guardar(ruta, datos).status_code, 302)
        usuario = Usuario.objects.using('central').get(pk=self.tecnico.pk)
        self.assertTrue(usuario.activo)
        self.assertTrue(usuario.check_password(datos['password1']))
        self.assertEqual(self.cliente.get('/sistema/').status_code, 200)

    def test_validaciones_y_csrf_evitan_guardados_parciales(self):
        self.entrar()
        datos = self.datos_cuenta(password1='abc', password2='def')
        self.assertEqual(self.guardar('/sistema/cuentas/nueva/', datos).status_code, 200)
        self.assertFalse(Usuario.objects.using('central').filter(email=datos['email']).exists())
        self.assertEqual(self.cliente.post('/sistema/cuentas/nueva/', self.datos_cuenta()).status_code, 403)

    def test_usuarios_y_cuentas_tienen_paginacion_de_25_y_busqueda(self):
        self.entrar()
        for numero in range(27):
            Usuario.objects.db_manager('central').create_user(email=f'qa{numero}@example.invalid', nombres=f'Cuenta {numero:02}', is_staff=True)
        pagina = self.cliente.get('/sistema/cuentas/')
        self.assertEqual(len(pagina.context['cuentas_tecnicas']), 25)
        self.assertTrue(pagina.context['pagina'].has_next())
        self.assertContains(self.cliente.get('/sistema/cuentas/', {'search': 'qa26@'}), 'qa26@example.invalid')

    def test_reportes_y_descargas_conservan_el_inventario_de_cada_empresa(self):
        self.entrar()
        for codigo, nombre, stock in (('la-fragua', self.fragua.nombre, 15), ('punto-motor', self.motor.nombre, 4)):
            respuesta = self.cliente.get('/sistema/reportes/', {'empresa': codigo, 'informe': 'existencias', 'bodega': 1, 'exportar': 'csv'})
            self.assertEqual(respuesta.status_code, 200)
            csv = b''.join(respuesta.streaming_content).decode('utf-8-sig')
            self.assertIn('Empresa;' + nombre, csv)
            self.assertIn(';' + str(stock) + ';', csv)
            pdf = self.cliente.get('/sistema/reportes/', {'empresa': codigo, 'informe': 'existencias', 'bodega': 1, 'exportar': 'pdf'})
            self.assertContains(pdf, nombre)

    def test_filtros_vacios_no_impiden_consultar_y_fechas_invertidas_muestran_error(self):
        self.entrar()
        respuesta = self.cliente.get('/sistema/movimientos/', {'empresa': 'la-fragua', 'desde': '', 'hasta': '', 'search': ''})
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.context['columnas'])
        auditoria = self.cliente.get('/sistema/auditoria/', {'desde': '', 'hasta': ''})
        self.assertNotIn('error_consulta', auditoria.context)
        error = self.cliente.get('/sistema/reportes/', {'empresa': 'la-fragua', 'desde': '2026-11-20', 'hasta': '2026-11-01'})
        self.assertContains(error, 'La fecha inicial debe ser anterior o igual a la final.')

    def test_empresa_inactiva_sigue_visible_para_soporte_y_bloquea_el_login_del_cliente(self):
        self.entrar()
        self.guardar('/sistema/empresas/la-fragua/editar/', {'nombre': self.fragua.nombre, 'codigo': 'la-fragua'})
        self.assertFalse(Empresa.objects.get(pk=self.fragua.pk).activa)
        self.assertEqual(self.cliente.get('/sistema/usuarios/', {'empresa': 'la-fragua'}).status_code, 200)
        cliente = APIClient(HTTP_HOST='la-fragua.localhost:8000')
        self.assertEqual(cliente.get('/').status_code, 404)

    def test_empresa_inexistente_o_alias_no_configurado_no_cambia_el_ambito(self):
        self.entrar()
        Empresa.objects.create(codigo='no-configurada', nombre='Otra', alias_bd='central')
        for codigo in ('inexistente', 'no-configurada'):
            self.assertEqual(self.cliente.get('/sistema/usuarios/', {'empresa': codigo}).status_code, 404)
        self.assertIsNone(empresa_actual())

    def test_un_error_de_empresa_muestra_un_estado_y_el_panel_sigue_disponible(self):
        self.entrar()
        with patch('esquema_multiempresa.sistema.Producto.objects.filter', side_effect=OperationalError('base indisponible')):
            pagina = self.cliente.get('/sistema/')
        self.assertContains(pagina, 'Sin conexión con la empresa')
        self.assertEqual(self.cliente.get('/sistema/cuentas/').status_code, 200)

    def test_eliminar_superusuario_central_conserva_auditoria_y_usuarios_de_empresas(self):
        cuenta = Usuario.objects.db_manager('central').create_superuser(
            pk=92, email='eliminar@example.invalid', password=self.clave, nombres='Cuenta central')
        for empresa in (self.fragua, self.motor):
            with usar_empresa(empresa):
                Usuario.objects.create_user(
                    pk=92, email=cuenta.email, password=self.clave, nombres=empresa.nombre,
                    rol=Rol.objects.get(codigo='operador'))
        registro = Auditoria.objects.using('central').create(
            usuario=cuenta, accion='LOGIN', modelo='Usuario', descripcion='Historial anterior')
        Sesion.objects.using('central').create(
            usuario=cuenta, token_jti='sesion-cuenta-92',
            fecha_expiracion=timezone.now() + timedelta(days=1))
        self.entrar(self.superusuario)
        ruta = '/sistema/configuracion/usuarios/usuario/92/delete/'
        self.assertContains(self.cliente.get(ruta), cuenta.email)
        respuesta = self.guardar(ruta, {'post': 'yes'})
        self.assertEqual(respuesta.status_code, 302)
        self.assertFalse(Usuario.objects.using('central').filter(pk=92).exists())
        self.assertTrue(Usuario.objects.using('central').filter(pk=self.superusuario.pk).exists())
        self.assertFalse(Sesion.objects.using('central').filter(usuario_id=92).exists())
        registro.refresh_from_db(using='central')
        self.assertIsNone(registro.usuario_id)
        self.assertEqual(registro.descripcion, 'Historial anterior')
        for empresa in (self.fragua, self.motor):
            with usar_empresa(empresa):
                self.assertEqual(Usuario.objects.get(pk=92).nombres, empresa.nombre)

    def test_eliminar_cuentas_centrales_desde_accion_del_listado(self):
        for pk in (92, 93):
            Usuario.objects.db_manager('central').create_user(
                pk=pk, email=f'eliminar-{pk}@example.invalid', password=self.clave,
                nombres=f'Cuenta {pk}', is_staff=True)
        self.entrar(self.superusuario)
        ruta = '/sistema/configuracion/usuarios/usuario/'
        datos = {'action': 'delete_selected', '_selected_action': ['92', '93']}
        confirmacion = self.guardar(ruta, datos)
        self.assertContains(confirmacion, 'eliminar-92@example.invalid')
        self.assertContains(confirmacion, 'eliminar-93@example.invalid')
        respuesta = self.guardar(ruta, {**datos, 'post': 'yes'})
        self.assertEqual(respuesta.status_code, 302)
        self.assertFalse(Usuario.objects.using('central').filter(pk__in=(92, 93)).exists())
        self.assertEqual(Usuario.objects.using('central').filter(pk__in=(90, 91)).count(), 2)

    def test_tecnico_no_puede_eliminar_un_superusuario_por_url_directa(self):
        self.entrar()
        ruta = '/sistema/configuracion/usuarios/usuario/90/delete/'
        self.assertEqual(self.cliente.get(ruta).status_code, 403)
        self.assertEqual(self.guardar(ruta, {'post': 'yes'}).status_code, 403)
        self.assertTrue(Usuario.objects.using('central').filter(pk=90, is_superuser=True).exists())
