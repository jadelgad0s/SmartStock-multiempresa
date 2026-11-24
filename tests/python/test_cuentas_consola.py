"""Pruebas aisladas: nunca conectan a Neon ni reciben credenciales reales."""
import contextlib
import io
import unittest
from unittest import mock

from scripts import actualizar_cuenta_empresa as cli


def url_prueba(base="repuestos_punto_motor", extra="sslmode=require"):
    return f"postgresql://fixture:clave-de-fixture@{cli.SERVIDOR_PRODUCCION}/{base}?{extra}"


class ConexionTests(unittest.TestCase):
    def test_acepta_destino_exacto_y_conserva_verificacion_tls(self):
        cfg = cli.validar_conexion(url_prueba(extra="sslmode=verify-full"), "punto-motor")
        self.assertEqual(cfg["NAME"], "repuestos_punto_motor")
        self.assertEqual(cfg["OPTIONS"]["sslmode"], "verify-full")

    def test_rechaza_otra_empresa(self):
        with self.assertRaises(cli.ErrorRecuperacion):
            cli.validar_conexion(url_prueba("ferreteria_la_fragua"), "punto-motor")

    def test_rechaza_otra_rama_y_pooler(self):
        for host in ("otra-rama.neon.tech", cli.SERVIDOR_PRODUCCION.replace(".c-7", "-pooler.c-7")):
            with self.subTest(host=host), self.assertRaises(cli.ErrorRecuperacion):
                cli.validar_conexion(url_prueba().replace(cli.SERVIDOR_PRODUCCION, host), "punto-motor")

    def test_rechaza_opciones_que_podrian_cambiar_el_destino(self):
        for extra in ("sslmode=require&host=otro", "sslmode=require&service=otro", "sslmode=require&options=x"):
            with self.subTest(extra=extra), self.assertRaises(cli.ErrorRecuperacion):
                cli.validar_conexion(url_prueba(extra=extra), "punto-motor")

    def test_rechaza_tls_inseguro_duplicado_o_ausente(self):
        for extra in ("", "sslmode=disable", "sslmode=require&sslmode=disable"):
            with self.subTest(extra=extra), self.assertRaises(cli.ErrorRecuperacion):
                cli.validar_conexion(url_prueba(extra=extra), "punto-motor")

    def test_errores_no_incluyen_url_ni_clave(self):
        with self.assertRaises(cli.ErrorRecuperacion) as ctx:
            cli.validar_conexion(url_prueba().replace(cli.SERVIDOR_PRODUCCION, "localhost"), "punto-motor")
        self.assertNotIn("clave-de-fixture", str(ctx.exception))
        self.assertNotIn("postgresql://", str(ctx.exception))

    def test_error_inesperado_del_cli_no_expone_secretos(self):
        salida = io.StringIO()
        args = ["--empresa", "punto-motor", "--usuario", "actual@example.test",
                "--nombres", "Nombre", "--apellidos", "Apellido", "--correo", "nuevo@example.test"]
        with mock.patch.object(cli.sys.stdin, "isatty", return_value=True), \
                mock.patch.object(cli, "getpass", return_value=url_prueba()), \
                mock.patch.object(cli, "configurar_django", side_effect=RuntimeError(url_prueba())), \
                contextlib.redirect_stderr(salida), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(args), 1)
        self.assertNotIn("clave-de-fixture", salida.getvalue())
        self.assertNotIn("postgresql://", salida.getvalue())


class CuentaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cli.configurar_django({"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"})
        from django.apps import apps
        from django.db import connection
        from apps.usuarios.models import Rol, Usuario
        from apps.core.models import Auditoria

        cls.Rol, cls.Usuario, cls.Auditoria = Rol, Usuario, Auditoria
        with connection.schema_editor() as editor:
            for modelo in apps.get_models():
                editor.create_model(modelo)

    def setUp(self):
        self.Usuario.objects.all().delete()
        self.Auditoria.objects.all().delete()
        self.Rol.objects.all().delete()
        self.rol = self.Rol.objects.create(nombre="Administrador", codigo="administrador")
        self.usuario = self.Usuario.objects.create_user(
            "actual@example.test", "Anterior-fixture-8742!", nombres="Original", apellidos="Original",
            rol=self.rol, telefono="telefono-conservado", is_staff=False,
        )
        self.datos = dict(empresa="punto-motor", usuario_actual="actual@example.test",
                          nombres="Nombre Nuevo", apellidos="Apellido Nuevo", correo="nuevo@example.test",
                          clave="Clave-fixture-nueva-5931!", confirmacion="Clave-fixture-nueva-5931!")
        self.hash_original = self.usuario.password

    def comprobar_original(self):
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.email, "actual@example.test")
        self.assertEqual(self.usuario.nombres, "Original")
        self.assertEqual(self.usuario.password, self.hash_original)
        self.assertEqual(self.Auditoria.objects.count(), 0)

    def test_actualiza_datos_hash_y_auditoria_conservando_permisos(self):
        from datetime import timedelta
        from django.utils import timezone

        self.usuario.intentos_fallidos = 5
        self.usuario.bloqueado_hasta = timezone.now() + timedelta(minutes=15)
        self.usuario.save(update_fields=["intentos_fallidos", "bloqueado_hasta"])
        cli.actualizar_cuenta(**self.datos)
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.email, "nuevo@example.test")
        self.assertEqual(self.usuario.nombres, "Nombre Nuevo")
        self.assertEqual(self.usuario.apellidos, "Apellido Nuevo")
        self.assertTrue(self.usuario.check_password(self.datos["clave"]))
        self.assertEqual(self.usuario.rol_id, self.rol.pk)
        self.assertFalse(self.usuario.is_staff)
        self.assertFalse(self.usuario.is_superuser)
        self.assertTrue(self.usuario.activo)
        self.assertEqual(self.usuario.telefono, "telefono-conservado")
        self.assertEqual(self.usuario.intentos_fallidos, 0)
        self.assertIsNone(self.usuario.bloqueado_hasta)
        self.assertIsNone(self.usuario.ultimo_login)
        evento = self.Auditoria.objects.get()
        self.assertEqual(evento.empresa_codigo, "punto-motor")
        self.assertNotIn(self.datos["clave"], str(evento.cambios))
        self.assertNotIn(self.usuario.password, str(evento.cambios))

    def test_cli_completo_no_imprime_la_url_ni_la_contrasena(self):
        args = ["--empresa", "punto-motor", "--usuario", self.datos["usuario_actual"],
                "--nombres", self.datos["nombres"], "--apellidos", self.datos["apellidos"],
                "--correo", self.datos["correo"]]
        salida, errores = io.StringIO(), io.StringIO()
        with mock.patch.object(cli.sys.stdin, "isatty", return_value=True), \
                mock.patch.object(cli, "getpass", side_effect=[url_prueba(), self.datos["clave"], self.datos["clave"]]), \
                mock.patch.object(cli, "configurar_django"), \
                contextlib.redirect_stdout(salida), contextlib.redirect_stderr(errores):
            self.assertEqual(cli.main(args), 0)
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.email, self.datos["correo"])
        self.assertTrue(self.usuario.check_password(self.datos["clave"]))
        self.assertNotIn(self.datos["clave"], salida.getvalue() + errores.getvalue())
        self.assertNotIn("postgresql://", salida.getvalue() + errores.getvalue())

    def test_confirmacion_distinta_no_modifica_la_cuenta(self):
        self.datos["confirmacion"] = "Otra-clave"
        with self.assertRaises(cli.ErrorRecuperacion):
            cli.actualizar_cuenta(**self.datos)
        self.comprobar_original()

    def test_aplica_validacion_real_de_contrasenas(self):
        from django.core.exceptions import ValidationError

        self.datos["clave"] = self.datos["confirmacion"] = "12345678"
        with self.assertRaises(ValidationError):
            cli.actualizar_cuenta(**self.datos)
        self.comprobar_original()

    def test_correo_duplicado_no_modifica_la_cuenta(self):
        self.Usuario.objects.create_user("nuevo@example.test", "Otra-fixture-8761!", rol=self.rol)
        with self.assertRaises(cli.ErrorRecuperacion):
            cli.actualizar_cuenta(**self.datos)
        self.comprobar_original()

    def test_error_en_auditoria_revierte_todos_los_cambios(self):
        from django.db import DatabaseError
        from django.db.models.query import QuerySet

        original = QuerySet.create

        def crear(queryset, **kwargs):
            if queryset.model is self.Auditoria:
                raise DatabaseError("Fallo simulado de auditoría")
            return original(queryset, **kwargs)

        with mock.patch.object(QuerySet, "create", new=crear), self.assertRaises(DatabaseError):
            cli.actualizar_cuenta(**self.datos)
        self.comprobar_original()

    def test_conserva_desactivacion_y_rechaza_operadores(self):
        self.usuario.activo = False
        self.usuario.save(update_fields=["activo"])
        with self.assertRaises(cli.ErrorRecuperacion):
            cli.actualizar_cuenta(**self.datos)
        self.usuario.activo = True
        self.usuario.rol = self.Rol.objects.create(nombre="Operador", codigo="operador")
        self.usuario.save(update_fields=["activo", "rol"])
        with self.assertRaises(cli.ErrorRecuperacion):
            cli.actualizar_cuenta(**self.datos)
        self.comprobar_original()


if __name__ == "__main__":
    unittest.main()
