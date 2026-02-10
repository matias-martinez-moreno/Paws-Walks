from django.views import View
from django.http import JsonResponse
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.core.exceptions import ValidationError
from servicios.models import Usuario
from servicios.services import SolicitudServicioService
from datetime import datetime


@method_decorator(csrf_exempt, name='dispatch')
class CrearSolicitudServicioView(LoginRequiredMixin, View):
    """
    Vista basada en clase para crear solicitudes de servicio.
    Responsabilidad única: capturar datos del request y llamar al Service.
    """
    
    def post(self, request):
        try:
            datos = {'idDueño': Usuario.objects.get(user=request.user), 'idCuidador_id': request.POST.get('idCuidador_id'), 'idMascota_id': request.POST.get('idMascota_id'), 'tipoServicio': request.POST.get('tipoServicio'), 'fecha': datetime.strptime(request.POST.get('fecha'), '%Y-%m-%d').date(), 'idBloqueHorario_id': request.POST.get('idBloqueHorario_id')}
            solicitud = SolicitudServicioService().crear_solicitud(datos)
            return JsonResponse({'success': True, 'idSolicitud': str(solicitud.idSolicitud), 'mensaje': 'Solicitud creada exitosamente'}, status=201)
        except (Usuario.DoesNotExist, ValidationError) as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=404 if isinstance(e, Usuario.DoesNotExist) else 400)
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)

