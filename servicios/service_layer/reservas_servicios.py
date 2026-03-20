# modulo de servicios: ciclo de vida de solicitudes y reservas
from __future__ import annotations

from datetime import date, time

from django.db import transaction
from django.utils import timezone

from servicios.domain.builder import SolicitudServicioBuilder
from servicios.domain.exceptions import (
    ConflictError,
    DomainValidationError,
    ResourceNotFoundError,
)
from servicios.infra.factory import NotificadorFactory
from servicios.models import (
    BloqueTiempo,
    EstadoSolicitud,
    Evento,
    Mascota,
    SlotDisponibilidad,
    SlotEvento,
    SolicitudServicio,
    TipoServicio,
    Usuario,
    VentanaDisponibilidad,
)
from servicios.service_layer.utils import haversine_km
from servicios.service_layer.validacion_servicios import (
    CalcularMontoPagoService,
    CuposDisponiblesEventoService,
    NormalizarDuracionGuarderiaService,
    ResolverCuidadorVerificadoService,
    ResolverMascotaDeDueñoService,
    ResolverPrecioActivoService,
    ValidarFechasSolicitudService,
    ValidarTipoServicioService,
)


class SolicitudServicioService:
    # orquesta builder y factory

    def __init__(self, notificador=None):
        self.notificador = notificador or NotificadorFactory.crear()

    def crear_solicitud(self, datos):
        dueño = datos["idDueño"]
        tipo_servicio = ValidarTipoServicioService.validar(datos.get("tipoServicio"))
        fecha = datos["fecha"]
        fecha_fin = datos.get("fechaFin")
        ValidarFechasSolicitudService.validar(fecha, fecha_fin)

        cuidador = ResolverCuidadorVerificadoService.resolver(datos.get("idCuidador_id"))
        mascota = ResolverMascotaDeDueñoService.resolver(dueño, datos.get("idMascota_id"))
        precio = ResolverPrecioActivoService.resolver(cuidador, tipo_servicio)

        with transaction.atomic():
            try:
                bloque = BloqueTiempo.objects.select_related("idCuidador__idCuidador").select_for_update().get(
                    idBloque=datos["idBloqueHorario_id"]
                )
            except BloqueTiempo.DoesNotExist:
                raise ResourceNotFoundError("el bloque no existe")

            if not bloque.disponible:
                raise ConflictError("el bloque no esta disponible")
            if bloque.idCuidador.idCuidador.idUsuario != cuidador.idUsuario:
                raise ConflictError("el bloque no pertenece al cuidador")
            if bloque.tipoServicio != tipo_servicio:
                raise ConflictError("el bloque no corresponde al tipo de servicio solicitado")

            monto_pago = CalcularMontoPagoService.calcular(
                tipo_servicio=tipo_servicio,
                precio_base_hora=precio.precioCOP,
                fecha=fecha,
                fecha_fin=fecha_fin,
                bloque=bloque,
            )

            builder = (
                SolicitudServicioBuilder()
                .para_dueño(dueño)
                .para_cuidador(cuidador)
                .para_mascota(mascota)
                .con_servicio(tipo_servicio)
                .en_fecha(fecha)
                .en_bloque(bloque)
                .con_monto_pago(monto_pago)
            )
            if fecha_fin:
                builder = builder.en_fecha_fin(fecha_fin)

            solicitud = SolicitudServicio.objects.create(**builder.build())
            bloque.disponible = False
            bloque.save(update_fields=["disponible"])

        self.notificador.enviar_nueva_solicitud(solicitud)
        return solicitud

    def crear_solicitud_evento(self, datos):
        """Crea solicitud usando Evento (nuevo flujo unificado)."""
        dueño = datos["idDueño"]
        tipo_servicio = ValidarTipoServicioService.validar(datos.get("tipoServicio"))
        fecha = datos["fecha"]
        fecha_fin = datos.get("fechaFin")
        ValidarFechasSolicitudService.validar(fecha, fecha_fin)

        cuidador = ResolverCuidadorVerificadoService.resolver(datos.get("idCuidador_id"))
        mascota = ResolverMascotaDeDueñoService.resolver(dueño, datos.get("idMascota_id"))
        precio = ResolverPrecioActivoService.resolver(cuidador, tipo_servicio)
        duracion_guarderia = NormalizarDuracionGuarderiaService.normalizar(datos.get("duracionMinutosSolicitados"))

        with transaction.atomic():
            try:
                evento = Evento.objects.select_related("idCuidador__idCuidador").select_for_update().get(
                    idEvento=datos["idEvento_id"]
                )
            except Evento.DoesNotExist:
                raise ResourceNotFoundError("el evento no existe")

            if not evento.disponible:
                raise ConflictError("el evento no está disponible")
            if evento.idCuidador.idCuidador.idUsuario != cuidador.idUsuario:
                raise ConflictError("el evento no pertenece al cuidador")
            if evento.tipoServicio != tipo_servicio:
                raise ConflictError("el evento no corresponde al tipo de servicio solicitado")

            slot = None
            slot_id = datos.get("idSlotEvento_id")
            if slot_id:
                try:
                    slot = SlotEvento.objects.select_for_update().get(idSlot=slot_id, idEvento=evento)
                except SlotEvento.DoesNotExist:
                    raise ResourceNotFoundError("el slot no existe o no pertenece al evento")
                if not slot.disponible:
                    raise ConflictError("el slot no está disponible")
            elif evento.duracionSlotMinutos is not None:
                raise DomainValidationError("este evento requiere seleccionar un slot")

            if slot is None:
                cupos_disponibles, _ = CuposDisponiblesEventoService.calcular(evento, fecha)
                if cupos_disponibles < 1:
                    raise ConflictError("el evento ya no tiene cupos disponibles para ese día")

            monto_pago = CalcularMontoPagoService.calcular(
                tipo_servicio=tipo_servicio,
                precio_base_hora=precio.precioCOP,
                fecha=fecha,
                fecha_fin=fecha_fin,
                evento=evento,
                duracion_guarderia_minutos=duracion_guarderia,
            )

            builder = (
                SolicitudServicioBuilder()
                .para_dueño(dueño)
                .para_cuidador(cuidador)
                .para_mascota(mascota)
                .con_servicio(tipo_servicio)
                .en_fecha(fecha)
                .en_evento(evento, slot)
                .con_monto_pago(monto_pago)
            )
            if fecha_fin:
                builder = builder.en_fecha_fin(fecha_fin)

            solicitud = SolicitudServicio.objects.create(**builder.build())
            if slot is not None:
                slot.disponible = False
                slot.save(update_fields=["disponible"])

        self.notificador.enviar_nueva_solicitud(solicitud)
        return solicitud


class CrearSolicitudConAsignacionEventoService:
    """Crea solicitud para evento con slots (paseo con cupos). Asigna hora por proximidad."""

    def __init__(self, notificador=None):
        self.notificador = notificador or NotificadorFactory.crear()

    def crear(self, datos: dict) -> SolicitudServicio:
        dueño = datos["idDueño"]
        cuidador_id = datos["idCuidador_id"]
        mascota_id = datos["idMascota_id"]
        tipo_servicio = ValidarTipoServicioService.validar(datos["tipoServicio"])
        fecha = datos["fecha"]
        id_evento = datos.get("idEvento_id")
        ValidarFechasSolicitudService.validar(fecha, datos.get("fechaFin"))

        if tipo_servicio == TipoServicio.GUARDERIA:
            raise DomainValidationError("use el flujo de guardería para este tipo de servicio")

        cuidador = ResolverCuidadorVerificadoService.resolver(cuidador_id)
        mascota = ResolverMascotaDeDueñoService.resolver(dueño, mascota_id)
        precio = ResolverPrecioActivoService.resolver(cuidador, tipo_servicio)

        try:
            evento = Evento.objects.get(idEvento=id_evento, idCuidador__idCuidador=cuidador)
        except Evento.DoesNotExist:
            raise ResourceNotFoundError("el evento no existe o no pertenece al cuidador")

        if evento.duracionSlotMinutos is None:
            raise DomainValidationError("este evento no tiene slots; usa crear_solicitud_evento")

        asignador = AsignarHoraRecogidaService()
        hora_asignada, orden_ruta, slot = asignador.asignar_evento(cuidador, evento, fecha, mascota, dueño)

        with transaction.atomic():
            slot = SlotEvento.objects.select_for_update().get(idSlot=slot.idSlot)
            if not slot.disponible:
                raise ConflictError("el slot ya no está disponible")

            monto_pago = CalcularMontoPagoService.calcular(
                tipo_servicio=tipo_servicio,
                precio_base_hora=precio.precioCOP,
                fecha=fecha,
                fecha_fin=datos.get("fechaFin"),
                evento=evento,
            )

            builder = (
                SolicitudServicioBuilder()
                .para_dueño(dueño)
                .para_cuidador(cuidador)
                .para_mascota(mascota)
                .con_servicio(tipo_servicio)
                .en_fecha(fecha)
                .en_evento(evento, slot)
                .con_hora_asignada_evento(hora_asignada, orden_ruta, slot)
                .con_monto_pago(monto_pago)
            )
            if datos.get("fechaFin"):
                builder = builder.en_fecha_fin(datos["fechaFin"])
            solicitud = SolicitudServicio.objects.create(**builder.build())
            slot.disponible = False
            slot.save(update_fields=["disponible"])

        self.notificador.enviar_nueva_solicitud(solicitud)
        return solicitud


class AsignarHoraRecogidaService:
    """Calcula horaRecogidaAsignada y ordenEnRuta por proximidad (Haversine)."""

    def asignar(self, cuidador, ventana, fecha, mascota, dueño):
        solicitudes_existentes = SolicitudServicio.objects.filter(
            idVentana=ventana,
            fecha=fecha,
            estado__in=[EstadoSolicitud.PENDIENTE, EstadoSolicitud.ACEPTADO],
        ).select_related("idDueño", "idMascota").order_by("ordenEnRuta", "horaRecogidaAsignada")

        slots_disponibles = list(
            SlotDisponibilidad.objects.filter(
                idVentana=ventana,
                disponible=True,
            ).order_by("horaInicio")
        )

        if not slots_disponibles:
            raise ConflictError("no hay slots disponibles en esta ventana")

        hora, orden, _ = self._calcular_ruta(
            cuidador, dueño, solicitudes_existentes, slots_disponibles[0].horaInicio
        )
        return hora, orden, slots_disponibles[0]

    def asignar_evento(self, cuidador, evento, fecha, mascota, dueño):
        solicitudes_existentes = SolicitudServicio.objects.filter(
            idEvento=evento,
            fecha=fecha,
            estado__in=[EstadoSolicitud.PENDIENTE, EstadoSolicitud.ACEPTADO],
        ).select_related("idDueño", "idMascota").order_by("ordenEnRuta", "horaRecogidaAsignada")

        slots_disponibles = list(
            SlotEvento.objects.filter(
                idEvento=evento,
                disponible=True,
            ).order_by("horaInicio")
        )

        if not slots_disponibles:
            raise ConflictError("no hay slots disponibles en este evento")

        hora, orden, _ = self._calcular_ruta(
            cuidador, dueño, solicitudes_existentes, slots_disponibles[0].horaInicio
        )
        return hora, orden, slots_disponibles[0]

    def _calcular_ruta(self, cuidador, dueño, solicitudes_existentes, hora_default):
        cuidador_lat = cuidador.latitud
        cuidador_lon = cuidador.longitud
        dueño_lat = dueño.latitud
        dueño_lon = dueño.longitud

        if not dueño_lat or not dueño_lon:
            raise DomainValidationError("el dueño debe tener ubicación registrada para asignar hora de recogida")

        if not cuidador_lat or not cuidador_lon:
            cuidador_lat = dueño_lat
            cuidador_lon = dueño_lon

        if not solicitudes_existentes:
            return hora_default, 1, None

        rutas = []
        for sol in solicitudes_existentes:
            d = sol.idDueño
            if d.latitud and d.longitud:
                dist = haversine_km(float(cuidador_lat), float(cuidador_lon), float(d.latitud), float(d.longitud))
            else:
                dist = 9999
            rutas.append((dist, sol))

        if dueño_lat and dueño_lon:
            dist_nuevo = haversine_km(float(cuidador_lat), float(cuidador_lon), float(dueño_lat), float(dueño_lon))
        else:
            dist_nuevo = 9999

        rutas.append((dist_nuevo, None))
        rutas.sort(key=lambda x: x[0])

        pos_nuevo = next(i for i, (_, s) in enumerate(rutas) if s is None)
        orden_en_ruta = pos_nuevo + 1

        return hora_default, orden_en_ruta, None


class CrearSolicitudConAsignacionService:
    """Orquesta: valida, asigna slot/hora, crea solicitud, marca slot ocupado."""

    def __init__(self, notificador=None):
        self.notificador = notificador or NotificadorFactory.crear()

    def crear(self, datos: dict) -> SolicitudServicio:
        dueño = datos["idDueño"]
        cuidador_id = datos["idCuidador_id"]
        mascota_id = datos["idMascota_id"]
        tipo_servicio = ValidarTipoServicioService.validar(datos["tipoServicio"])
        fecha = datos["fecha"]
        id_ventana = datos.get("idVentana_id")
        ValidarFechasSolicitudService.validar(fecha, datos.get("fechaFin"))

        if tipo_servicio == TipoServicio.GUARDERIA:
            raise DomainValidationError("use el flujo de guardería para este tipo de servicio")

        cuidador = ResolverCuidadorVerificadoService.resolver(cuidador_id)
        mascota = ResolverMascotaDeDueñoService.resolver(dueño, mascota_id)
        precio = ResolverPrecioActivoService.resolver(cuidador, tipo_servicio)

        dia_semana = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"][fecha.weekday()]

        ventanas = VentanaDisponibilidad.objects.filter(
            idCuidador__idCuidador=cuidador,
            tipoServicio=tipo_servicio,
            diaSemana=dia_semana,
        ).prefetch_related("slots")

        if not ventanas.exists():
            raise ConflictError("el cuidador no tiene ventanas disponibles para ese día")

        ventana = None
        if id_ventana:
            try:
                ventana = ventanas.get(idVentana=id_ventana)
            except VentanaDisponibilidad.DoesNotExist:
                raise ResourceNotFoundError("la ventana no existe o no pertenece al cuidador")
        else:
            ventana = ventanas.first()

        asignador = AsignarHoraRecogidaService()
        hora_asignada, orden_ruta, slot = asignador.asignar(cuidador, ventana, fecha, mascota, dueño)

        with transaction.atomic():
            slot = SlotDisponibilidad.objects.select_for_update().get(idSlot=slot.idSlot)
            if not slot.disponible:
                raise ConflictError("el slot ya no está disponible")

            monto_pago = CalcularMontoPagoService.calcular(
                tipo_servicio=tipo_servicio,
                precio_base_hora=precio.precioCOP,
                fecha=fecha,
                fecha_fin=datos.get("fechaFin"),
                ventana=ventana,
            )

            builder = (
                SolicitudServicioBuilder()
                .para_dueño(dueño)
                .para_cuidador(cuidador)
                .para_mascota(mascota)
                .con_servicio(tipo_servicio)
                .en_fecha(fecha)
                .en_ventana(ventana)
                .con_hora_asignada(hora_asignada, orden_ruta, slot)
                .con_monto_pago(monto_pago)
            )
            if datos.get("fechaFin"):
                builder = builder.en_fecha_fin(datos["fechaFin"])
            solicitud = SolicitudServicio.objects.create(**builder.build())
            slot.disponible = False
            slot.save(update_fields=["disponible"])

        self.notificador.enviar_nueva_solicitud(solicitud)
        return solicitud


class CambiarEstadoSolicitudService:
    """Aceptar o rechazar una solicitud pendiente (cuidador)."""

    def __init__(self, notificador=None):
        self.notificador = notificador or NotificadorFactory.crear()

    def aceptar(self, solicitud_id: str, cuidador: Usuario) -> SolicitudServicio:
        try:
            with transaction.atomic():
                solicitud = SolicitudServicio.objects.select_for_update().get(idSolicitud=solicitud_id)
                if solicitud.idCuidador_id != cuidador.idUsuario:
                    raise DomainValidationError("solo el cuidador asignado puede aceptar esta solicitud")
                if solicitud.estado != EstadoSolicitud.PENDIENTE:
                    raise DomainValidationError("solo se pueden aceptar solicitudes pendientes")
                solicitud.estado = EstadoSolicitud.ACEPTADO
                solicitud.save(update_fields=["estado", "updated_at"])
        except SolicitudServicio.DoesNotExist:
            raise ResourceNotFoundError("la solicitud no existe")
        self.notificador.enviar_solicitud_aceptada(solicitud)
        return solicitud

    def rechazar(self, solicitud_id: str, cuidador: Usuario) -> SolicitudServicio:
        try:
            with transaction.atomic():
                solicitud = SolicitudServicio.objects.select_for_update().get(idSolicitud=solicitud_id)
                if solicitud.idCuidador_id != cuidador.idUsuario:
                    raise DomainValidationError("solo el cuidador asignado puede rechazar esta solicitud")
                if solicitud.estado != EstadoSolicitud.PENDIENTE:
                    raise DomainValidationError("solo se pueden rechazar solicitudes pendientes")

                if solicitud.idSlotEvento_id:
                    slot = SlotEvento.objects.select_for_update().get(idSlot=solicitud.idSlotEvento_id)
                    slot.disponible = True
                    slot.save(update_fields=["disponible"])
                elif solicitud.idEvento_id:
                    evento = Evento.objects.select_for_update().get(idEvento=solicitud.idEvento_id)
                    evento.disponible = True
                    evento.save(update_fields=["disponible"])
                if solicitud.idSlot_id:
                    slot = SlotDisponibilidad.objects.select_for_update().get(idSlot=solicitud.idSlot_id)
                    slot.disponible = True
                    slot.save(update_fields=["disponible"])
                if solicitud.idBloqueHorario_id:
                    bloque = BloqueTiempo.objects.select_for_update().get(idBloque=solicitud.idBloqueHorario_id)
                    bloque.disponible = True
                    bloque.save(update_fields=["disponible"])

                solicitud.estado = EstadoSolicitud.RECHAZADO
                solicitud.save(update_fields=["estado", "updated_at"])
        except SolicitudServicio.DoesNotExist:
            raise ResourceNotFoundError("la solicitud no existe")
        self.notificador.enviar_solicitud_rechazada(solicitud)
        return solicitud


class MarcarServicioCompletadoService:
    """Marca una solicitud aceptada como finalizada (solo cuidador)."""

    def __init__(self, notificador=None):
        self.notificador = notificador or NotificadorFactory.crear()

    def marcar(self, solicitud_id: str, actor: Usuario, forzar: bool = False) -> SolicitudServicio:
        from servicios.service_layer.disponibilidad import (
            ya_paso_fin_programado_paseo,
        )

        try:
            solicitud = SolicitudServicio.objects.get(idSolicitud=solicitud_id)
        except SolicitudServicio.DoesNotExist:
            raise ResourceNotFoundError("la solicitud no existe")

        if solicitud.idCuidador_id != actor.idUsuario:
            raise DomainValidationError("solo el cuidador asignado puede finalizar este servicio")

        if solicitud.estado != EstadoSolicitud.ACEPTADO:
            raise DomainValidationError("solo se pueden finalizar solicitudes aceptadas")

        if not forzar:
            if solicitud.tipoServicio == TipoServicio.PASEO:
                if not ya_paso_fin_programado_paseo(solicitud):
                    raise DomainValidationError("solo se puede finalizar cuando la hora del paseo ya terminó")
            else:
                hoy = timezone.localdate()
                fecha_limite = solicitud.fechaFin or solicitud.fecha
                if fecha_limite > hoy:
                    raise DomainValidationError("solo se puede finalizar cuando la fecha del servicio ya llegó")

        solicitud.estado = EstadoSolicitud.COMPLETADO
        solicitud.save(update_fields=["estado", "updated_at"])
        self.notificador.enviar_servicio_completado(solicitud)
        self.notificador.enviar_resena_pendiente(solicitud)
        return solicitud


class CancelarSolicitudService:
    """Cancela una solicitud (dueño o cuidador). Libera slot/bloque."""

    def __init__(self, notificador=None):
        self.notificador = notificador or NotificadorFactory.crear()

    def cancelar(self, solicitud_id: str, actor: Usuario) -> SolicitudServicio:
        try:
            with transaction.atomic():
                solicitud = SolicitudServicio.objects.select_for_update().get(idSolicitud=solicitud_id)
                if solicitud.idCuidador_id != actor.idUsuario and solicitud.idDueño_id != actor.idUsuario:
                    raise DomainValidationError("solo el cuidador o el dueño pueden cancelar esta solicitud")
                if solicitud.estado not in (EstadoSolicitud.PENDIENTE, EstadoSolicitud.ACEPTADO):
                    raise DomainValidationError("solo se pueden cancelar solicitudes pendientes o aceptadas")
                hoy = date.today()
                fecha_limite = solicitud.fechaFin or solicitud.fecha
                if fecha_limite < hoy:
                    raise DomainValidationError("no se puede cancelar un servicio cuya fecha ya pasó")

                if solicitud.idSlotEvento_id:
                    slot = SlotEvento.objects.select_for_update().get(idSlot=solicitud.idSlotEvento_id)
                    slot.disponible = True
                    slot.save(update_fields=["disponible"])
                elif solicitud.idEvento_id:
                    evento = Evento.objects.select_for_update().get(idEvento=solicitud.idEvento_id)
                    evento.disponible = True
                    evento.save(update_fields=["disponible"])
                if solicitud.idSlot_id:
                    slot = SlotDisponibilidad.objects.select_for_update().get(idSlot=solicitud.idSlot_id)
                    slot.disponible = True
                    slot.save(update_fields=["disponible"])
                if solicitud.idBloqueHorario_id:
                    bloque = BloqueTiempo.objects.select_for_update().get(idBloque=solicitud.idBloqueHorario_id)
                    bloque.disponible = True
                    bloque.save(update_fields=["disponible"])

                solicitud.estado = EstadoSolicitud.CANCELADO
                solicitud.save(update_fields=["estado", "updated_at"])
        except SolicitudServicio.DoesNotExist:
            raise ResourceNotFoundError("la solicitud no existe")

        receptor = solicitud.idDueño
        if actor.idUsuario == solicitud.idDueño_id:
            receptor = solicitud.idCuidador
        destino = "/cuidador/calendario/" if receptor.rol == "cuidador" else "/dueño/mis-reservas/"

        self.notificador.enviar_reserva_cancelada(
            solicitud,
            actor=actor,
            receptor=receptor,
            destino=destino,
        )
        return solicitud


class ObtenerSolicitudServicioService:
    """Consulta una solicitud con sus relaciones para exposicion API."""

    def obtener(self, solicitud_id: str) -> SolicitudServicio:
        try:
            return SolicitudServicio.objects.select_related(
                "idDueño",
                "idCuidador",
                "idMascota",
                "idEvento",
                "idSlotEvento",
            ).get(idSolicitud=solicitud_id)
        except SolicitudServicio.DoesNotExist:
            raise ResourceNotFoundError("la solicitud no existe")


class ObtenerSolicitudParaChatService:
    """Resuelve solicitud para chat validando pertenencia segun rol."""

    def obtener_para_dueño(self, solicitud_id: str, dueño: Usuario) -> SolicitudServicio:
        if not solicitud_id:
            raise DomainValidationError("solicitud_id es requerido")
        try:
            return SolicitudServicio.objects.select_related("idDueño", "idCuidador").get(
                idSolicitud=solicitud_id,
                idDueño=dueño,
            )
        except SolicitudServicio.DoesNotExist:
            raise ResourceNotFoundError("la solicitud no existe")

    def obtener_para_cuidador(self, solicitud_id: str, cuidador: Usuario) -> SolicitudServicio:
        if not solicitud_id:
            raise DomainValidationError("solicitud_id es requerido")
        try:
            return SolicitudServicio.objects.select_related("idDueño", "idCuidador").get(
                idSolicitud=solicitud_id,
                idCuidador=cuidador,
            )
        except SolicitudServicio.DoesNotExist:
            raise ResourceNotFoundError("la solicitud no existe")
