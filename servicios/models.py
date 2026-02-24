from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from decimal import Decimal
import uuid
from datetime import date


class TipoMascota(models.TextChoices):
    PERRO = 'perro', 'Perro'
    GATO = 'gato', 'Gato'
    OTRO = 'otro', 'Otro'


class RolUsuario(models.TextChoices):
    DUEÑO = 'dueño', 'Dueño'
    CUIDADOR = 'cuidador', 'Cuidador'
    AMBOS = 'ambos', 'Ambos'


class TipoServicio(models.TextChoices):
    PASEO = 'paseo', 'Paseo'
    GUARDERIA = 'guarderia', 'Guardería'
    OTRO = 'otro', 'Otro'


class DiaSemana(models.TextChoices):
    LUNES = 'lunes', 'Lunes'
    MARTES = 'martes', 'Martes'
    MIERCOLES = 'miercoles', 'Miércoles'
    JUEVES = 'jueves', 'Jueves'
    VIERNES = 'viernes', 'Viernes'
    SABADO = 'sabado', 'Sábado'
    DOMINGO = 'domingo', 'Domingo'


class EstadoSolicitud(models.TextChoices):
    PENDIENTE = 'pendiente', 'Pendiente'
    ACEPTADO = 'aceptado', 'Aceptado'
    RECHAZADO = 'rechazado', 'Rechazado'
    COMPLETADO = 'completado', 'Completado'


class Usuario(models.Model):
    """
    Extiende el modelo User de Django con campos adicionales del dominio.
    """
    idUsuario = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='perfil_usuario')
    nombre = models.CharField(max_length=100)
    correo = models.EmailField(unique=True)
    rol = models.CharField(max_length=20, choices=RolUsuario.choices)
    fotoPerfil = models.URLField(blank=True, null=True)
    verificado = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nombre} ({self.rol})"


class Mascota(models.Model):
    idMascota = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idDueño = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='mascotas')
    nombreMascota = models.CharField(max_length=100)
    tipo = models.CharField(max_length=20, choices=TipoMascota.choices)
    edad = models.IntegerField(validators=[MinValueValidator(0)])
    notas = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nombreMascota} ({self.tipo})"


class PerfilCuidador(models.Model):
    idCuidador = models.OneToOneField(
        Usuario, 
        on_delete=models.CASCADE, 
        primary_key=True,
        related_name='perfil_cuidador'
    )
    tipoServicio = models.CharField(max_length=20, choices=TipoServicio.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Cuidador: {self.idCuidador.nombre}"


class BloqueTiempo(models.Model):
    idBloque = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idCuidador = models.ForeignKey(PerfilCuidador, on_delete=models.CASCADE, related_name='bloques_tiempo')
    diaSemana = models.CharField(max_length=20, choices=DiaSemana.choices)
    horaInicio = models.TimeField()
    horaFin = models.TimeField()
    disponible = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['idCuidador', 'diaSemana', 'horaInicio', 'horaFin']

    def clean(self):
        # regla: hora fin debe ser mayor a hora inicio
        if self.horaFin <= self.horaInicio:
            raise ValidationError("La hora de fin debe ser mayor que la hora de inicio.")

    def __str__(self):
        return f"{self.idCuidador.idCuidador.nombre} - {self.diaSemana} {self.horaInicio}"

class PrecioServicio(models.Model):
    idPrecio = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idCuidador = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='precios_servicio')
    tipoServicio = models.CharField(max_length=20, choices=TipoServicio.choices)
    precioCOP = models.IntegerField(validators=[MinValueValidator(1)])
    activo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['idCuidador', 'tipoServicio']

    def __str__(self):
        return f"{self.idCuidador.nombre} - {self.tipoServicio}: ${self.precioCOP} COP"


class SolicitudServicio(models.Model):
    idSolicitud = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idDueño = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='solicitudes_enviadas')
    idCuidador = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='solicitudes_recibidas')
    idMascota = models.ForeignKey(Mascota, on_delete=models.CASCADE, related_name='solicitudes')
    tipoServicio = models.CharField(max_length=20, choices=TipoServicio.choices)
    fecha = models.DateField()
    idBloqueHorario = models.ForeignKey(BloqueTiempo, on_delete=models.CASCADE, related_name='solicitudes')
    estado = models.CharField(max_length=20, choices=EstadoSolicitud.choices, default=EstadoSolicitud.PENDIENTE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        # regla: no permitir fechas pasadas
        if self.fecha and self.fecha < date.today():
            raise ValidationError("La fecha del servicio no puede ser en el pasado.")

    def __str__(self):
        return f"Solicitud {self.idSolicitud} - {self.idDueño.nombre} -> {self.idCuidador.nombre}"


class Calificacion(models.Model):
    idCalificación = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idDe = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='calificaciones_dadas')
    idParaCuidador = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='calificaciones_recibidas')
    estrellas = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comentario = models.TextField(blank=True)
    fecha = models.DateField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Calificación {self.estrellas}/5 - {self.idDe.nombre} -> {self.idParaCuidador.nombre}"

