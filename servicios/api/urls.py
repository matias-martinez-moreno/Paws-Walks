from django.urls import path

from servicios.api.views import (
    AliadoAPIView,
    ClimaAPIView,
    DisponibilidadCuidadoresAPIView,
    SolicitudServicioCancelarAPIView,
    SolicitudServicioCreateAPIView,
    SolicitudServicioDetailAPIView,
    SistemaEstadoAPIView,
    CuidadoresListadoAPIView,
)

app_name = "servicios_api"

urlpatterns = [
    path("v1/solicitudes/", SolicitudServicioCreateAPIView.as_view(), name="crear_solicitud"),
    path("v1/solicitudes/<uuid:solicitud_id>/", SolicitudServicioDetailAPIView.as_view(), name="detalle_solicitud"),
    path("v1/solicitudes/<uuid:solicitud_id>/cancelar/", SolicitudServicioCancelarAPIView.as_view(), name="cancelar_solicitud"),
    path("v1/disponibilidad/", DisponibilidadCuidadoresAPIView.as_view(), name="disponibilidad_cuidadores"),
    path("v1/clima/", ClimaAPIView.as_view(), name="clima_ciudad"),
    path("v1/sistema/estado/", SistemaEstadoAPIView.as_view(), name="sistema_estado"),
    path("v1/cuidadores/listado/", CuidadoresListadoAPIView.as_view(), name="cuidadores_listado"),
    path("v1/aliado/estado/", AliadoAPIView.as_view(), name="aliado_estado"),
]
