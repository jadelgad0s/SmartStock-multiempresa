"""Identificación del cliente en el directorio central."""
import re

from django.core.exceptions import ValidationError


def normalizar_rut(valor):
    texto = re.sub(r'[.\s-]', '', valor or '').upper()
    return f'{texto[:-1]}-{texto[-1]}' if len(texto) > 1 else texto


def validar_rut(valor):
    if not valor:
        return
    rut = normalizar_rut(valor)
    if not re.fullmatch(r'[1-9][0-9]{5,7}-[0-9K]', rut):
        raise ValidationError('Ingresa un RUT válido, por ejemplo 12.345.678-5.')
    cuerpo, verificador = rut.split('-')
    suma = sum(int(digito) * (2 + posicion % 6) for posicion, digito in enumerate(reversed(cuerpo)))
    resto = 11 - suma % 11
    esperado = '0' if resto == 11 else 'K' if resto == 10 else str(resto)
    if verificador != esperado:
        raise ValidationError('El dígito verificador del RUT no coincide. Revisa el dato.')
