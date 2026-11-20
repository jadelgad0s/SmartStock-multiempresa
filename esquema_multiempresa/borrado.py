from django.db.models import CASCADE


def cascada_central(collector, field, sub_objs, using):
    """La relación pertenece a la central; no consulta esa tabla en clientes."""
    if using == 'central':
        CASCADE(collector, field, sub_objs, using)


cascada_central.lazy_sub_objs = True
