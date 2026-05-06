from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.translation import gettext_lazy as _
from decimal import Decimal
import uuid


class TipoMascota(models.TextChoices):
    PERRO = 'perro', _('Perro')
    GATO = 'gato', _('Gato')


class SexoMascota(models.TextChoices):
    MACHO = 'macho', _('Macho')
    HEMBRA = 'hembra', _('Hembra')


class TamanoMascota(models.TextChoices):
    PEQUENO = 'pequeno', _('Pequeño')
    MEDIANO = 'mediano', _('Mediano')
    GRANDE = 'grande', _('Grande')


class RolUsuario(models.TextChoices):
    DUEÑO = 'dueño', _('Dueño')
    CUIDADOR = 'cuidador', _('Cuidador')


class TipoServicio(models.TextChoices):
    PASEO = 'paseo', _('Paseo')
    GUARDERIA = 'guarderia', _('Guardería')


class DiaSemana(models.TextChoices):
    LUNES = 'lunes', _('Lunes')
    MARTES = 'martes', _('Martes')
    MIERCOLES = 'miercoles', _('Miércoles')
    JUEVES = 'jueves', _('Jueves')
    VIERNES = 'viernes', _('Viernes')
    SABADO = 'sabado', _('Sábado')
    DOMINGO = 'domingo', _('Domingo')


class EstadoSolicitud(models.TextChoices):
    PENDIENTE = 'pendiente', _('Pendiente')
    ACEPTADO = 'aceptado', _('Aceptado')
    RECHAZADO = 'rechazado', _('Rechazado')
    CANCELADO = 'cancelado', _('Cancelado')
    COMPLETADO = 'completado', _('Finalizado')


class Usuario(models.Model):
    """
    Extiende el modelo User de Django con campos adicionales del dominio.
    """
    idUsuario = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='perfil_usuario')
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    username = models.CharField(max_length=150, unique=True)
    correo = models.EmailField()
    cedula = models.CharField(max_length=20, unique=True)
    telefono = models.CharField(max_length=20)
    fechaNacimiento = models.DateField()
    ciudad = models.CharField(max_length=100)
    direccion = models.CharField(max_length=200, blank=True, default='')
    latitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, help_text="Para búsqueda por proximidad")
    longitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, help_text="Para búsqueda por proximidad")
    radioKm = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(3)], help_text="Radio de cobertura en km (solo cuidadores, 1-3 km)")
    rol = models.CharField(max_length=20, choices=RolUsuario.choices)
    fotoPerfil = models.ImageField(upload_to='perfiles/', blank=True, null=True)
    verificado = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nombre} {self.apellido} ({self.rol})"


class Mascota(models.Model):
    idMascota = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idDueño = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='mascotas')
    nombreMascota = models.CharField(max_length=100)
    tipo = models.CharField(max_length=20, choices=TipoMascota.choices)
    foto = models.ImageField(upload_to='mascotas/', blank=True, null=True)
    raza = models.CharField(max_length=100, blank=True, default='')
    sexo = models.CharField(max_length=10, choices=SexoMascota.choices, blank=True, default='')
    tamano = models.CharField(max_length=20, choices=TamanoMascota.choices, blank=True, default='')
    edad = models.IntegerField(validators=[MinValueValidator(0)])
    peso = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    esterilizado = models.BooleanField(default=False)
    vacunasAlDia = models.BooleanField(default=False)
    condicionesMedicas = models.TextField(blank=True, default='')
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
    descripcion = models.TextField(blank=True, default='')
    tarifaHora = models.IntegerField(validators=[MinValueValidator(0)], default=0)
    tiposMascotaPreferidos = models.CharField(max_length=50, default='ambos', help_text="perro, gato o ambos")
    ciudadServicio = models.CharField(max_length=100, blank=True, default='', help_text="Ciudad operativa usada en búsqueda de servicios")
    latitudServicio = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, help_text="Ubicación operativa para servicios")
    longitudServicio = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, help_text="Ubicación operativa para servicios")
    radioKmServicio = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(3)],
        help_text="Radio de cobertura operativo en km (1-3)",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Cuidador: {self.idCuidador.nombre}"


class BloqueTiempo(models.Model):
    """Bloque de disponibilidad individual de un cuidador (reunión 1:1)."""
    idBloque = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idCuidador = models.ForeignKey(PerfilCuidador, on_delete=models.CASCADE, related_name='bloques_tiempo')
    tipoServicio = models.CharField(max_length=20, choices=TipoServicio.choices, default=TipoServicio.PASEO)
    diaSemana = models.CharField(max_length=20, choices=DiaSemana.choices)
    horaInicio = models.TimeField()
    horaFin = models.TimeField()
    disponible = models.BooleanField(default=True)
    nombreLugar = models.CharField(max_length=120, blank=True, default='', help_text="Nombre del lugar (ej: Casa norte, Apartamento centro)")
    latitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, help_text="Ubicación del lugar")
    longitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, help_text="Ubicación del lugar")
    precioCOP = models.IntegerField(null=True, blank=True, help_text="Precio por reunión. Si vacío, usa tarifa global.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['idCuidador', 'tipoServicio', 'diaSemana', 'horaInicio', 'horaFin', 'nombreLugar']]

    def __str__(self):
        return f"{self.idCuidador.idCuidador.nombre} - {self.diaSemana} {self.horaInicio}"


class VentanaDisponibilidad(models.Model):
    """Ventana de disponibilidad con slots para paseos grupales."""
    idVentana = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idCuidador = models.ForeignKey(PerfilCuidador, on_delete=models.CASCADE, related_name='ventanas_disponibilidad')
    tipoServicio = models.CharField(max_length=20, choices=TipoServicio.choices, default=TipoServicio.PASEO)
    diaSemana = models.CharField(max_length=20, choices=DiaSemana.choices)
    horaInicio = models.TimeField()
    horaFin = models.TimeField()
    duracionSlotMinutos = models.IntegerField(default=30, validators=[MinValueValidator(15), MaxValueValidator(120)])
    capacidadMaxima = models.IntegerField(default=5, validators=[MinValueValidator(1), MaxValueValidator(20)])
    nombreLugar = models.CharField(max_length=120, blank=True, default='', help_text="Lugar del paseo (ej: Parque Norte, Zona centro)")
    latitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    precioCOP = models.IntegerField(null=True, blank=True, help_text="Precio por reunión. Si vacío, usa tarifa global.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['idCuidador', 'tipoServicio', 'diaSemana', 'horaInicio', 'horaFin', 'nombreLugar']]

    def __str__(self):
        return f"{self.idCuidador.idCuidador.nombre} - {self.diaSemana} {self.horaInicio}-{self.horaFin}"


class SlotDisponibilidad(models.Model):
    """Slot de tiempo dentro de una ventana de disponibilidad."""
    idSlot = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idVentana = models.ForeignKey(VentanaDisponibilidad, on_delete=models.CASCADE, related_name='slots')
    horaInicio = models.TimeField()
    disponible = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['idVentana', 'horaInicio']

    def __str__(self):
        return f"{self.idVentana} - {self.horaInicio}"


class Evento(models.Model):
    """Evento/reunión ofrecido por el cuidador. Unifica paseo y guardería como artículos de marketplace."""
    idEvento = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idCuidador = models.ForeignKey(PerfilCuidador, on_delete=models.CASCADE, related_name='eventos')
    tipoServicio = models.CharField(max_length=20, choices=TipoServicio.choices)

    nombreLugar = models.CharField(max_length=120, blank=True, default='')
    descripcion = models.TextField(blank=True, default='')
    latitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    diaSemana = models.CharField(max_length=20, choices=DiaSemana.choices)
    horaInicio = models.TimeField()
    horaFin = models.TimeField()

    precioCOP = models.IntegerField(null=True, blank=True)
    capacidadMaxima = models.IntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(20)])
    duracionSlotMinutos = models.IntegerField(null=True, blank=True)
    disponible = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['idCuidador', 'tipoServicio', 'diaSemana', 'horaInicio', 'horaFin', 'nombreLugar']]

    def __str__(self):
        return f"{self.idCuidador.idCuidador.nombre} - {self.diaSemana} {self.horaInicio}-{self.horaFin}"


class SlotEvento(models.Model):
    """Slot dentro de un evento (paseo con cupos)."""
    idSlot = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idEvento = models.ForeignKey(Evento, on_delete=models.CASCADE, related_name='slots')
    horaInicio = models.TimeField()
    disponible = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['idEvento', 'horaInicio']

    def __str__(self):
        return f"{self.idEvento} - {self.horaInicio}"


class PrecioServicio(models.Model):
    idPrecio = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idCuidador = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='precios_servicio')
    tipoServicio = models.CharField(max_length=20, choices=TipoServicio.choices)
    precioCOP = models.IntegerField(validators=[MinValueValidator(1)])
    descripcion = models.TextField(blank=True, default='')
    activo = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['idCuidador', 'tipoServicio']

    def __str__(self):
        return f"{self.idCuidador.nombre} - {self.tipoServicio}: ${self.precioCOP} COP"


class EstadoPago(models.TextChoices):
    PENDIENTE = 'pendiente', _('Pendiente')
    PROCESANDO = 'procesando', _('Procesando')
    COMPLETADO = 'completado', _('Completado')
    RECHAZADO = 'rechazado', _('Rechazado')
    REEMBOLSADO = 'reembolsado', _('Reembolsado')


class SolicitudServicio(models.Model):
    idSolicitud = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idDueño = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='solicitudes_enviadas')
    idCuidador = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='solicitudes_recibidas')
    idMascota = models.ForeignKey(Mascota, on_delete=models.CASCADE, related_name='solicitudes')
    tipoServicio = models.CharField(max_length=20, choices=TipoServicio.choices)
    fecha = models.DateField()
    fechaFin = models.DateField(null=True, blank=True, help_text="Solo para guardería/cuidado; paseo usa solo fecha.")
    idEvento = models.ForeignKey(Evento, on_delete=models.CASCADE, related_name='solicitudes', null=True, blank=True)
    idSlotEvento = models.ForeignKey(SlotEvento, on_delete=models.CASCADE, related_name='solicitudes', null=True, blank=True)
    idBloqueHorario = models.ForeignKey(BloqueTiempo, on_delete=models.CASCADE, related_name='solicitudes', null=True, blank=True)
    idVentana = models.ForeignKey(VentanaDisponibilidad, on_delete=models.CASCADE, related_name='solicitudes', null=True, blank=True)
    idSlot = models.ForeignKey(SlotDisponibilidad, on_delete=models.CASCADE, related_name='solicitudes', null=True, blank=True)
    horaRecogidaAsignada = models.TimeField(null=True, blank=True, help_text="Asignada por el sistema según ruta")
    ordenEnRuta = models.PositiveIntegerField(default=1, help_text="Orden en el paseo grupal")
    estado = models.CharField(max_length=20, choices=EstadoSolicitud.choices, default=EstadoSolicitud.PENDIENTE)
    estado_pago = models.CharField(max_length=20, choices=EstadoPago.choices, default=EstadoPago.PENDIENTE)
    monto_pago = models.IntegerField(validators=[MinValueValidator(0)], null=True, blank=True)
    referencia_pago = models.CharField(max_length=200, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Solicitud {self.idSolicitud} - {self.idDueño.nombre} -> {self.idCuidador.nombre}"


class Calificacion(models.Model):
    idCalificación = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idDe = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='calificaciones_dadas')
    idParaUsuario = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='calificaciones_recibidas')
    idSolicitud = models.ForeignKey(SolicitudServicio, on_delete=models.CASCADE, null=True, blank=True, related_name='calificaciones')
    estrellas = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comentario = models.TextField(blank=True)
    fecha = models.DateField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['idSolicitud', 'idDe'], name='uniq_calificacion_solicitud_autor'),
        ]

    def __str__(self):
        return f"Calificación {self.estrellas}/5 - {self.idDe.nombre} -> {self.idParaUsuario.nombre}"


class CalificacionMascota(models.Model):
    idCalificacionMascota = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idDe = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='calificaciones_mascota_dadas')
    idParaMascota = models.ForeignKey(Mascota, on_delete=models.CASCADE, related_name='calificaciones_recibidas')
    idSolicitud = models.ForeignKey(SolicitudServicio, on_delete=models.CASCADE, null=True, blank=True, related_name='calificaciones_mascota')
    estrellas = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comentario = models.TextField(blank=True)
    fecha = models.DateField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['idSolicitud', 'idDe'], name='uniq_calificacion_mascota_solicitud_autor'),
        ]

    def __str__(self):
        return f"Calificación mascota {self.estrellas}/5 - {self.idDe.nombre} -> {self.idParaMascota.nombreMascota}"


class CategoriaNotificacion(models.TextChoices):
    NEGOCIO = 'negocio', _('Negocio')
    SISTEMA = 'sistema', _('Sistema')


class TipoNotificacion(models.TextChoices):
    NUEVA_RESERVA = 'nueva_reserva', _('Nueva reserva')
    RESERVA_ACEPTADA = 'reserva_aceptada', _('Reserva aceptada')
    RESERVA_RECHAZADA = 'reserva_rechazada', _('Reserva rechazada')
    RESERVA_CANCELADA = 'reserva_cancelada', _('Reserva cancelada')
    SERVICIO_COMPLETADO = 'servicio_completado', _('Servicio completado')
    RESENA_PENDIENTE = 'resena_pendiente', _('Reseña pendiente')
    MENSAJE_CHAT = 'mensaje_chat', _('Mensaje de chat')
    MASCOTA_CREADA = 'mascota_creada', _('Mascota creada')
    MASCOTA_EDITADA = 'mascota_editada', _('Mascota editada')
    MASCOTA_ELIMINADA = 'mascota_eliminada', _('Mascota eliminada')
    PERFIL_ACTUALIZADO = 'perfil_actualizado', _('Perfil actualizado')


class Notificacion(models.Model):
    idNotificacion = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idParaUsuario = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='notificaciones_recibidas')
    idActorUsuario = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True, blank=True, related_name='notificaciones_generadas')
    idSolicitud = models.ForeignKey(SolicitudServicio, on_delete=models.CASCADE, null=True, blank=True, related_name='notificaciones')
    idMascota = models.ForeignKey(Mascota, on_delete=models.SET_NULL, null=True, blank=True, related_name='notificaciones')
    categoria = models.CharField(max_length=20, choices=CategoriaNotificacion.choices, default=CategoriaNotificacion.NEGOCIO)
    tipoEvento = models.CharField(max_length=50, choices=TipoNotificacion.choices)
    titulo = models.CharField(max_length=180)
    descripcion = models.TextField(blank=True, default='')
    urlDestino = models.CharField(max_length=255, blank=True, default='')
    leida = models.BooleanField(default=False)
    leidaEn = models.DateTimeField(null=True, blank=True)
    eliminada = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['idParaUsuario', 'eliminada', 'leida']),
            models.Index(fields=['idParaUsuario', 'categoria', 'eliminada']),
        ]

    def __str__(self):
        return f"Notificación {self.tipoEvento} para {self.idParaUsuario.nombre}"


class MensajeChat(models.Model):
    """Chat entre cuidador y dueño por reunión/solicitud."""
    idMensaje = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idSolicitud = models.ForeignKey(SolicitudServicio, on_delete=models.CASCADE, related_name='mensajes_chat')
    idDe = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='mensajes_enviados')
    mensaje = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.idDe.nombre} - {self.idSolicitud_id}"

