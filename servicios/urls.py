# urls de la app servicios
from django.urls import path
from servicios.views import CrearSolicitudServicioView

urlpatterns = [
    path('solicitud/crear/', CrearSolicitudServicioView.as_view(), name='crear_solicitud'),
]

