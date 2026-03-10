# notificador - interfaz y implementaciones
from abc import ABC, abstractmethod


class NotificadorBase(ABC):
    """interfaz para notificadores"""

    @abstractmethod
    def enviar_confirmacion(self, solicitud):
        pass

    def enviar_nueva_solicitud(self, solicitud):
        """Notifica al cuidador que tiene una nueva solicitud."""
        self.enviar_confirmacion(solicitud)

    def enviar_solicitud_aceptada(self, solicitud):
        """Notifica al dueño que el cuidador aceptó."""
        pass

    def enviar_solicitud_rechazada(self, solicitud):
        """Notifica al dueño que el cuidador rechazó."""
        pass

    def enviar_servicio_completado(self, solicitud):
        """Notifica a ambos que el servicio fue completado."""
        pass


class NotificadorMock(NotificadorBase):
    """mock - imprime en consola para desarrollo"""

    def enviar_confirmacion(self, solicitud):
        print(f"[MOCK] confirmación enviada: solicitud {solicitud.idSolicitud}")

    def enviar_nueva_solicitud(self, solicitud):
        print(f"[MOCK] nueva solicitud → cuidador {solicitud.idCuidador.correo}: {solicitud.idSolicitud}")

    def enviar_solicitud_aceptada(self, solicitud):
        print(f"[MOCK] solicitud aceptada → dueño {solicitud.idDueño.correo}: {solicitud.idSolicitud}")

    def enviar_solicitud_rechazada(self, solicitud):
        print(f"[MOCK] solicitud rechazada → dueño {solicitud.idDueño.correo}: {solicitud.idSolicitud}")

    def enviar_servicio_completado(self, solicitud):
        print(f"[MOCK] servicio completado → dueño {solicitud.idDueño.correo}, cuidador {solicitud.idCuidador.correo}")


class NotificadorReal(NotificadorBase):
    """real - aquí se integraría email real (sendgrid, ses, etc)"""

    def enviar_confirmacion(self, solicitud):
        print(f"[REAL] enviando email a {solicitud.idDueño.correo}: solicitud {solicitud.idSolicitud}")

    def enviar_nueva_solicitud(self, solicitud):
        print(f"[REAL] enviando email a cuidador {solicitud.idCuidador.correo}: nueva solicitud {solicitud.idSolicitud}")

    def enviar_solicitud_aceptada(self, solicitud):
        print(f"[REAL] enviando email a dueño {solicitud.idDueño.correo}: solicitud aceptada {solicitud.idSolicitud}")

    def enviar_solicitud_rechazada(self, solicitud):
        print(f"[REAL] enviando email a dueño {solicitud.idDueño.correo}: solicitud rechazada {solicitud.idSolicitud}")

    def enviar_servicio_completado(self, solicitud):
        print(f"[REAL] enviando email a dueño y cuidador: servicio completado {solicitud.idSolicitud}")
