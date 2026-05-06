# API Gateway: fachada de entrada para todas las operaciones HTTP de la API v1.
#
# Justificacion del patron:
#   Las vistas DRF solo conocen este Gateway — nunca los servicios internos.
#   Esto cumple el principio de minimo conocimiento (Law of Demeter) y facilita
#   cambiar la implementacion interna sin tocar la capa de presentacion.
#
# buscar_disponibilidad() delega al microservicio Flask si DISPONIBILIDAD_SERVICE_URL
# está configurado; en caso de fallo cae al servicio interno (fallback).
from __future__ import annotations

import json
import logging

import requests as http_requests
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder

from servicios.infra.factory import ClimaAdapterFactory
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
from servicios.service_layer.clima_servicios import ClimaService
from servicios.service_layer.reservas_servicios import ObtenerSolicitudServicioService

_logger = logging.getLogger(__name__)


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
        clima_service: ClimaService | None = None,
    ):
        self._crear_solicitud_service = crear_solicitud_service or CrearSolicitudServicioApiAppService()
        self._obtener_solicitud_service = obtener_solicitud_service or ObtenerSolicitudServicioService()
        self._cancelar_solicitud_service = cancelar_solicitud_service or CancelarSolicitudDesdeApiService()
        self._buscar_disponibilidad_service = buscar_disponibilidad_service or BuscarDisponibilidadDesdeApiService()
        self._resultado_mapper = resultado_mapper or MapearResultadosDisponibilidadApiService()
        self._validar_creacion_service = validar_creacion_service or ValidarCrearSolicitudApiService()
        self._validar_disponibilidad_service = validar_disponibilidad_service or ValidarBusquedaDisponibilidadApiService()
        self._clima_service = clima_service or ClimaService(ClimaAdapterFactory.crear())

    def crear_solicitud(self, payload: dict) -> SolicitudServicio:
        data = self._validar_creacion_service.validar(payload)
        return self._crear_solicitud_service.crear_desde_api(data)

    def obtener_solicitud(self, solicitud_id: str) -> SolicitudServicio:
        return self._obtener_solicitud_service.obtener(solicitud_id)

    def cancelar_solicitud(self, solicitud_id: str, actor_id) -> SolicitudServicio:
        return self._cancelar_solicitud_service.cancelar(solicitud_id, actor_id)

    def buscar_disponibilidad(self, payload: dict) -> list[dict]:
        # Validar SIEMPRE primero: el validador inyecta idDueño_id desde el actor
        # y normaliza campos. Flask necesita el payload ya validado.
        data = self._validar_disponibilidad_service.validar(payload)

        flask_url = getattr(settings, "DISPONIBILIDAD_SERVICE_URL", "")
        if flask_url:
            try:
                json_payload = json.loads(json.dumps(data, cls=DjangoJSONEncoder))
                resp = http_requests.post(
                    f"{flask_url}/disponibilidad",
                    json=json_payload,
                    timeout=10,
                )
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:  # noqa: BLE001
                _logger.warning("Microservicio disponibilidad no disponible, usando fallback: %s", exc)

        # Fallback: servicio interno Django
        resultados = self._buscar_disponibilidad_service.buscar(data)
        return self._resultado_mapper.mapear(resultados, data["tipoServicio"], data)

    def obtener_clima_ciudad(self, ciudad: str) -> dict:
        return self._clima_service.obtener_clima_para_paseo(ciudad)
