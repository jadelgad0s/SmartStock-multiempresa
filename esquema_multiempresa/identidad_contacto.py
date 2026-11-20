"""Impide asignar el perfil exclusivo mediante otros formularios o save()."""
from django.core.exceptions import ValidationError
from django.db.models.signals import pre_save
from django.dispatch import receiver

from apps.usuarios.models import Usuario
from .permisos import CONTACTO, CORREO_CONTACTO


@receiver(pre_save, sender=Usuario, dispatch_uid='smartstock_identidad_contacto')
def validar_identidad_contacto(sender, instance, using, **kwargs):
    if using != 'central' or kwargs.get('raw'):
        return
    reservado = instance.email.strip().lower() == CORREO_CONTACTO
    rol_contacto = bool(instance.rol_id and instance.rol.codigo == CONTACTO)
    if reservado or rol_contacto:
        if not (reservado and rol_contacto and instance.is_staff and not instance.is_superuser):
            raise ValidationError('Contacto es exclusivo de contacto@smartstockchile.cl y no puede ser superusuario.')
        instance.email = CORREO_CONTACTO
    if instance.pk:
        anterior = sender.objects.using('central').filter(pk=instance.pk).values('email', 'rol__codigo').first()
        if anterior and anterior['rol__codigo'] == CONTACTO and not (reservado and rol_contacto):
            raise ValidationError('El correo y el perfil de la cuenta de contacto son fijos.')
