"""
Interfaz y implementaciones del Notificador.
Soporte para enviar confirmaciones de solicitudes (email, consola, etc.).
"""
from abc import ABC, abstractmethod


class NotificadorBase(ABC):
    """Interfaz abstracta para notificadores."""

    @abstractmethod
    def enviar_confirmacion(self, solicitud):
        """
        Envía confirmación al dueño tras crear una solicitud.

        Args:
            solicitud: Instancia de SolicitudServicio
        """
        pass


class NotificadorMock(NotificadorBase):
    """
    Implementación Mock: imprime en consola.
    Usado en desarrollo/testing (ENV_TYPE=MOCK o DEV).
    """

    def enviar_confirmacion(self, solicitud):
        mensaje = (
            f"[MOCK] Confirmación de solicitud enviada:\n"
            f"  ID: {solicitud.idSolicitud}\n"
            f"  Dueño: {solicitud.idDueño.nombre}\n"
            f"  Cuidador: {solicitud.idCuidador.nombre}\n"
            f"  Servicio: {solicitud.tipoServicio} - {solicitud.fecha}\n"
        )
        print(mensaje)


class NotificadorReal(NotificadorBase):
    """
    Implementación Real: envía notificación por canal real.
    Aquí se integraría SendGrid, AWS SES, etc.
    Por ahora simula el envío (punto de extensión).
    """

    def enviar_confirmacion(self, solicitud):
        # Punto de extensión: aquí iría la integración con SendGrid, SES, etc.
        # Ejemplo: sendgrid_client.send(to=solicitud.idDueño.correo, ...)
        mensaje = (
            f"[REAL] Enviando email a {solicitud.idDueño.correo}: "
            f"Solicitud #{solicitud.idSolicitud} confirmada - "
            f"{solicitud.tipoServicio} con {solicitud.idCuidador.nombre}"
        )
        # En producción se enviaría el email real
        print(mensaje)
