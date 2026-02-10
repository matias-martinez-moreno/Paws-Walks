"""
Capa de Aplicación (Service Layer).
Aquí reside el algoritmo de negocio.
"""
from django.core.exceptions import ValidationError

from servicios.models import (
    SolicitudServicio, Usuario, Mascota,
    BloqueTiempo, PrecioServicio, EstadoSolicitud
)


class SolicitudServicioService:
    """
    Service Layer para la lógica de negocio de SolicitudServicio.
    """

    def crear_solicitud(self, datos):
        """
        Crea una solicitud de servicio siguiendo las reglas de negocio.

        Args:
            datos: dict con idDueño, idCuidador_id, idMascota_id, tipoServicio, fecha, idBloqueHorario_id

        Returns:
            SolicitudServicio: La solicitud creada y guardada.

        Raises:
            ValidationError: Si alguna validación de negocio falla.
        """
        cuidador = self._validar_cuidador(datos)
        bloque_tiempo = self._validar_bloque(datos, cuidador)
        self._validar_precio(cuidador, datos['tipoServicio'])
        mascota = self._validar_mascota(datos)

        solicitud = SolicitudServicio(
            idDueño=datos['idDueño'],
            idCuidador=cuidador,
            idMascota=mascota,
            tipoServicio=datos['tipoServicio'],
            fecha=datos['fecha'],
            idBloqueHorario=bloque_tiempo,
            estado=EstadoSolicitud.PENDIENTE,
        )
        solicitud.save()

        bloque_tiempo.disponible = False
        bloque_tiempo.save()

        return solicitud

    def _validar_cuidador(self, datos):
        try:
            cuidador = Usuario.objects.get(idUsuario=datos['idCuidador_id'])
        except Usuario.DoesNotExist:
            raise ValidationError("El cuidador especificado no existe")
        if cuidador.rol not in ['cuidador', 'ambos']:
            raise ValidationError("El usuario especificado no es un cuidador")
        if not cuidador.verificado:
            raise ValidationError("El cuidador no está verificado")
        return cuidador

    def _validar_bloque(self, datos, cuidador):
        try:
            bloque = BloqueTiempo.objects.get(idBloque=datos['idBloqueHorario_id'])
        except BloqueTiempo.DoesNotExist:
            raise ValidationError("El bloque de tiempo especificado no existe")
        if not bloque.disponible:
            raise ValidationError("El bloque de tiempo no está disponible")
        if bloque.idCuidador.idCuidador != cuidador:
            raise ValidationError("El bloque de tiempo no pertenece al cuidador especificado")
        return bloque

    def _validar_precio(self, cuidador, tipo_servicio):
        try:
            PrecioServicio.objects.get(
                idCuidador=cuidador, tipoServicio=tipo_servicio, activo=True
            )
        except PrecioServicio.DoesNotExist:
            raise ValidationError(
                f"El cuidador no tiene un precio configurado para {tipo_servicio}"
            )

    def _validar_mascota(self, datos):
        try:
            return Mascota.objects.get(
                idMascota=datos['idMascota_id'],
                idDueño=datos['idDueño'],
            )
        except Mascota.DoesNotExist:
            raise ValidationError("La mascota especificada no existe o no pertenece al dueño")
