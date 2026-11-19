from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Empresa',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('codigo', models.SlugField(max_length=60, unique=True)),
                ('nombre', models.CharField(max_length=160)),
                ('alias_bd', models.SlugField(max_length=64, unique=True)),
                ('activa', models.BooleanField(default=True)),
            ],
            options={
                'db_table': 'empresas',
                'default_permissions': (),
            },
        ),
    ]
