from django.db import models


class Empresa(models.Model):
    codigo = models.SlugField(max_length=60, unique=True)
    nombre = models.CharField(max_length=160)
    alias_bd = models.SlugField(max_length=64, unique=True)
    activa = models.BooleanField(default=True)

    class Meta:
        db_table = 'empresas'
        default_permissions = ()

    def __str__(self):
        return self.nombre
