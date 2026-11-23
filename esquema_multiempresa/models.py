from uuid import uuid4

from django.db import models
from django.utils import timezone

from .validadores import normalizar_rut, validar_rut
from .borrado import anular_central, cascada_central


class Empresa(models.Model):
    RUBROS = [('ferreteria', 'Ferretería'), ('repuestos', 'Repuestos'), ('otro', 'Otra pyme')]

    codigo = models.SlugField(max_length=60, unique=True)
    nombre = models.CharField(max_length=160)
    razon_social = models.CharField('razón social o nombre del titular', max_length=200, blank=True)
    rut = models.CharField('RUT del cliente', max_length=12, blank=True, validators=[validar_rut])
    rubro = models.CharField(max_length=20, blank=True, choices=RUBROS)
    contacto_nombre = models.CharField('nombre(s) del contacto', max_length=160, blank=True)
    contacto_apellidos = models.CharField('apellido(s) del contacto', max_length=160, blank=True)
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
    def logo_estatico(self):
        # La marca procede de la empresa resuelta por el servidor, no de parámetros del navegador.
        return {
            'la-fragua': 'branding/empresas/la-fragua.png',
            'punto-motor': 'branding/empresas/punto-motor.png',
        }.get(self.codigo, '')

    @property
    def datos_pendientes(self):
        campos = [('razon_social', 'razón social o titular'), ('rut', 'RUT'), ('rubro', 'rubro'),
                  ('contacto_nombre', 'nombre del contacto'), ('contacto_apellidos', 'apellidos del contacto'),
                  ('contacto_email', 'correo de contacto')]
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


class AtencionSoporte(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name='atenciones_soporte')
    # Las cuentas del equipo existen únicamente en la central. No se expone
    # ninguna relación inversa sobre los usuarios operativos de las empresas.
    tecnico = models.ForeignKey('usuarios.Usuario', on_delete=anular_central, null=True, blank=True, related_name='+')
    asunto = models.CharField(max_length=160)
    motivo = models.TextField(max_length=2000)
    estado = models.CharField(max_length=12, choices=[('abierta', 'Abierta'), ('cerrada', 'Cerrada')], default='abierta')
    creada_en = models.DateTimeField(default=timezone.now)
    cerrada_en = models.DateTimeField(null=True, blank=True)
    resolucion = models.TextField(max_length=2000, blank=True)

    class Meta:
        db_table = 'atenciones_soporte'
        default_permissions = ()
        ordering = ['-creada_en', '-pk']


class AccesoSoporte(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    atencion = models.ForeignKey(AtencionSoporte, on_delete=models.PROTECT, related_name='accesos')
    tecnico = models.ForeignKey('usuarios.Usuario', on_delete=anular_central, null=True, related_name='+')
    alcances = models.JSONField(default=list)
    motivo = models.TextField(max_length=1000)
    minutos = models.PositiveSmallIntegerField(default=30, choices=[(15, '15 minutos'), (30, '30 minutos'), (60, '60 minutos')])
    estado = models.CharField(max_length=12, default='pendiente', choices=[
        ('pendiente', 'Pendiente de autorización'), ('aprobado', 'Autorizado'),
        ('rechazado', 'Rechazado'), ('revocado', 'Revocado')])
    solicitado_en = models.DateTimeField(default=timezone.now)
    decidido_en = models.DateTimeField(null=True, blank=True)
    expira_en = models.DateTimeField(null=True, blank=True, db_index=True)
    # El aprobador pertenece a la empresa: solo se guarda su identidad histórica,
    # sin una FK hacia una tabla de usuarios de otra base.
    aprobador_id = models.PositiveBigIntegerField(null=True, blank=True)
    aprobador_email = models.EmailField(blank=True)

    class Meta:
        db_table = 'accesos_soporte'
        default_permissions = ()
        ordering = ['-solicitado_en', '-pk']
        constraints = [
            models.CheckConstraint(condition=models.Q(minutos__in=[15, 30, 60]), name='soporte_duracion_acotada'),
            models.CheckConstraint(condition=~models.Q(estado='aprobado') | (
                models.Q(expira_en__isnull=False, decidido_en__isnull=False, aprobador_id__isnull=False)
                & models.Q(expira_en__gt=models.F('decidido_en'))), name='soporte_aprobacion_completa'),
            models.UniqueConstraint(fields=['atencion'], condition=models.Q(estado='pendiente'), name='soporte_una_solicitud_pendiente'),
        ]

    @property
    def vigente(self):
        return bool(self.estado == 'aprobado' and self.expira_en and self.expira_en > timezone.now())

    @property
    def estado_visible(self):
        return 'Vencido' if self.estado == 'aprobado' and not self.vigente else self.get_estado_display()

    @property
    def permisos_visibles(self):
        from .autorizacion_soporte import ALCANCES
        return [ALCANCES[clave] for clave in self.alcances if clave in ALCANCES]


class NotificacionSistema(models.Model):
    """Avisos del panel interno, separados de las notificaciones de clientes."""
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    # La relación no se expone en los gestores operativos de usuarios: la
    # tabla solo existe en la central, no en las bases de las empresas.
    destinatario = models.ForeignKey('usuarios.Usuario', on_delete=cascada_central, related_name='+')
    titulo = models.CharField(max_length=150)
    mensaje = models.TextField()
    empresa_nombre = models.CharField(max_length=160, blank=True)
    link = models.CharField(max_length=300, blank=True)
    leida = models.BooleanField(default=False)
    fecha_creacion = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'notificaciones_sistema'
        default_permissions = ()
        ordering = ['-fecha_creacion', '-id']
        indexes = [models.Index(fields=['destinatario', 'leida', '-fecha_creacion'], name='aviso_sistema_pendientes')]


class BuzonContacto(models.Model):
    """Estado del único buzón y autorización cifrada con la clave del servidor."""
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    cuenta_zoho = models.CharField(max_length=40, blank=True)
    ultima_consulta = models.DateTimeField(null=True, blank=True)
    siguiente_pagina = models.PositiveIntegerField(default=1)
    historial_completo = models.BooleanField(default=False)
    bloqueo = models.UUIDField(null=True, blank=True)
    iniciado_en = models.DateTimeField(null=True, blank=True)
    credenciales_cifradas = models.TextField(blank=True, editable=False)
    conexion_estado = models.CharField(max_length=20, default='pendiente',
        choices=[('pendiente', 'Pendiente de conexión'), ('conectado', 'Conexión comprobada'), ('error', 'Requiere revisión')])
    ultimo_error = models.CharField(max_length=400, blank=True)
    comprobado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'buzon_contacto'
        default_permissions = ()
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name='buzon_contacto_unico')]


class MensajeContacto(models.Model):
    ESTADOS = [('pendiente', 'Pendiente'), ('seguimiento', 'En seguimiento'), ('resuelto', 'Resuelto')]
    CATEGORIAS = [('general', 'Consulta general'), ('acceso', 'Acceso a la cuenta'),
                  ('uso', 'Ayuda con SmartStock'), ('incidencia', 'Incidencia'), ('otro', 'Otro')]
    cuenta_zoho = models.CharField(max_length=40)
    mensaje_zoho = models.CharField(max_length=40)
    carpeta_zoho = models.CharField(max_length=40)
    remitente_nombre = models.CharField(max_length=200, blank=True)
    remitente_email = models.EmailField(max_length=254, blank=True)
    asunto = models.CharField(max_length=300, blank=True)
    resumen = models.TextField(blank=True)
    contenido = models.TextField(blank=True)
    contenido_cargado = models.BooleanField(default=False)
    tiene_adjuntos = models.BooleanField(default=False)
    recibido_en = models.DateTimeField(default=timezone.now)
    leido = models.BooleanField(default=False)
    estado = models.CharField(max_length=20, choices=ESTADOS, default='pendiente')
    categoria = models.CharField(max_length=20, choices=CATEGORIAS, default='general')
    seguimiento = models.DateField(null=True, blank=True)
    version = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'mensajes_contacto'
        default_permissions = ()
        ordering = ['-recibido_en', '-pk']
        constraints = [models.UniqueConstraint(fields=['cuenta_zoho', 'mensaje_zoho'], name='correo_contacto_sin_duplicar')]
        indexes = [models.Index(fields=['estado', '-recibido_en'], name='contacto_estado_fecha')]


class NotaContacto(models.Model):
    mensaje = models.ForeignKey(MensajeContacto, on_delete=models.CASCADE, related_name='notas')
    texto = models.TextField()
    creada_en = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'notas_contacto'
        default_permissions = ()
        ordering = ['-creada_en', '-pk']


class RespuestaContacto(models.Model):
    ESTADOS = [('borrador', 'Borrador'), ('enviando', 'Enviando'), ('enviada', 'Enviada'),
               ('incierta', 'Revisar en Zoho'), ('rechazada', 'No enviada')]
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    mensaje = models.ForeignKey(MensajeContacto, on_delete=models.CASCADE, related_name='respuestas')
    texto = models.TextField()
    estado = models.CharField(max_length=20, choices=ESTADOS, default='borrador')
    version = models.PositiveIntegerField(default=0)
    creada_en = models.DateTimeField(default=timezone.now)
    enviada_en = models.DateTimeField(null=True, blank=True)
    iniciado_en = models.DateTimeField(null=True, blank=True)
    mensaje_zoho = models.CharField(max_length=40, blank=True)

    class Meta:
        db_table = 'respuestas_contacto'
        default_permissions = ()
        ordering = ['-creada_en']
        constraints = [models.UniqueConstraint(fields=['mensaje'], condition=models.Q(estado='borrador'), name='contacto_un_borrador')]
