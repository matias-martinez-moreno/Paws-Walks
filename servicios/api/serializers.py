from rest_framework import serializers

from servicios.models import EstadoSolicitud, Evento, TipoServicio


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

    def validate(self, attrs):
        tipo_servicio = attrs.get("tipoServicio")
        fecha = attrs.get("fecha")
        fecha_fin = attrs.get("fechaFin")

        if tipo_servicio == TipoServicio.PASEO and fecha_fin is not None and fecha_fin != fecha:
            raise serializers.ValidationError(
                {"fechaFin": "para paseo la fecha fin debe coincidir con la fecha seleccionada"}
            )

        if tipo_servicio == TipoServicio.GUARDERIA and fecha_fin is not None and fecha_fin < fecha:
            raise serializers.ValidationError(
                {"fechaFin": "la fecha fin debe ser igual o posterior a la fecha"}
            )

        duracion = attrs.get("duracionMinutosSolicitados")
        if duracion is not None and (duracion < 60 or duracion % 30 != 0):
            raise serializers.ValidationError(
                {
                    "duracionMinutosSolicitados": (
                        "la duración de guardería debe ser mínimo 60 minutos y en múltiplos de 30"
                    )
                }
            )

        evento_id = attrs.get("idEvento_id")
        if evento_id:
            evento = Evento.objects.filter(idEvento=evento_id).only("duracionSlotMinutos").first()
            if evento and evento.duracionSlotMinutos is not None and not attrs.get("idSlotEvento_id"):
                raise serializers.ValidationError(
                    {"idSlotEvento_id": "este evento requiere seleccionar un slot"}
                )

        return attrs


class SolicitudServicioCancelSerializer(serializers.Serializer):
    actor_id = serializers.UUIDField()


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

    def validate(self, attrs):
        tipo_servicio = attrs.get("tipoServicio")

        if tipo_servicio == TipoServicio.PASEO:
            if attrs.get("fecha") is None:
                raise serializers.ValidationError({"fecha": "fecha es requerida para paseo"})
            if attrs.get("duracionMinutos") is None:
                raise serializers.ValidationError(
                    {"duracionMinutos": "duracionMinutos es requerida para paseo"}
                )

            ciudad = str(attrs.get("ciudadPaseo") or "").strip()
            latitud = attrs.get("latitudPaseo")
            longitud = attrs.get("longitudPaseo")

            if (latitud is None) != (longitud is None):
                raise serializers.ValidationError(
                    "latitudPaseo y longitudPaseo deben enviarse juntas"
                )

            if not ciudad and (latitud is None or longitud is None):
                raise serializers.ValidationError(
                    "para paseo debes enviar ciudadPaseo o coordenadas de referencia"
                )

        if tipo_servicio == TipoServicio.GUARDERIA:
            fecha_inicio = attrs.get("fechaInicioGuarderia")
            fecha_fin = attrs.get("fechaFinGuarderia")
            if fecha_inicio is None:
                raise serializers.ValidationError(
                    {"fechaInicioGuarderia": "fechaInicioGuarderia es requerida para guardería"}
                )
            if fecha_fin is not None and fecha_fin < fecha_inicio:
                raise serializers.ValidationError(
                    {
                        "fechaFinGuarderia": (
                            "fechaFinGuarderia debe ser igual o posterior a fechaInicioGuarderia"
                        )
                    }
                )

        precio_min = attrs.get("precioMinHora")
        precio_max = attrs.get("precioMaxHora")
        if precio_min is not None and precio_max is not None and precio_min > precio_max:
            raise serializers.ValidationError(
                {"precioMinHora": "precioMinHora no puede ser mayor que precioMaxHora"}
            )

        hora_inicio = attrs.get("horaInicio")
        hora_fin = attrs.get("horaFin")
        if hora_inicio is not None and hora_fin is not None and hora_fin <= hora_inicio:
            raise serializers.ValidationError(
                {"horaFin": "horaFin debe ser posterior a horaInicio"}
            )

        return attrs


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
