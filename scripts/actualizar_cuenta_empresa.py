"""Recuperación de una cuenta administradora mediante una conexión de empresa.

La URL y la contraseña se solicitan de forma oculta. Este proceso independiente
no carga el perfil web ni modifica archivos de entorno o variables de Render.
"""
from __future__ import annotations

import argparse
import copy
from getpass import getpass
import os
from pathlib import Path
import secrets
import sys
from urllib.parse import parse_qs, urlsplit

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

SERVIDOR_PRODUCCION = "ep-blue-rain-b58nn17d.c-7.us-east-2.aws.neon.tech"
EMPRESAS = {
    "la-fragua": ("Ferretería La Fragua", "ferreteria_la_fragua", "SS_FERRETERIA_DATABASE_URL"),
    "punto-motor": ("Repuestos Punto Motor", "repuestos_punto_motor", "SS_REPUESTOS_DATABASE_URL"),
}


class ErrorRecuperacion(ValueError):
    pass


def validar_conexion(url: str, empresa: str) -> dict:
    """Restringe el destino a la base y rama de producción seleccionadas."""
    import dj_database_url

    try:
        partes = urlsplit(url.strip())
        parametros = parse_qs(partes.query, keep_blank_values=True)
        valido = (
            partes.scheme in {"postgres", "postgresql"}
            and partes.hostname == SERVIDOR_PRODUCCION
            and partes.port in {None, 5432}
            and partes.username and partes.password
            and not partes.fragment
            and set(parametros) <= {"sslmode", "channel_binding"}
            and all(len(valores) == 1 for valores in parametros.values())
            and parametros.get("sslmode", [None])[0] in {"require", "verify-ca", "verify-full"}
        )
        if not valido:
            raise ValueError
        cfg = dj_database_url.parse(url.strip(), conn_max_age=0)
        if cfg["NAME"] != EMPRESAS[empresa][1]:
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise ErrorRecuperacion(
            "La conexión debe ser la URL directa con SSL de esta empresa en "
            "produccion-multiempresa. Cópiala de Environment en el servicio publicado."
        ) from None
    cfg["OPTIONS"]["connect_timeout"] = 15
    return cfg


def configurar_django(database: dict) -> None:
    """Inicia solo los modelos necesarios con la política real de contraseñas."""
    import django
    from django.conf import global_settings, settings

    if settings.configured:
        raise ErrorRecuperacion("Ejecuta el archivo desde una terminal nueva de CMD.")
    clave_temporal = secrets.token_urlsafe(64)
    os.environ.setdefault("SECRET_KEY", clave_temporal)
    from config.settings import base

    settings.configure(
        SECRET_KEY=clave_temporal,
        INSTALLED_APPS=[
            "django.contrib.auth", "django.contrib.contenttypes", "apps.core", "apps.usuarios",
        ],
        AUTH_USER_MODEL=base.AUTH_USER_MODEL,
        AUTH_PASSWORD_VALIDATORS=copy.deepcopy(base.AUTH_PASSWORD_VALIDATORS),
        PASSWORD_HASHERS=getattr(base, "PASSWORD_HASHERS", global_settings.PASSWORD_HASHERS),
        DATABASES={"default": database},
        DATABASE_ROUTERS=[],
        USE_TZ=base.USE_TZ,
        TIME_ZONE=base.TIME_ZONE,
        LANGUAGE_CODE=base.LANGUAGE_CODE,
        DEFAULT_AUTO_FIELD=base.DEFAULT_AUTO_FIELD,
    )
    django.setup()


def comprobar_administrador(usuario) -> None:
    if not usuario.activo:
        raise ErrorRecuperacion("La cuenta está desactivada; este comando conserva su estado.")
    if not usuario.is_superuser and not (
        usuario.rol_id and usuario.rol.activo and usuario.rol.codigo == "administrador"
    ):
        raise ErrorRecuperacion("La cuenta seleccionada no es una administradora activa.")


def actualizar_cuenta(*, empresa, usuario_actual, nombres, apellidos, correo, clave, confirmacion):
    from django.contrib.auth.password_validation import validate_password
    from django.core.validators import validate_email
    from django.db import transaction
    from apps.core.models import Auditoria
    from apps.usuarios.models import Usuario

    nombres, apellidos, correo = nombres.strip(), apellidos.strip(), correo.strip().lower()
    if not nombres or not apellidos or len(nombres) > 100 or len(apellidos) > 100:
        raise ErrorRecuperacion("Nombres y apellidos requieren entre 1 y 100 caracteres.")
    if len(correo) > 254:
        raise ErrorRecuperacion("El correo es demasiado largo.")
    validate_email(correo)
    if clave != confirmacion:
        raise ErrorRecuperacion("Las contraseñas no coinciden. Vuelve a ejecutar el comando.")

    try:
        usuario = Usuario.objects.using("default").select_related("rol").get(email__iexact=usuario_actual)
    except Usuario.DoesNotExist:
        raise ErrorRecuperacion("No se encontró la cuenta con el correo actual indicado.") from None
    comprobar_administrador(usuario)
    usuario.nombres, usuario.apellidos, usuario.email = nombres, apellidos, correo
    validate_password(clave, user=usuario)

    with transaction.atomic(using="default"):
        actual = Usuario.objects.using("default").select_for_update(of=("self",)).get(
            pk=usuario.pk, email__iexact=usuario_actual,
        )
        comprobar_administrador(actual)
        if Usuario.objects.using("default").filter(email__iexact=correo).exclude(pk=actual.pk).exists():
            raise ErrorRecuperacion("El correo nuevo ya pertenece a otra cuenta de esta empresa.")
        cambios = {
            campo: {"antes": getattr(actual, campo), "despues": valor}
            for campo, valor in (("nombres", nombres), ("apellidos", apellidos), ("email", correo))
        }
        cambios["clave_actualizada"] = True
        actual.nombres, actual.apellidos, actual.email = nombres, apellidos, correo
        actual.set_password(clave)
        actual.intentos_fallidos = 0
        actual.bloqueado_hasta = None
        actual.save(using="default", update_fields=[
            "nombres", "apellidos", "email", "password", "intentos_fallidos",
            "bloqueado_hasta", "fecha_modificacion",
        ])
        Auditoria.objects.using("default").create(
            accion="UPDATE", modelo="Usuario", objeto_id=str(actual.pk),
            descripcion="Recuperación administrativa de cuenta desde consola.",
            actor={"nombre": "Mantenimiento por consola"},
            empresa_codigo=empresa, empresa_nombre=EMPRESAS[empresa][0],
            modulo="usuarios", operacion="actualizar_cuenta_consola",
            resultado="completada", cambios=cambios,
        )
    return actual.email


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--empresa", choices=EMPRESAS, required=True)
    parser.add_argument("--usuario", required=True, help="Correo actual de la cuenta administradora.")
    parser.add_argument("--nombres", required=True)
    parser.add_argument("--apellidos", required=True)
    parser.add_argument("--correo", required=True, help="Correo nuevo de la cuenta.")
    args = parser.parse_args(argv)
    try:
        if not sys.stdin.isatty():
            raise ErrorRecuperacion("Ejecuta el comando en una terminal interactiva de CMD.")
        print(f"Destino: {EMPRESAS[args.empresa][0]} / produccion-multiempresa.")
        cfg = validar_conexion(getpass(f"Pega {EMPRESAS[args.empresa][2]} (entrada oculta): "), args.empresa)
        configurar_django(cfg)
        from django.db import connections

        try:
            correo = actualizar_cuenta(
                empresa=args.empresa, usuario_actual=args.usuario,
                nombres=args.nombres, apellidos=args.apellidos, correo=args.correo,
                clave=getpass("Contraseña nueva: "), confirmacion=getpass("Repite la contraseña: "),
            )
        finally:
            connections.close_all()
        print(f"Cuenta actualizada correctamente. Correo de acceso: {correo}")
        return 0
    except ErrorRecuperacion as exc:
        print(f"Error: {exc}", file=sys.stderr)
    except KeyboardInterrupt:
        print("\nOperación interrumpida.", file=sys.stderr)
    except ImportError:
        print("Faltan dependencias. Ejecuta: python -m pip install -r requirements-web.txt", file=sys.stderr)
    except Exception as exc:
        from django.core.exceptions import ValidationError

        if isinstance(exc, ValidationError):
            print("Error: " + " ".join(exc.messages), file=sys.stderr)
        else:
            print(
                f"No se pudo completar la recuperación ({type(exc).__name__}). "
                "Comprueba la conexión y el correo actual. Los detalles privados se omiten.",
                file=sys.stderr,
            )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
