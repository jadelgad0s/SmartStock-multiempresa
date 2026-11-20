"""Prueba de dos empresas en pestañas del mismo navegador con bases SQLite desechables."""
import atexit
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.management import call_command
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support.ui import Select

from apps.core.empresa import usar_empresa
from apps.productos.models import Bodega, Producto, StockBodega
from apps.core.models import Auditoria
from apps.usuarios.models import Usuario
from esquema_multiempresa.models import Empresa
from esquema_multiempresa.permisos import ADMINISTRADOR_PLATAFORMA, SOPORTE_TECNICO


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
        navegador.switch_to.new_window('tab')
        navegador.get(self.live_server_url)
        navegador.find_element(By.ID, 'email').send_keys('tecnico@example.invalid')
        navegador.find_element(By.ID, 'password').send_keys('Tecnico-clave-de-fixture')
        navegador.find_element(By.ID, 'login-submit').click()
        espera.until(EC.url_contains('/sistema/'))
        self.assertIn('Administración de SmartStock', navegador.find_element(By.TAG_NAME, 'body').text)
        self.assertTrue(navegador.find_elements(By.CSS_SELECTOR, 'a[href="/sistema/configuracion/"]'))
        self.comprobar_menu(navegador)
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
        for campo, valor in (('nombres', 'Operador'), ('apellidos', 'QA'), ('email', 'operador-qa@example.invalid'),
                             ('password1', 'Cuenta-operador-fixture-2626!'), ('password2', 'Cuenta-operador-fixture-2626!')):
            navegador.find_element(By.ID, 'id_' + campo).send_keys(valor)
        Select(navegador.find_element(By.ID, 'id_rol')).select_by_visible_text('Operador')
        navegador.find_element(By.CSS_SELECTOR, 'form.ss-sistema-formulario button[type="submit"]').click()
        espera.until(lambda d: urlsplit(d.current_url).path == '/sistema/usuarios/')
        self.assertTrue(Usuario.objects.using('ferreteria').filter(email='operador-qa@example.invalid').exists())
        self.assertFalse(Usuario.objects.using('repuestos').filter(email='operador-qa@example.invalid').exists())
        navegador.get(self.live_server_url + '/sistema/inventario/?empresa=la-fragua')
        self.assertEqual(navegador.find_element(By.ID, 'sistema-kpi-stock').text, '15')
        navegador.set_window_size(390, 844)
        navegador.get(self.live_server_url + '/sistema/')
        navegador.find_element(By.CSS_SELECTOR, '.ss-menu-toggle').click()
        espera.until(lambda d: 'ss-sidebar-open' in d.find_element(By.ID, 'ss-navigation').get_attribute('class'))
        self.assertTrue(navegador.execute_script('return document.documentElement.scrollWidth <= window.innerWidth'))
        self.comprobar_menu(navegador)
        navegador.find_element(By.CSS_SELECTOR, 'a.ss-sistema-perfil').click()
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
        guardar.click()
        espera.until(lambda d: urlsplit(d.current_url).path == '/sistema/empresas/la-fragua/')
        self.assertIn('12345678-5', navegador.find_element(By.TAG_NAME, 'body').text)
        self.assertIn('contacto@example.invalid', navegador.find_element(By.TAG_NAME, 'body').text)
        self.assertIn('César Andrés', navegador.find_element(By.TAG_NAME, 'body').text)
        self.assertIn('Guzmán Pérez', navegador.find_element(By.TAG_NAME, 'body').text)
        self.assertTrue(navegador.execute_script('return document.documentElement.scrollWidth <= window.innerWidth'))
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
