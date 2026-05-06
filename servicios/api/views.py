from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Count, Q
from django.utils import timezone

from servicios.domain.exceptions import DomainError
from servicios.api.serializers import (
    DisponibilidadBusquedaSerializer,
    DisponibilidadResultadoSerializer,
    SolicitudServicioCreateSerializer,
    SolicitudServicioCancelSerializer,
    SolicitudServicioSerializer,
)
from servicios.services import (
    MapearErroresApiService,
    PoliticaAccesoServiciosApiService,
    ServiciosApiGatewayService,
)


class BaseServiciosAPIView(APIView):
    """Base APIView para centralizar traducción de errores de dominio."""

    permission_classes = [IsAuthenticated]
    _error_mapper = MapearErroresApiService(logger_name=__name__)
    _policy = PoliticaAccesoServiciosApiService()
    _gateway = ServiciosApiGatewayService()

    def _respuesta_error(self, exc: Exception, operacion: str):
        payload, status_code = self._error_mapper.mapear(exc, operacion)
        return Response(payload, status=status_code)


class SolicitudServicioCreateAPIView(BaseServiciosAPIView):
    # endpoint drf para crear solicitud

    def post(self, request):
        try:
            actor = self._policy.resolver_actor(request.user)
            self._policy.exigir_rol_dueño_para_crear(actor)
        except DomainError as exc:
            return self._respuesta_error(exc, "crear solicitud")
        except Exception as exc:
            return self._respuesta_error(exc, "crear solicitud")

        # valida estructura de entrada
        in_serializer = SolicitudServicioCreateSerializer(data=request.data)
        if not in_serializer.is_valid():
            return Response(in_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            data = self._policy.forzar_dueño_del_actor(
                in_serializer.validated_data,
                actor,
                mismatch_msg="no puedes crear solicitudes para otro dueño",
            )
            # delega al service layer
            solicitud = self._gateway.crear_solicitud(data)
        except DomainError as exc:
            return self._respuesta_error(exc, "crear solicitud")
        except Exception as exc:
            return self._respuesta_error(exc, "crear solicitud")

        # responde con la entidad creada
        out_serializer = SolicitudServicioSerializer(solicitud)
        return Response(out_serializer.data, status=status.HTTP_201_CREATED)


class SolicitudServicioDetailAPIView(BaseServiciosAPIView):
    # endpoint drf para consultar una solicitud puntual

    def get(self, request, solicitud_id):
        try:
            actor = self._policy.resolver_actor(request.user)
            solicitud = self._gateway.obtener_solicitud(str(solicitud_id))
            self._policy.validar_participacion_en_solicitud(actor, solicitud)
        except DomainError as exc:
            return self._respuesta_error(exc, "detalle solicitud")
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
            actor = self._policy.resolver_actor(request.user)
            actor_id = self._policy.validar_actor_cancelacion(
                actor,
                in_serializer.validated_data.get("actor_id"),
            )
            solicitud = self._gateway.cancelar_solicitud(
                str(solicitud_id),
                actor_id,
            )
        except DomainError as exc:
            return self._respuesta_error(exc, "cancelar solicitud")
        except Exception as exc:
            return self._respuesta_error(exc, "cancelar solicitud")

        out_serializer = SolicitudServicioSerializer(solicitud)
        return Response(out_serializer.data, status=status.HTTP_200_OK)


class ClimaAPIView(BaseServiciosAPIView):
    # endpoint para consultar el clima de una ciudad (Adapter pattern)

    def get(self, request):
        ciudad = request.query_params.get("ciudad", "").strip()
        if not ciudad:
            return Response({"error": "Parámetro 'ciudad' requerido."}, status=status.HTTP_400_BAD_REQUEST)
        resultado = self._gateway.obtener_clima_ciudad(ciudad)
        return Response(resultado, status=status.HTTP_200_OK)


class AliadoAPIView(APIView):
    """Consume el endpoint del equipo aliado vía AliadoPort (Adapter pattern).

    Si ALIADO_API_URL no está configurada, usa AliadoMockAdapter.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        gateway = ServiciosApiGatewayService()
        return Response(gateway.obtener_estado_aliado(), status=status.HTTP_200_OK)


class DisponibilidadCuidadoresAPIView(BaseServiciosAPIView):
    # endpoint drf para buscar cuidadores disponibles

    def post(self, request):
        try:
            actor = self._policy.resolver_actor(request.user)
            self._policy.exigir_rol_dueño_para_buscar(actor)
        except DomainError as exc:
            return self._respuesta_error(exc, "buscar disponibilidad")
        except Exception as exc:
            return self._respuesta_error(exc, "buscar disponibilidad")

        in_serializer = DisponibilidadBusquedaSerializer(data=request.data)
        if not in_serializer.is_valid():
            return Response(in_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            data = self._policy.forzar_dueño_del_actor(
                in_serializer.validated_data,
                actor,
                mismatch_msg="no puedes buscar disponibilidad para otro dueño",
            )
            payload = self._gateway.buscar_disponibilidad(data)
        except DomainError as exc:
            return self._respuesta_error(exc, "buscar disponibilidad")
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


class SistemaEstadoAPIView(APIView):
    """Endpoint público: estado general del sistema para consumo externo."""
    permission_classes = [AllowAny]

    def get(self, request):
        from servicios.models import Usuario, SolicitudServicio, Calificacion
        from datetime import timedelta

        try:
            total_usuarios = Usuario.objects.count()
            total_dueños = Usuario.objects.filter(rol='dueño').count()
            total_cuidadores = Usuario.objects.filter(rol='cuidador').count()

            total_solicitudes = SolicitudServicio.objects.count()
            solicitudes_completadas = SolicitudServicio.objects.filter(estado='completado').count()
            solicitudes_pendientes = SolicitudServicio.objects.filter(estado='pendiente').count()

            total_resenas = Calificacion.objects.count()

            hoy = timezone.now().date()
            hace_30_dias = hoy - timedelta(days=30)
            solicitudes_mes = SolicitudServicio.objects.filter(
                fecha__gte=hace_30_dias
            ).count()

            return Response({
                "sistema": "Paws & Walks - Plataforma de Cuidado de Mascotas",
                "timestamp": timezone.now().isoformat(),
                "usuarios": {
                    "total": total_usuarios,
                    "dueños": total_dueños,
                    "cuidadores": total_cuidadores,
                },
                "solicitudes": {
                    "total": total_solicitudes,
                    "completadas": solicitudes_completadas,
                    "pendientes": solicitudes_pendientes,
                    "ultimo_mes": solicitudes_mes,
                },
                "reseñas": {
                    "total": total_resenas,
                },
                "estado": "operativo"
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {"error": str(e), "estado": "error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class CuidadoresListadoAPIView(APIView):
    """Endpoint público: listado de cuidadores disponibles para consumo externo."""
    permission_classes = [AllowAny]

    def get(self, request):
        from django.db.models import Avg
        from servicios.models import Usuario, Calificacion

        try:
            cuidadores = Usuario.objects.filter(rol='cuidador', verificado=True)

            result = []
            for cuidador in cuidadores:
                resenas = Calificacion.objects.filter(idParaUsuario=cuidador)
                promedio = resenas.aggregate(avg=Avg('estrellas'))['avg'] or 0

                result.append({
                    "id": str(cuidador.idUsuario),
                    "nombre": f"{cuidador.nombre} {cuidador.apellido}",
                    "ciudad": cuidador.ciudad,
                    "foto": cuidador.fotoPerfil.url if cuidador.fotoPerfil else None,
                    "verificado": cuidador.verificado,
                    "total_reseñas": resenas.count(),
                    "rating_promedio": round(float(promedio), 2),
                })

            return Response({
                "count": len(result),
                "resultados": result,
                "timestamp": timezone.now().isoformat()
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {"error": str(e), "estado": "error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

