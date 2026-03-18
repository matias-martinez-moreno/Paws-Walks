from django.urls import path

from servicios.api.views import (
    DisponibilidadCuidadoresAPIView,
    SolicitudServicioCancelarAPIView,
    SolicitudServicioCreateAPIView,
    SolicitudServicioDetailAPIView,
)

app_name = "servicios_api"

urlpatterns = [
    path("v1/solicitudes/", SolicitudServicioCreateAPIView.as_view(), name="crear_solicitud"),
    path("v1/solicitudes/<uuid:solicitud_id>/", SolicitudServicioDetailAPIView.as_view(), name="detalle_solicitud"),
    path("v1/solicitudes/<uuid:solicitud_id>/cancelar/", SolicitudServicioCancelarAPIView.as_view(), name="cancelar_solicitud"),
    path("v1/disponibilidad/", DisponibilidadCuidadoresAPIView.as_view(), name="disponibilidad_cuidadores"),
]
