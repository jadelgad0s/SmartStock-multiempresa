import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('empresas', '0001_initial')]

    operations = [
        migrations.CreateModel(
            name='TicketAcceso',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('usuario_id', models.PositiveBigIntegerField()),
                ('huella_clave', models.CharField(max_length=64)),
                ('origen', models.URLField(max_length=300)),
                ('fecha_expiracion', models.DateTimeField(db_index=True)),
                ('empresa', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='empresas.empresa')),
            ],
            options={'db_table': 'tickets_acceso', 'default_permissions': ()},
        ),
    ]
