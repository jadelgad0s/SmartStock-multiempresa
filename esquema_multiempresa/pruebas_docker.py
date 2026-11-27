from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TransactionTestCase, override_settings

from apps.core.empresa import usar_empresa
from apps.productos.models import Producto
from apps.usuarios.models import Rol, Usuario
from .models import Empresa


class ProteccionPreparacionDockerTests(SimpleTestCase):
    @override_settings(DOCKER_LOCAL_DEMO=False)
    def test_el_comando_exige_el_perfil_docker_antes_de_modificar_bases(self):
        with self.assertRaisesMessage(CommandError, 'esquema_multiempresa.docker'):
            call_command('preparar_docker')


@override_settings(DOCKER_LOCAL_DEMO=True, PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class PreparacionDockerTests(TransactionTestCase):
    databases = {'central', 'ferreteria', 'repuestos'}

    def preparar(self):
        with patch.dict('os.environ', {'SS_DOCKER_DEMO_PASSWORD': 'Clave-demo-aislada-2026'}):
            call_command('preparar_docker', stdout=StringIO())

    def test_prepara_las_tres_cuentas_y_las_empresas_con_sus_perfiles(self):
        self.preparar()
        tecnico = Usuario.objects.using('central').get(email='tecnico@smartstock.test')
        self.assertTrue(tecnico.is_superuser and tecnico.is_staff)
        self.assertTrue(tecnico.check_password('Clave-demo-aislada-2026'))
        for codigo, email in (('la-fragua', 'admin.lafragua@smartstock.test'),
                              ('punto-motor', 'admin.puntomotor@smartstock.test')):
            empresa = Empresa.objects.using('central').get(codigo=codigo)
            with usar_empresa(empresa):
                cuenta = Usuario.objects.get(email=email)
                self.assertEqual(cuenta.rol.codigo, 'administrador')
                self.assertFalse(cuenta.is_superuser or cuenta.is_staff)
                self.assertTrue(cuenta.check_password('Clave-demo-aislada-2026'))

    def test_reiniciar_preserva_cuentas_modificadas_permisos_y_productos(self):
        self.preparar()
        empresa = Empresa.objects.using('central').get(codigo='la-fragua')
        with usar_empresa(empresa):
            cuenta = Usuario.objects.get(email='admin.lafragua@smartstock.test')
            cuenta.set_password('Otra-clave-local')
            cuenta.save(update_fields=['password'])
            rol = Rol.objects.get(codigo='administrador')
            rol.permisos.remove(rol.permisos.first())
            permisos = set(rol.permisos.values_list('pk', flat=True))
            Producto.objects.create(sku='CONSERVAR', nombre='Producto conservado')
        self.preparar()
        with usar_empresa(empresa):
            cuenta.refresh_from_db()
            self.assertTrue(cuenta.check_password('Otra-clave-local'))
            self.assertEqual(Usuario.objects.count(), 1)
            self.assertEqual(set(rol.permisos.values_list('pk', flat=True)), permisos)
            self.assertEqual(Producto.objects.get(sku='CONSERVAR').nombre, 'Producto conservado')
