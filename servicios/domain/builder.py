"""
Patrón Builder para SolicitudServicio.
Construye el modelo paso a paso con validaciones, garantizando su validez antes de .save().
Implementa Fluent Interface para encadenar llamadas.
"""
from django.core.exceptions import ValidationError

from servicios.models import (
    SolicitudServicio, Usuario, Mascota,
    BloqueTiempo, PrecioServicio, EstadoSolicitud,
    TipoServicio,
)


class SolicitudServicioBuilder:
    """
    Builder para construir SolicitudServicio de forma incremental.
    Valida todas las reglas de negocio antes de retornar el objeto.
    """

    def __init__(self):
        self._datos = {}

    def para_dueño(self, dueño):
        """Establece el dueño de la mascota que solicita el servicio."""
        if not isinstance(dueño, Usuario):
            raise ValidationError("El dueño debe ser una instancia de Usuario")
        self._datos['idDueño'] = dueño
        return self

    def para_cuidador(self, cuidador_id):
        """
        Establece el cuidador por ID.
        Valida que exista, sea cuidador y esté verificado.
        """
        try:
            cuidador = Usuario.objects.get(idUsuario=cuidador_id)
        except Usuario.DoesNotExist:
            raise ValidationError("El cuidador especificado no existe")
        if cuidador.rol not in ['cuidador', 'ambos']:
            raise ValidationError("El usuario especificado no es un cuidador")
        if not cuidador.verificado:
            raise ValidationError("El cuidador no está verificado")
        self._datos['idCuidador'] = cuidador
        return self

    def para_mascota(self, mascota_id):
        """
        Establece la mascota por ID.
        Valida que exista y pertenezca al dueño.
        """
        dueño = self._datos.get('idDueño')
        if not dueño:
            raise ValidationError("Debe especificar el dueño antes de la mascota")
        try:
            mascota = Mascota.objects.get(
                idMascota=mascota_id,
                idDueño=dueño,
            )
        except Mascota.DoesNotExist:
            raise ValidationError(
                "La mascota especificada no existe o no pertenece al dueño"
            )
        self._datos['idMascota'] = mascota
        return self

    def con_servicio(self, tipo_servicio):
        """Establece el tipo de servicio (paseo, guarderia, otro)."""
        opciones = [choice[0] for choice in TipoServicio.choices]
        if tipo_servicio not in opciones:
            raise ValidationError(f"Tipo de servicio inválido: {tipo_servicio}")
        self._datos['tipoServicio'] = tipo_servicio
        return self

    def en_fecha(self, fecha):
        """Establece la fecha del servicio."""
        self._datos['fecha'] = fecha
        return self

    def en_bloque(self, bloque_id):
        """
        Establece el bloque horario.
        Valida disponibilidad y que pertenezca al cuidador.
        """
        cuidador = self._datos.get('idCuidador')
        if not cuidador:
            raise ValidationError("Debe especificar el cuidador antes del bloque")
        try:
            bloque = BloqueTiempo.objects.get(idBloque=bloque_id)
        except BloqueTiempo.DoesNotExist:
            raise ValidationError("El bloque de tiempo especificado no existe")
        if not bloque.disponible:
            raise ValidationError("El bloque de tiempo no está disponible")
        if bloque.idCuidador.idCuidador != cuidador:
            raise ValidationError("El bloque de tiempo no pertenece al cuidador especificado")
        self._datos['idBloqueHorario'] = bloque
        return self

    def _validar_precio_cuidador(self):
        """Valida que el cuidador tenga precio configurado para el tipo de servicio."""
        cuidador = self._datos.get('idCuidador')
        tipo_servicio = self._datos.get('tipoServicio')
        if not cuidador or not tipo_servicio:
            return
        try:
            PrecioServicio.objects.get(
                idCuidador=cuidador,
                tipoServicio=tipo_servicio,
                activo=True
            )
        except PrecioServicio.DoesNotExist:
            raise ValidationError(
                f"El cuidador no tiene un precio configurado para {tipo_servicio}"
            )

    def _validar_completo(self):
        """Verifica que todos los campos obligatorios estén presentes."""
        campos = ['idDueño', 'idCuidador', 'idMascota', 'tipoServicio', 'fecha', 'idBloqueHorario']
        faltantes = [c for c in campos if c not in self._datos]
        if faltantes:
            raise ValidationError(f"Campos obligatorios faltantes: {', '.join(faltantes)}")

    def build(self) -> SolicitudServicio:
        """
        Construye y retorna la SolicitudServicio validada.
        No llama a .save(); eso es responsabilidad del Service.
        """
        self._validar_completo()
        self._validar_precio_cuidador()

        return SolicitudServicio(
            idDueño=self._datos['idDueño'],
            idCuidador=self._datos['idCuidador'],
            idMascota=self._datos['idMascota'],
            tipoServicio=self._datos['tipoServicio'],
            fecha=self._datos['fecha'],
            idBloqueHorario=self._datos['idBloqueHorario'],
            estado=EstadoSolicitud.PENDIENTE,
        )
