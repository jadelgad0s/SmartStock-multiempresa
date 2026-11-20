from django.contrib.auth.tokens import PasswordResetTokenGenerator
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.core.empresa import identidad_empresa


class TokenConEmpresa:
    def __init__(self, token=None, verify=True):
        super().__init__(token, verify)
        empresa = identidad_empresa()
        if token is None and empresa is not None:
            self['empresa'] = empresa

    def verify(self):
        if self.get('empresa') != identidad_empresa():
            raise TokenError('El token no es válido para esta empresa.')
        super().verify()


class AccesoEmpresa(TokenConEmpresa, AccessToken):
    pass


class RenovacionEmpresa(TokenConEmpresa, RefreshToken):
    access_token_class = AccesoEmpresa


class RecuperacionEmpresa(PasswordResetTokenGenerator):
    def _make_hash_value(self, user, timestamp):
        valor = super()._make_hash_value(user, timestamp)
        empresa = identidad_empresa()
        return f'{empresa}|{valor}' if empresa is not None else valor


token_recuperacion = RecuperacionEmpresa()
