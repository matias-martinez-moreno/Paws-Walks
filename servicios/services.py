from django.core.exceptions import ValidationError
from servicios.models import (
    SolicitudServicio, Usuario, Mascota, 
    BloqueTiempo, PrecioServicio, TipoServicio, EstadoSolicitud
)


class SolicitudServicioService:
    """
    Service Layer para la lógica de negocio de SolicitudServicio.
    """
    
    def crear_solicitud(self, datos):
        """
        Crea una solicitud de servicio siguiendo las reglas de negocio.
        
        Args:
            datos: dict con las siguientes claves:
                - idDueño: Usuario
                - idCuidador_id: UUID del Usuario (cuidador)
                - idMascota_id: UUID de la Mascota
                - tipoServicio: str (TipoServicio)
                - fecha: date
                - idBloqueHorario_id: UUID del BloqueTiempo
        
        Returns:
            SolicitudServicio: La solicitud creada y guardada
        
        Raises:
            ValidationError: Si alguna validación de negocio falla
        """
        # 1. Validar que el cuidador existe y está verificado
        try:
            cuidador = Usuario.objects.get(idUsuario=datos['idCuidador_id'])
        except Usuario.DoesNotExist:
            raise ValidationError("El cuidador especificado no existe")
        
        if cuidador.rol not in ['cuidador', 'ambos']:
            raise ValidationError("El usuario especificado no es un cuidador")
        
        if not cuidador.verificado:
            raise ValidationError("El cuidador no está verificado")
        
        # 2. Validar que el bloque de tiempo existe y está disponible
        try:
            bloque_tiempo = BloqueTiempo.objects.get(idBloque=datos['idBloqueHorario_id'])
        except BloqueTiempo.DoesNotExist:
            raise ValidationError("El bloque de tiempo especificado no existe")
        
        if not bloque_tiempo.disponible:
            raise ValidationError("El bloque de tiempo no está disponible")
        
        if bloque_tiempo.idCuidador.idCuidador != cuidador:
            raise ValidationError("El bloque de tiempo no pertenece al cuidador especificado")
        
        # 3. Validar que existe precio para el tipo de servicio
        try:
            precio_servicio = PrecioServicio.objects.get(
                idCuidador=cuidador,
                tipoServicio=datos['tipoServicio'],
                activo=True
            )
        except PrecioServicio.DoesNotExist:
            raise ValidationError(
                f"El cuidador no tiene un precio configurado para {datos['tipoServicio']}"
            )
        
        # 4. Obtener la mascota
        try:
            mascota = Mascota.objects.get(
                idMascota=datos['idMascota_id'],
                idDueño=datos['idDueño']
            )
        except Mascota.DoesNotExist:
            raise ValidationError("La mascota especificada no existe o no pertenece al dueño")
        
        # 5. Crear la solicitud
        solicitud = SolicitudServicio(
            idDueño=datos['idDueño'],
            idCuidador=cuidador,
            idMascota=mascota,
            tipoServicio=datos['tipoServicio'],
            fecha=datos['fecha'],
            idBloqueHorario=bloque_tiempo,
            estado=EstadoSolicitud.PENDIENTE
        )
        
        # 6. Guardar en la base de datos
        solicitud.save()
        
        # 7. Marcar el bloque de tiempo como no disponible
        bloque_tiempo.disponible = False
        bloque_tiempo.save()
        
        return solicitud

