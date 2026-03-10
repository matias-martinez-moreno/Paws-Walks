# builder: crea solicitud paso a paso
from datetime import date
from servicios.domain.exceptions import (
    ConflictError,
    DomainValidationError,
    ResourceNotFoundError,
)
from servicios.models import (
    BloqueTiempo,
    Evento,
    PrecioServicio,
    SolicitudServicio,
    SlotDisponibilidad,
    SlotEvento,
    Usuario,
    VentanaDisponibilidad,
    Mascota,
    EstadoSolicitud,
    TipoServicio,
)


class SolicitudServicioBuilder:
    # valida datos antes de crear la solicitud

    def __init__(self):
        self._datos = {}

    def para_dueño(self, dueño):
        # valida tipo de duenio
        if not isinstance(dueño, Usuario):
            raise DomainValidationError("el dueño debe ser una instancia de usuario")
        self._datos['idDueño'] = dueño
        return self

    def para_cuidador(self, cuidador_id):
        # valida cuidador existente y verificado
        try:
            cuidador = Usuario.objects.get(idUsuario=cuidador_id)
        except Usuario.DoesNotExist:
            raise ResourceNotFoundError("el cuidador no existe")
        if cuidador.rol != 'cuidador':
            raise DomainValidationError("el usuario no es cuidador")
        if not cuidador.verificado:
            raise DomainValidationError("el cuidador no esta verificado")
        self._datos['idCuidador'] = cuidador
        return self

    def para_mascota(self, mascota_id):
        # valida mascota del duenio
        dueño = self._datos.get('idDueño')
        if not dueño:
            raise DomainValidationError("debe especificar el dueño primero")
        try:
            mascota = Mascota.objects.get(idMascota=mascota_id)
        except Mascota.DoesNotExist:
            raise ResourceNotFoundError("la mascota no existe")
        if mascota.idDueño_id != dueño.idUsuario:
            raise ConflictError("la mascota no pertenece al dueño")
        self._datos['idMascota'] = mascota
        return self

    def con_servicio(self, tipo_servicio):
        # valida tipo de servicio
        opciones = [choice[0] for choice in TipoServicio.choices]
        if tipo_servicio not in opciones:
            raise DomainValidationError(f"tipo de servicio invalido: {tipo_servicio}")
        self._datos['tipoServicio'] = tipo_servicio
        return self

    def en_fecha(self, fecha):
        # regla: no permitir fecha pasada
        if fecha < date.today():
            raise DomainValidationError("la fecha del servicio no puede ser en el pasado")
        self._datos['fecha'] = fecha
        return self

    def en_fecha_fin(self, fecha_fin):
        # opcional: para guardería/cuidado (rango de fechas)
        if fecha_fin is None:
            return self
        if fecha_fin < date.today():
            raise DomainValidationError("la fecha fin no puede ser en el pasado")
        fecha_inicio = self._datos.get('fecha')
        if fecha_inicio and fecha_fin < fecha_inicio:
            raise DomainValidationError("la fecha fin debe ser igual o posterior a la fecha de inicio")
        self._datos['fechaFin'] = fecha_fin
        return self

    def en_bloque(self, bloque_id):
        # valida bloque disponible del cuidador (legacy)
        cuidador = self._datos.get('idCuidador')
        if not cuidador:
            raise DomainValidationError("debe especificar el cuidador primero")
        try:
            bloque = BloqueTiempo.objects.get(idBloque=bloque_id)
        except BloqueTiempo.DoesNotExist:
            raise ResourceNotFoundError("el bloque no existe")
        # valida disponibilidad
        if not bloque.disponible:
            raise ConflictError("el bloque no esta disponible")
        # valida pertenencia al cuidador
        if bloque.idCuidador.idCuidador.idUsuario != cuidador.idUsuario:
            raise ConflictError("el bloque no pertenece al cuidador")
        # valida que el bloque corresponda al tipo de servicio
        tipo_servicio = self._datos.get('tipoServicio')
        if tipo_servicio and bloque.tipoServicio != tipo_servicio:
            raise ConflictError("el bloque no corresponde al tipo de servicio solicitado")
        self._datos['idBloqueHorario'] = bloque
        return self

    def en_ventana(self, ventana_id):
        # valida ventana del cuidador
        cuidador = self._datos.get('idCuidador')
        if not cuidador:
            raise DomainValidationError("debe especificar el cuidador primero")
        try:
            ventana = VentanaDisponibilidad.objects.get(idVentana=ventana_id)
        except VentanaDisponibilidad.DoesNotExist:
            raise ResourceNotFoundError("la ventana no existe")
        if ventana.idCuidador.idCuidador.idUsuario != cuidador.idUsuario:
            raise ConflictError("la ventana no pertenece al cuidador")
        tipo_servicio = self._datos.get('tipoServicio')
        if tipo_servicio and ventana.tipoServicio != tipo_servicio:
            raise ConflictError("la ventana no corresponde al tipo de servicio solicitado")
        self._datos['idVentana'] = ventana
        return self

    def en_evento(self, evento_id, slot_id=None):
        """Valida evento del cuidador. Nuevo flujo unificado."""
        cuidador = self._datos.get('idCuidador')
        if not cuidador:
            raise DomainValidationError("debe especificar el cuidador primero")
        try:
            evento = Evento.objects.get(idEvento=evento_id)
        except Evento.DoesNotExist:
            raise ResourceNotFoundError("el evento no existe")
        if evento.idCuidador.idCuidador.idUsuario != cuidador.idUsuario:
            raise ConflictError("el evento no pertenece al cuidador")
        tipo_servicio = self._datos.get('tipoServicio')
        if tipo_servicio and evento.tipoServicio != tipo_servicio:
            raise ConflictError("el evento no corresponde al tipo de servicio solicitado")
        if evento.duracionSlotMinutos is not None and not slot_id:
            raise DomainValidationError("este evento requiere seleccionar un slot")
        self._datos['idEvento'] = evento
        if slot_id:
            try:
                slot = SlotEvento.objects.get(idSlot=slot_id, idEvento=evento)
            except SlotEvento.DoesNotExist:
                raise ResourceNotFoundError("el slot no existe o no pertenece al evento")
            if not slot.disponible:
                raise ConflictError("el slot no está disponible")
            self._datos['idSlotEvento'] = slot
        return self

    def con_hora_asignada(self, hora_recogida, orden_ruta: int, slot: SlotDisponibilidad):
        # asigna hora y slot calculados por AsignarHoraRecogidaService (legacy ventana)
        ventana = self._datos.get('idVentana')
        if not ventana:
            raise DomainValidationError("debe especificar la ventana primero")
        if slot.idVentana_id != ventana.idVentana:
            raise ConflictError("el slot no pertenece a la ventana")
        if not slot.disponible:
            raise ConflictError("el slot no está disponible")
        self._datos['idSlot'] = slot
        self._datos['horaRecogidaAsignada'] = hora_recogida
        self._datos['ordenEnRuta'] = orden_ruta
        return self

    def con_hora_asignada_evento(self, hora_recogida, orden_ruta: int, slot: SlotEvento):
        """Asigna hora y slot para flujo Evento."""
        evento = self._datos.get('idEvento')
        if not evento:
            raise DomainValidationError("debe especificar el evento primero")
        if slot.idEvento_id != evento.idEvento:
            raise ConflictError("el slot no pertenece al evento")
        if not slot.disponible:
            raise ConflictError("el slot no está disponible")
        self._datos['idSlotEvento'] = slot
        self._datos['horaRecogidaAsignada'] = hora_recogida
        self._datos['ordenEnRuta'] = orden_ruta
        return self

    def _validar_precio_cuidador(self):
        # valida tarifa activa por tipo de servicio
        cuidador = self._datos.get('idCuidador')
        tipo_servicio = self._datos.get('tipoServicio')
        if not cuidador or not tipo_servicio:
            return
        existe = PrecioServicio.objects.filter(
            idCuidador=cuidador,
            tipoServicio=tipo_servicio,
            activo=True,
        ).exists()
        if not existe:
            raise DomainValidationError("el cuidador no ofrece ese tipo de servicio")

    def _validar_completo(self):
        # valida campos obligatorios: flujo evento (nuevo), ventana o bloque (legacy)
        base = ['idDueño', 'idCuidador', 'idMascota', 'tipoServicio', 'fecha']
        if 'idEvento' in self._datos:
            evento = self._datos['idEvento']
            if evento.duracionSlotMinutos is not None:
                campos = base + ['idEvento', 'idSlotEvento', 'horaRecogidaAsignada', 'ordenEnRuta']
            else:
                campos = base + ['idEvento']
        elif 'idVentana' in self._datos:
            campos = base + ['idVentana', 'idSlot', 'horaRecogidaAsignada', 'ordenEnRuta']
        else:
            campos = base + ['idBloqueHorario']
        faltantes = [c for c in campos if c not in self._datos]
        if faltantes:
            raise DomainValidationError(f"faltan campos: {', '.join(faltantes)}")

    def _calcular_monto_pago(self) -> int:
        """Calcula monto_pago según tipo de servicio. Usa precio del evento si existe."""
        cuidador = self._datos['idCuidador']
        tipo_servicio = self._datos['tipoServicio']
        precio = PrecioServicio.objects.filter(
            idCuidador=cuidador, tipoServicio=tipo_servicio, activo=True
        ).first()
        if not precio:
            return 0
        if tipo_servicio == TipoServicio.GUARDERIA:
            fecha_inicio = self._datos['fecha']
            fecha_fin = self._datos.get('fechaFin')
            if not fecha_fin:
                return 0
            num_days = (fecha_fin - fecha_inicio).days + 1
            tarifa_dia = precio.precioCOP  # COP/día
            if 'idEvento' in self._datos and self._datos['idEvento'].precioCOP:
                tarifa_dia = self._datos['idEvento'].precioCOP
            return int(tarifa_dia * num_days)
        # PASEO: COP/hora o precio del evento
        if 'idEvento' in self._datos:
            evento = self._datos['idEvento']
            if evento.precioCOP:
                return evento.precioCOP
            duracion_min = evento.duracionSlotMinutos
            if duracion_min is None:
                duracion_min = (evento.horaFin.hour * 60 + evento.horaFin.minute) - (
                    evento.horaInicio.hour * 60 + evento.horaInicio.minute
                )
        elif 'idVentana' in self._datos:
            ventana = self._datos['idVentana']
            duracion_min = ventana.duracionSlotMinutos
        else:
            bloque = self._datos['idBloqueHorario']
            duracion_min = (bloque.horaFin.hour * 60 + bloque.horaFin.minute) - (
                bloque.horaInicio.hour * 60 + bloque.horaInicio.minute
            )
        duracion_horas = duracion_min / 60.0
        tarifa = precio.precioCOP
        if 'idEvento' in self._datos and self._datos['idEvento'].precioCOP:
            tarifa = self._datos['idEvento'].precioCOP
        return int(tarifa * duracion_horas)

    def build(self):
        # ejecuta validaciones finales
        self._validar_completo()
        self._validar_precio_cuidador()
        monto = self._calcular_monto_pago()
        kwargs = {
            "idDueño": self._datos['idDueño'],
            "idCuidador": self._datos['idCuidador'],
            "idMascota": self._datos['idMascota'],
            "tipoServicio": self._datos['tipoServicio'],
            "fecha": self._datos['fecha'],
            "fechaFin": self._datos.get('fechaFin'),
            "estado": EstadoSolicitud.PENDIENTE,
            "monto_pago": monto if monto > 0 else None,
        }
        if "idEvento" in self._datos:
            kwargs["idEvento"] = self._datos["idEvento"]
            if "idSlotEvento" in self._datos:
                kwargs["idSlotEvento"] = self._datos["idSlotEvento"]
            if "horaRecogidaAsignada" in self._datos:
                kwargs["horaRecogidaAsignada"] = self._datos["horaRecogidaAsignada"]
            if "ordenEnRuta" in self._datos:
                kwargs["ordenEnRuta"] = self._datos["ordenEnRuta"]
        elif "idVentana" in self._datos:
            kwargs["idVentana"] = self._datos["idVentana"]
            kwargs["idSlot"] = self._datos["idSlot"]
            kwargs["horaRecogidaAsignada"] = self._datos["horaRecogidaAsignada"]
            kwargs["ordenEnRuta"] = self._datos["ordenEnRuta"]
        else:
            kwargs["idBloqueHorario"] = self._datos["idBloqueHorario"]
        return SolicitudServicio(**kwargs)
