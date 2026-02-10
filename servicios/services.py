# capa de aplicación - aquí está la lógica de negocio
from django.core.exceptions import ValidationError
from servicios.domain.builder import SolicitudServicioBuilder
from servicios.infra.factory import NotificadorFactory


class SolicitudServicioService:
    """service layer - orquesta builder y factory"""

    def __init__(self, notificador=None):
        # inyección de dependencias - permite pasar notificador o usar factory
        self.notificador = notificador or NotificadorFactory.crear()

    def crear_solicitud(self, datos):
        # usa builder para construir y validar
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
        
        # marca bloque como no disponible
        bloque = solicitud.idBloqueHorario
        bloque.disponible = False
        bloque.save()
        
        # notifica usando factory
        self.notificador.enviar_confirmacion(solicitud)
        
        return solicitud
