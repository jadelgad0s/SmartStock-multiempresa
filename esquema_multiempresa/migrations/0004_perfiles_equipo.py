from django.db import migrations
from django.utils import timezone


def preparar_perfiles(apps, schema_editor):
    if schema_editor.connection.alias != 'central':
        return
    Rol = apps.get_model('usuarios', 'Rol')
    Usuario = apps.get_model('usuarios', 'Usuario')
    Auditoria = apps.get_model('core', 'Auditoria')
    administrador, _ = Rol.objects.using('central').get_or_create(
        codigo='administrador_plataforma',
        defaults={'nombre': 'Administrador de plataforma', 'activo': True, 'es_sistema': True,
                  'descripcion': 'Gestiona empresas y sus usuarios desde el panel de SmartStock.'},
    )
    Rol.objects.using('central').get_or_create(
        codigo='soporte_tecnico',
        defaults={'nombre': 'Soporte técnico', 'activo': True, 'es_sistema': True,
                  'descripcion': 'Consulta la información de las empresas para atender incidencias.'},
    )
    # El perfil anterior tenía funciones de gestión de clientes. Se preserva
    # ese acceso en las cuentas existentes, con el nuevo límite del equipo.
    anteriores = Usuario.objects.using('central').filter(
        is_staff=True, is_superuser=False, rol__isnull=True,
    )
    identificadores = list(anteriores.values_list('pk', flat=True))
    anteriores.update(rol_id=administrador.pk, fecha_modificacion=timezone.now())
    Auditoria.objects.using('central').bulk_create([
        Auditoria(accion='UPDATE', modelo='Usuario', objeto_id=str(pk),
                  descripcion='SmartStock · Actualización de perfiles internos · Administrador de plataforma asignado a cuenta técnica existente.')
        for pk in identificadores
    ])


class Migration(migrations.Migration):
    dependencies = [
        ('empresas', '0003_ficha_empresa'),
        ('usuarios', '0002_alter_permiso_options_alter_rol_options_and_more'),
        ('core', '0005_consultas_empresa'),
    ]
    operations = [migrations.RunPython(preparar_perfiles, migrations.RunPython.noop)]
