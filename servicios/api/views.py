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
from servicios.application.api_services import (
    MapearErroresApiService,
    ServiciosApiGatewayService,
)


class BaseServiciosAPIView(APIView):
    """Base APIView para centralizar traducción de errores de dominio."""

    _error_mapper = MapearErroresApiService(logger_name=__name__)
    _gateway = ServiciosApiGatewayService()

    def _respuesta_error(self, exc: Exception, operacion: str):
        payload, status_code = self._error_mapper.mapear(exc, operacion)
        return Response(payload, status=status_code)


class SolicitudServicioCreateAPIView(BaseServiciosAPIView):
    # endpoint drf para crear solicitud

    def post(self, request):
        # valida estructura de entrada
        in_serializer = SolicitudServicioCreateSerializer(data=request.data)
        if not in_serializer.is_valid():
            return Response(in_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            # delega al service layer
            solicitud = self._gateway.crear_solicitud(
                in_serializer.validated_data
            )
        except Exception as exc:
            return self._respuesta_error(exc, "crear solicitud")

        # responde con la entidad creada
        out_serializer = SolicitudServicioSerializer(solicitud)
        return Response(out_serializer.data, status=status.HTTP_201_CREATED)


class SolicitudServicioDetailAPIView(BaseServiciosAPIView):
    # endpoint drf para consultar una solicitud puntual

    def get(self, request, solicitud_id):
        try:
            solicitud = self._gateway.obtener_solicitud(str(solicitud_id))
        except Exception as exc:
            return self._respuesta_error(exc, "detalle solicitud")

        out_serializer = SolicitudServicioSerializer(solicitud)
        return Response(out_serializer.data, status=status.HTTP_200_OK)


class SolicitudServicioCancelarAPIView(BaseServiciosAPIView):
    # endpoint drf para cancelar solicitud

    def post(self, request, solicitud_id):
        in_serializer = SolicitudServicioCancelSerializer(data=request.data)
        if not in_serializer.is_valid():
            return Response(in_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            solicitud = self._gateway.cancelar_solicitud(
                str(solicitud_id),
                in_serializer.validated_data["actor_id"],
            )
        except Exception as exc:
            return self._respuesta_error(exc, "cancelar solicitud")

        out_serializer = SolicitudServicioSerializer(solicitud)
        return Response(out_serializer.data, status=status.HTTP_200_OK)


class DisponibilidadCuidadoresAPIView(BaseServiciosAPIView):
    # endpoint drf para buscar cuidadores disponibles

    def post(self, request):
        in_serializer = DisponibilidadBusquedaSerializer(data=request.data)
        if not in_serializer.is_valid():
            return Response(in_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = in_serializer.validated_data

        try:
            payload = self._gateway.buscar_disponibilidad(data)
        except Exception as exc:
            return self._respuesta_error(exc, "buscar disponibilidad")

        out_serializer = DisponibilidadResultadoSerializer(payload, many=True)
        return Response(
            {
                "count": len(payload),
                "results": out_serializer.data,
            },
            status=status.HTTP_200_OK,
        )

