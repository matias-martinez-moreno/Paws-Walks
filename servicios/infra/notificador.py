# notificador - interfaz y implementaciones
from abc import ABC, abstractmethod


class NotificadorBase(ABC):
    """interfaz para notificadores"""

    @abstractmethod
    def enviar_confirmacion(self, solicitud):
        pass


class NotificadorMock(NotificadorBase):
    """mock - imprime en consola para desarrollo"""

    def enviar_confirmacion(self, solicitud):
        print(f"[MOCK] confirmación enviada: solicitud {solicitud.idSolicitud}")


class NotificadorReal(NotificadorBase):
    """real - aquí se integraría email real (sendgrid, ses, etc)"""

    def enviar_confirmacion(self, solicitud):
        # punto de extensión para integración real
        print(f"[REAL] enviando email a {solicitud.idDueño.correo}: solicitud {solicitud.idSolicitud}")
