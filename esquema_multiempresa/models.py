from uuid import uuid4

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


class TicketAcceso(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    usuario_id = models.PositiveBigIntegerField()
    huella_clave = models.CharField(max_length=64)
    origen = models.URLField(max_length=300)
    fecha_expiracion = models.DateTimeField(db_index=True)

    class Meta:
        db_table = 'tickets_acceso'
        default_permissions = ()
