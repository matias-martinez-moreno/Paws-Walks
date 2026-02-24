# rutas de la app servicios
from django.urls import path
from servicios.api.views import SolicitudServicioCreateAPIView
from servicios.views import CrearSolicitudServicioView

urlpatterns = [
    path('solicitud/crear/', CrearSolicitudServicioView.as_view(), name='crear_solicitud'),
    # endpoint api para crear solicitudes
    path("v1/solicitudes/", SolicitudServicioCreateAPIView.as_view(), name="api_crear_solicitud"),
]

