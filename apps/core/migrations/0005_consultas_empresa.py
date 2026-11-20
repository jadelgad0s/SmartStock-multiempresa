from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0004_acciones_desactivacion_reactivacion')]

    operations = [
        migrations.AlterField(
            model_name='auditoria', name='accion',
            field=models.CharField(max_length=20, choices=[
                ('CREATE', 'Creación'), ('UPDATE', 'Modificación'),
                ('DEACTIVATE', 'Desactivación'), ('REACTIVATE', 'Reactivación'),
                ('DELETE', 'Eliminación definitiva'), ('LOGIN', 'Inicio de sesión'),
                ('LOGOUT', 'Cierre de sesión'), ('LOGIN_FAILED', 'Intento fallido de login'),
                ('CONSULTA', 'Consulta de empresa'),
            ]),
        ),
    ]
