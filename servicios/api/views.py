from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from servicios.api.serializers import (
    SolicitudServicioCreateSerializer,
    SolicitudServicioSerializer,
)
from servicios.domain.exceptions import (
    ConflictError,
    DomainValidationError,
    ResourceNotFoundError,
)
from servicios.services import CrearSolicitudServicioAppService


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

        # responde con la entidad creada
        out_serializer = SolicitudServicioSerializer(solicitud)
        return Response(out_serializer.data, status=status.HTTP_201_CREATED)

