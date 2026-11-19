"""Prueba de dos empresas en pestañas del mismo navegador con bases SQLite desechables."""
from io import StringIO
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
from apps.usuarios.models import Usuario
from esquema_multiempresa.models import Empresa


if (settings.SETTINGS_MODULE != 'esquema_multiempresa.testing'
        or settings.DATABASES['central']['ENGINE'] != 'django.db.backends.sqlite3'):
    raise RuntimeError('Ejecuta esta suite con esquema_multiempresa.testing y SS_TEST_POSTGRES desactivado.')


class DosEmpresasEnChromeTests(StaticLiveServerTestCase):
    databases = {'central', 'ferreteria', 'repuestos'}

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
        navegador.find_element(By.LINK_TEXT, 'Cuentas técnicas').click()
        navegador.find_element(By.LINK_TEXT, 'Añadir cuenta técnica').click()
        for campo, valor in (('nombres', 'Soporte'), ('apellidos', 'QA'), ('email', 'soporte-qa@example.invalid'),
                             ('password1', 'Cuenta-soporte-fixture-2626!'), ('password2', 'Cuenta-soporte-fixture-2626!')):
            navegador.find_element(By.ID, 'id_' + campo).send_keys(valor)
        Select(navegador.find_element(By.ID, 'id_perfil')).select_by_value('tecnico')
        navegador.find_element(By.CSS_SELECTOR, 'form.ss-sistema-formulario button[type="submit"]').click()
        espera.until(lambda d: urlsplit(d.current_url).path == '/sistema/cuentas/')
        self.assertIn('soporte-qa@example.invalid', navegador.find_element(By.TAG_NAME, 'body').text)
        navegador.find_element(By.CSS_SELECTOR, 'button[form="ss-cerrar-sesion"]').click()
        espera.until(EC.visibility_of_element_located((By.ID, 'email')))
        navegador.find_element(By.ID, 'email').send_keys('soporte-qa@example.invalid')
        navegador.find_element(By.ID, 'password').send_keys('Cuenta-soporte-fixture-2626!')
        navegador.find_element(By.ID, 'login-submit').click()
        espera.until(EC.url_contains('/sistema/'))
        self.assertFalse(navegador.find_elements(By.CSS_SELECTOR, 'a[href="/sistema/configuracion/"]'))
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
