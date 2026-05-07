# constantes de presentacion para views y templates
from django.utils.translation import gettext_lazy as _

from servicios.models import EstadoSolicitud, TipoServicio


HISTORIAL_ESTADO_OPCIONES = [
    ("todas", _("Todos los estados")),
    (EstadoSolicitud.COMPLETADO, _("Finalizados")),
    (EstadoSolicitud.CANCELADO, _("Cancelados")),
    (EstadoSolicitud.RECHAZADO, _("Rechazados")),
    (EstadoSolicitud.ACEPTADO, _("Aceptados")),
    (EstadoSolicitud.PENDIENTE, _("Pendientes")),
]

HISTORIAL_SERVICIO_OPCIONES = [
    ("todos", _("Todos los servicios")),
    (TipoServicio.PASEO, _("Paseo")),
    (TipoServicio.GUARDERIA, _("Guardería")),
]

PREFIJOS_TELEFONO = ("+57", "+1", "+34", "+52", "+54", "+56", "+58")
