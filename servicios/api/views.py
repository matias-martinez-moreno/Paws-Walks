import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from servicios.api.serializers import (
    DisponibilidadBusquedaSerializer,
    DisponibilidadResultadoSerializer,
    SolicitudServicioCreateSerializer,
    SolicitudServicioCancelSerializer,
    SolicitudServicioSerializer,
)
from servicios.domain.exceptions import (
    ConflictError,
    DomainValidationError,
    ResourceNotFoundError,
)
from servicios.models import TipoServicio
from servicios.services import (
    BuscarDisponibilidadDesdeApiService,
    CancelarSolicitudDesdeApiService,
    CrearSolicitudServicioAppService,
    ObtenerSolicitudServicioService,
)


logger = logging.getLogger(__name__)


def _respuesta_error_inesperado(operacion: str):
    logger.exception("Error interno inesperado en API de servicios (%s)", operacion)
    return Response(
        {"detail": "ocurrió un error interno inesperado"},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


class SolicitudServicioCreateAPIView(APIView):
    # endpoint drf para crear solicitud

    def post(self, request):
        # valida estructura de entrada
        in_serializer = SolicitudServicioCreateSerializer(data=request.data)
        if not in_serializer.is_valid():
            return Response(in_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            # delega al service layer
            solicitud = CrearSolicitudServicioAppService().crear_desde_api(
                in_serializer.validated_data
            )
        except ResourceNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except ConflictError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        except DomainValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            return _respuesta_error_inesperado("crear solicitud")

        # responde con la entidad creada
        out_serializer = SolicitudServicioSerializer(solicitud)
        return Response(out_serializer.data, status=status.HTTP_201_CREATED)


class SolicitudServicioDetailAPIView(APIView):
    # endpoint drf para consultar una solicitud puntual

    def get(self, request, solicitud_id):
        try:
            solicitud = ObtenerSolicitudServicioService().obtener(str(solicitud_id))
        except ResourceNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except Exception:
            return _respuesta_error_inesperado("detalle solicitud")

        out_serializer = SolicitudServicioSerializer(solicitud)
        return Response(out_serializer.data, status=status.HTTP_200_OK)


class SolicitudServicioCancelarAPIView(APIView):
    # endpoint drf para cancelar solicitud

    def post(self, request, solicitud_id):
        in_serializer = SolicitudServicioCancelSerializer(data=request.data)
        if not in_serializer.is_valid():
            return Response(in_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            solicitud = CancelarSolicitudDesdeApiService().cancelar(
                str(solicitud_id),
                in_serializer.validated_data["actor_id"],
            )
        except ResourceNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except ConflictError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        except DomainValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            return _respuesta_error_inesperado("cancelar solicitud")

        out_serializer = SolicitudServicioSerializer(solicitud)
        return Response(out_serializer.data, status=status.HTTP_200_OK)


class DisponibilidadCuidadoresAPIView(APIView):
    # endpoint drf para buscar cuidadores disponibles

    def post(self, request):
        in_serializer = DisponibilidadBusquedaSerializer(data=request.data)
        if not in_serializer.is_valid():
            return Response(in_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = in_serializer.validated_data

        try:
            resultados = BuscarDisponibilidadDesdeApiService().buscar(data)
        except ResourceNotFoundError as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        except ConflictError as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        except DomainValidationError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            return _respuesta_error_inesperado("buscar disponibilidad")

        payload = [
            self._map_resultado(item, data["tipoServicio"], data)
            for item in resultados
        ]
        out_serializer = DisponibilidadResultadoSerializer(payload, many=True)
        return Response(
            {
                "count": len(payload),
                "results": out_serializer.data,
            },
            status=status.HTTP_200_OK,
        )

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

    def _map_resultado(self, item: dict, tipo_servicio: str, data: dict) -> dict:
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

