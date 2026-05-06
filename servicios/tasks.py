import logging

from celery import shared_task

_logger = logging.getLogger(__name__)


# Las tareas reciben IDs (strings) porque los objetos ORM no son serializables.
# Cada tarea recarga el objeto desde BD y delega al NotificadorLogOnly
# (la tarea ya es async — no necesita disparar otra tarea).


def _notificador_sync():
    from servicios.infra.notificador import NotificadorLogOnly
    return NotificadorLogOnly()


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def task_nueva_solicitud(self, solicitud_id: str):
    try:
        from servicios.models import SolicitudServicio
        solicitud = SolicitudServicio.objects.get(idSolicitud=solicitud_id)
        _notificador_sync().enviar_nueva_solicitud(solicitud)
    except Exception as exc:
        _logger.error("task_nueva_solicitud falló para %s: %s", solicitud_id, exc)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def task_solicitud_aceptada(self, solicitud_id: str):
    try:
        from servicios.models import SolicitudServicio
        solicitud = SolicitudServicio.objects.get(idSolicitud=solicitud_id)
        _notificador_sync().enviar_solicitud_aceptada(solicitud)
    except Exception as exc:
        _logger.error("task_solicitud_aceptada falló para %s: %s", solicitud_id, exc)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def task_solicitud_rechazada(self, solicitud_id: str):
    try:
        from servicios.models import SolicitudServicio
        solicitud = SolicitudServicio.objects.get(idSolicitud=solicitud_id)
        _notificador_sync().enviar_solicitud_rechazada(solicitud)
    except Exception as exc:
        _logger.error("task_solicitud_rechazada falló para %s: %s", solicitud_id, exc)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def task_servicio_completado(self, solicitud_id: str):
    try:
        from servicios.models import SolicitudServicio
        solicitud = SolicitudServicio.objects.get(idSolicitud=solicitud_id)
        _notificador_sync().enviar_servicio_completado(solicitud)
        _notificador_sync().enviar_resena_pendiente(solicitud)
    except Exception as exc:
        _logger.error("task_servicio_completado falló para %s: %s", solicitud_id, exc)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def task_reserva_cancelada(self, solicitud_id: str, actor_id: str, receptor_id: str, destino: str):
    try:
        from servicios.models import SolicitudServicio, Usuario
        solicitud = SolicitudServicio.objects.get(idSolicitud=solicitud_id)
        actor = Usuario.objects.filter(idUsuario=actor_id).first()
        receptor = Usuario.objects.get(idUsuario=receptor_id)
        _notificador_sync().enviar_reserva_cancelada(solicitud, actor=actor, receptor=receptor, destino=destino)
    except Exception as exc:
        _logger.error("task_reserva_cancelada falló para %s: %s", solicitud_id, exc)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def task_mensaje_chat(self, solicitud_id: str, actor_id: str, receptor_id: str, mensaje: str):
    try:
        from servicios.models import SolicitudServicio, Usuario
        solicitud = SolicitudServicio.objects.get(idSolicitud=solicitud_id)
        actor = Usuario.objects.filter(idUsuario=actor_id).first()
        receptor = Usuario.objects.filter(idUsuario=receptor_id).first()
        _notificador_sync().enviar_mensaje_chat(solicitud, actor, receptor, mensaje)
    except Exception as exc:
        _logger.error("task_mensaje_chat falló para %s: %s", solicitud_id, exc)
        raise self.retry(exc=exc)
