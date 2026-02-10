"""
Capa de Aplicación (Service Layer).
Aquí reside el algoritmo de negocio.
Orquesta al Builder y a la Factory.
"""
from django.core.exceptions import ValidationError

from servicios.domain.builder import SolicitudServicioBuilder
from servicios.infra.factory import NotificadorFactory


class SolicitudServicioService:
    """
    Service Layer para la lógica de negocio de SolicitudServicio.
    Utiliza Inyección de Dependencias para el Notificador.
    """

    def __init__(self, notificador=None):
        """
        Args:
            notificador: Inyección de dependencias. Si es None, usa NotificadorFactory.
        """
        self.notificador = notificador or NotificadorFactory.crear()

    def crear_solicitud(self, datos):
        """
        Crea una solicitud de servicio siguiendo las reglas de negocio.
        Usa el Builder para construir el objeto validado y la Factory para notificar.

        Args:
            datos: dict con idDueño, idCuidador_id, idMascota_id, tipoServicio, fecha, idBloqueHorario_id

        Returns:
            SolicitudServicio: La solicitud creada y guardada.

        Raises:
            ValidationError: Si alguna validación de negocio falla.
        """
        solicitud = (
            SolicitudServicioBuilder()
            .para_dueño(datos['idDueño'])
            .para_cuidador(datos['idCuidador_id'])
            .para_mascota(datos['idMascota_id'])
            .con_servicio(datos['tipoServicio'])
            .en_fecha(datos['fecha'])
            .en_bloque(datos['idBloqueHorario_id'])
            .build()
        )
        solicitud.save()

        bloque_tiempo = solicitud.idBloqueHorario
        bloque_tiempo.disponible = False
        bloque_tiempo.save()

        self.notificador.enviar_confirmacion(solicitud)

        return solicitud
