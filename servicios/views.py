from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.shortcuts import render

from servicios.domain.exceptions import DomainError
from servicios.services import CrearSolicitudServicioAppService


@method_decorator(csrf_exempt, name='dispatch')
class CrearSolicitudServicioView(View):
    # vista delgada: solo request/response
    
    def get(self, request):
        # pide contexto al app service
        ctx = CrearSolicitudServicioAppService().get_form_context()
        return render(request, "servicios/crear_solicitud.html", ctx)
    
    def post(self, request):
        try:
            # delega el caso de uso al app service
            service = CrearSolicitudServicioAppService()
            solicitud = service.crear_desde_form(request.POST)

            ctx = service.get_form_context()
            ctx["mensaje"] = f"Solicitud creada: {solicitud.idSolicitud}"
            return render(request, "servicios/crear_solicitud.html", ctx)
        except DomainError as e:
            return self._render_error(request, str(e))
        except Exception as e:
            return self._render_error(request, str(e))
    
    def _render_error(self, request, error_msg):
        # reusa contexto del formulario en caso de error
        service = CrearSolicitudServicioAppService()
        ctx = service.get_form_context()
        ctx["error"] = error_msg
        return render(request, "servicios/crear_solicitud.html", ctx)

