from uuid import uuid4

from django.db import models
from django.utils import timezone

from .validadores import normalizar_rut, validar_rut


class Empresa(models.Model):
    RUBROS = [('ferreteria', 'Ferretería'), ('repuestos', 'Repuestos'), ('otro', 'Otra pyme')]

    codigo = models.SlugField(max_length=60, unique=True)
    nombre = models.CharField(max_length=160)
    razon_social = models.CharField('razón social o nombre del titular', max_length=200, blank=True)
    rut = models.CharField('RUT del cliente', max_length=12, blank=True, validators=[validar_rut])
    rubro = models.CharField(max_length=20, blank=True, choices=RUBROS)
    contacto_nombre = models.CharField('contacto principal', max_length=160, blank=True)
    contacto_email = models.EmailField('correo de contacto', max_length=254, blank=True)
    contacto_telefono = models.CharField('teléfono de contacto', max_length=30, blank=True)
    direccion = models.CharField('dirección', max_length=250, blank=True)
    comuna = models.CharField(max_length=100, blank=True)
    region = models.CharField('región', max_length=100, blank=True)
    alias_bd = models.SlugField(max_length=64, unique=True)
    activa = models.BooleanField(default=True)
    creada_en = models.DateTimeField(default=timezone.now, null=True, editable=False)
    actualizada_en = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        db_table = 'empresas'
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=['rut'], condition=~models.Q(rut=''), name='empresa_rut_unico')]

    def clean(self):
        super().clean()
        self.rut = normalizar_rut(self.rut)

    def save(self, *args, **kwargs):
        self.rut = normalizar_rut(self.rut)
        return super().save(*args, **kwargs)

    @property
    def datos_pendientes(self):
        campos = [('razon_social', 'razón social o titular'), ('rut', 'RUT'), ('rubro', 'rubro'),
                  ('contacto_nombre', 'contacto principal'), ('contacto_email', 'correo de contacto')]
        return [etiqueta for campo, etiqueta in campos if not getattr(self, campo)]

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
