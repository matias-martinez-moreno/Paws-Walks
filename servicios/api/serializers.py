from rest_framework import serializers

from servicios.models import EstadoSolicitud, TipoServicio


class SolicitudServicioCreateSerializer(serializers.Serializer):
    # valida solo formato y tipos de entrada

    idDueño_id = serializers.UUIDField()
    idCuidador_id = serializers.UUIDField()
    idMascota_id = serializers.UUIDField()
    tipoServicio = serializers.ChoiceField(choices=[c[0] for c in TipoServicio.choices])
    fecha = serializers.DateField()
    idBloqueHorario_id = serializers.UUIDField()


class SolicitudServicioSerializer(serializers.Serializer):
    # arma la respuesta de salida

    idSolicitud = serializers.UUIDField()
    idDueño = serializers.UUIDField(source="idDueño.idUsuario")
    idCuidador = serializers.UUIDField(source="idCuidador.idUsuario")
    idMascota = serializers.UUIDField(source="idMascota.idMascota")
    tipoServicio = serializers.ChoiceField(choices=[c[0] for c in TipoServicio.choices])
    fecha = serializers.DateField()
    idBloqueHorario = serializers.UUIDField(source="idBloqueHorario.idBloque")
    estado = serializers.ChoiceField(choices=[c[0] for c in EstadoSolicitud.choices])
    created_at = serializers.DateTimeField()
