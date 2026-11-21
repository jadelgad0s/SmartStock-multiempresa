from django.db.models import CASCADE


def anular_central(collector, field, sub_objs, using):
    from django.db.models import SET_NULL
    if using == 'central':
        SET_NULL(collector, field, sub_objs, using)


anular_central.lazy_sub_objs = True


def cascada_central(collector, field, sub_objs, using):
    """La relación pertenece a la central; no consulta esa tabla en clientes."""
    if using == 'central':
        CASCADE(collector, field, sub_objs, using)


cascada_central.lazy_sub_objs = True
