from rest_framework import serializers

from servicios.models import EstadoSolicitud, TipoServicio


# ── Serializers de entrada ──────────────────────────────────────────────────
# Solo validan estructura (tipos, formatos, campos requeridos).
# Las reglas de negocio se validan explícitamente en el APIView,
# delegando al Service Layer (ValidarCrearSolicitudApiService /
# ValidarBusquedaDisponibilidadApiService). Esto cumple SRP:
# el Serializer es responsable de la forma del dato, no de las reglas.

class SolicitudServicioCreateSerializer(serializers.Serializer):
    idDueño_id = serializers.UUIDField()
    idCuidador_id = serializers.UUIDField()
    idMascota_id = serializers.UUIDField()
    tipoServicio = serializers.ChoiceField(choices=[c[0] for c in TipoServicio.choices])
    fecha = serializers.DateField()
    fechaFin = serializers.DateField(required=False, allow_null=True)
    idEvento_id = serializers.UUIDField()
    idSlotEvento_id = serializers.UUIDField(required=False, allow_null=True)
    duracionMinutosSolicitados = serializers.IntegerField(required=False, allow_null=True)


class SolicitudServicioCancelSerializer(serializers.Serializer):
    actor_id = serializers.UUIDField(required=False, allow_null=True)


class SolicitudServicioSerializer(serializers.Serializer):
    idSolicitud = serializers.UUIDField()
    idDueño = serializers.UUIDField(source="idDueño.idUsuario")
    idCuidador = serializers.UUIDField(source="idCuidador.idUsuario")
    idMascota = serializers.UUIDField(source="idMascota.idMascota")
    tipoServicio = serializers.ChoiceField(choices=[c[0] for c in TipoServicio.choices])
    fecha = serializers.DateField()
    fechaFin = serializers.DateField(allow_null=True)
    idEvento = serializers.SerializerMethodField()
    idSlotEvento = serializers.SerializerMethodField()
    horaRecogidaAsignada = serializers.TimeField(format="%H:%M", allow_null=True)
    ordenEnRuta = serializers.IntegerField(allow_null=True)
    estado = serializers.ChoiceField(choices=[c[0] for c in EstadoSolicitud.choices])
    created_at = serializers.DateTimeField()

    def get_idEvento(self, obj):
        return str(obj.idEvento.idEvento) if obj.idEvento_id else None

    def get_idSlotEvento(self, obj):
        return str(obj.idSlotEvento.idSlot) if obj.idSlotEvento_id else None


class DisponibilidadBusquedaSerializer(serializers.Serializer):
    idDueño_id = serializers.UUIDField()
    idMascota_id = serializers.UUIDField()
    tipoServicio = serializers.ChoiceField(choices=[c[0] for c in TipoServicio.choices])

    # Paseo
    fecha = serializers.DateField(required=False, allow_null=True)
    duracionMinutos = serializers.IntegerField(required=False, allow_null=True)
    ciudadPaseo = serializers.CharField(required=False, allow_blank=True)
    latitudPaseo = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)
    longitudPaseo = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True)

    # Guarderia
    fechaInicioGuarderia = serializers.DateField(required=False, allow_null=True)
    fechaFinGuarderia = serializers.DateField(required=False, allow_null=True)

    # Filtros
    precioMinHora = serializers.IntegerField(required=False, allow_null=True)
    precioMaxHora = serializers.IntegerField(required=False, allow_null=True)
    horaInicio = serializers.TimeField(required=False, allow_null=True)
    horaFin = serializers.TimeField(required=False, allow_null=True)


class DisponibilidadSlotGuarderiaSerializer(serializers.Serializer):
    eventoId = serializers.UUIDField()
    fecha = serializers.DateField()
    horaInicio = serializers.TimeField(format="%H:%M")
    horaFin = serializers.TimeField(format="%H:%M")
    cuposDisponibles = serializers.IntegerField()
    cupoMaximo = serializers.IntegerField()
    duracionOpciones = serializers.ListField(child=serializers.IntegerField())


class DisponibilidadResultadoSerializer(serializers.Serializer):
    cuidadorId = serializers.UUIDField()
    cuidadorNombre = serializers.CharField()
    cuidadorApellido = serializers.CharField()
    tipoServicio = serializers.ChoiceField(choices=[c[0] for c in TipoServicio.choices])
    eventoId = serializers.UUIDField(allow_null=True)

    fecha = serializers.DateField(allow_null=True, required=False)
    horaInicio = serializers.TimeField(format="%H:%M", allow_null=True, required=False)
    horaFin = serializers.TimeField(format="%H:%M", allow_null=True, required=False)

    tarifaHora = serializers.IntegerField()
    tarifaTotal = serializers.IntegerField()

    cupoMaximo = serializers.IntegerField(allow_null=True, required=False)
    cuposDisponibles = serializers.IntegerField(allow_null=True, required=False)
    totalSlotsDisponibles = serializers.IntegerField(required=False)

    distanciaKm = serializers.FloatField(allow_null=True, required=False)
    calificacionPromedio = serializers.FloatField(allow_null=True, required=False)
    calificacionCount = serializers.IntegerField(required=False)
    descripcionServicio = serializers.CharField(required=False, allow_blank=True)
    slotsGuarderia = DisponibilidadSlotGuarderiaSerializer(many=True, required=False)


class VentanaDisponibilidadSerializer(serializers.Serializer):
    idVentana = serializers.UUIDField()
    tipoServicio = serializers.ChoiceField(choices=[c[0] for c in TipoServicio.choices])
    diaSemana = serializers.CharField()
    horaInicio = serializers.TimeField(format="%H:%M")
    horaFin = serializers.TimeField(format="%H:%M")
    duracionSlotMinutos = serializers.IntegerField()
    capacidadMaxima = serializers.IntegerField()


class SlotDisponibilidadSerializer(serializers.Serializer):
    idSlot = serializers.UUIDField()
    horaInicio = serializers.TimeField(format="%H:%M")
    disponible = serializers.BooleanField()
