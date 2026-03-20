# API Gateway: fachada de entrada para todas las operaciones HTTP de la API v1.
#
# Justificacion del patron:
#   Las vistas DRF solo conocen este Gateway — nunca los servicios internos.
#   Esto cumple el principio de minimo conocimiento (Law of Demeter) y facilita
#   cambiar la implementacion interna sin tocar la capa de presentacion.
from __future__ import annotations

from servicios.models import SolicitudServicio
from servicios.service_layer.api_disponibilidad_servicios import BuscarDisponibilidadDesdeApiService
from servicios.service_layer.api_servicios import (
    CancelarSolicitudDesdeApiService,
    CrearSolicitudServicioApiAppService,
)
from servicios.service_layer.api_validadores import (
    MapearResultadosDisponibilidadApiService,
    ValidarBusquedaDisponibilidadApiService,
    ValidarCrearSolicitudApiService,
)
from servicios.service_layer.reservas_servicios import ObtenerSolicitudServicioService


class ServiciosApiGatewayService:
    """Fachada de entrada para operaciones HTTP de la API v1 de servicios."""

    def __init__(
        self,
        crear_solicitud_service: CrearSolicitudServicioApiAppService | None = None,
        obtener_solicitud_service: ObtenerSolicitudServicioService | None = None,
        cancelar_solicitud_service: CancelarSolicitudDesdeApiService | None = None,
        buscar_disponibilidad_service: BuscarDisponibilidadDesdeApiService | None = None,
        resultado_mapper: MapearResultadosDisponibilidadApiService | None = None,
        validar_creacion_service: ValidarCrearSolicitudApiService | None = None,
        validar_disponibilidad_service: ValidarBusquedaDisponibilidadApiService | None = None,
    ):
        self._crear_solicitud_service = crear_solicitud_service or CrearSolicitudServicioApiAppService()
        self._obtener_solicitud_service = obtener_solicitud_service or ObtenerSolicitudServicioService()
        self._cancelar_solicitud_service = cancelar_solicitud_service or CancelarSolicitudDesdeApiService()
        self._buscar_disponibilidad_service = buscar_disponibilidad_service or BuscarDisponibilidadDesdeApiService()
        self._resultado_mapper = resultado_mapper or MapearResultadosDisponibilidadApiService()
        self._validar_creacion_service = validar_creacion_service or ValidarCrearSolicitudApiService()
        self._validar_disponibilidad_service = validar_disponibilidad_service or ValidarBusquedaDisponibilidadApiService()

    def crear_solicitud(self, payload: dict) -> SolicitudServicio:
        data = self._validar_creacion_service.validar(payload)
        return self._crear_solicitud_service.crear_desde_api(data)

    def obtener_solicitud(self, solicitud_id: str) -> SolicitudServicio:
        return self._obtener_solicitud_service.obtener(solicitud_id)

    def cancelar_solicitud(self, solicitud_id: str, actor_id) -> SolicitudServicio:
        return self._cancelar_solicitud_service.cancelar(solicitud_id, actor_id)

    def buscar_disponibilidad(self, payload: dict) -> list[dict]:
        data = self._validar_disponibilidad_service.validar(payload)
        resultados = self._buscar_disponibilidad_service.buscar(data)
        return self._resultado_mapper.mapear(resultados, data["tipoServicio"], data)
