from django.db import models

class TimestampedModel(models.Model):
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_modificacion = models.DateTimeField(auto_now=True)
    class Meta: abstract = True

class SoftDeleteModel(TimestampedModel):
    activo = models.BooleanField(default=True)
    class Meta: abstract = True
    def desactivar(self):
        self.activo = False
        self.save(update_fields=['activo', 'fecha_modificacion'])
    def activar(self):
        self.activo = True
        self.save(update_fields=['activo', 'fecha_modificacion'])

class Auditoria(TimestampedModel):
    ACCION_CHOICES = [
        ('CREATE', 'Creación'), ('UPDATE', 'Modificación'),
        ('DEACTIVATE', 'Desactivación'), ('REACTIVATE', 'Reactivación'),
        ('DELETE', 'Eliminación definitiva'), ('LOGIN', 'Inicio de sesión'),
        ('LOGOUT', 'Cierre de sesión'), ('LOGIN_FAILED', 'Intento fallido de login'),
        ('CONSULTA', 'Consulta de empresa'),
        ('ACCESS_DENIED', 'Acceso denegado'), ('EXPORT', 'Exportación'),
    ]
    usuario = models.ForeignKey('usuarios.Usuario', on_delete=models.SET_NULL, null=True, blank=True, related_name='acciones_auditoria')
    accion = models.CharField(max_length=20, choices=ACCION_CHOICES)
    modelo = models.CharField(max_length=100)
    objeto_id = models.CharField(max_length=50, blank=True)
    descripcion = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    # Instantáneas del momento del evento; el historial anterior queda vacío.
    actor = models.JSONField(default=dict, blank=True)
    empresa_codigo = models.CharField(max_length=100, blank=True, db_index=True)
    empresa_nombre = models.CharField(max_length=200, blank=True)
    atencion_id = models.UUIDField(null=True, blank=True, db_index=True)
    modulo = models.CharField(max_length=100, blank=True)
    operacion = models.CharField(max_length=120, blank=True)
    resultado = models.CharField(max_length=15, blank=True, choices=[
        ('solicitada', 'Solicitada'), ('completada', 'Completada'),
        ('denegada', 'Denegada'), ('fallida', 'Fallida'),
    ])
    cambios = models.JSONField(default=dict, blank=True)
    class Meta:
        db_table = 'auditoria'
        indexes = [
            models.Index(fields=['-fecha_creacion', '-id'], name='audit_fecha_id_idx'),
            models.Index(fields=['accion', '-fecha_creacion'], name='audit_accion_fecha_idx'),
        ]

