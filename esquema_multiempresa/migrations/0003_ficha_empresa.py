import django.utils.timezone
from django.db import migrations, models

import esquema_multiempresa.validadores


class Migration(migrations.Migration):
    dependencies = [('empresas', '0002_ticket_acceso')]

    operations = [
        migrations.AddField(model_name='empresa', name='razon_social', field=models.CharField(blank=True, max_length=200, verbose_name='razón social o nombre del titular')),
        migrations.AddField(model_name='empresa', name='rut', field=models.CharField(blank=True, max_length=12, validators=[esquema_multiempresa.validadores.validar_rut], verbose_name='RUT del cliente')),
        migrations.AddField(model_name='empresa', name='rubro', field=models.CharField(blank=True, choices=[('ferreteria', 'Ferretería'), ('repuestos', 'Repuestos'), ('otro', 'Otra pyme')], max_length=20)),
        migrations.AddField(model_name='empresa', name='contacto_nombre', field=models.CharField(blank=True, max_length=160, verbose_name='contacto principal')),
        migrations.AddField(model_name='empresa', name='contacto_email', field=models.EmailField(blank=True, max_length=254, verbose_name='correo de contacto')),
        migrations.AddField(model_name='empresa', name='contacto_telefono', field=models.CharField(blank=True, max_length=30, verbose_name='teléfono de contacto')),
        migrations.AddField(model_name='empresa', name='direccion', field=models.CharField(blank=True, max_length=250, verbose_name='dirección')),
        migrations.AddField(model_name='empresa', name='comuna', field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name='empresa', name='region', field=models.CharField(blank=True, max_length=100, verbose_name='región')),
        # Las fechas históricas se mantienen desconocidas. El valor automático
        # se aplica a las altas posteriores a esta migración.
        migrations.AddField(model_name='empresa', name='creada_en', field=models.DateTimeField(editable=False, null=True)),
        migrations.AlterField(model_name='empresa', name='creada_en', field=models.DateTimeField(default=django.utils.timezone.now, editable=False, null=True)),
        migrations.AddField(model_name='empresa', name='actualizada_en', field=models.DateTimeField(editable=False, null=True)),
        migrations.AlterField(model_name='empresa', name='actualizada_en', field=models.DateTimeField(auto_now=True, null=True)),
        migrations.AddConstraint(model_name='empresa', constraint=models.UniqueConstraint(condition=~models.Q(rut=''), fields=('rut',), name='empresa_rut_unico')),
    ]
