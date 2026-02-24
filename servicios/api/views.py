from django.core.exceptions import ValidationError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from servicios.api.serializers import (
    SolicitudServicioCreateSerializer,
    SolicitudServicioSerializer,
)
from servicios.services import CrearSolicitudServicioAppService


def _status_from_validation_error(err: ValidationError) -> int:
    # traduce errores de dominio a codigos http
    msg = str(err).lower()
    if "no existe" in msg:
        return status.HTTP_404_NOT_FOUND
    if "no está disponible" in msg or "no pertenece" in msg or "conflict" in msg:
        return status.HTTP_409_CONFLICT
    return status.HTTP_400_BAD_REQUEST


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
        except ValidationError as e:
            # devuelve 400, 404 o 409 segun el dominio
            return Response(
                {"detail": str(e)},
                status=_status_from_validation_error(e),
            )

        # responde con la entidad creada
        out_serializer = SolicitudServicioSerializer(solicitud)
        return Response(out_serializer.data, status=status.HTTP_201_CREATED)

