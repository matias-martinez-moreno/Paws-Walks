from rest_framework import serializers

from servicios.models import EstadoSolicitud, TipoServicio


class SolicitudServicioCreateSerializer(serializers.Serializer):
    idDueño_id = serializers.UUIDField()
    idCuidador_id = serializers.UUIDField()
    idMascota_id = serializers.UUIDField()
    tipoServicio = serializers.ChoiceField(choices=[c[0] for c in TipoServicio.choices])
    fecha = serializers.DateField()
    fechaFin = serializers.DateField(required=False, allow_null=True)
    idVentana_id = serializers.UUIDField(required=False, allow_null=True)
    idBloqueHorario_id = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, attrs):
        tipo = attrs.get("tipoServicio")
        ventana = attrs.get("idVentana_id")
        bloque = attrs.get("idBloqueHorario_id")
        if tipo == TipoServicio.PASEO and not ventana and not bloque:
            raise serializers.ValidationError(
                {"idVentana_id": "Para paseo debes indicar idVentana_id (o idBloqueHorario_id para legacy)"}
            )
        if tipo == TipoServicio.GUARDERIA and not bloque:
            raise serializers.ValidationError(
                {"idBloqueHorario_id": "Para guardería debes indicar idBloqueHorario_id"}
            )
        return attrs


class SolicitudServicioSerializer(serializers.Serializer):
    idSolicitud = serializers.UUIDField()
    idDueño = serializers.UUIDField(source="idDueño.idUsuario")
    idCuidador = serializers.UUIDField(source="idCuidador.idUsuario")
    idMascota = serializers.UUIDField(source="idMascota.idMascota")
    tipoServicio = serializers.ChoiceField(choices=[c[0] for c in TipoServicio.choices])
    fecha = serializers.DateField()
    fechaFin = serializers.DateField(allow_null=True)
    idBloqueHorario = serializers.SerializerMethodField()
    idVentana = serializers.SerializerMethodField()
    horaRecogidaAsignada = serializers.TimeField(format="%H:%M", allow_null=True)
    ordenEnRuta = serializers.IntegerField(allow_null=True)
    estado = serializers.ChoiceField(choices=[c[0] for c in EstadoSolicitud.choices])
    created_at = serializers.DateTimeField()

    def get_idBloqueHorario(self, obj):
        return str(obj.idBloqueHorario.idBloque) if obj.idBloqueHorario_id else None

    def get_idVentana(self, obj):
        return str(obj.idVentana.idVentana) if obj.idVentana_id else None


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
