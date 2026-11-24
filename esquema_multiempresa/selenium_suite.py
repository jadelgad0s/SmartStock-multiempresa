"""Prueba de dos empresas en pestañas del mismo navegador con bases SQLite desechables."""
import atexit
from datetime import timedelta
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from urllib.parse import urlsplit
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.management import call_command
from django.utils import timezone
from django.test import override_settings
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support.ui import Select

from apps.core.empresa import usar_empresa
from apps.productos.models import Bodega, Producto, StockBodega
from apps.core.models import Auditoria
from apps.core.registro_auditoria import crear_evento
from apps.usuarios.models import Usuario
from esquema_multiempresa.models import AccesoSoporte, AtencionSoporte, BuzonContacto, Empresa, MensajeContacto, NotaContacto, NotificacionSistema, RespuestaContacto
from esquema_multiempresa.permisos import ADMINISTRADOR_PLATAFORMA, SOPORTE_TECNICO
from esquema_multiempresa.permisos import CONTACTO, CORREO_CONTACTO
from apps.usuarios.models import Rol


if (settings.SETTINGS_MODULE != 'esquema_multiempresa.testing'
        or settings.DATABASES['central']['ENGINE'] != 'django.db.backends.sqlite3'):
    raise RuntimeError('Ejecuta esta suite con esquema_multiempresa.testing y SS_TEST_POSTGRES desactivado.')


# Cada alias utiliza su propio archivo desechable para que las peticiones
# simultáneas de las dos pestañas tengan conexiones SQLite independientes.
_datos_selenium = TemporaryDirectory(prefix='smartstock-empresas-selenium-')
atexit.register(_datos_selenium.cleanup)
for _alias in ('central', 'ferreteria', 'repuestos'):
    settings.DATABASES[_alias].setdefault('TEST', {})['NAME'] = str(Path(_datos_selenium.name) / f'{_alias}.sqlite3')


class DosEmpresasEnChromeTests(StaticLiveServerTestCase):
    databases = {'central', 'ferreteria', 'repuestos'}

    def setUp(self):
        super().setUp()
        # StaticLiveServerTestCase vacía los datos entre clases; los roles de
        # migración se preparan también cuando otra prueba de Chrome va antes.
        for codigo, nombre in ((ADMINISTRADOR_PLATAFORMA, 'Administrador de plataforma'),
                               (SOPORTE_TECNICO, 'Soporte técnico')):
            Rol.objects.using('central').get_or_create(codigo=codigo, defaults={'nombre': nombre, 'es_sistema': True})

    def comprobar_menu(self, navegador):
        grupos = navegador.execute_script('''
            return Array.from(document.querySelectorAll('.ss-sistema-menu-lista'), grupo =>
                Array.from(grupo.querySelectorAll('.sidebar-item'), enlace => {
                    const r = enlace.getBoundingClientRect();
                    return {top: r.top, bottom: r.bottom, height: r.height, left: r.left, right: r.right};
                }));
        ''')
        for filas in grupos:
            for anterior, actual in zip(filas, filas[1:]):
                self.assertAlmostEqual(anterior['height'], actual['height'], delta=1)
                self.assertAlmostEqual(anterior['left'], actual['left'], delta=1)
                self.assertAlmostEqual(anterior['right'], actual['right'], delta=1)
                self.assertGreaterEqual(actual['top'] - anterior['bottom'], 0)
                self.assertLessEqual(actual['top'] - anterior['bottom'], 6)
        self.assertFalse(navegador.find_elements(By.CSS_SELECTOR, '.ss-sidebar-links a[href="/sistema/mi-cuenta/"]'))
        perfil = navegador.find_element(By.CSS_SELECTOR, 'a.ss-sistema-perfil')
        self.assertEqual(urlsplit(perfil.get_attribute('href')).path, '/sistema/mi-cuenta/')
        self.assertTrue(navegador.execute_script('''
            const perfil = arguments[0].getBoundingClientRect();
            const menu = document.querySelector('.ss-sidebar-links').getBoundingClientRect();
            return perfil.bottom <= window.innerHeight && menu.bottom <= perfil.top + 1;
        ''', perfil))

    def test_mismo_navegador_dos_inventarios_y_cierre_de_sesion_independiente(self):
        call_command('registrar_empresas_prueba', stdout=StringIO())
        opciones = webdriver.ChromeOptions()
        opciones.add_argument('--headless=new')
        opciones.add_argument('--window-size=1440,1000')
        navegador = webdriver.Chrome(options=opciones)
        self.addCleanup(navegador.quit)
        espera = WebDriverWait(navegador, 20)
        pestanas = []
        for codigo, cantidad in (('la-fragua', 15), ('punto-motor', 4)):
            empresa = Empresa.objects.get(codigo=codigo)
            salida = StringIO()
            call_command('seed_empresa', codigo, stdout=salida)
            clave = next(linea.partition(':')[2].strip() for linea in salida.getvalue().splitlines()
                         if linea.strip().startswith('Password:'))
            with usar_empresa(empresa):
                bodega = Bodega.objects.create(nombre='Bodega Central')
                producto = Producto.objects.create(sku='QA-001', nombre='Pieza de prueba')
                StockBodega.objects.create(bodega=bodega, producto=producto, cantidad_total=cantidad)

            if pestanas:
                navegador.switch_to.new_window('tab')
            pestanas.append(navegador.current_window_handle)
            navegador.get(self.live_server_url)
            espera.until(EC.visibility_of_element_located((By.ID, 'email')))
            navegador.find_element(By.ID, 'email').send_keys('admin@smartstock.cl')
            navegador.find_element(By.ID, 'password').send_keys(clave)
            navegador.find_element(By.ID, 'login-submit').click()
            espera.until(EC.url_contains('/dashboard/'))
            self.assertEqual(urlsplit(navegador.current_url).hostname, codigo + '.localhost')
            self.assertIn(empresa.nombre, navegador.title)
            espera.until(lambda d: d.find_element(By.ID, 'kpi-stock').text == str(cantidad))
            self.assertTrue(navegador.find_elements(By.ID, 'ss-navegacion-inicial'))
            self.assertEqual(navegador.execute_script("return performance.getEntriesByType('resource').filter(r=>new URL(r.name).pathname==='/api/v1/auth/navegacion/').length"), 0)

        navegador.switch_to.window(pestanas[0])
        espera.until(EC.element_to_be_clickable((By.ID, 'btn-logout'))).click()
        espera.until(EC.visibility_of_element_located((By.ID, 'email')))
        navegador.switch_to.window(pestanas[1])
        navegador.refresh()
        espera.until(lambda d: d.find_element(By.ID, 'kpi-stock').text == '4')
        self.assertIn('Repuestos Punto Motor', navegador.title)

        Usuario.objects.db_manager('central').create_superuser(
            email='tecnico@example.invalid', password='Tecnico-clave-de-fixture',
            nombres='Equipo', apellidos='SmartStock',
        )
        AtencionSoporte.objects.using('central').create(
            empresa=Empresa.objects.get(codigo='la-fragua'), asunto='Revisión de acceso',
            motivo='Solicitud de prueba para comprobar la atención pendiente')
        AtencionSoporte.objects.using('central').create(
            empresa=Empresa.objects.get(codigo='punto-motor'), asunto='Consulta resuelta',
            motivo='Solicitud de prueba finalizada', estado='cerrada')
        navegador.switch_to.new_window('tab')
        navegador.get(self.live_server_url)
        navegador.find_element(By.ID, 'email').send_keys('tecnico@example.invalid')
        navegador.find_element(By.ID, 'password').send_keys('Tecnico-clave-de-fixture')
        navegador.find_element(By.ID, 'login-submit').click()
        espera.until(EC.url_contains('/sistema/'))
        self.assertIn('Administración de SmartStock', navegador.find_element(By.TAG_NAME, 'body').text)
        self.assertTrue(navegador.find_elements(By.CSS_SELECTOR, 'a[href="/sistema/configuracion/"]'))
        self.comprobar_menu(navegador)
        self.comprobar_resumen_central(navegador, espera)
        navegador.find_element(By.CSS_SELECTOR, 'a.ss-sistema-perfil').click()
        espera.until(lambda d: urlsplit(d.current_url).path == '/sistema/mi-cuenta/')
        self.assertEqual(navegador.find_element(By.CSS_SELECTOR, 'a.ss-sistema-perfil').get_attribute('aria-current'), 'page')
        self.assertEqual(navegador.find_element(By.ID, 'id_email').get_attribute('value'), 'tecnico@example.invalid')
        navegador.find_element(By.LINK_TEXT, 'Equipo de SmartStock').click()
        for perfil, correo in ((ADMINISTRADOR_PLATAFORMA, 'gestion-qa@example.invalid'),
                               (SOPORTE_TECNICO, 'soporte-qa@example.invalid')):
            navegador.find_element(By.LINK_TEXT, 'Añadir cuenta del equipo').click()
            for campo, valor in (('nombres', 'Equipo'), ('apellidos', 'QA'), ('email', correo),
                                 ('password1', 'Cuenta-equipo-fixture-2626!'), ('password2', 'Cuenta-equipo-fixture-2626!')):
                navegador.find_element(By.ID, 'id_' + campo).send_keys(valor)
            Select(navegador.find_element(By.ID, 'id_perfil')).select_by_value(perfil)
            navegador.find_element(By.CSS_SELECTOR, 'form.ss-sistema-formulario button[type="submit"]').click()
            espera.until(lambda d: urlsplit(d.current_url).path == '/sistema/cuentas/')
            self.assertIn(correo, navegador.find_element(By.TAG_NAME, 'body').text)
        # Accesos aprobados explícitos del cliente para las comprobaciones
        # históricas de consulta. El flujo de aprobación se prueba por separado.
        from .autorizacion_soporte import ALCANCES, LECTURAS
        for correo in ('gestion-qa@example.invalid', 'soporte-qa@example.invalid'):
            tecnico = Usuario.objects.using('central').get(email=correo)
            for empresa in Empresa.objects.all():
                caso = AtencionSoporte.objects.using('central').create(empresa=empresa, tecnico=tecnico,
                    asunto='Consulta autorizada de prueba', motivo='Revisión solicitada por el cliente')
                ahora = timezone.now()
                AccesoSoporte.objects.using('central').create(atencion=caso, tecnico=tecnico,
                    alcances=list(ALCANCES if correo.startswith('gestion') else LECTURAS),
                    motivo='Autorización explícita para la prueba', estado='aprobado',
                    decidido_en=ahora, expira_en=ahora + timedelta(minutes=60), aprobador_id=1,
                    aprobador_email='admin@smartstock.cl')
        espera.until(lambda d: d.find_element(By.ID, 'sistema-notificaciones-total').text == '2')
        self.assertTrue(navegador.find_element(By.ID, 'sistema-confirmacion').is_displayed())
        self.assertFalse(navegador.find_elements(By.CSS_SELECTOR, '.alert.alert-success'))
        navegador.find_element(By.ID, 'sistema-notificaciones-boton').click()
        espera.until(EC.visibility_of_element_located((By.ID, 'sistema-notificaciones-panel')))
        self.assertFalse(navegador.find_element(By.ID, 'sistema-confirmacion').is_displayed())
        navegador.find_element(By.ID, 'sistema-notificaciones-leer').click()
        espera.until(lambda d: not d.find_element(By.ID, 'sistema-notificaciones-total').is_displayed())
        navegador.find_element(By.ID, 'sistema-notificaciones-historial').click()
        espera.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, '#sistema-notificaciones-lista button[data-leida="true"]')) == 2)
        navegador.find_element(By.ID, 'sistema-notificaciones-boton').click()
        navegador.find_element(By.CSS_SELECTOR, 'button[form="ss-cerrar-sesion"]').click()
        espera.until(EC.visibility_of_element_located((By.ID, 'email')))
        navegador.find_element(By.ID, 'email').send_keys('gestion-qa@example.invalid')
        navegador.find_element(By.ID, 'password').send_keys('Cuenta-equipo-fixture-2626!')
        navegador.find_element(By.ID, 'login-submit').click()
        espera.until(EC.url_contains('/sistema/'))
        self.assertFalse(navegador.find_elements(By.CSS_SELECTOR, 'a[href="/sistema/configuracion/"]'))
        self.assertFalse(navegador.find_elements(By.CSS_SELECTOR, 'a[href="/sistema/cuentas/"]'))
        self.assertIn('Administrador de plataforma', navegador.find_element(By.TAG_NAME, 'body').text)
        estado_configuracion = navegador.execute_async_script(
            "const listo = arguments[arguments.length - 1]; fetch('/sistema/configuracion/').then(r => listo(r.status));")
        self.assertEqual(estado_configuracion, 403)
        navegador.get(self.live_server_url + '/sistema/usuarios/?empresa=la-fragua')
        navegador.find_element(By.LINK_TEXT, 'Añadir usuario').click()
        for campo, valor in (('nombres', 'Operador'), ('apellidos', 'QA'), ('email', 'operador-qa@example.invalid')):
            navegador.find_element(By.ID, 'id_' + campo).send_keys(valor)
        Select(navegador.find_element(By.ID, 'id_rol')).select_by_visible_text('Operador')
        navegador.find_element(By.CSS_SELECTOR, 'form.ss-sistema-formulario button[type="submit"]').click()
        espera.until(lambda d: urlsplit(d.current_url).path == '/sistema/usuarios/')
        self.assertTrue(Usuario.objects.using('ferreteria').filter(email='operador-qa@example.invalid').exists())
        self.assertFalse(Usuario.objects.using('repuestos').filter(email='operador-qa@example.invalid').exists())
        navegador.get(self.live_server_url + '/sistema/inventario/?empresa=la-fragua')
        self.assertEqual(navegador.find_element(By.ID, 'sistema-kpi-stock').text, '15')
        navegador.find_element(By.ID, 'sistema-notificaciones-boton').click()
        espera.until(EC.element_to_be_clickable((By.CSS_SELECTOR, '#sistema-notificaciones-lista button'))).click()
        espera.until(lambda d: urlsplit(d.current_url).path == '/sistema/usuarios/' and 'empresa=la-fragua' in d.current_url)
        navegador.set_window_size(390, 844)
        navegador.get(self.live_server_url + '/sistema/')
        navegador.find_element(By.CSS_SELECTOR, '.ss-menu-toggle').click()
        espera.until(lambda d: 'ss-sidebar-open' in d.find_element(By.ID, 'ss-navigation').get_attribute('class'))
        self.assertTrue(navegador.execute_script('return document.documentElement.scrollWidth <= window.innerWidth'))
        self.comprobar_menu(navegador)
        perfil = espera.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'a.ss-sistema-perfil')))
        # La clase se añade al iniciar la animación del menú. El clic requiere
        # que el perfil ya esté dentro de la pantalla y libre de superposiciones.
        espera.until(lambda d: d.execute_script('''
            const e=arguments[0], r=e.getBoundingClientRect();
            const visible=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);
            return r.left>=0 && r.right<=innerWidth && r.top>=0 && r.bottom<=innerHeight
                && visible && (visible===e || e.contains(visible));
        ''', perfil))
        perfil.click()
        espera.until(lambda d: urlsplit(d.current_url).path == '/sistema/mi-cuenta/')
        self.assertEqual(navegador.find_element(By.ID, 'id_email').get_attribute('value'), 'gestion-qa@example.invalid')
        navegador.find_element(By.CSS_SELECTOR, '.ss-menu-toggle').click()
        espera.until(lambda d: 'ss-sidebar-open' in d.find_element(By.ID, 'ss-navigation').get_attribute('class'))
        self.assertEqual(navegador.find_element(By.CSS_SELECTOR, 'a.ss-sistema-perfil').get_attribute('aria-current'), 'page')
        self.comprobar_menu(navegador)
        navegador.find_element(By.CSS_SELECTOR, '.ss-sidebar-close').click()

        navegador.get(self.live_server_url + '/sistema/empresas/nueva/')
        self.assertIn('No hay bases disponibles', navegador.find_element(By.TAG_NAME, 'body').text)
        self.assertFalse(navegador.find_element(By.CSS_SELECTOR, 'form.ss-sistema-formulario button[type="submit"]').is_enabled())
        self.assertTrue(navegador.execute_script('return document.documentElement.scrollWidth <= window.innerWidth'))
        navegador.get(self.live_server_url + '/sistema/empresas/la-fragua/editar/')
        for campo, valor in (('razon_social', 'Ferretería La Fragua Limitada'), ('rut', '12.345.678-5'),
                             ('contacto_nombre', 'César Andrés'), ('contacto_apellidos', 'Guzmán Pérez'),
                             ('contacto_email', 'contacto@example.invalid'), ('contacto_telefono', '+56 9 1234 5678'),
                             ('direccion', 'Dirección de prueba 100')):
            elemento = navegador.find_element(By.ID, 'id_' + campo)
            elemento.clear()
            elemento.send_keys(valor)
        self.assertFalse(navegador.find_element(By.ID, 'id_comuna').is_enabled())
        region = Select(navegador.find_element(By.ID, 'id_region'))
        region.select_by_visible_text('Maule')
        comuna = Select(navegador.find_element(By.ID, 'id_comuna'))
        self.assertIn('Talca', [opcion.text for opcion in comuna.options])
        self.assertNotIn('Providencia', [opcion.text for opcion in comuna.options])
        comuna.select_by_visible_text('Talca')
        region.select_by_visible_text('Metropolitana de Santiago')
        self.assertEqual(comuna.first_selected_option.get_attribute('value'), '')
        comuna.select_by_visible_text('Providencia')
        Select(navegador.find_element(By.ID, 'id_rubro')).select_by_value('ferreteria')
        guardar = navegador.find_element(By.CSS_SELECTOR, 'form.ss-sistema-formulario button[type="submit"]')
        navegador.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'instant'});", guardar)
        espera.until(lambda d: d.execute_script(
            'const r = arguments[0].getBoundingClientRect(); return r.top >= 0 && r.bottom <= window.innerHeight;', guardar))
        # Pausa solo la navegación de este envío para observar el indicador;
        # después se restablece la página y se realiza el guardado real.
        navegador.execute_script('''
            window.pausarEnvioQA = evento => evento.preventDefault();
            arguments[0].form.addEventListener('submit', window.pausarEnvioQA);
        ''', guardar)
        guardar.click()
        espera.until(lambda d: d.find_element(By.ID, 'ss-carga').get_attribute('open') is not None)
        self.assertIn('Guardando empresa', navegador.find_element(By.ID, 'ss-carga-texto').text)
        self.assertTrue(navegador.find_element(By.CSS_SELECTOR, '#ss-carga .ss-carga-spinner').is_displayed())
        navegador.execute_script('''
            arguments[0].form.removeEventListener('submit', window.pausarEnvioQA);
            window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted: true}));
        ''', guardar)
        espera.until(lambda d: d.find_element(By.ID, 'ss-carga').get_attribute('open') is None)
        guardar.click()
        espera.until(lambda d: urlsplit(d.current_url).path == '/sistema/empresas/la-fragua/')
        self.assertIn('12345678-5', navegador.find_element(By.TAG_NAME, 'body').text)
        self.assertIn('contacto@example.invalid', navegador.find_element(By.TAG_NAME, 'body').text)
        self.assertIn('César Andrés', navegador.find_element(By.TAG_NAME, 'body').text)
        self.assertIn('Guzmán Pérez', navegador.find_element(By.TAG_NAME, 'body').text)
        self.assertTrue(navegador.execute_script('return document.documentElement.scrollWidth <= window.innerWidth'))
        espera.until(EC.visibility_of_element_located((By.ID, 'sistema-confirmacion')))
        navegador.find_element(By.ID, 'sistema-notificaciones-boton').click()
        espera.until(EC.visibility_of_element_located((By.ID, 'sistema-notificaciones-panel')))
        self.assertTrue(navegador.execute_script('''
            const r = document.getElementById('sistema-notificaciones-panel').getBoundingClientRect();
            return r.left >= 0 && r.right <= window.innerWidth && r.top >= 0 && r.bottom <= window.innerHeight;
        '''))
        navegador.find_element(By.ID, 'sistema-notificaciones-leer').click()
        espera.until(lambda d: not d.find_element(By.ID, 'sistema-notificaciones-total').is_displayed())
        navegador.refresh()
        self.assertFalse(navegador.find_element(By.ID, 'sistema-confirmacion').is_displayed())
        self.assertEqual(NotificacionSistema.objects.using('central').filter(destinatario__email='gestion-qa@example.invalid').count(), 2)
        navegador.get(self.live_server_url + '/sistema/empresas/la-fragua/editar/')
        self.assertEqual(Select(navegador.find_element(By.ID, 'id_region')).first_selected_option.text, 'Metropolitana de Santiago')
        self.assertEqual(Select(navegador.find_element(By.ID, 'id_comuna')).first_selected_option.text, 'Providencia')
        navegador.refresh()
        self.assertEqual(Select(navegador.find_element(By.ID, 'id_comuna')).first_selected_option.text, 'Providencia')
        navegador.set_window_size(1440, 1000)
        Bodega.objects.using('ferreteria').update(activa=False)
        navegador.get(self.live_server_url + '/sistema/inventario/?empresa=la-fragua')
        self.assertIn('Sin bodegas activas', navegador.find_element(By.TAG_NAME, 'body').text)
        self.assertFalse(navegador.find_elements(By.ID, 'sistema-grafico-estado'))
        Bodega.objects.using('ferreteria').update(activa=True)
        Producto.objects.using('ferreteria').update(activo=False)
        navegador.refresh()
        self.assertIn('Sin productos activos', navegador.find_element(By.TAG_NAME, 'body').text)
        self.assertFalse(navegador.find_elements(By.ID, 'sistema-grafico-estado'))
        Producto.objects.using('ferreteria').update(activo=True)
        navegador.refresh()
        self.assertIn('Sin movimientos en el período', navegador.find_element(By.TAG_NAME, 'body').text)
        self.assertTrue(navegador.find_elements(By.ID, 'sistema-grafico-estado'))
        self.assertFalse(navegador.find_elements(By.ID, 'sistema-grafico-movimientos'))

        navegador.find_element(By.CSS_SELECTOR, 'button[form="ss-cerrar-sesion"]').click()
        espera.until(EC.visibility_of_element_located((By.ID, 'email')))
        navegador.find_element(By.ID, 'email').send_keys('soporte-qa@example.invalid')
        navegador.find_element(By.ID, 'password').send_keys('Cuenta-equipo-fixture-2626!')
        navegador.find_element(By.ID, 'login-submit').click()
        espera.until(EC.url_contains('/sistema/'))
        self.assertIn('Soporte técnico', navegador.find_element(By.TAG_NAME, 'body').text)
        navegador.find_element(By.ID, 'sistema-notificaciones-boton').click()
        espera.until(lambda d: 'No tienes notificaciones nuevas.' in d.find_element(By.ID, 'sistema-notificaciones-lista').text)
        navegador.find_element(By.ID, 'sistema-notificaciones-boton').click()
        for ruta in ('/sistema/cuentas/', '/sistema/configuracion/', '/sistema/empresas/nueva/'):
            self.assertFalse(navegador.find_elements(By.CSS_SELECTOR, f'a[href="{ruta}"]'))
        navegador.get(self.live_server_url + '/sistema/usuarios/?empresa=la-fragua')
        self.assertFalse(navegador.find_elements(By.LINK_TEXT, 'Añadir usuario'))
        self.assertFalse(navegador.find_elements(By.LINK_TEXT, 'Editar'))
        for ruta in ('/sistema/empresas/la-fragua/editar/', '/sistema/cuentas/', '/sistema/configuracion/'):
            estado = navegador.execute_async_script(
                "const listo = arguments[arguments.length - 1]; fetch(arguments[0]).then(r => listo(r.status));", ruta)
            self.assertEqual(estado, 403)
        navegador.get(self.live_server_url + '/sistema/inventario/?empresa=la-fragua')
        self.assertEqual(navegador.find_element(By.ID, 'sistema-kpi-stock').text, '15')
        soporte = Usuario.objects.using('central').get(email='soporte-qa@example.invalid')
        self.assertTrue(Auditoria.objects.using('central').filter(usuario=soporte, accion='CONSULTA',
                                                               objeto_id=str(Empresa.objects.get(codigo='la-fragua').pk)).exists())
        self.assertEqual(StockBodega.objects.using('repuestos').get(producto__sku='QA-001').cantidad_total, 4)

    def comprobar_resumen_central(self, navegador, espera):
        self.assertEqual(len(navegador.find_elements(By.CSS_SELECTOR, '.ss-dash-kpi')), 4)
        self.assertIn('Sin responsable: 1', navegador.find_element(By.CSS_SELECTOR, '.ss-sistema-kpi-aviso').text)
        self.assertTrue(navegador.find_elements(By.CSS_SELECTOR, '.ss-sistema-tabla time[datetime]'))
        fila = navegador.find_element(By.CSS_SELECTOR, '[data-empresa="la-fragua"]')
        acceso = fila.find_element(By.CSS_SELECTOR, '.ss-sistema-acceso-empresa a')
        self.assertEqual(urlsplit(acceso.get_attribute('href')).hostname, 'la-fragua.localhost')
        self.assertEqual(acceso.get_attribute('target'), '_blank')
        self.assertFalse(fila.find_element(By.CSS_SELECTOR, 'a[href^="/sistema/atenciones/nueva/"]').is_displayed())
        navegador.save_screenshot('/tmp/ss-panel-sistema-escritorio.png')
        fila.find_element(By.TAG_NAME, 'summary').send_keys(Keys.ENTER)
        espera.until(lambda d: d.find_element(By.CSS_SELECTOR, '[data-empresa="la-fragua"] details').get_attribute('open') is not None)
        navegador.save_screenshot('/tmp/ss-panel-sistema-acciones.png')
        fila.find_element(By.LINK_TEXT, 'Abrir atención').click()
        espera.until(lambda d: urlsplit(d.current_url).path == '/sistema/atenciones/nueva/')
        self.assertIn('empresa=la-fragua', navegador.current_url)
        navegador.get(self.live_server_url + '/sistema/')
        navegador.find_element(By.LINK_TEXT, 'Ver abiertas').click()
        espera.until(lambda d: urlsplit(d.current_url).path == '/sistema/atenciones/')
        self.assertIn('Revisión de acceso', navegador.find_element(By.TAG_NAME, 'body').text)
        self.assertNotIn('Consulta resuelta', navegador.find_element(By.TAG_NAME, 'body').text)
        navegador.get(self.live_server_url + '/sistema/')
        navegador.find_element(By.CSS_SELECTOR, '.ss-theme-toggle').click()
        espera.until(lambda d: d.find_element(By.TAG_NAME, 'html').get_attribute('data-bs-theme') == 'dark')
        navegador.save_screenshot('/tmp/ss-panel-sistema-oscuro.png')
        navegador.find_element(By.CSS_SELECTOR, '.ss-theme-toggle').click()
        for ancho in (390, 320):
            navegador.set_window_size(ancho, 844)
            navegador.get(self.live_server_url + '/sistema/')
            self.assertTrue(navegador.execute_script('return document.documentElement.scrollWidth <= innerWidth'))
            if ancho == 390:
                navegador.save_screenshot('/tmp/ss-panel-sistema-movil.png')
            fila = navegador.find_element(By.CSS_SELECTOR, '[data-empresa="la-fragua"]')
            fila.find_element(By.TAG_NAME, 'summary').click()
            enlace = fila.find_element(By.LINK_TEXT, 'Usuarios')
            self.assertTrue(enlace.is_displayed())
            self.assertTrue(navegador.execute_script('''
                const menu = arguments[0].getBoundingClientRect();
                return menu.left >= 0 && menu.right <= innerWidth
                    && document.documentElement.scrollWidth <= innerWidth;
            ''', enlace))
            if ancho == 390:
                navegador.save_screenshot('/tmp/ss-panel-sistema-acciones-movil.png')
                responsable = navegador.find_element(By.CSS_SELECTOR, '.ss-sistema-tabla .badge-soft-warning')
                navegador.execute_script('arguments[0].scrollIntoView({block:"center"})', responsable)
                navegador.save_screenshot('/tmp/ss-panel-sistema-soporte-movil.png')
        navegador.set_window_size(1440, 1000)
        navegador.get(self.live_server_url + '/sistema/')


class SoporteEnChromeTests(StaticLiveServerTestCase):
    databases = {'central', 'ferreteria', 'repuestos'}

    def pulsar(self, navegador, selector):
        espera = WebDriverWait(navegador, 20)
        elemento = espera.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
        navegador.execute_script('arguments[0].scrollIntoView({block:"center",behavior:"instant"});', elemento)
        espera.until(lambda d: d.execute_script('''
            const e=arguments[0],r=e.getBoundingClientRect();
            const superior=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);
            return r.top>=0 && r.bottom<=innerHeight && superior && (superior===e || e.contains(superior));
        ''', elemento))
        elemento.click()

    def test_cliente_autoriza_y_revoca_lectura_en_dos_pestanas_y_menu_movil(self):
        call_command('registrar_empresas_prueba', stdout=StringIO())
        empresa = Empresa.objects.get(codigo='la-fragua')
        call_command('seed_empresa', empresa.codigo, sin_admin=True, stdout=StringIO())
        with usar_empresa(empresa):
            Usuario.objects.create_user(pk=90, email='cliente-qa@example.invalid', password='Cliente-qa-fixture-2026!',
                nombres='Cliente', apellidos='QA', rol=Rol.objects.get(codigo='administrador'))
            bodega = Bodega.objects.create(nombre='Central')
            producto = Producto.objects.create(sku='QA-AUTORIZADO', nombre='Producto autorizado del cliente')
            StockBodega.objects.create(producto=producto, bodega=bodega, cantidad_total=15)
        rol, _ = Rol.objects.using('central').get_or_create(codigo=SOPORTE_TECNICO, defaults={'nombre': 'Soporte técnico'})
        tecnico = Usuario.objects.db_manager('central').create_user(email='soporte-temporal@example.invalid',
            password='Soporte-qa-fixture-2026!', nombres='Soporte', apellidos='QA', is_staff=True, rol=rol)
        caso = AtencionSoporte.objects.using('central').create(empresa=empresa, tecnico=tecnico,
            asunto='Revisión de stock solicitada', motivo='El cliente necesita revisar sus existencias')
        opciones = webdriver.ChromeOptions()
        opciones.add_argument('--headless=new')
        opciones.add_argument('--window-size=1440,1000')
        navegador = webdriver.Chrome(options=opciones)
        self.addCleanup(navegador.quit)
        espera = WebDriverWait(navegador, 20)
        navegador.get(self.live_server_url)
        navegador.find_element(By.ID, 'email').send_keys(tecnico.email)
        navegador.find_element(By.ID, 'password').send_keys('Soporte-qa-fixture-2026!')
        navegador.find_element(By.ID, 'login-submit').click()
        espera.until(EC.url_contains('/sistema/'))
        pestana_tecnico = navegador.current_window_handle
        navegador.get(self.live_server_url + f'/sistema/atenciones/{caso.pk}/')
        self.assertFalse(navegador.find_elements(By.CSS_SELECTOR, '.ss-sidebar-links a[href*="/catalogo/"]'))
        self.pulsar(navegador, 'input[name="alcances"][value="catalogo"]')
        Select(navegador.find_element(By.ID, 'id_minutos')).select_by_value('15')
        navegador.find_element(By.ID, 'id_motivo').send_keys('Comprobar las existencias indicadas por el cliente')
        self.pulsar(navegador, 'button[name="accion"][value="solicitar"]')
        espera.until(lambda d: AccesoSoporte.objects.using('central').filter(atencion=caso, estado='pendiente').exists())
        espera.until(lambda d: 'Pendiente de autorización' in d.find_element(By.TAG_NAME, 'body').text)
        acceso = AccesoSoporte.objects.using('central').get(atencion=caso)
        ruta = f'/sistema/catalogo/?empresa=la-fragua&atencion={caso.pk}'
        self.assertEqual(navegador.execute_async_script(
            'const listo=arguments[arguments.length-1];fetch(arguments[0]).then(r=>listo(r.status));', ruta), 403)

        navegador.switch_to.new_window('tab')
        pestana_cliente = navegador.current_window_handle
        # La sesión técnica central permanece abierta en la otra pestaña.
        # El cliente entra desde el host propio de su empresa.
        origen_cliente = 'http://la-fragua.localhost:' + str(urlsplit(self.live_server_url).port)
        navegador.get(origen_cliente)
        navegador.find_element(By.ID, 'email').send_keys('cliente-qa@example.invalid')
        navegador.find_element(By.ID, 'password').send_keys('Cliente-qa-fixture-2026!')
        navegador.find_element(By.ID, 'login-submit').click()
        espera.until(EC.url_contains('/dashboard/'))
        espera.until(lambda d: d.find_element(By.ID, 'kpi-stock').text == '15')
        soporte_link = espera.until(EC.visibility_of_element_located((By.CSS_SELECTOR, 'a[href="/soporte/"]')))
        soporte_link.click()
        espera.until(lambda d: urlsplit(d.current_url).path == '/soporte/')
        espera.until(lambda d: d.find_element(By.CSS_SELECTOR, '.ss-app-layout').get_attribute('data-ss-autorizado') is not None)
        espera.until(lambda d: d.find_element(By.ID, 'user-name').text == 'Cliente QA')
        self.assertEqual(navegador.find_element(By.CSS_SELECTOR, '#ss-navigation .sidebar-item.active').get_attribute('href'), origen_cliente + '/soporte/')
        self.assertIn('Consultar catálogo y stock', navegador.find_element(By.TAG_NAME, 'body').text)
        self.assertIn('15 minutos', navegador.find_element(By.TAG_NAME, 'body').text)
        self.assertFalse(navegador.find_elements(By.CSS_SELECTOR, 'a[href*="/sistema/configuracion/"]'))
        navegador.set_window_size(390, 844)
        self.assertTrue(navegador.execute_script('return document.documentElement.scrollWidth<=innerWidth'))
        self.pulsar(navegador, 'button[name="accion"][value="aprobar"]')
        espera.until(lambda d: AccesoSoporte.objects.using('central').get(pk=acceso.pk).estado == 'aprobado')
        espera.until(EC.visibility_of_element_located((By.CSS_SELECTOR, 'button[value="revocar"]')))

        navegador.switch_to.window(pestana_tecnico)
        navegador.set_window_size(1440, 1000)
        navegador.refresh()
        espera.until(EC.visibility_of_element_located((By.CSS_SELECTOR, 'a[href*="/sistema/catalogo/"]')))
        self.pulsar(navegador, '.ss-sidebar-links a[href*="/catalogo/"]')
        espera.until(lambda d: urlsplit(d.current_url).path == '/sistema/catalogo/')
        self.assertIn('Producto autorizado del cliente', navegador.find_element(By.TAG_NAME, 'body').text)
        self.assertIn('Acceso temporal autorizado hasta', navegador.find_element(By.TAG_NAME, 'body').text)
        navegador.set_window_size(390, 844)
        self.assertTrue(navegador.execute_script('return document.documentElement.scrollWidth<=innerWidth'))
        self.pulsar(navegador, '.ss-menu-toggle')
        espera.until(lambda d: 'ss-sidebar-open' in d.find_element(By.ID, 'ss-navigation').get_attribute('class'))
        # La clase cambia al iniciar la animación; esperar a que el enlace
        # esté visible comprueba el menú abierto, no un fotograma intermedio.
        espera.until(EC.visibility_of_element_located((By.CSS_SELECTOR, '.ss-sidebar-links a[href*="/catalogo/"]')))
        self.assertFalse(navegador.find_elements(By.LINK_TEXT, 'Movimientos'))
        self.pulsar(navegador, '.ss-sidebar-close')

        navegador.switch_to.window(pestana_cliente)
        self.pulsar(navegador, 'button[name="accion"][value="revocar"]')
        espera.until(lambda d: AccesoSoporte.objects.using('central').get(pk=acceso.pk).estado == 'revocado')
        espera.until(lambda d: 'Revocado' in d.find_element(By.TAG_NAME, 'body').text)
        navegador.switch_to.window(pestana_tecnico)
        self.assertEqual(navegador.execute_async_script(
            'const listo=arguments[arguments.length-1];fetch(arguments[0]).then(r=>listo(r.status));', ruta), 403)
        navegador.get(self.live_server_url + f'/sistema/atenciones/{caso.pk}/')
        self.assertFalse(navegador.find_elements(By.CSS_SELECTOR, '.ss-sidebar-links a[href*="/catalogo/"]'))


class ContactoEnChromeTests(StaticLiveServerTestCase):
    databases = {'central', 'ferreteria', 'repuestos'}

    def comprobar_carga(self, navegador, selector, esperado):
        """Pausa una navegación para observar el indicador antes del cambio de página."""
        enlace = WebDriverWait(navegador, 20).until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
        navegador.execute_script('''
            const enlace=arguments[0];
            document.addEventListener('click', function pausar(evento) {
                if (evento.target.closest('a') !== enlace) return;
                evento.preventDefault();
                document.removeEventListener('click', pausar);
            });
        ''', enlace)
        self.pulsar(navegador, By.CSS_SELECTOR, selector)
        WebDriverWait(navegador, 20).until(EC.visibility_of_element_located((By.ID, 'ss-carga')))
        self.assertEqual(navegador.find_element(By.ID, 'ss-carga-texto').text, esperado)
        self.assertTrue(navegador.execute_script('''
            const d=document.getElementById('ss-carga'), r=d.getBoundingClientRect();
            return d.scrollWidth<=d.clientWidth && d.scrollHeight<=d.clientHeight
                && r.left>=0 && r.right<=innerWidth && r.top>=0 && r.bottom<=innerHeight;
        '''))
        navegador.execute_script('window.dispatchEvent(new PageTransitionEvent("pageshow", {persisted:true}));')
        WebDriverWait(navegador, 20).until(EC.invisibility_of_element_located((By.ID, 'ss-carga')))

    def comprobar_menu(self, navegador):
        """Los contadores permanecen junto al texto en todas las páginas."""
        filas = navegador.execute_script('''return Array.from(
            document.querySelectorAll('.ss-menu-con-contador'), e => {
                const r=e.getBoundingClientRect();
                const texto=e.querySelector('span:not(.ss-menu-contador)').getBoundingClientRect();
                const contador=e.querySelector('.ss-menu-contador').getBoundingClientRect();
                return {alto:r.height, diferencia:Math.abs(texto.top+texto.height/2-contador.top-contador.height/2)};
            });''')
        self.assertEqual(len(filas), 7)
        self.assertTrue(all(fila['alto'] <= 44 and fila['diferencia'] <= 1 for fila in filas), filas)

    def pulsar(self, navegador, tipo, selector):
        elemento = WebDriverWait(navegador, 20).until(EC.element_to_be_clickable((tipo, selector)))
        # Bootstrap utiliza desplazamiento suave. Antes del clic nativo se
        # termina el desplazamiento y se comprueba que el control esté visible.
        navegador.execute_script('arguments[0].scrollIntoView({block:"center",behavior:"instant"});', elemento)
        WebDriverWait(navegador, 20).until(lambda d: d.execute_script('''
            const e=arguments[0], r=e.getBoundingClientRect();
            const x=r.left+r.width/2, y=r.top+r.height/2;
            const visible=document.elementFromPoint(x,y);
            return x>=0 && x<innerWidth && y>=0 && y<innerHeight && visible && (visible===e || e.contains(visible));
        ''', elemento))
        elemento.click()

    def test_alta_exclusiva_login_bandeja_borradores_y_seguimiento_en_movil(self):
        Usuario.objects.db_manager('central').create_superuser(
            email='root-contacto@example.invalid', password='Root-fixture-contacto-2026!', nombres='Root')
        Rol.objects.using('central').get_or_create(codigo=CONTACTO, defaults={'nombre':'Contacto', 'es_sistema':True})
        mensaje = MensajeContacto.objects.using('central').create(
            cuenta_zoho='101', mensaje_zoho='201', carpeta_zoho='301', remitente_email='consulta@example.invalid',
            remitente_nombre='Persona de prueba', asunto='Necesito ayuda con mi cuenta', contenido_cargado=True,
            contenido='Quiero orientación sobre SmartStock.', resumen='Consulta de acceso')
        opciones = webdriver.ChromeOptions()
        opciones.add_argument('--headless=new')
        opciones.add_argument('--window-size=1440,1000')
        navegador = webdriver.Chrome(options=opciones)
        self.addCleanup(navegador.quit)
        espera = WebDriverWait(navegador, 20)
        navegador.get(self.live_server_url)
        navegador.find_element(By.ID, 'email').send_keys('root-contacto@example.invalid')
        navegador.find_element(By.ID, 'password').send_keys('Root-fixture-contacto-2026!')
        self.pulsar(navegador, By.ID, 'login-submit')
        espera.until(EC.url_contains('/sistema/'))
        navegador.get(self.live_server_url + '/sistema/cuentas/nueva/')
        self.assertNotIn('Contacto', [opcion.text for opcion in Select(navegador.find_element(By.ID, 'id_perfil')).options])
        navegador.get(self.live_server_url + '/sistema/contacto/cuenta/')
        self.assertFalse(navegador.find_element(By.ID, 'id_email').is_enabled())
        for campo, valor in [('nombres','Contacto'),('apellidos','SmartStock'),
                             ('password1','Cuenta-fixture-contacto-2026!'),('password2','Cuenta-fixture-contacto-2026!')]:
            navegador.find_element(By.ID, 'id_' + campo).send_keys(valor)
        self.pulsar(navegador, By.CSS_SELECTOR, '.ss-sistema-formulario button[type="submit"]')
        espera.until(lambda d: Usuario.objects.using('central').filter(email=CORREO_CONTACTO).exists())
        espera.until(EC.visibility_of_element_located((By.ID, 'sistema-confirmacion')))
        self.pulsar(navegador, By.ID, 'sistema-confirmacion-cerrar')
        espera.until(EC.invisibility_of_element_located((By.ID, 'sistema-confirmacion')))
        self.pulsar(navegador, By.CSS_SELECTOR, 'button[form="ss-cerrar-sesion"]')
        espera.until(EC.visibility_of_element_located((By.ID, 'email')))
        navegador.find_element(By.ID, 'email').send_keys(CORREO_CONTACTO)
        navegador.find_element(By.ID, 'password').send_keys('Cuenta-fixture-contacto-2026!')
        self.pulsar(navegador, By.ID, 'login-submit')
        espera.until(EC.url_contains('/contacto/bandeja/'))
        self.assertIn('Atención de SmartStock', navegador.find_element(By.TAG_NAME, 'body').text)
        for ruta in ('/sistema/','/sistema/empresas/','/sistema/configuracion/'):
            self.assertFalse(navegador.find_elements(By.CSS_SELECTOR, f'.ss-sidebar a[href="{ruta}"]'))
        self.pulsar(navegador, By.CSS_SELECTOR, f'a[href="/contacto/mensajes/{mensaje.pk}/"]')
        espera.until(EC.url_contains(f'/contacto/mensajes/{mensaje.pk}/'))
        Select(navegador.find_element(By.ID, 'id_estado')).select_by_value('seguimiento')
        self.pulsar(navegador, By.CSS_SELECTOR, 'button[value="seguimiento"]')
        espera.until(lambda d: MensajeContacto.objects.using('central').get(pk=mensaje.pk).estado == 'seguimiento')
        espera.until(EC.visibility_of_element_located((By.ID, 'sistema-confirmacion')))
        self.pulsar(navegador, By.ID, 'sistema-confirmacion-cerrar')
        espera.until(EC.invisibility_of_element_located((By.ID, 'sistema-confirmacion')))
        navegador.find_element(By.CSS_SELECTOR, '[data-borrador-editor] textarea').send_keys('Gracias por escribirnos. Te orientaremos sobre el acceso.')
        self.pulsar(navegador, By.CSS_SELECTOR, 'button[value="borrador"]')
        espera.until(lambda d: RespuestaContacto.objects.using('central').filter(mensaje=mensaje).exists())
        espera.until(EC.visibility_of_element_located((By.ID, 'sistema-confirmacion')))
        self.pulsar(navegador, By.ID, 'sistema-confirmacion-cerrar')
        espera.until(EC.invisibility_of_element_located((By.ID, 'sistema-confirmacion')))
        self.assertFalse(navegador.find_element(By.CSS_SELECTOR, '[data-respuesta-enviar]').is_enabled())
        nota = navegador.find_element(By.CSS_SELECTOR, '.ss-contacto-seguimiento textarea[name="texto"]')
        nota.send_keys('Revisar consulta mañana.')
        self.pulsar(navegador, By.CSS_SELECTOR, 'button[value="nota"]')
        espera.until(lambda d: NotaContacto.objects.using('central').filter(mensaje=mensaje).exists())
        espera.until(EC.visibility_of_element_located((By.ID, 'sistema-confirmacion')))
        self.pulsar(navegador, By.ID, 'sistema-confirmacion-cerrar')
        espera.until(EC.invisibility_of_element_located((By.ID, 'sistema-confirmacion')))
        navegador.set_window_size(390, 844)
        self.assertTrue(navegador.execute_script('return document.documentElement.scrollWidth <= window.innerWidth'))
        self.assertTrue(navegador.find_element(By.CSS_SELECTOR, '.ss-contacto-texto').is_displayed())
        self.pulsar(navegador, By.CSS_SELECTOR, '.ss-menu-toggle')
        espera.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'a.ss-sistema-perfil'))).click()
        espera.until(EC.url_contains('/contacto/mi-cuenta/'))
        self.comprobar_menu(navegador)
        self.assertFalse(navegador.find_element(By.ID, 'id_email').is_enabled())
        self.assertFalse(navegador.find_elements(By.ID, 'id_perfil'))
        self.assertTrue(navegador.execute_script('return document.documentElement.scrollWidth <= window.innerWidth'))

    def test_conexion_web_actualizacion_y_respuesta_desde_smartstock(self):
        """Contrato de Zoho simulado: el navegador recorre el mismo flujo real, sin enviar correo externo."""
        clave = 'Cuenta-fixture-buzon-2026!'
        Usuario.objects.db_manager('central').create_superuser(email='root-buzon@example.invalid', password=clave, nombres='Root')
        rol, _ = Rol.objects.using('central').get_or_create(codigo=CONTACTO, defaults={'nombre':'Contacto','es_sistema':True})
        Usuario.objects.db_manager('central').create_user(email=CORREO_CONTACTO, password=clave, nombres='Contacto', is_staff=True, rol=rol)
        llamadas, envios, recibidos = [], [], []
        contenido_iniciado, entregar_contenido = Event(), Event()
        def resultado(data):
            return SimpleNamespace(status_code=200, content=b'{}', json=lambda:{'status':{'code':200},'data':data})
        def api(metodo, url, **opciones):
            llamadas.append((metodo,url))
            if url.endswith('/api/accounts'):
                return resultado([{'accountId':'101','primaryEmailAddress':CORREO_CONTACTO}])
            if url.endswith('/messages/view'):
                return resultado([])
            if url.endswith('/messages/search'):
                self.assertEqual(opciones['params']['searchKey'], 'in:Inbox::groupResult:false')
                return resultado(list(recibidos))
            if url.endswith('/messages/201/content'):
                contenido_iniciado.set()
                if not entregar_contenido.wait(timeout=15):
                    raise AssertionError('La página debe permitir usar el editor antes de recibir el contenido de Zoho.')
                return resultado({'content':'<p>Necesito ayuda con mi acceso.</p>'})
            if metodo == 'POST' and url.endswith('/messages/201'):
                envios.append(opciones['json'])
                return resultado({'messageId':'501'})
            raise AssertionError('Petición de correo no prevista: ' + metodo)
        opciones = webdriver.ChromeOptions()
        opciones.add_argument('--headless=new')
        opciones.add_argument('--window-size=1440,1000')
        navegador = webdriver.Chrome(options=opciones)
        self.addCleanup(navegador.quit)
        espera = WebDriverWait(navegador, 20)
        def ingresar(correo):
            navegador.get(self.live_server_url)
            espera.until(EC.visibility_of_element_located((By.ID,'email'))).send_keys(correo)
            navegador.find_element(By.ID,'password').send_keys(clave)
            self.pulsar(navegador, By.ID, 'login-submit')
            espera.until(lambda d: '/sistema/' in d.current_url or '/contacto/bandeja/' in d.current_url)
        def cerrar_confirmacion(documento_anterior):
            # La escritura en BD puede terminar antes de la redirección del POST.
            # Espera el documento nuevo antes de consultar su confirmación.
            espera.until(EC.staleness_of(documento_anterior))
            espera.until(lambda d: d.execute_script('return document.readyState') == 'complete')
            espera.until(EC.visibility_of_element_located((By.ID,'sistema-confirmacion')))
            self.pulsar(navegador, By.ID, 'sistema-confirmacion-cerrar')
            espera.until(EC.invisibility_of_element_located((By.ID,'sistema-confirmacion')))
        with patch('esquema_multiempresa.zoho_contacto.requests.post', return_value=SimpleNamespace(
                status_code=200, json=lambda:{'access_token':'access-navegador-fixture','refresh_token':'refresh-navegador-fixture'})), \
             patch('esquema_multiempresa.zoho_contacto.requests.request', side_effect=api):
            ingresar('root-buzon@example.invalid')
            navegador.get(self.live_server_url + '/sistema/contacto/cuenta/')
            self.pulsar(navegador, By.LINK_TEXT, 'Conectar Zoho Mail')
            espera.until(EC.url_contains('/sistema/contacto/conexion/'))
            for nombre, valor in [('client_id','client-navegador-fixture'),('client_secret','secret-navegador-fixture'),('codigo','code-navegador-fixture')]:
                navegador.find_element(By.ID,'id_' + nombre).send_keys(valor)
            documento = navegador.find_element(By.TAG_NAME, 'html')
            self.pulsar(navegador, By.CSS_SELECTOR, 'button[value="conectar"]')
            espera.until(lambda d: BuzonContacto.objects.using('central').filter(conexion_estado='conectado').exists())
            cerrar_confirmacion(documento)
            self.assertEqual(len(envios), 0)
            self.pulsar(navegador, By.CSS_SELECTOR, 'button[form="ss-cerrar-sesion"]')
            espera.until(EC.visibility_of_element_located((By.ID,'email')))
            ingresar(CORREO_CONTACTO)
            self.assertIn('No hay correos importados', navegador.find_element(By.TAG_NAME,'body').text)
            self.comprobar_menu(navegador)
            self.pulsar(navegador, By.CSS_SELECTOR, 'a.ss-sistema-perfil')
            espera.until(EC.url_contains('/contacto/mi-cuenta/'))
            self.comprobar_menu(navegador)
            self.pulsar(navegador, By.CSS_SELECTOR, '.ss-sidebar-links a[href="/contacto/bandeja/"]')
            espera.until(EC.url_contains('/contacto/bandeja/'))
            recibidos.append({'messageId':'201','folderId':'301','fromAddress':'consulta@example.invalid',
                'sender':'Persona de prueba','subject':'Correo de prueba recibido',
                'receivedtime':str(int(timezone.now().timestamp() * 1000) - 15000),
                'summary':'Necesito ayuda con mi acceso','hasAttachment':'0'})
            antes = sum(url.endswith('/messages/search') for _,url in llamadas)
            documento = navegador.find_element(By.TAG_NAME, 'html')
            self.pulsar(navegador, By.ID, 'contacto-actualizar')
            cerrar_confirmacion(documento)
            self.assertGreater(sum(url.endswith('/messages/search') for _,url in llamadas), antes)
            self.assertIn('Correo de prueba recibido', navegador.find_element(By.TAG_NAME,'body').text)
            self.comprobar_menu(navegador)
            self.comprobar_carga(navegador, '.ss-sidebar-links a[href="/contacto/bandeja/?vista=sin-leer"]', 'Cargando Sin leer…')
            self.comprobar_carga(navegador, 'a.ss-sistema-perfil', 'Abriendo mi cuenta…')
            self.comprobar_carga(navegador, '.ss-contacto-fila', 'Abriendo correo…')

            mensaje = MensajeContacto.objects.using('central').get(mensaje_zoho='201')
            self.pulsar(navegador, By.CSS_SELECTOR, f'a[href="/contacto/mensajes/{mensaje.pk}/"]')
            espera.until(EC.url_contains(f'/contacto/mensajes/{mensaje.pk}/'))
            self.assertTrue(contenido_iniciado.wait(timeout=10))
            editor = navegador.find_element(By.CSS_SELECTOR, '[data-borrador-editor] textarea')
            self.assertTrue(editor.is_enabled())
            self.assertIsNone(navegador.find_element(By.ID, 'ss-carga').get_attribute('open'))
            editor.send_keys('Borrador mientras llega el contenido')
            entregar_contenido.set()
            espera.until(EC.text_to_be_present_in_element((By.CSS_SELECTOR,'.ss-contacto-texto'), 'Necesito ayuda con mi acceso.'))
            self.assertEqual(editor.get_attribute('value'), 'Borrador mientras llega el contenido')
            editor.clear()
            self.pulsar(navegador, By.CSS_SELECTOR, 'a[href="#contacto-responder"]')
            navegador.find_element(By.CSS_SELECTOR,'[data-borrador-editor] textarea').send_keys('Gracias por escribirnos. Te ayudaremos a recuperar el acceso.')
            documento = navegador.find_element(By.TAG_NAME, 'html')
            self.pulsar(navegador, By.CSS_SELECTOR, 'button[value="borrador"]')
            cerrar_confirmacion(documento)
            self.assertTrue(navegador.find_element(By.CSS_SELECTOR,'[data-respuesta-enviar]').is_enabled())
            documento = navegador.find_element(By.TAG_NAME, 'html')
            self.pulsar(navegador, By.CSS_SELECTOR, '[data-respuesta-enviar]')
            cerrar_confirmacion(documento)
            self.assertEqual(len(envios), 1)
            self.assertEqual(envios[0]['fromAddress'], CORREO_CONTACTO)
            self.assertEqual(envios[0]['toAddress'],'consulta@example.invalid')
            navegador.get(self.live_server_url + '/contacto/bandeja/?vista=enviados')
            self.assertIn('Gracias por escribirnos.', navegador.find_element(By.TAG_NAME,'body').text)
            self.assertFalse(navegador.find_elements(By.CSS_SELECTOR,'.ss-contacto-kpis'))
            navegador.set_window_size(390,844)
            self.assertTrue(navegador.execute_script('return document.documentElement.scrollWidth <= window.innerWidth'))
            self.comprobar_carga(navegador, '.ss-contacto-fila', 'Abriendo correo…')


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class AccesoUnificadoEnChromeTests(StaticLiveServerTestCase):
    databases = {'central', 'ferreteria', 'repuestos'}
    pulsar = ContactoEnChromeTests.pulsar

    def test_seleccion_autorizada_transicion_y_sesion_sin_repetir_clave(self):
        call_command('registrar_empresas_prueba', stdout=StringIO())
        clave = 'Cuenta-acceso-unificado-fixture-2026!'
        for empresa in Empresa.objects.using('central').all():
            call_command('seed_empresa', empresa.codigo, sin_admin=True, stdout=StringIO())
            with usar_empresa(empresa):
                Usuario.objects.create_user(email='compartida@example.invalid', password=clave,
                    nombres='Cuenta de prueba', rol=Rol.objects.get(codigo='administrador'))
        opciones = webdriver.ChromeOptions()
        opciones.add_argument('--headless=new')
        opciones.add_argument('--window-size=1440,1000')
        navegador = webdriver.Chrome(options=opciones)
        self.addCleanup(navegador.quit)
        espera = WebDriverWait(navegador, 20)
        navegador.get(self.live_server_url)
        espera.until(EC.visibility_of_element_located((By.ID, 'login-submit')))
        navegador.find_element(By.ID, 'email').send_keys('compartida@example.invalid')
        self.assertFalse(navegador.find_element(By.ID, 'ss-acceso-transicion').is_displayed())
        navegador.find_element(By.ID, 'password').send_keys(clave)
        self.pulsar(navegador, By.ID, 'login-submit')
        espera.until(EC.visibility_of_element_located((By.ID, 'opciones-acceso')))
        botones = navegador.find_elements(By.CSS_SELECTOR, '#destinos-acceso button')
        self.assertEqual({b.text for b in botones}, {'Ferretería La Fragua', 'Repuestos Punto Motor'})
        self.assertEqual(navegador.find_element(By.ID, 'password').get_attribute('value'), '')
        navegador.save_screenshot('/tmp/ss-acceso-unificado-selector.png')
        navegador.execute_cdp_cmd('Emulation.setEmulatedMedia', {'features': [{'name': 'prefers-reduced-motion', 'value': 'reduce'}]})
        # ChromeDriver cambia de documento durante una navegación pendiente.
        # Pausar únicamente el envío nativo permite inspeccionar el fotograma
        # anterior; después se ejecuta el POST real y se verifica la sesión.
        navegador.execute_script("""
            const enviar=HTMLFormElement.prototype.submit;
            HTMLFormElement.prototype.submit=function(){
                if(this.matches('form[data-ss-entrega-acceso]')) window.entregarAcceso=()=>enviar.call(this);
                else enviar.call(this);
            };
        """)
        self.pulsar(navegador, By.XPATH, '//div[@id="destinos-acceso"]/button[contains(.,"La Fragua")]')
        espera.until(lambda d: d.execute_script('return typeof window.entregarAcceso==="function"'))
        self.assertTrue(navegador.find_element(By.ID, 'ss-acceso-transicion').is_displayed())
        self.assertEqual(navegador.find_element(By.ID, 'ss-acceso-titulo').text, 'Abriendo Ferretería La Fragua…')
        self.assertIsNone(navegador.execute_script('return localStorage.getItem("access_token")'))
        self.assertIsNone(navegador.find_element(By.ID, 'ss-carga').get_attribute('open'))
        self.assertEqual(navegador.execute_script('return getComputedStyle(document.getElementById("ss-acceso-indicador")).animationName'), 'none')
        imagen = navegador.find_element(By.ID, 'ss-acceso-logo')
        espera.until(lambda d: d.execute_script('return arguments[0].complete && arguments[0].naturalWidth>0;', imagen))
        self.assertIn('/branding/empresas/la-fragua.png', imagen.get_attribute('src'))
        navegador.save_screenshot('/tmp/ss-acceso-unificado-transicion.png')
        navegador.set_window_size(390, 844)
        self.assertTrue(navegador.execute_script('return document.documentElement.scrollWidth<=innerWidth'))
        navegador.save_screenshot('/tmp/ss-acceso-unificado-transicion-movil.png')
        navegador.execute_script('window.entregarAcceso()')
        espera.until(EC.url_contains('/dashboard/'))
        self.assertEqual(urlsplit(navegador.current_url).hostname, 'la-fragua.localhost')
        self.assertIn('Ferretería La Fragua', navegador.title)
        self.assertFalse(navegador.find_elements(By.ID, 'login-form'))


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class AuditoriaEnChromeTests(StaticLiveServerTestCase):
    databases = {'central', 'ferreteria', 'repuestos'}
    pulsar = ContactoEnChromeTests.pulsar

    def test_filtros_grupos_detalle_y_documento_en_escritorio_y_movil(self):
        clave = 'Cuenta-fixture-auditoria-2026!'
        raiz = Usuario.objects.db_manager('central').create_superuser(
            email='raiz-auditoria@example.invalid', password=clave, nombres='Javier', apellidos='De prueba')
        call_command('registrar_empresas_prueba', stdout=StringIO())
        empresa = Empresa.objects.using('central').get(codigo='la-fragua')
        motor = Empresa.objects.using('central').get(codigo='punto-motor')
        consultas = []
        for empresa_consultada in (empresa, motor, empresa):
            consultas.append(crear_evento(alias='central', usuario=raiz, empresa=empresa_consultada, accion='CONSULTA', modelo='Empresa',
                descripcion='QA-AUD Consulta de empresas', operacion='Consulta de Empresas', resultado='solicitada'))
        fecha = timezone.localtime().replace(minute=0, second=0, microsecond=0)
        for indice, consulta in enumerate(consultas):
            Auditoria.objects.using('central').filter(pk=consulta.pk).update(fecha_creacion=fecha.replace(microsecond=indice * 100))
        evento = crear_evento(alias='central', usuario=raiz, accion='DEACTIVATE', modelo='Usuario',
            descripcion='QA-AUD Cuenta de prueba suspendida. Descripción completa del evento.',
            operacion='Cuenta desactivada', cambios={'activo': {'antes': True, 'despues': False}})
        opciones = webdriver.ChromeOptions()
        opciones.add_argument('--headless=new')
        opciones.add_argument('--window-size=1700,1000')
        navegador = webdriver.Chrome(options=opciones)
        self.addCleanup(navegador.quit)
        espera = WebDriverWait(navegador, 20)
        navegador.get(self.live_server_url)
        navegador.find_element(By.ID, 'email').send_keys(raiz.email)
        navegador.find_element(By.ID, 'password').send_keys(clave)
        self.pulsar(navegador, By.ID, 'login-submit')
        espera.until(EC.url_contains('/sistema/'))
        navegador.get(self.live_server_url + '/sistema/auditoria/?search=QA-AUD')
        espera.until(EC.visibility_of_element_located((By.ID, 'buscar-evento')))
        self.assertFalse(navegador.find_element(By.ID, 'auditoria-usuario').is_displayed())
        self.assertEqual(len(navegador.find_elements(By.CSS_SELECTOR, '.ss-aud-evento')), 4)
        self.assertEqual(len(navegador.find_elements(By.CSS_SELECTOR, '.ss-aud-grupo')), 1)
        grupo = navegador.find_element(By.CSS_SELECTOR, '.ss-aud-grupo summary').text
        self.assertIn('3 consultas · 2 empresas', grupo)
        self.assertIn(raiz.email, grupo)
        self.assertIn('Superusuario técnico', grupo)
        self.assertIn('Solicitud registrada', grupo)
        self.assertIn(fecha.strftime('%d/%m/%Y · %H:%M:%S') + ' · Ver eventos individuales', grupo)
        navegador.save_screenshot('/tmp/ss-auditoria-filtros-compactos.png')
        self.pulsar(navegador, By.CSS_SELECTOR, '.ss-aud-grupo summary')
        self.assertEqual(len([e for e in navegador.find_elements(By.CSS_SELECTOR, '.ss-aud-evento') if e.is_displayed()]), 4)
        self.assertTrue(navegador.execute_script('return document.documentElement.scrollWidth<=innerWidth'))
        navegador.execute_script('scrollTo({top:0,behavior:"instant"});')
        navegador.save_screenshot('/tmp/ss-auditoria-escritorio.png')
        self.pulsar(navegador, By.CSS_SELECTOR, '.ss-aud-avanzados summary')
        Select(navegador.find_element(By.ID, 'auditoria-accion')).select_by_value('DEACTIVATE')
        self.pulsar(navegador, By.CSS_SELECTOR, '.ss-aud-filtros button[type="submit"]')
        espera.until(lambda d: 'accion=DEACTIVATE' in d.current_url)
        self.assertEqual(len(navegador.find_elements(By.CSS_SELECTOR, '.ss-aud-evento')), 1)
        self.assertEqual(navegador.find_element(By.CSS_SELECTOR, '.ss-aud-evento dl > div:nth-child(3) dd').text, 'SmartStock')
        self.assertTrue(navegador.find_element(By.ID, 'auditoria-accion').is_displayed())
        self.assertEqual(Select(navegador.find_element(By.ID, 'auditoria-accion')).first_selected_option.get_attribute('value'), 'DEACTIVATE')
        self.assertIn('1 activo', navegador.find_element(By.CSS_SELECTOR, '.ss-aud-avanzados summary').text)
        navegador.execute_script('scrollTo({top:0,behavior:"instant"});')
        navegador.save_screenshot('/tmp/ss-auditoria-filtros-activos.png')
        self.pulsar(navegador, By.CSS_SELECTOR, '.ss-aud-ver-detalle')
        espera.until(EC.url_contains(f'/sistema/auditoria/{evento.pk}/'))
        self.assertIn('Descripción completa del evento.', navegador.find_element(By.TAG_NAME, 'body').text)
        self.assertIn('Cuenta activa', navegador.find_element(By.TAG_NAME, 'body').text)
        self.assertIn('Superusuario técnico', navegador.find_element(By.TAG_NAME, 'body').text)
        navegador.set_window_size(390, 844)
        espera.until(lambda d: d.execute_script('return document.getElementById("ss-navigation").getBoundingClientRect().right<=1'))
        self.assertTrue(navegador.execute_script('return document.documentElement.scrollWidth<=innerWidth'))
        navegador.save_screenshot('/tmp/ss-auditoria-detalle-movil.png')
        self.pulsar(navegador, By.LINK_TEXT, 'Volver al historial')
        espera.until(lambda d: urlsplit(d.current_url).path == '/sistema/auditoria/')
        self.assertIn('accion=DEACTIVATE', navegador.current_url)
        self.assertTrue(navegador.execute_script('return document.documentElement.scrollWidth<=innerWidth'))
        self.pulsar(navegador, By.CSS_SELECTOR, '.ss-aud-avanzados summary')
        self.assertFalse(navegador.find_element(By.ID, 'auditoria-accion').is_displayed())
        self.assertIn('1 activo', navegador.find_element(By.CSS_SELECTOR, '.ss-aud-avanzados summary').text)
        navegador.execute_script('document.querySelector(".ss-aud-evento").scrollIntoView({block:"start",behavior:"instant"});')
        navegador.save_screenshot('/tmp/ss-auditoria-listado-movil.png')
        pestana = navegador.current_window_handle
        self.pulsar(navegador, By.LINK_TEXT, 'Imprimir / PDF')
        espera.until(lambda d: len(d.window_handles) == 2)
        navegador.switch_to.window(next(p for p in navegador.window_handles if p != pestana))
        espera.until(EC.visibility_of_element_located((By.ID, 'auditoria-imprimir')))
        self.assertIn('1 evento', navegador.find_element(By.TAG_NAME, 'body').text)
        self.assertIn('QA-AUD Cuenta de prueba suspendida', navegador.find_element(By.TAG_NAME, 'body').text)
        self.assertNotIn('QA-AUD Consulta de empresas', navegador.find_element(By.TAG_NAME, 'body').text)
        navegador.close()
        navegador.switch_to.window(pestana)
        navegador.get(self.live_server_url + '/sistema/auditoria/?search=QA-AUD&vista=consultas')
        espera.until(EC.visibility_of_element_located((By.CSS_SELECTOR, '.ss-aud-grupo summary')))
        self.assertIn(raiz.email, navegador.find_element(By.CSS_SELECTOR, '.ss-aud-grupo summary').text)
        self.assertTrue(navegador.execute_script('return document.documentElement.scrollWidth<=innerWidth'))
        navegador.execute_script('scrollTo({top:0,behavior:"instant"});')
        navegador.save_screenshot('/tmp/ss-auditoria-filtros-movil.png')
        navegador.execute_script('arguments[0].scrollIntoView({block:"center",behavior:"instant"});',
                                 navegador.find_element(By.CSS_SELECTOR, '.ss-aud-grupo summary'))
        navegador.save_screenshot('/tmp/ss-auditoria-grupo-movil.png')


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class MarcasEmpresaEnChromeTests(StaticLiveServerTestCase):
    databases = {'central', 'ferreteria', 'repuestos'}
    pulsar = ContactoEnChromeTests.pulsar

    def comprobar_logo(self, navegador, selector, codigo):
        espera = WebDriverWait(navegador, 20)
        imagen = espera.until(EC.visibility_of_element_located((By.CSS_SELECTOR, selector)))
        espera.until(lambda d: d.execute_script('return arguments[0].complete && arguments[0].naturalWidth>0;', imagen))
        self.assertEqual(urlsplit(imagen.get_attribute('src')).path, f'/static/branding/empresas/{codigo}.png')
        self.assertTrue(navegador.execute_script("""
            const img=arguments[0], r=img.getBoundingClientRect(), padre=img.parentElement.getBoundingClientRect();
            return getComputedStyle(img).objectFit==='contain'
                && img.naturalWidth/img.naturalHeight>2 && r.width/r.height>2
                && r.left>=padre.left && r.right<=padre.right && r.top>=padre.top && r.bottom<=padre.bottom
                && getComputedStyle(img.parentElement).backgroundColor==='rgb(255, 255, 255)';
        """, imagen))
        if selector.startswith('#ss-navigation'):
            self.assertLess(imagen.find_element(By.XPATH, '..').size['height'], 110,
                            'El logo horizontal debe dejar un encabezado compacto.')
            self.assertTrue(navegador.execute_script("""
                const cerrar=document.querySelector('.ss-sidebar-close');
                return !cerrar || !cerrar.getClientRects().length
                    || arguments[0].getBoundingClientRect().right<=cerrar.getBoundingClientRect().left;
            """, imagen), 'El botón de cerrar debe quedar fuera del logo.')
        self.assertTrue(navegador.execute_script('return document.documentElement.scrollWidth<=innerWidth'))

    def test_logos_por_host_en_acceso_menu_movil_y_modo_oscuro(self):
        call_command('registrar_empresas_prueba', stdout=StringIO())
        clave = 'Fixture-marcas-2026!'
        opciones = webdriver.ChromeOptions()
        opciones.add_argument('--headless=new')
        opciones.add_argument('--window-size=1440,1000')
        navegador = webdriver.Chrome(options=opciones)
        self.addCleanup(navegador.quit)
        espera = WebDriverWait(navegador, 20)
        for codigo in ('la-fragua', 'punto-motor'):
            empresa = Empresa.objects.get(codigo=codigo)
            call_command('seed_empresa', codigo, sin_admin=True, stdout=StringIO())
            with usar_empresa(empresa):
                Usuario.objects.create_user(email='marca@example.invalid', password=clave,
                    nombres='Empresa de prueba', rol=Rol.objects.get(codigo='administrador'))
            origen = f'http://{codigo}.localhost:{urlsplit(self.live_server_url).port}'
            navegador.set_window_size(1440, 1000)
            navegador.get(origen + '/')
            self.comprobar_logo(navegador, '.ss-auth-brand-panel .ss-company-logo', codigo)
            self.assertEqual(navegador.find_element(By.CSS_SELECTOR, '.ss-auth-company').text, empresa.nombre)
            color = 'rgb(194, 65, 12)' if codigo == 'la-fragua' else 'rgb(185, 28, 28)'
            self.assertEqual(navegador.execute_script('return getComputedStyle(document.getElementById("login-submit")).backgroundColor;'), color)
            navegador.save_screenshot(f'/tmp/ss-empresa-{codigo}-acceso.png')
            navegador.set_window_size(390, 844)
            self.comprobar_logo(navegador, '.ss-auth-mobile-brand .ss-company-logo', codigo)
            self.assertTrue(navegador.find_element(By.CSS_SELECTOR, '.ss-auth-company').is_displayed())
            navegador.save_screenshot(f'/tmp/ss-empresa-{codigo}-acceso-movil.png')
            navegador.set_window_size(320, 740)
            self.assertTrue(navegador.execute_script('return document.documentElement.scrollWidth<=innerWidth'))
            self.pulsar(navegador, By.LINK_TEXT, '¿Necesitas ayuda para ingresar?')
            espera.until(EC.text_to_be_present_in_element((By.ID, 'titulo-acceso'), 'Contacta a SmartStock'))
            self.assertEqual(navegador.find_element(By.CSS_SELECTOR, '.ss-auth-company').text, empresa.nombre)
            self.assertEqual(navegador.find_element(By.CSS_SELECTOR, 'a[href^="mailto:"]').get_attribute('href'),
                             'mailto:contacto@smartstockchile.cl')
            self.pulsar(navegador, By.CSS_SELECTOR, '.ss-auth-back')
            espera.until(EC.visibility_of_element_located((By.ID, 'login-submit')))
            self.pulsar(navegador, By.LINK_TEXT, '¿Olvidaste tu contraseña?')
            espera.until(EC.visibility_of_element_located((By.ID, 'id_email')))
            self.assertEqual(navegador.find_element(By.CSS_SELECTOR, '.ss-auth-company').text, empresa.nombre)
            self.assertIn('Si está registrado, recibirás un enlace', navegador.find_element(By.CSS_SELECTOR, '.ss-auth-intro').text)
            navegador.set_window_size(1440, 1000)
            self.comprobar_logo(navegador, '.ss-auth-brand-panel .ss-company-logo', codigo)
            navegador.save_screenshot(f'/tmp/ss-empresa-{codigo}-recuperacion.png')
            navegador.set_window_size(390, 844)
            self.comprobar_logo(navegador, '.ss-auth-mobile-brand .ss-company-logo', codigo)
            navegador.save_screenshot(f'/tmp/ss-empresa-{codigo}-recuperacion-movil.png')
            navegador.find_element(By.ID, 'id_email').send_keys('sin-cuenta@ejemplo.invalid')
            self.pulsar(navegador, By.CSS_SELECTOR, '.ss-auth-form button[type="submit"]')
            espera.until(EC.text_to_be_present_in_element((By.ID, 'titulo-acceso'), 'Revisa tu correo'))
            self.assertIn('Si existe una cuenta activa asociada', navegador.find_element(By.CSS_SELECTOR, '.ss-auth-intro').text)
            self.assertEqual(navegador.find_element(By.CSS_SELECTOR, '.ss-auth-company').text, empresa.nombre)
            self.pulsar(navegador, By.LINK_TEXT, 'Volver a iniciar sesión')
            espera.until(EC.visibility_of_element_located((By.ID, 'login-submit')))
            navegador.set_window_size(1440, 1000)
            navegador.find_element(By.ID, 'email').send_keys('marca@example.invalid')
            navegador.find_element(By.ID, 'password').send_keys(clave)
            self.pulsar(navegador, By.ID, 'login-submit')
            espera.until(EC.url_contains('/dashboard/'))
            self.comprobar_logo(navegador, '#ss-navigation .ss-company-logo', codigo)
            espera.until(lambda d: d.find_element(By.ID, 'kpi-stock').text == '0')
            navegador.save_screenshot(f'/tmp/ss-empresa-{codigo}-escritorio.png')
            self.pulsar(navegador, By.CSS_SELECTOR, '.ss-theme-toggle')
            espera.until(lambda d: d.find_element(By.TAG_NAME, 'html').get_attribute('data-bs-theme') == 'dark')
            self.comprobar_logo(navegador, '#ss-navigation .ss-company-logo', codigo)
            navegador.save_screenshot(f'/tmp/ss-empresa-{codigo}-oscuro.png')
            navegador.set_window_size(390, 844)
            espera.until(lambda d: d.execute_script('return document.getElementById("ss-navigation").getBoundingClientRect().right<=1'))
            self.pulsar(navegador, By.CSS_SELECTOR, '.ss-menu-toggle')
            espera.until(lambda d: d.execute_script('return document.getElementById("ss-navigation").getBoundingClientRect().left>=0'))
            self.comprobar_logo(navegador, '#ss-navigation .ss-company-logo', codigo)
            navegador.save_screenshot(f'/tmp/ss-empresa-{codigo}-movil.png')
        navegador.set_window_size(1440, 1000)
        navegador.get(self.live_server_url + '/?empresa=la-fragua')
        self.assertFalse(navegador.find_elements(By.CSS_SELECTOR, '.ss-company-logo'))
        self.assertTrue(navegador.find_elements(By.CSS_SELECTOR, '.ss-auth-brand .ss-brand-logo'))


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class CatalogoEmpresaEnChromeTests(StaticLiveServerTestCase):
    databases = {'central', 'ferreteria', 'repuestos'}
    pulsar = ContactoEnChromeTests.pulsar

    @patch('apps.productos.views_consulta_codigos.consultar_open_food_facts')
    def test_codigo_nuevo_se_confirma_y_existente_inactivo_no_se_duplica_en_dos_empresas(self, proveedor):
        call_command('registrar_empresas_prueba', stdout=StringIO())
        opciones = webdriver.ChromeOptions()
        opciones.add_argument('--headless=new')
        opciones.add_argument('--window-size=1440,1000')
        navegador = webdriver.Chrome(options=opciones)
        self.addCleanup(navegador.quit)
        espera = WebDriverWait(navegador, 20)
        codigo_barra = '3017620422003'
        for codigo in ('la-fragua', 'punto-motor'):
            empresa = Empresa.objects.get(codigo=codigo)
            call_command('seed_empresa', codigo, sin_admin=True, stdout=StringIO())
            with usar_empresa(empresa):
                Usuario.objects.create_user(email='catalogo@example.invalid', password='Catalogo-fixture-2026!',
                    nombres='Catálogo de prueba', rol=Rol.objects.get(codigo='administrador'))
            origen = f'http://{codigo}.localhost:{urlsplit(self.live_server_url).port}'
            navegador.set_window_size(1440, 1000)
            navegador.get(origen + '/')
            navegador.find_element(By.ID, 'email').send_keys('catalogo@example.invalid')
            navegador.find_element(By.ID, 'password').send_keys('Catalogo-fixture-2026!')
            self.pulsar(navegador, By.ID, 'login-submit')
            espera.until(EC.url_contains('/dashboard/'))
            navegador.get(origen + '/productos/')
            self.pulsar(navegador, By.ID, 'btnNuevoProducto')
            espera.until(EC.visibility_of_element_located((By.ID, 'consultaCodigoProducto')))
            self.assertNotIn('Open Food Facts', navegador.find_element(By.ID, 'modalNuevoProducto').text)
            self.assertEqual(navegador.find_element(By.ID, 'buscarDatosProducto').text, 'Buscar en catálogo')
            if codigo == 'punto-motor':
                navegador.set_window_size(390, 844)
            navegador.find_element(By.ID, 'consultaCodigoProducto').send_keys(codigo_barra)
            self.pulsar(navegador, By.ID, 'buscarDatosProducto')
            espera.until(lambda d: 'no está registrado' in d.find_element(By.ID, 'estadoConsultaCodigo').text)
            self.assertFalse(Producto.objects.using(empresa.alias_bd).exists())
            self.assertEqual(navegador.find_element(By.CSS_SELECTOR, '#listaCodigosNuevo input').get_attribute('value'), codigo_barra)
            self.assertTrue(navegador.execute_script('return document.documentElement.scrollWidth<=innerWidth'))
            navegador.save_screenshot(f'/tmp/ss-catalogo-empresa-{codigo}-codigo-nuevo.png')
            for campo, valor in (('inputSku', 'HER-1'), ('inputNombre', 'Tornillo hexagonal M8'), ('inputPrecio', '150')):
                navegador.find_element(By.ID, campo).send_keys(valor)
            self.pulsar(navegador, By.ID, 'guardarNuevoProducto')
            espera.until(EC.invisibility_of_element_located((By.ID, 'modalNuevoProducto')))
            self.assertEqual(Producto.objects.using(empresa.alias_bd).count(), 1)
            Producto.objects.using(empresa.alias_bd).filter(sku='HER-1').update(activo=False)
            self.pulsar(navegador, By.ID, 'btnNuevoProducto')
            espera.until(EC.visibility_of_element_located((By.ID, 'consultaCodigoProducto'))).send_keys(codigo_barra)
            self.pulsar(navegador, By.ID, 'buscarDatosProducto')
            espera.until(EC.visibility_of_element_located((By.ID, 'verProductoEncontrado')))
            self.assertIn('Inactivo', navegador.find_element(By.ID, 'resultadoConsultaCodigo').text)
            self.assertFalse(navegador.find_element(By.ID, 'guardarNuevoProducto').is_enabled())
            navegador.save_screenshot(f'/tmp/ss-catalogo-empresa-{codigo}-existente.png')
            self.pulsar(navegador, By.ID, 'verProductoEncontrado')
            espera.until(EC.visibility_of_element_located((By.ID, 'modalDetalleProducto')))
            espera.until(lambda d: 'Tornillo hexagonal M8' in d.find_element(By.ID, 'modalDetalleProducto').text)
        proveedor.assert_not_called()
