# builder: crea solicitud paso a paso
from django.core.exceptions import ValidationError
from datetime import date
from servicios.models import (
    SolicitudServicio, Usuario, Mascota,
    BloqueTiempo, PrecioServicio, EstadoSolicitud,
    TipoServicio,
)


class SolicitudServicioBuilder:
    # valida datos antes de crear la solicitud

    def __init__(self):
        self._datos = {}

    def para_dueño(self, dueño):
        # valida tipo de duenio
        if not isinstance(dueño, Usuario):
            raise ValidationError("el dueño debe ser una instancia de usuario")
        self._datos['idDueño'] = dueño
        return self

    def para_cuidador(self, cuidador_id):
        # valida cuidador existente y verificado
        try:
            cuidador = Usuario.objects.get(idUsuario=cuidador_id)
        except Usuario.DoesNotExist:
            raise ValidationError("el cuidador no existe")
        if cuidador.rol not in ['cuidador', 'ambos']:
            raise ValidationError("el usuario no es cuidador")
        if not cuidador.verificado:
            raise ValidationError("el cuidador no está verificado")
        self._datos['idCuidador'] = cuidador
        return self

    def para_mascota(self, mascota_id):
        # valida mascota del duenio
        dueño = self._datos.get('idDueño')
        if not dueño:
            raise ValidationError("debe especificar el dueño primero")
        try:
            mascota = Mascota.objects.get(idMascota=mascota_id, idDueño=dueño)
        except Mascota.DoesNotExist:
            raise ValidationError("la mascota no existe o no pertenece al dueño")
        self._datos['idMascota'] = mascota
        return self

    def con_servicio(self, tipo_servicio):
        # valida tipo de servicio
        opciones = [choice[0] for choice in TipoServicio.choices]
        if tipo_servicio not in opciones:
            raise ValidationError(f"tipo de servicio inválido: {tipo_servicio}")
        self._datos['tipoServicio'] = tipo_servicio
        return self

    def en_fecha(self, fecha):
        # regla: no permitir fecha pasada
        if fecha < date.today():
            raise ValidationError("La fecha del servicio no puede ser en el pasado.")
        self._datos['fecha'] = fecha
        return self

    def en_bloque(self, bloque_id):
        # valida bloque disponible del cuidador
        cuidador = self._datos.get('idCuidador')
        if not cuidador:
            raise ValidationError("debe especificar el cuidador primero")
        try:
            bloque = BloqueTiempo.objects.get(idBloque=bloque_id)
        except BloqueTiempo.DoesNotExist:
            raise ValidationError("el bloque no existe")
        # valida disponibilidad
        if not bloque.disponible:
            raise ValidationError("el bloque no está disponible")
        # valida pertenencia al cuidador
        if bloque.idCuidador.idCuidador.idUsuario != cuidador.idUsuario:
            raise ValidationError("el bloque no pertenece al cuidador")
        self._datos['idBloqueHorario'] = bloque
        return self

    def _validar_precio_cuidador(self):
        # valida tarifa activa del cuidador
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
            raise ValidationError(f"el cuidador no tiene precio para {tipo_servicio}")

    def _validar_completo(self):
        # valida campos obligatorios
        campos = ['idDueño', 'idCuidador', 'idMascota', 'tipoServicio', 'fecha', 'idBloqueHorario']
        faltantes = [c for c in campos if c not in self._datos]
        if faltantes:
            raise ValidationError(f"faltan campos: {', '.join(faltantes)}")

    def build(self):
        # ejecuta validaciones finales
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
