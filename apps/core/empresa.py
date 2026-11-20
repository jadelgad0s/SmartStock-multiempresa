"""Empresa asociada a la petición o al comando que está trabajando en sus datos."""
from contextlib import contextmanager
from contextvars import ContextVar

from django.db import DEFAULT_DB_ALIAS, transaction


_empresa = ContextVar('smartstock_empresa', default=None)


@contextmanager
def usar_empresa(empresa):
    anterior = _empresa.set(empresa)
    try:
        yield
    finally:
        _empresa.reset(anterior)


def empresa_actual():
    return _empresa.get()


def alias_operativo():
    empresa = empresa_actual()
    return empresa.alias_bd if empresa is not None else DEFAULT_DB_ALIAS


def identidad_empresa():
    empresa = empresa_actual()
    if empresa is not None:
        # Un alta nueva o una reasignación del alias invalida las credenciales anteriores.
        return f'{empresa.pk}:{empresa.alias_bd}'
    return None


@contextmanager
def transaccion_operativa():
    with transaction.atomic(using=alias_operativo()):
        yield
