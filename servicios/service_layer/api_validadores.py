# capa de aplicacion: validadores, mappers y politica de acceso para la API
from __future__ import annotations

import logging

from servicios.domain.exceptions import (
    AuthorizationError,
    ConflictError,
    DomainError,
    DomainValidationError,
    ResourceNotFoundError,
)
from servicios.models import (
    SolicitudServicio,
    TipoServicio,
    Usuario,
)


class ValidarCrearSolicitudApiService:
    """Valida reglas de negocio de creacion de solicitud para capa API."""

    def validar(self, attrs: dict) -> dict:
        tipo_servicio = attrs.get("tipoServicio")
        fecha = attrs.get("fecha")
        fecha_fin = attrs.get("fechaFin")

        if tipo_servicio == TipoServicio.PASEO and fecha_fin is not None and fecha_fin != fecha:
            raise DomainValidationError(
                {"fechaFin": "para paseo la fecha fin debe coincidir con la fecha seleccionada"}
            )

        if tipo_servicio == TipoServicio.GUARDERIA and fecha_fin is not None and fecha_fin < fecha:
            raise DomainValidationError(
                {"fechaFin": "la fecha fin debe ser igual o posterior a la fecha"}
            )

        duracion = attrs.get("duracionMinutosSolicitados")
        if duracion is not None and (duracion < 60 or duracion % 30 != 0):
            raise DomainValidationError(
                {
                    "duracionMinutosSolicitados": (
                        "la duracion de guarderia debe ser minimo 60 minutos y en multiplos de 30"
                    )
                }
            )

        # La validación de si el evento requiere un slot se hace en el service layer
        # (CrearSolicitudServicioApiAppService), ya que requiere una consulta a BD.
        return attrs


class ValidarBusquedaDisponibilidadApiService:
    """Valida reglas de busqueda de disponibilidad para capa API."""

    def validar(self, attrs: dict) -> dict:
        tipo_servicio = attrs.get("tipoServicio")

        if tipo_servicio == TipoServicio.PASEO:
            if attrs.get("fecha") is None:
                raise DomainValidationError({"fecha": "fecha es requerida para paseo"})
            if attrs.get("duracionMinutos") is None:
                raise DomainValidationError(
                    {"duracionMinutos": "duracionMinutos es requerida para paseo"}
                )

            ciudad = str(attrs.get("ciudadPaseo") or "").strip()
            latitud = attrs.get("latitudPaseo")
            longitud = attrs.get("longitudPaseo")

            if (latitud is None) != (longitud is None):
                raise DomainValidationError("latitudPaseo y longitudPaseo deben enviarse juntas")

            if not ciudad and (latitud is None or longitud is None):
                raise DomainValidationError(
                    "para paseo debes enviar ciudadPaseo o coordenadas de referencia"
                )

        if tipo_servicio == TipoServicio.GUARDERIA:
            fecha_inicio = attrs.get("fechaInicioGuarderia")
            fecha_fin = attrs.get("fechaFinGuarderia")
            if fecha_inicio is None:
                raise DomainValidationError(
                    {"fechaInicioGuarderia": "fechaInicioGuarderia es requerida para guarderia"}
                )
            if fecha_fin is not None and fecha_fin < fecha_inicio:
                raise DomainValidationError(
                    {
                        "fechaFinGuarderia": (
                            "fechaFinGuarderia debe ser igual o posterior a fechaInicioGuarderia"
                        )
                    }
                )

        precio_min = attrs.get("precioMinHora")
        precio_max = attrs.get("precioMaxHora")
        if precio_min is not None and precio_max is not None and precio_min > precio_max:
            raise DomainValidationError(
                {"precioMinHora": "precioMinHora no puede ser mayor que precioMaxHora"}
            )

        hora_inicio = attrs.get("horaInicio")
        hora_fin = attrs.get("horaFin")
        if hora_inicio is not None and hora_fin is not None and hora_fin <= hora_inicio:
            raise DomainValidationError({"horaFin": "horaFin debe ser posterior a horaInicio"})

        return attrs


class MapearResultadosDisponibilidadApiService:
    """Transforma resultados de disponibilidad de dominio a payload API."""

    @staticmethod
    def _map_slot_guarderia(slot: dict) -> dict:
        return {
            "eventoId": slot["evento_id"],
            "fecha": slot["fecha"],
            "horaInicio": slot["hora_inicio"],
            "horaFin": slot["hora_fin"],
            "cuposDisponibles": int(slot["cupos_disponibles"]),
            "cupoMaximo": int(slot["cupo_maximo"]),
            "duracionOpciones": list(slot.get("duracion_opciones") or []),
        }

    def mapear_item(self, item: dict, tipo_servicio: str, data: dict) -> dict:
        cuidador = item["cuidador"]
        evento = item.get("evento")
        evento_id = None
        fecha = None
        hora_inicio = item.get("hora_inicio")
        hora_fin = item.get("hora_fin")
        slots_guarderia = []

        if tipo_servicio == TipoServicio.PASEO:
            fecha = data.get("fecha")
            if evento is not None:
                evento_id = str(evento.idEvento)
                hora_inicio = hora_inicio or evento.horaInicio
                hora_fin = hora_fin or evento.horaFin
        else:
            evento_id = item.get("evento_default_id")
            fecha = item.get("fecha_default")
            if evento is not None:
                evento_id = evento_id or str(evento.idEvento)
                hora_inicio = hora_inicio or evento.horaInicio
                hora_fin = hora_fin or evento.horaFin
            slots_guarderia = [
                self._map_slot_guarderia(slot)
                for slot in (item.get("slots_guarderia") or [])
            ]

        payload = {
            "cuidadorId": str(cuidador.idUsuario),
            "cuidadorNombre": cuidador.nombre,
            "cuidadorApellido": cuidador.apellido,
            "tipoServicio": tipo_servicio,
            "eventoId": evento_id,
            "fecha": fecha,
            "horaInicio": hora_inicio,
            "horaFin": hora_fin,
            "tarifaHora": int(item.get("tarifa_hora") or 0),
            "tarifaTotal": int(item.get("tarifa_total") or 0),
            "cupoMaximo": item.get("cupo_maximo"),
            "cuposDisponibles": item.get("cupos_disponibles"),
            "totalSlotsDisponibles": int(item.get("total_slots_disponibles") or 0),
            "distanciaKm": item.get("distancia_km"),
            "calificacionPromedio": item.get("calificacion_promedio"),
            "calificacionCount": int(item.get("calificacion_count") or 0),
            "descripcionServicio": item.get("descripcion_servicio") or "",
        }

        if slots_guarderia:
            payload["slotsGuarderia"] = slots_guarderia

        return payload

    def mapear(self, resultados: list, tipo_servicio: str, data: dict) -> list[dict]:
        return [self.mapear_item(item, tipo_servicio, data) for item in (resultados or [])]


class MapearErroresApiService:
    """Normaliza excepciones de dominio a respuestas HTTP para DRF."""

    def __init__(self, logger_name: str = __name__):
        self._logger = logging.getLogger(logger_name)

    def mapear(self, exc: Exception, operacion: str) -> tuple[dict, int]:
        if isinstance(exc, AuthorizationError):
            return {"detail": str(exc)}, 403
        if isinstance(exc, ResourceNotFoundError):
            return {"detail": str(exc)}, 404
        if isinstance(exc, ConflictError):
            return {"detail": str(exc)}, 409
        if isinstance(exc, DomainValidationError):
            detail = exc.args[0] if exc.args else str(exc)
            if isinstance(detail, dict):
                return detail, 400
            return {"detail": str(detail)}, 400
        if isinstance(exc, DomainError):
            return {"detail": str(exc)}, 400

        self._logger.exception("Error interno inesperado en API de servicios (%s)", operacion)
        return {"detail": "ocurrio un error interno inesperado"}, 500


class PoliticaAccesoServiciosApiService:
    """Centraliza validaciones de actor y permisos para capa de presentacion API."""

    def resolver_actor(self, user) -> Usuario:
        actor = getattr(user, "perfil_usuario", None)
        if actor is None:
            raise AuthorizationError("usuario autenticado sin perfil de dominio")
        return actor

    @staticmethod
    def exigir_rol_dueño_para_crear(actor: Usuario) -> None:
        if actor.rol != "dueño":
            raise AuthorizationError("solo un dueño puede crear solicitudes")

    @staticmethod
    def exigir_rol_dueño_para_buscar(actor: Usuario) -> None:
        if actor.rol != "dueño":
            raise AuthorizationError("solo un dueño puede buscar disponibilidad")

    @staticmethod
    def forzar_dueño_del_actor(payload: dict, actor: Usuario, *, mismatch_msg: str) -> dict:
        data = dict(payload)
        dueño_payload = data.get("idDueño_id")
        if dueño_payload and dueño_payload != actor.idUsuario:
            raise AuthorizationError(mismatch_msg)
        data["idDueño_id"] = actor.idUsuario
        return data

    @staticmethod
    def validar_actor_cancelacion(actor: Usuario, actor_payload_id) -> str:
        if actor_payload_id and actor_payload_id != actor.idUsuario:
            raise AuthorizationError("el actor del payload no coincide con tu sesión")
        return str(actor.idUsuario)

    @staticmethod
    def validar_participacion_en_solicitud(actor: Usuario, solicitud: SolicitudServicio) -> None:
        if actor.idUsuario not in (solicitud.idDueño_id, solicitud.idCuidador_id):
            raise AuthorizationError("no tienes permisos para ver esta solicitud")
