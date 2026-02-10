# comando para crear datos de prueba
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from servicios.models import Usuario, Mascota, PerfilCuidador, BloqueTiempo, PrecioServicio
from datetime import time


class Command(BaseCommand):
    help = 'crea datos de prueba para el sistema'

    def handle(self, *args, **options):
        # limpiar datos anteriores si existen
        BloqueTiempo.objects.all().update(disponible=True)
        
        # crear usuario dueño si no existe
        user_dueño, _ = User.objects.get_or_create(
            username='dueño1',
            defaults={'email': 'dueño@test.com'}
        )
        user_dueño.set_password('test123')
        user_dueño.save()
        
        dueño, _ = Usuario.objects.get_or_create(
            user=user_dueño,
            defaults={
                'nombre': 'Juan Dueño',
                'correo': 'dueño@test.com',
                'rol': 'dueño',
                'verificado': True
            }
        )
        
        # crear usuario cuidador si no existe
        user_cuidador, _ = User.objects.get_or_create(
            username='cuidador1',
            defaults={'email': 'cuidador@test.com'}
        )
        user_cuidador.set_password('test123')
        user_cuidador.save()
        
        cuidador, _ = Usuario.objects.get_or_create(
            user=user_cuidador,
            defaults={
                'nombre': 'María Cuidador',
                'correo': 'cuidador@test.com',
                'rol': 'cuidador',
                'verificado': True
            }
        )
        
        # crear perfil de cuidador
        perfil, _ = PerfilCuidador.objects.get_or_create(
            idCuidador=cuidador,
            defaults={'tipoServicio': 'paseo'}
        )
        
        # crear precio de servicio
        PrecioServicio.objects.get_or_create(
            idCuidador=cuidador,
            tipoServicio='paseo',
            defaults={'precioCOP': 50000, 'activo': True}
        )
        
        # crear mascota
        mascota, _ = Mascota.objects.get_or_create(
            idDueño=dueño,
            nombreMascota='Firulais',
            defaults={'tipo': 'perro', 'edad': 3}
        )
        
        # crear múltiples bloques disponibles
        dias = ['lunes', 'martes', 'miercoles', 'jueves', 'viernes']
        horas = [
            (time(9, 0), time(11, 0)),
            (time(14, 0), time(16, 0)),
            (time(17, 0), time(19, 0))
        ]
        
        bloques_creados = 0
        for dia in dias:
            for hora_inicio, hora_fin in horas:
                bloque, created = BloqueTiempo.objects.get_or_create(
                    idCuidador=perfil,
                    diaSemana=dia,
                    horaInicio=hora_inicio,
                    horaFin=hora_fin,
                    defaults={'disponible': True}
                )
                if created:
                    bloques_creados += 1
                else:
                    bloque.disponible = True
                    bloque.save()
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Datos creados: {bloques_creados} bloques nuevos, '
                f'total bloques disponibles: {BloqueTiempo.objects.filter(disponible=True).count()}'
            )
        )

