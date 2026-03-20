# capa de aplicacion: servicios de validacion y resolucion de entidades
#
# Estos servicios encapsulan reglas de negocio que antes eran funciones
# libres en base_servicios.py. Al ser clases, son inyectables y testeables.
from __future__ import annotations

from datetime import date

from servicios.domain.exceptions import (
    ConflictError,
    DomainValidationError,
    ResourceNotFoundError,
)
from servicios.models import (
    EstadoSolicitud,
    Evento,
    Mascota,
    PerfilCuidador,
    PrecioServicio,
    SolicitudServicio,
    TipoServicio,
    Usuario,
)
from servicios.service_layer.utils import time_to_minutes


PASEO_DURACIONES_MINUTOS = (60, 90, 120, 150, 180)
ESTADOS_OCUPAN_CUPO = (
    EstadoSolicitud.PENDIENTE,
    EstadoSolicitud.ACEPTADO,
    EstadoSolicitud.COMPLETADO,
)


class ValidarTipoServicioService:
    """Valida que el tipo de servicio sea valido."""

    @staticmethod
    def validar(tipo_servicio: str) -> str:
        tipo = str(tipo_servicio or "").strip()
        if tipo not in (TipoServicio.PASEO, TipoServicio.GUARDERIA):
            raise DomainValidationError("tipo de servicio inválido")
        return tipo


class ResolverCuidadorVerificadoService:
    """Resuelve y valida que un cuidador exista y este verificado."""

    @staticmethod
    def resolver(cuidador_id) -> Usuario:
        try:
            cuidador = Usuario.objects.get(idUsuario=cuidador_id)
        except Usuario.DoesNotExist:
            raise ResourceNotFoundError("el cuidador no existe")
        if cuidador.rol != "cuidador":
            raise DomainValidationError("el usuario no es cuidador")
        if not cuidador.verificado:
            raise DomainValidationError("el cuidador no está verificado")
        return cuidador


class ResolverMascotaDeDueñoService:
    """Resuelve y valida que una mascota pertenezca al dueño."""

    @staticmethod
    def resolver(dueño: Usuario, mascota_id) -> Mascota:
        if not isinstance(dueño, Usuario):
            raise DomainValidationError("el dueño debe ser un usuario válido")
        try:
            return Mascota.objects.get(idMascota=mascota_id, idDueño=dueño)
        except Mascota.DoesNotExist:
            raise ResourceNotFoundError("la mascota no existe o no te pertenece")


class ValidarFechasSolicitudService:
    """Valida fechas de solicitud de servicio."""

    @staticmethod
    def validar(fecha: date, fecha_fin: date | None = None) -> None:
        if fecha < date.today():
            raise DomainValidationError("la fecha del servicio no puede ser en el pasado")
        if fecha_fin is None:
            return
        if fecha_fin < date.today():
            raise DomainValidationError("la fecha fin no puede ser en el pasado")
        if fecha_fin < fecha:
            raise DomainValidationError("la fecha fin debe ser igual o posterior a la fecha de inicio")


class ResolverPrecioActivoService:
    """Resuelve el precio activo de un cuidador para un tipo de servicio."""

    @staticmethod
    def resolver(cuidador: Usuario, tipo_servicio: str) -> PrecioServicio:
        precio = PrecioServicio.objects.filter(
            idCuidador=cuidador,
            tipoServicio=tipo_servicio,
            activo=True,
        ).first()
        if not precio:
            raise DomainValidationError("el cuidador no ofrece ese tipo de servicio")
        return precio


class NormalizarDuracionGuarderiaService:
    """Normaliza y valida la duracion de guarderia en minutos."""

    @staticmethod
    def normalizar(duracion_minutos) -> int | None:
        if duracion_minutos is None or str(duracion_minutos).strip() == "":
            return None
        try:
            minutos = int(duracion_minutos)
        except (TypeError, ValueError):
            raise DomainValidationError("la duración de guardería debe ser un número entero")
        if minutos < 60:
            raise DomainValidationError("la duración mínima de guardería es 1 hora")
        if minutos % 30 != 0:
            raise DomainValidationError("la duración de guardería debe ser en múltiplos de 30 minutos")
        return minutos


class CalcularMontoPagoService:
    """Calcula el monto de pago para una solicitud de servicio."""

    @staticmethod
    def calcular(
        *,
        tipo_servicio: str,
        precio_base_hora: int,
        fecha: date,
        fecha_fin: date | None = None,
        evento: Evento | None = None,
        ventana=None,
        bloque=None,
        duracion_guarderia_minutos: int | None = None,
    ) -> int | None:
        if tipo_servicio == TipoServicio.GUARDERIA:
            if evento is not None:
                duracion_min = duracion_guarderia_minutos
                if duracion_min is None:
                    duracion_min = (time_to_minutes(evento.horaFin) - time_to_minutes(evento.horaInicio))
                tarifa_hora = int(evento.precioCOP) if evento.precioCOP else int(precio_base_hora)
                monto = int(tarifa_hora * (duracion_min / 60.0))
                return monto if monto > 0 else None

            if fecha_fin is None:
                return None
            num_days = (fecha_fin - fecha).days + 1
            monto = int(int(precio_base_hora) * num_days)
            return monto if monto > 0 else None

        if evento is not None:
            if evento.precioCOP:
                return int(evento.precioCOP)
            duracion_min = evento.duracionSlotMinutos
            if duracion_min is None:
                duracion_min = time_to_minutes(evento.horaFin) - time_to_minutes(evento.horaInicio)
        elif ventana is not None:
            duracion_min = int(ventana.duracionSlotMinutos)
        elif bloque is not None:
            duracion_min = time_to_minutes(bloque.horaFin) - time_to_minutes(bloque.horaInicio)
        else:
            return None

        monto = int(int(precio_base_hora) * (duracion_min / 60.0))
        return monto if monto > 0 else None


class CuposDisponiblesEventoService:
    """Calcula cupos disponibles de un evento para una fecha."""

    @staticmethod
    def calcular(evento: Evento, fecha_servicio: date) -> tuple[int, int]:
        capacidad_total = max(1, int(evento.capacidadMaxima or 1))
        if evento.tipoServicio == TipoServicio.PASEO:
            capacidad_total = min(capacidad_total, 4)

        ocupados = SolicitudServicio.objects.filter(
            idEvento=evento,
            fecha=fecha_servicio,
            estado__in=ESTADOS_OCUPAN_CUPO,
        ).count()
        cupos = max(0, capacidad_total - ocupados)
        return cupos, capacidad_total


class CoberturaOperativaCuidadorService:
    """Obtiene la ubicacion/radio operativos del cuidador para busquedas."""

    @staticmethod
    def obtener(perfil: PerfilCuidador, cuidador: Usuario):
        ciudad = (perfil.ciudadServicio or "").strip() or (cuidador.ciudad or "").strip()
        latitud = perfil.latitudServicio if perfil.latitudServicio is not None else cuidador.latitud
        longitud = perfil.longitudServicio if perfil.longitudServicio is not None else cuidador.longitud
        radio_km = perfil.radioKmServicio if perfil.radioKmServicio is not None else cuidador.radioKm
        return ciudad, latitud, longitud, radio_km
