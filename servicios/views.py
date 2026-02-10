from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.core.exceptions import ValidationError
from django.shortcuts import render
from servicios.models import Usuario, Mascota, BloqueTiempo
from servicios.services import SolicitudServicioService
from datetime import datetime
import json


@method_decorator(csrf_exempt, name='dispatch')
class CrearSolicitudServicioView(View):
    """vista para crear solicitudes - solo captura datos y llama al service"""
    
    def get(self, request):
        # muestra formulario básico con datos disponibles
        cuidadores = Usuario.objects.filter(rol__in=['cuidador', 'ambos'], verificado=True)
        mascotas = Mascota.objects.all()
        bloques = BloqueTiempo.objects.filter(disponible=True).select_related('idCuidador__idCuidador')
        # agrupar bloques por cuidador para el javascript
        bloques_por_cuidador = {}
        for bloque in bloques:
            cuidador_id = str(bloque.idCuidador.idCuidador.idUsuario)
            if cuidador_id not in bloques_por_cuidador:
                bloques_por_cuidador[cuidador_id] = []
            bloques_por_cuidador[cuidador_id].append({
                'id': str(bloque.idBloque),
                'texto': f"{bloque.diaSemana} {bloque.horaInicio}-{bloque.horaFin}"
            })
        return render(request, 'servicios/crear_solicitud.html', {
            'cuidadores': cuidadores,
            'mascotas': mascotas,
            'bloques_por_cuidador': json.dumps(bloques_por_cuidador)
        })
    
    def post(self, request):
        try:
            # captura datos y delega al service
            dueño = Usuario.objects.first()
            if not dueño:
                return self._render_error(request, 'no hay usuarios en la base de datos')
            datos = {'idDueño': dueño, 'idCuidador_id': request.POST.get('idCuidador_id'), 'idMascota_id': request.POST.get('idMascota_id'), 'tipoServicio': request.POST.get('tipoServicio'), 'fecha': datetime.strptime(request.POST.get('fecha'), '%Y-%m-%d').date(), 'idBloqueHorario_id': request.POST.get('idBloqueHorario_id')}
            solicitud = SolicitudServicioService().crear_solicitud(datos)
            return self._render_success(request, solicitud.idSolicitud)
        except (Usuario.DoesNotExist, ValidationError) as e:
            return self._render_error(request, str(e))
        except Exception as e:
            return self._render_error(request, str(e))
    
    def _get_context(self, mensaje=None, error=None):
        # contexto común para el template
        cuidadores = Usuario.objects.filter(rol__in=['cuidador', 'ambos'], verificado=True)
        bloques = BloqueTiempo.objects.filter(disponible=True).select_related('idCuidador__idCuidador')
        bloques_por_cuidador = {}
        for bloque in bloques:
            cuidador_id = str(bloque.idCuidador.idCuidador.idUsuario)
            if cuidador_id not in bloques_por_cuidador:
                bloques_por_cuidador[cuidador_id] = []
            bloques_por_cuidador[cuidador_id].append({
                'id': str(bloque.idBloque),
                'texto': f"{bloque.diaSemana} {bloque.horaInicio}-{bloque.horaFin}"
            })
        ctx = {'cuidadores': cuidadores, 'mascotas': Mascota.objects.all(), 'bloques_por_cuidador': json.dumps(bloques_por_cuidador)}
        if mensaje:
            ctx['mensaje'] = mensaje
        if error:
            ctx['error'] = error
        return ctx
    
    def _render_success(self, request, solicitud_id):
        return render(request, 'servicios/crear_solicitud.html', self._get_context(mensaje=f'Solicitud creada: {solicitud_id}'))
    
    def _render_error(self, request, error_msg):
        return render(request, 'servicios/crear_solicitud.html', self._get_context(error=error_msg))

