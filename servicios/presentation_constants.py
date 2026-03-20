# constantes de presentacion para views y templates
from servicios.models import EstadoSolicitud, TipoServicio


HISTORIAL_ESTADO_OPCIONES = [
    ("todas", "Todos los estados"),
    (EstadoSolicitud.COMPLETADO, "Finalizados"),
    (EstadoSolicitud.CANCELADO, "Cancelados"),
    (EstadoSolicitud.RECHAZADO, "Rechazados"),
    (EstadoSolicitud.ACEPTADO, "Aceptados"),
    (EstadoSolicitud.PENDIENTE, "Pendientes"),
]

HISTORIAL_SERVICIO_OPCIONES = [
    ("todos", "Todos los servicios"),
    (TipoServicio.PASEO, "Paseo"),
    (TipoServicio.GUARDERIA, "Guardería"),
]

PREFIJOS_TELEFONO = ("+57", "+1", "+34", "+52", "+54", "+56", "+58")
