# capa de aplicacion: logica de negocio
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, time
from decimal import Decimal

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.db.models import Q
from django.db import transaction

from servicios.domain.builder import SolicitudServicioBuilder
from servicios.domain.exceptions import (
    ConflictError,
    DomainValidationError,
    ResourceNotFoundError,
)
from servicios.infra.factory import NotificadorFactory
from servicios.models import (
    BloqueTiempo,
    Calificacion,
    DiaSemana,
    EstadoSolicitud,
    Evento,
    Mascota,
    PerfilCuidador,
    PrecioServicio,
    SolicitudServicio,
    SlotDisponibilidad,
    SlotEvento,
    TipoMascota,
    TipoServicio,
    Usuario,
    VentanaDisponibilidad,
)


class SolicitudServicioService:
    # orquesta builder y factory

    def __init__(self, notificador=None):
        # inyeccion de dependencias
        self.notificador = notificador or NotificadorFactory.crear()

    def crear_solicitud(self, datos):
        # construye y valida con builder (legacy: bloque)
        with transaction.atomic():
            builder = (
                SolicitudServicioBuilder()
                .para_dueño(datos["idDueño"])
                .para_cuidador(datos["idCuidador_id"])
                .para_mascota(datos["idMascota_id"])
                .con_servicio(datos["tipoServicio"])
                .en_fecha(datos["fecha"])
                .en_bloque(datos["idBloqueHorario_id"])
            )
            if datos.get("fechaFin"):
                builder = builder.en_fecha_fin(datos["fechaFin"])
            solicitud = builder.build()

            # bloquea el bloque para evitar carrera de reservas
            bloque = BloqueTiempo.objects.select_for_update().get(
                idBloque=solicitud.idBloqueHorario.idBloque
            )
            if not bloque.disponible:
                raise ConflictError("el bloque no esta disponible")

            solicitud.idBloqueHorario = bloque
            solicitud.save()
            bloque.disponible = False
            bloque.save(update_fields=["disponible"])

        # envia notificacion al cuidador (nueva solicitud pendiente)
        self.notificador.enviar_nueva_solicitud(solicitud)

        return solicitud

    def crear_solicitud_evento(self, datos):
        """Crea solicitud usando Evento (nuevo flujo unificado)."""
        with transaction.atomic():
            builder = (
                SolicitudServicioBuilder()
                .para_dueño(datos["idDueño"])
                .para_cuidador(datos["idCuidador_id"])
                .para_mascota(datos["idMascota_id"])
                .con_servicio(datos["tipoServicio"])
                .en_fecha(datos["fecha"])
                .en_evento(datos["idEvento_id"], datos.get("idSlotEvento_id"))
            )
            if datos.get("fechaFin"):
                builder = builder.en_fecha_fin(datos["fechaFin"])
            solicitud = builder.build()

            evento = Evento.objects.select_for_update().get(idEvento=datos["idEvento_id"])
            if not evento.disponible:
                raise ConflictError("el evento no está disponible")

            if solicitud.idSlotEvento_id:
                slot = SlotEvento.objects.select_for_update().get(idSlot=solicitud.idSlotEvento_id)
                if not slot.disponible:
                    raise ConflictError("el slot no está disponible")
                slot.disponible = False
                slot.save(update_fields=["disponible"])
            else:
                evento.disponible = False
                evento.save(update_fields=["disponible"])

            solicitud.save()

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
        tipo_servicio = datos["tipoServicio"]
        fecha = datos["fecha"]
        id_evento = datos.get("idEvento_id")

        if tipo_servicio == TipoServicio.GUARDERIA:
            raise DomainValidationError("use el flujo de guardería para este tipo de servicio")

        try:
            cuidador = Usuario.objects.get(idUsuario=cuidador_id)
        except Usuario.DoesNotExist:
            raise ResourceNotFoundError("el cuidador no existe")
        if cuidador.rol != "cuidador":
            raise DomainValidationError("el usuario no es cuidador")
        if not cuidador.verificado:
            raise DomainValidationError("el cuidador no está verificado")

        try:
            mascota = Mascota.objects.get(idMascota=mascota_id, idDueño=dueño)
        except Mascota.DoesNotExist:
            raise ResourceNotFoundError("la mascota no existe o no te pertenece")

        if not PrecioServicio.objects.filter(
            idCuidador=cuidador,
            tipoServicio=tipo_servicio,
            activo=True,
        ).exists():
            raise DomainValidationError("el cuidador no ofrece ese tipo de servicio")

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

            builder = (
                SolicitudServicioBuilder()
                .para_dueño(dueño)
                .para_cuidador(datos["idCuidador_id"])
                .para_mascota(datos["idMascota_id"])
                .con_servicio(datos["tipoServicio"])
                .en_fecha(datos["fecha"])
                .en_evento(str(evento.idEvento), str(slot.idSlot))
                .con_hora_asignada_evento(hora_asignada, orden_ruta, slot)
            )
            if datos.get("fechaFin"):
                builder = builder.en_fecha_fin(datos["fechaFin"])
            solicitud = builder.build()
            solicitud.save()
            slot.disponible = False
            slot.save(update_fields=["disponible"])

        self.notificador.enviar_nueva_solicitud(solicitud)
        return solicitud


class AgregarVentanaDisponibilidadService:
    """Cuidador crea ventana (ej: 9:00-12:00) y se generan slots automáticamente."""

    def agregar(self, cuidador: Usuario, datos: dict) -> VentanaDisponibilidad:
        if cuidador.rol != "cuidador":
            raise DomainValidationError("el usuario no tiene rol de cuidador")

        perfil, _ = PerfilCuidador.objects.get_or_create(idCuidador=cuidador)

        dia = datos.get("diaSemana", "").strip()
        hora_inicio_str = datos.get("horaInicio", "").strip()
        hora_fin_str = datos.get("horaFin", "").strip()
        duracion_slot = int(datos.get("duracionSlotMinutos", 30))
        capacidad = int(datos.get("capacidadMaxima", 5))

        if not dia or not hora_inicio_str or not hora_fin_str:
            raise DomainValidationError("día, hora inicio y hora fin son requeridos")

        opciones_dia = [c[0] for c in DiaSemana.choices]
        if dia not in opciones_dia:
            raise DomainValidationError(f"día inválido: {dia}")

        try:
            partes_i = hora_inicio_str.replace(".", ":").split(":")
            hora_inicio = time(int(partes_i[0]), int(partes_i[1]))
            partes_f = hora_fin_str.replace(".", ":").split(":")
            hora_fin = time(int(partes_f[0]), int(partes_f[1]))
        except (ValueError, IndexError):
            raise DomainValidationError("formato de hora inválido (HH:MM)")

        if hora_fin <= hora_inicio:
            raise DomainValidationError("la hora fin debe ser posterior a la hora inicio")

        if duracion_slot < 15 or duracion_slot > 120:
            raise DomainValidationError("duracionSlotMinutos debe estar entre 15 y 120")

        tipo = datos.get("tipoServicio", "").strip()
        validos = {TipoServicio.PASEO, TipoServicio.GUARDERIA}
        if tipo == TipoServicio.PASEO and (capacidad < 1 or capacidad > 4):
            raise DomainValidationError("capacidadMaxima para Paseo debe estar entre 1 y 4 perros")
        if tipo == TipoServicio.GUARDERIA and (capacidad < 1 or capacidad > 5):
            raise DomainValidationError("capacidadMaxima para Guardería debe estar entre 1 y 5")
        if tipo not in validos:
            raise DomainValidationError("tipo de servicio inválido para la ventana")
        if not PrecioServicio.objects.filter(
            idCuidador=cuidador, tipoServicio=tipo, activo=True
        ).exists():
            raise DomainValidationError("debes tener el servicio activo antes de agregar horarios")

        nombre_lugar = (datos.get("nombreLugar") or "").strip()
        lat = datos.get("latitud")
        lng = datos.get("longitud")
        precio = datos.get("precioCOP")
        lat_dec = lng_dec = None
        if lat is not None and str(lat).strip():
            try:
                lat_dec = Decimal(str(lat))
            except Exception:
                pass
        if lng is not None and str(lng).strip():
            try:
                lng_dec = Decimal(str(lng))
            except Exception:
                pass
        precio_int = None
        if precio is not None and str(precio).strip():
            try:
                precio_int = int(precio)
                if precio_int < 1:
                    precio_int = None
            except (ValueError, TypeError):
                pass

        existe = VentanaDisponibilidad.objects.filter(
            idCuidador=perfil, tipoServicio=tipo, diaSemana=dia,
            horaInicio=hora_inicio, horaFin=hora_fin, nombreLugar=nombre_lugar or "",
        ).exists()
        if existe:
            raise ConflictError("ya existe una ventana con ese horario y lugar")

        with transaction.atomic():
            ventana = VentanaDisponibilidad.objects.create(
                idCuidador=perfil,
                tipoServicio=tipo,
                diaSemana=dia,
                horaInicio=hora_inicio,
                horaFin=hora_fin,
                duracionSlotMinutos=duracion_slot,
                capacidadMaxima=capacidad,
                nombreLugar=nombre_lugar or "",
                latitud=lat_dec,
                longitud=lng_dec,
                precioCOP=precio_int,
            )
            hi_m = _time_to_minutes(hora_inicio)
            hf_m = _time_to_minutes(hora_fin)
            m = hi_m
            while m < hf_m:
                SlotDisponibilidad.objects.create(
                    idVentana=ventana,
                    horaInicio=_minutes_to_time(m),
                    disponible=True,
                )
                m += duracion_slot
        return ventana


class AgregarEventoService:
    """Unifica BloqueTiempo y VentanaDisponibilidad. Crea Evento con o sin slots según tipo."""

    def agregar(self, cuidador: Usuario, datos: dict) -> Evento:
        if cuidador.rol != "cuidador":
            raise DomainValidationError("el usuario no tiene rol de cuidador")

        perfil, _ = PerfilCuidador.objects.get_or_create(idCuidador=cuidador)

        dia = datos.get("diaSemana", "").strip()
        hora_inicio_str = datos.get("horaInicio", "").strip()
        hora_fin_str = datos.get("horaFin", "").strip()

        if not dia or not hora_inicio_str or not hora_fin_str:
            raise DomainValidationError("día, hora inicio y hora fin son requeridos")

        opciones_dia = [c[0] for c in DiaSemana.choices]
        if dia not in opciones_dia:
            raise DomainValidationError(f"día inválido: {dia}")

        try:
            partes_i = hora_inicio_str.replace(".", ":").split(":")
            hora_inicio = time(int(partes_i[0]), int(partes_i[1]))
            partes_f = hora_fin_str.replace(".", ":").split(":")
            hora_fin = time(int(partes_f[0]), int(partes_f[1]))
        except (ValueError, IndexError):
            raise DomainValidationError("formato de hora inválido (HH:MM)")

        if hora_fin <= hora_inicio:
            raise DomainValidationError("la hora fin debe ser posterior a la hora inicio")

        tipo = datos.get("tipoServicio", "").strip()
        validos = {TipoServicio.PASEO, TipoServicio.GUARDERIA}
        if tipo not in validos:
            raise DomainValidationError("tipo de servicio inválido para el evento")
        if not PrecioServicio.objects.filter(
            idCuidador=cuidador, tipoServicio=tipo, activo=True
        ).exists():
            raise DomainValidationError("debes tener el servicio activo antes de agregar horarios")

        nombre_lugar = (datos.get("nombreLugar") or "").strip()
        lat = datos.get("latitud")
        lng = datos.get("longitud")
        precio = datos.get("precioCOP")
        lat_dec = lng_dec = None
        if lat is not None and str(lat).strip():
            try:
                lat_dec = Decimal(str(lat))
            except Exception:
                pass
        if lng is not None and str(lng).strip():
            try:
                lng_dec = Decimal(str(lng))
            except Exception:
                pass
        precio_int = None
        if precio is not None and str(precio).strip():
            try:
                precio_int = int(precio)
                if precio_int < 1:
                    precio_int = None
            except (ValueError, TypeError):
                pass

        duracion_slot = datos.get("duracionSlotMinutos")
        capacidad = int(datos.get("capacidadMaxima", 1))

        if tipo == TipoServicio.GUARDERIA:
            duracion_slot = None
            if capacidad < 1 or capacidad > 5:
                raise DomainValidationError("capacidadMaxima para Guardería debe estar entre 1 y 5")
        elif tipo == TipoServicio.PASEO:
            if duracion_slot is not None and str(duracion_slot).strip():
                duracion_slot = int(duracion_slot)
                if duracion_slot < 15 or duracion_slot > 120:
                    raise DomainValidationError("duracionSlotMinutos debe estar entre 15 y 120")
            else:
                duracion_slot = None
            if capacidad < 1 or capacidad > 4:
                raise DomainValidationError("capacidadMaxima para Paseo debe estar entre 1 y 4 perros")

        existe = Evento.objects.filter(
            idCuidador=perfil, tipoServicio=tipo, diaSemana=dia,
            horaInicio=hora_inicio, horaFin=hora_fin, nombreLugar=nombre_lugar or "",
        ).exists()
        if existe:
            raise ConflictError("ya existe un evento con ese horario y lugar")

        with transaction.atomic():
            evento = Evento.objects.create(
                idCuidador=perfil,
                tipoServicio=tipo,
                diaSemana=dia,
                horaInicio=hora_inicio,
                horaFin=hora_fin,
                nombreLugar=nombre_lugar or "",
                latitud=lat_dec,
                longitud=lng_dec,
                precioCOP=precio_int,
                capacidadMaxima=capacidad,
                duracionSlotMinutos=duracion_slot,
                disponible=True,
            )
            if duracion_slot is not None:
                hi_m = _time_to_minutes(hora_inicio)
                hf_m = _time_to_minutes(hora_fin)
                m = hi_m
                while m < hf_m:
                    SlotEvento.objects.create(
                        idEvento=evento,
                        horaInicio=_minutes_to_time(m),
                        disponible=True,
                    )
                    m += duracion_slot
        return evento


class EliminarEventoService:
    """Elimina un evento. No permite si hay reservas pendientes o aceptadas."""

    def eliminar(self, cuidador: Usuario, evento_id: str):
        if cuidador.rol != "cuidador":
            raise DomainValidationError("el usuario no tiene rol de cuidador")
        try:
            perfil = PerfilCuidador.objects.get(idCuidador=cuidador)
        except PerfilCuidador.DoesNotExist:
            raise ResourceNotFoundError("perfil de cuidador no encontrado")
        try:
            evento = Evento.objects.get(idEvento=evento_id, idCuidador=perfil)
        except Evento.DoesNotExist:
            raise ResourceNotFoundError("evento no encontrado")
        if evento.solicitudes.filter(estado__in=["pendiente", "aceptado"]).exists():
            raise ConflictError("no puedes eliminar un evento con reservas pendientes o aceptadas")
        evento.delete()


class ListarEventosCuidadorService:
    """Lista todos los eventos del cuidador, opcionalmente filtrados por tipo."""

    def listar(self, cuidador: Usuario, tipo_servicio: str | None = None):
        if cuidador.rol != "cuidador":
            raise DomainValidationError("el usuario no tiene rol de cuidador")
        try:
            perfil = PerfilCuidador.objects.get(idCuidador=cuidador)
        except PerfilCuidador.DoesNotExist:
            return []
        qs = Evento.objects.filter(idCuidador=perfil).prefetch_related("slots")
        if tipo_servicio:
            qs = qs.filter(tipoServicio=tipo_servicio)
        return qs.order_by("tipoServicio", "diaSemana", "horaInicio")


class AsignarHoraRecogidaService:
    """Calcula horaRecogidaAsignada y ordenEnRuta por proximidad (Haversine)."""

    def asignar(
        self,
        cuidador: Usuario,
        ventana: VentanaDisponibilidad,
        fecha: date,
        mascota: Mascota,
        dueño: Usuario,
    ) -> tuple[time, int, SlotDisponibilidad]:
        """
        Retorna (horaRecogidaAsignada, ordenEnRuta, slot). Legacy: ventana + SlotDisponibilidad.
        """
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

    def asignar_evento(
        self,
        cuidador: Usuario,
        evento: Evento,
        fecha: date,
        mascota: Mascota,
        dueño: Usuario,
    ) -> tuple[time, int, SlotEvento]:
        """
        Retorna (horaRecogidaAsignada, ordenEnRuta, slot). Nuevo: evento + SlotEvento.
        """
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
                dist = _haversine_km(float(cuidador_lat), float(cuidador_lon), float(d.latitud), float(d.longitud))
            else:
                dist = 9999
            rutas.append((dist, sol))

        if dueño_lat and dueño_lon:
            dist_nuevo = _haversine_km(float(cuidador_lat), float(cuidador_lon), float(dueño_lat), float(dueño_lon))
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
        tipo_servicio = datos["tipoServicio"]
        fecha = datos["fecha"]
        id_ventana = datos.get("idVentana_id")

        if tipo_servicio == TipoServicio.GUARDERIA:
            raise DomainValidationError("use el flujo de guardería para este tipo de servicio")

        try:
            cuidador = Usuario.objects.get(idUsuario=cuidador_id)
        except Usuario.DoesNotExist:
            raise ResourceNotFoundError("el cuidador no existe")
        if cuidador.rol != "cuidador":
            raise DomainValidationError("el usuario no es cuidador")
        if not cuidador.verificado:
            raise DomainValidationError("el cuidador no está verificado")

        try:
            mascota = Mascota.objects.get(idMascota=mascota_id, idDueño=dueño)
        except Mascota.DoesNotExist:
            raise ResourceNotFoundError("la mascota no existe o no te pertenece")

        if not PrecioServicio.objects.filter(
            idCuidador=cuidador,
            tipoServicio=tipo_servicio,
            activo=True,
        ).exists():
            raise DomainValidationError("el cuidador no ofrece ese tipo de servicio")

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

            builder = (
                SolicitudServicioBuilder()
                .para_dueño(dueño)
                .para_cuidador(datos["idCuidador_id"])
                .para_mascota(datos["idMascota_id"])
                .con_servicio(datos["tipoServicio"])
                .en_fecha(datos["fecha"])
                .en_ventana(ventana.idVentana)
                .con_hora_asignada(hora_asignada, orden_ruta, slot)
            )
            if datos.get("fechaFin"):
                builder = builder.en_fecha_fin(datos["fechaFin"])
            solicitud = builder.build()
            solicitud.save()
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

                # Liberar slot o bloque según corresponda
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
    """Marca una solicitud aceptada como completada (cuidador o dueño)."""

    def __init__(self, notificador=None):
        self.notificador = notificador or NotificadorFactory.crear()

    def marcar(self, solicitud_id: str, actor: Usuario) -> SolicitudServicio:
        try:
            solicitud = SolicitudServicio.objects.get(idSolicitud=solicitud_id)
        except SolicitudServicio.DoesNotExist:
            raise ResourceNotFoundError("la solicitud no existe")

        if solicitud.idCuidador_id != actor.idUsuario and solicitud.idDueño_id != actor.idUsuario:
            raise DomainValidationError("solo el cuidador o el dueño pueden marcar como completado")

        if solicitud.estado != EstadoSolicitud.ACEPTADO:
            raise DomainValidationError("solo se pueden completar solicitudes aceptadas")

        hoy = date.today()
        if solicitud.fechaFin:
            fecha_limite = solicitud.fechaFin
        else:
            fecha_limite = solicitud.fecha
        if fecha_limite > hoy:
            raise DomainValidationError("solo se puede marcar completado cuando la fecha del servicio ya pasó")

        solicitud.estado = EstadoSolicitud.COMPLETADO
        solicitud.save(update_fields=["estado", "updated_at"])
        self.notificador.enviar_servicio_completado(solicitud)
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
        self.notificador.enviar_solicitud_rechazada(solicitud)
        return solicitud


class CrearSolicitudServicioAppService:
    # app service del flujo crear solicitud

    def __init__(
        self,
        solicitud_service: SolicitudServicioService | None = None,
        solicitud_con_asignacion: CrearSolicitudConAsignacionService | None = None,
        solicitud_con_asignacion_evento: CrearSolicitudConAsignacionEventoService | None = None,
    ):
        self._solicitud_service = solicitud_service or SolicitudServicioService()
        self._solicitud_con_asignacion = solicitud_con_asignacion or CrearSolicitudConAsignacionService()
        self._solicitud_con_asignacion_evento = solicitud_con_asignacion_evento or CrearSolicitudConAsignacionEventoService()

    def get_form_context(self) -> dict:
        # carga datos para el formulario: eventos (principal), ventanas y bloques (legacy)
        dueños = Usuario.objects.filter(rol="dueño")
        cuidadores = Usuario.objects.filter(rol="cuidador", verificado=True)
        mascotas = Mascota.objects.all()
        eventos = Evento.objects.filter(disponible=True).select_related("idCuidador__idCuidador").prefetch_related("slots")
        ventanas = VentanaDisponibilidad.objects.select_related("idCuidador__idCuidador").prefetch_related("slots")
        bloques = BloqueTiempo.objects.filter(disponible=True).select_related("idCuidador__idCuidador")

        eventos_por_cuidador: dict[str, dict[str, list[dict]]] = {}
        for e in eventos:
            cuidador_id = str(e.idCuidador.idCuidador.idUsuario)
            if cuidador_id not in eventos_por_cuidador:
                eventos_por_cuidador[cuidador_id] = {"paseo": [], "guarderia": []}
            slots_libres = e.slots.filter(disponible=True).count() if e.duracionSlotMinutos else 0
            texto = f"{e.diaSemana} {e.horaInicio}-{e.horaFin}"
            if slots_libres:
                texto += f" ({slots_libres} slots)"
            eventos_por_cuidador[cuidador_id][e.tipoServicio].append({
                "id": str(e.idEvento),
                "dia": e.diaSemana,
                "texto": texto,
            })

        ventanas_por_cuidador: dict[str, dict[str, list[dict]]] = {}
        for v in ventanas:
            cuidador_id = str(v.idCuidador.idCuidador.idUsuario)
            if cuidador_id not in ventanas_por_cuidador:
                ventanas_por_cuidador[cuidador_id] = {"paseo": [], "guarderia": []}
            slots_libres = v.slots.filter(disponible=True).count()
            ventanas_por_cuidador[cuidador_id][v.tipoServicio].append({
                "id": str(v.idVentana),
                "dia": v.diaSemana,
                "texto": f"{v.diaSemana} {v.horaInicio}-{v.horaFin} ({slots_libres} slots)",
            })

        bloques_por_cuidador: dict[str, dict[str, list[dict[str, str]]]] = {}
        for bloque in bloques:
            cuidador_id = str(bloque.idCuidador.idCuidador.idUsuario)
            if cuidador_id not in bloques_por_cuidador:
                bloques_por_cuidador[cuidador_id] = {"paseo": [], "guarderia": []}
            bloques_por_cuidador[cuidador_id][bloque.tipoServicio].append({
                "id": str(bloque.idBloque),
                "dia": bloque.diaSemana,
                "texto": f"{bloque.diaSemana} {bloque.horaInicio}-{bloque.horaFin}",
            })

        return {
            "dueños": dueños,
            "cuidadores": cuidadores,
            "mascotas": mascotas,
            "eventos_por_cuidador": json.dumps(eventos_por_cuidador),
            "ventanas_por_cuidador": json.dumps(ventanas_por_cuidador),
            "bloques_por_cuidador": json.dumps(bloques_por_cuidador),
        }

    def crear_desde_form(self, post_data) -> object:
        dueño = self._resolver_dueño(post_data.get("idDueño_id"))

        fecha_str = post_data.get("fecha")
        if not fecha_str:
            raise DomainValidationError("fecha es requerida")

        try:
            fecha = datetime.strptime(fecha_str, "%Y-%m-%d").date()
        except ValueError:
            raise DomainValidationError("formato de fecha invalido, use yyyy-mm-dd")

        tipo_servicio = post_data.get("tipoServicio")
        fecha_fin_str = post_data.get("fechaFin")
        fecha_fin = None
        if fecha_fin_str:
            try:
                fecha_fin = datetime.strptime(fecha_fin_str, "%Y-%m-%d").date()
            except ValueError:
                raise DomainValidationError("formato de fecha fin invalido, use yyyy-mm-dd")
        if tipo_servicio == TipoServicio.GUARDERIA and not fecha_fin:
            raise DomainValidationError("fechaFin es requerida para guardería")

        id_ventana = post_data.get("idVentana_id")
        id_bloque = post_data.get("idBloqueHorario_id")
        id_evento = post_data.get("idEvento_id")

        if id_evento:
            datos = {
                "idDueño": dueño,
                "idCuidador_id": post_data.get("idCuidador_id"),
                "idMascota_id": post_data.get("idMascota_id"),
                "tipoServicio": tipo_servicio,
                "fecha": fecha,
                "idEvento_id": id_evento,
            }
            if fecha_fin:
                datos["fechaFin"] = fecha_fin
            evento = Evento.objects.get(idEvento=id_evento)
            if evento.duracionSlotMinutos is not None:
                return self._solicitud_con_asignacion_evento.crear(datos)
            return self._solicitud_service.crear_solicitud_evento(datos)

        if tipo_servicio == TipoServicio.PASEO and id_ventana:
            datos = {
                "idDueño": dueño,
                "idCuidador_id": post_data.get("idCuidador_id"),
                "idMascota_id": post_data.get("idMascota_id"),
                "tipoServicio": tipo_servicio,
                "fecha": fecha,
                "idVentana_id": id_ventana,
            }
            return self._solicitud_con_asignacion.crear(datos)

        if id_bloque:
            datos = {
                "idDueño": dueño,
                "idCuidador_id": post_data.get("idCuidador_id"),
                "idMascota_id": post_data.get("idMascota_id"),
                "tipoServicio": tipo_servicio,
                "fecha": fecha,
                "idBloqueHorario_id": id_bloque,
            }
            if fecha_fin:
                datos["fechaFin"] = fecha_fin
            return self._solicitud_service.crear_solicitud(datos)

        if tipo_servicio == TipoServicio.PASEO:
            datos = {
                "idDueño": dueño,
                "idCuidador_id": post_data.get("idCuidador_id"),
                "idMascota_id": post_data.get("idMascota_id"),
                "tipoServicio": tipo_servicio,
                "fecha": fecha,
            }
            return self._solicitud_con_asignacion.crear(datos)

        raise DomainValidationError("debes seleccionar una ventana o bloque horario")

    def crear_desde_api(self, validated_data: dict) -> object:
        dueño = self._resolver_dueño(validated_data.get("idDueño_id"))
        tipo_servicio = validated_data.get("tipoServicio")
        fecha_fin = validated_data.get("fechaFin")
        if tipo_servicio == TipoServicio.GUARDERIA and not fecha_fin:
            raise DomainValidationError("fechaFin es requerida para guardería")

        id_ventana = validated_data.get("idVentana_id")
        id_bloque = validated_data.get("idBloqueHorario_id")
        id_evento = validated_data.get("idEvento_id")

        if id_evento:
            datos = {
                "idDueño": dueño,
                "idCuidador_id": validated_data.get("idCuidador_id"),
                "idMascota_id": validated_data.get("idMascota_id"),
                "tipoServicio": tipo_servicio,
                "fecha": validated_data.get("fecha"),
                "idEvento_id": id_evento,
            }
            if fecha_fin:
                datos["fechaFin"] = fecha_fin
            evento = Evento.objects.get(idEvento=id_evento)
            if evento.duracionSlotMinutos is not None:
                return self._solicitud_con_asignacion_evento.crear(datos)
            return self._solicitud_service.crear_solicitud_evento(datos)

        if tipo_servicio == TipoServicio.PASEO and (id_ventana or not id_bloque):
            datos = {
                "idDueño": dueño,
                "idCuidador_id": validated_data.get("idCuidador_id"),
                "idMascota_id": validated_data.get("idMascota_id"),
                "tipoServicio": tipo_servicio,
                "fecha": validated_data.get("fecha"),
                "idVentana_id": id_ventana,
            }
            if fecha_fin:
                datos["fechaFin"] = fecha_fin
            return self._solicitud_con_asignacion.crear(datos)

        if id_bloque:
            datos = {
                "idDueño": dueño,
                "idCuidador_id": validated_data.get("idCuidador_id"),
                "idMascota_id": validated_data.get("idMascota_id"),
                "tipoServicio": tipo_servicio,
                "fecha": validated_data.get("fecha"),
                "idBloqueHorario_id": id_bloque,
            }
            if fecha_fin:
                datos["fechaFin"] = fecha_fin
            return self._solicitud_service.crear_solicitud(datos)

        raise DomainValidationError("debes indicar idVentana_id o idBloqueHorario_id")

    def _resolver_dueño(self, dueño_id) -> Usuario:
        # exige dueño explicito para evitar defaults ocultos
        if not dueño_id:
            raise DomainValidationError("idDueño_id es requerido")
        try:
            dueño = Usuario.objects.get(idUsuario=dueño_id)
        except Usuario.DoesNotExist:
            raise ResourceNotFoundError("el dueño no existe")
        if dueño.rol != "dueño":
            raise DomainValidationError("el usuario no tiene rol de dueño")
        return dueño


class CrearUsuarioAppService:
    # app service para registro de usuarios

    _MAX_NOMBRE = 50
    _MAX_USERNAME = 30
    _MAX_CEDULA = 20
    _MAX_TELEFONO = 20

    def crear_usuario(self, datos: dict) -> Usuario:
        nombre = datos.get("nombre")
        apellido = datos.get("apellido")
        username = datos.get("username")
        correo = datos.get("correo")
        cedula = datos.get("cedula")
        telefono = datos.get("telefono")
        ciudad = datos.get("ciudad")
        rol = datos.get("rol")

        # Contraseña: acepta password o (password1, password2); validación en capa de aplicación
        password = datos.get("password")
        if password is None and "password1" in datos and "password2" in datos:
            if datos.get("password1") != datos.get("password2"):
                raise DomainValidationError("las contraseñas no coinciden")
            password = datos.get("password1")
        if not password:
            raise DomainValidationError("la contraseña es requerida")

        # Fecha nacimiento: acepta date o fechaNacimiento_str (yyyy-mm-dd)
        fecha_nacimiento = datos.get("fechaNacimiento")
        if fecha_nacimiento is None and datos.get("fechaNacimiento_str"):
            try:
                fecha_nacimiento = datetime.strptime(datos["fechaNacimiento_str"], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                raise DomainValidationError("formato de fecha de nacimiento inválido, use AAAA-MM-DD")
        if not fecha_nacimiento:
            raise DomainValidationError("la fecha de nacimiento es requerida")

        campos_requeridos = [
            nombre, apellido, username, correo, cedula,
            telefono, ciudad, rol,
        ]
        if not all(campos_requeridos):
            raise DomainValidationError(
                "todos los campos del registro son requeridos"
            )

        self._validar_longitudes(nombre, apellido, username, cedula, telefono)
        self._validar_correo(correo)
        self._validar_password(password)

        hoy = date.today()
        edad = (
            hoy.year - fecha_nacimiento.year
            - ((hoy.month, hoy.day) < (fecha_nacimiento.month, fecha_nacimiento.day))
        )
        if edad < 15:
            raise DomainValidationError("debes tener al menos 15 años para registrarte")

        if Usuario.objects.filter(username=username).exists():
            raise ConflictError("ya existe un usuario con ese nombre de usuario")
        if User.objects.filter(username=username).exists():
            raise ConflictError("ya existe una cuenta con ese nombre de usuario")
        if Usuario.objects.filter(cedula=cedula).exists():
            raise ConflictError("ya existe un usuario con esa cédula")

        opciones_rol = [choice[0] for choice in Usuario._meta.get_field("rol").choices]
        if rol not in opciones_rol:
            raise DomainValidationError(f"rol inválido: {rol}")

        with transaction.atomic():
            user = User.objects.create_user(
                username=username,
                email=correo,
                password=password,
            )
            usuario = Usuario.objects.create(
                user=user,
                nombre=nombre,
                apellido=apellido,
                username=username,
                correo=correo,
                cedula=cedula,
                telefono=telefono,
                fechaNacimiento=fecha_nacimiento,
                ciudad=ciudad,
                rol=rol,
                verificado=True,
            )
        return usuario

    def _validar_longitudes(self, nombre, apellido, username, cedula, telefono):
        if len(nombre) > self._MAX_NOMBRE:
            raise DomainValidationError(f"el nombre no puede superar {self._MAX_NOMBRE} caracteres")
        if len(apellido) > self._MAX_NOMBRE:
            raise DomainValidationError(f"el apellido no puede superar {self._MAX_NOMBRE} caracteres")
        if len(username) > self._MAX_USERNAME:
            raise DomainValidationError(f"el username no puede superar {self._MAX_USERNAME} caracteres")
        if len(cedula) > self._MAX_CEDULA:
            raise DomainValidationError(f"la cédula no puede superar {self._MAX_CEDULA} caracteres")
        if len(telefono) > self._MAX_TELEFONO:
            raise DomainValidationError(f"el teléfono no puede superar {self._MAX_TELEFONO} caracteres")

    @staticmethod
    def _validar_correo(correo: str):
        import re
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", correo):
            raise DomainValidationError("el correo no tiene un formato válido")

    @staticmethod
    def _validar_password(password: str):
        import re
        if len(password) < 8:
            raise DomainValidationError("la contraseña debe tener al menos 8 caracteres")
        if not re.search(r"[A-Z]", password):
            raise DomainValidationError("la contraseña debe tener al menos una mayúscula")
        if not re.search(r"[0-9]", password):
            raise DomainValidationError("la contraseña debe tener al menos un número")
        if not re.search(r"[^A-Za-z0-9]", password):
            raise DomainValidationError("la contraseña debe tener al menos un carácter especial")


class AutenticacionService:
    # reglas de autenticacion de dominio

    def autenticar(self, username: str, password: str) -> Usuario:
        if not username or not password:
            raise DomainValidationError("username y password son requeridos")

        user = authenticate(username=username, password=password)
        if user is None:
            raise DomainValidationError("credenciales inválidas")

        try:
            usuario = (
                Usuario.objects.only("idUsuario", "rol", "user")
                .select_related("user")
                .get(user=user)
            )
        except Usuario.DoesNotExist:
            raise ResourceNotFoundError("el usuario no existe en el dominio")

        # regla: cuidadores deben estar verificados para usar la plataforma
        if usuario.rol == "cuidador" and not usuario.verificado:
            raise DomainValidationError("el cuidador aún no está verificado")

        return usuario


def _haversine_km(lat1: Decimal | float, lon1: Decimal | float, lat2: Decimal | float, lon2: Decimal | float) -> float:
    """Distancia en km entre dos puntos (Haversine)."""
    R = 6371  # radio Tierra en km
    lat1, lon1, lat2, lon2 = map(math.radians, [float(lat1), float(lon1), float(lat2), float(lon2)])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    return R * c


def _time_to_minutes(t: time) -> int:
    """Convierte time a minutos desde medianoche."""
    return t.hour * 60 + t.minute


def _minutes_to_time(m: int) -> time:
    """Convierte minutos desde medianoche a time (HH:MM, sin segundos)."""
    h, mn = divmod(m % (24 * 60), 60)
    return time(h, mn, 0)


class BuscarCuidadoresDisponiblesService:
    """Busca cuidadores con bloques disponibles para fecha, hora y duración."""

    _DIAS = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
    _DURACIONES_VALIDAS = [30, 60, 90, 120]  # minutos, máx 2 horas

    def buscar(
        self,
        dueño: Usuario,
        mascota_id: str,
        fecha_o_str,
        hora_str: str,
        duracion_minutos: int,
        solo_ciudad: bool = True,
    ) -> list:
        """
        Busca cuidadores con bloques que se solapan con [hora_inicio, hora_fin].
        Ordena por proximidad: los que pueden empezar más cerca de la hora buscada primero.
        """
        if dueño.rol != "dueño":
            raise DomainValidationError("el usuario no tiene rol de dueño")
        if not mascota_id or not str(mascota_id).strip():
            raise DomainValidationError("debes seleccionar una mascota")
        if duracion_minutos not in self._DURACIONES_VALIDAS:
            raise DomainValidationError(
                "la duración debe ser 30, 60, 90, 120, 150, 180, 210 o 240 minutos"
            )
        # Acepta date o str (yyyy-mm-dd)
        if isinstance(fecha_o_str, date):
            fecha = fecha_o_str
        elif isinstance(fecha_o_str, str) and fecha_o_str.strip():
            try:
                fecha = datetime.strptime(fecha_o_str.strip(), "%Y-%m-%d").date()
            except ValueError:
                raise DomainValidationError("formato de fecha inválido, use AAAA-MM-DD")
        else:
            raise DomainValidationError("la fecha es requerida")
        try:
            mascota = Mascota.objects.get(idMascota=mascota_id, idDueño=dueño)
        except Mascota.DoesNotExist:
            raise ResourceNotFoundError("la mascota no existe o no te pertenece")

        if fecha < date.today():
            raise DomainValidationError("la fecha no puede ser en el pasado")

        try:
            hora_inicio = datetime.strptime(hora_str, "%H:%M").time()
        except ValueError:
            try:
                hora_inicio = datetime.strptime(hora_str, "%H:%M:%S").time()
            except ValueError:
                raise DomainValidationError("formato de hora inválido, use HH:MM")

        dt = datetime.combine(fecha, hora_inicio)
        hora_fin = (dt + timedelta(minutes=duracion_minutos)).time()

        dia_semana = self._DIAS[fecha.weekday()]

        dueño_lat = dueño.latitud
        dueño_lon = dueño.longitud
        usar_radio = solo_ciudad and dueño_lat and dueño_lon

        resultado = []

        # Eventos con slots (paseo con cupos) - flujo principal
        eventos_slots = (
            Evento.objects.filter(
                tipoServicio=TipoServicio.PASEO,
                diaSemana=dia_semana,
                horaInicio__lt=hora_fin,
                horaFin__gt=hora_inicio,
                duracionSlotMinutos__isnull=False,
                slots__disponible=True,
            )
            .select_related("idCuidador__idCuidador")
            .prefetch_related("slots")
            .distinct()
            .order_by("horaInicio")
        )
        if solo_ciudad and not usar_radio and dueño.ciudad:
            eventos_slots = eventos_slots.filter(idCuidador__idCuidador__ciudad=dueño.ciudad)

        for evento in eventos_slots:
            perfil = evento.idCuidador
            cuidador = perfil.idCuidador
            if not cuidador.verificado:
                continue
            precio = PrecioServicio.objects.filter(
                idCuidador=cuidador,
                tipoServicio=TipoServicio.PASEO,
                activo=True,
            ).first()
            if not precio:
                continue

            tipos_pref = (perfil.tiposMascotaPreferidos or "ambos").lower().strip()
            if tipos_pref != "ambos" and mascota.tipo not in tipos_pref.split(","):
                continue

            distancia_km = None
            if usar_radio and cuidador.latitud and cuidador.longitud:
                distancia_km = _haversine_km(dueño_lat, dueño_lon, cuidador.latitud, cuidador.longitud)
                if cuidador.radioKm and distancia_km > float(cuidador.radioKm):
                    continue
                if not cuidador.radioKm and dueño.ciudad and cuidador.ciudad != dueño.ciudad:
                    continue
            elif usar_radio and (not cuidador.latitud or not cuidador.longitud):
                if dueño.ciudad and cuidador.ciudad != dueño.ciudad:
                    continue

            hi_m = _time_to_minutes(evento.horaInicio)
            hf_m = _time_to_minutes(evento.horaFin)
            req_hi_m = _time_to_minutes(hora_inicio)
            req_hf_m = _time_to_minutes(hora_fin)

            inicio_sugerido_m = max(req_hi_m, hi_m)
            fin_sugerido_m = min(req_hf_m, hf_m)
            if fin_sugerido_m - inicio_sugerido_m < duracion_minutos:
                continue

            hora_sugerida = _minutes_to_time(inicio_sugerido_m)
            distancia_m = abs(inicio_sugerido_m - req_hi_m)

            slots_libres = [s for s in evento.slots.all() if s.disponible]
            duracion_horas = duracion_minutos / 60.0
            tarifa = evento.precioCOP or precio.precioCOP
            prom, cnt = _calificacion_promedio_count(cuidador)
            resultado.append({
                "evento": evento,
                "eventos_disponibles": [{"id": str(evento.idEvento), "texto": f"{evento.diaSemana} {evento.horaInicio}-{evento.horaFin}"}],
                "cuidador": cuidador,
                "perfil": perfil,
                "tarifa_total": evento.precioCOP or int(precio.precioCOP * duracion_horas),
                "tarifa_hora": precio.precioCOP,
                "duracion_minutos": duracion_minutos,
                "duracion_horas": duracion_horas,
                "hora_sugerida": hora_sugerida,
                "distancia_minutos": distancia_m,
                "distancia_km": round(distancia_km, 1) if distancia_km is not None else None,
                "calificacion_promedio": prom,
                "calificacion_count": cnt,
                "tipo_servicio": TipoServicio.PASEO,
                "descripcion_servicio": precio.descripcion or (perfil.descripcion or ""),
                "slots_libres": len(slots_libres),
            })

        # Fallback: Ventanas (legacy)
        ventanas = (
            VentanaDisponibilidad.objects.filter(
                tipoServicio=TipoServicio.PASEO,
                diaSemana=dia_semana,
                horaInicio__lt=hora_fin,
                horaFin__gt=hora_inicio,
                slots__disponible=True,
            )
            .select_related("idCuidador__idCuidador")
            .prefetch_related("slots")
            .distinct()
            .order_by("horaInicio")
        )
        if solo_ciudad and not usar_radio and dueño.ciudad:
            ventanas = ventanas.filter(idCuidador__idCuidador__ciudad=dueño.ciudad)

        for ventana in ventanas:
            perfil = ventana.idCuidador
            cuidador = perfil.idCuidador
            if not cuidador.verificado:
                continue
            precio = PrecioServicio.objects.filter(
                idCuidador=cuidador,
                tipoServicio=TipoServicio.PASEO,
                activo=True,
            ).first()
            if not precio:
                continue

            tipos_pref = (perfil.tiposMascotaPreferidos or "ambos").lower().strip()
            if tipos_pref != "ambos" and mascota.tipo not in tipos_pref.split(","):
                continue

            distancia_km = None
            if usar_radio and cuidador.latitud and cuidador.longitud:
                distancia_km = _haversine_km(dueño_lat, dueño_lon, cuidador.latitud, cuidador.longitud)
                if cuidador.radioKm and distancia_km > float(cuidador.radioKm):
                    continue
                if not cuidador.radioKm and dueño.ciudad and cuidador.ciudad != dueño.ciudad:
                    continue
            elif usar_radio and (not cuidador.latitud or not cuidador.longitud):
                if dueño.ciudad and cuidador.ciudad != dueño.ciudad:
                    continue

            hi_m = _time_to_minutes(ventana.horaInicio)
            hf_m = _time_to_minutes(ventana.horaFin)
            req_hi_m = _time_to_minutes(hora_inicio)
            req_hf_m = _time_to_minutes(hora_fin)

            inicio_sugerido_m = max(req_hi_m, hi_m)
            fin_sugerido_m = min(req_hf_m, hf_m)
            if fin_sugerido_m - inicio_sugerido_m < duracion_minutos:
                continue

            hora_sugerida = _minutes_to_time(inicio_sugerido_m)
            distancia_m = abs(inicio_sugerido_m - req_hi_m)

            slots_libres = [s for s in ventana.slots.all() if s.disponible]
            duracion_horas = duracion_minutos / 60.0
            prom, cnt = _calificacion_promedio_count(cuidador)
            resultado.append({
                "ventana": ventana,
                "ventanas_disponibles": [{"id": str(ventana.idVentana), "texto": f"{ventana.diaSemana} {ventana.horaInicio}-{ventana.horaFin}"}],
                "cuidador": cuidador,
                "perfil": perfil,
                "tarifa_total": int(precio.precioCOP * duracion_horas),
                "tarifa_hora": precio.precioCOP,
                "duracion_minutos": duracion_minutos,
                "duracion_horas": duracion_horas,
                "hora_sugerida": hora_sugerida,
                "distancia_minutos": distancia_m,
                "distancia_km": round(distancia_km, 1) if distancia_km is not None else None,
                "calificacion_promedio": prom,
                "calificacion_count": cnt,
                "tipo_servicio": TipoServicio.PASEO,
                "descripcion_servicio": precio.descripcion or (perfil.descripcion or ""),
                "slots_libres": len(slots_libres),
            })

        resultado.sort(key=lambda x: (
            (x["distancia_km"] if x["distancia_km"] is not None else 9999),
            x["distancia_minutos"],
            x["hora_sugerida"],
        ))

        # Fallback: si no hay ventanas, buscar por BloqueTiempo (legacy)
        if not resultado:
            bloques = (
                BloqueTiempo.objects.filter(
                    tipoServicio=TipoServicio.PASEO,
                    diaSemana=dia_semana,
                    disponible=True,
                    horaInicio__lt=hora_fin,
                    horaFin__gt=hora_inicio,
                )
                .select_related("idCuidador__idCuidador")
                .order_by("horaInicio")
            )
            if solo_ciudad and not usar_radio and dueño.ciudad:
                bloques = bloques.filter(idCuidador__idCuidador__ciudad=dueño.ciudad)

            for bloque in bloques:
                perfil = bloque.idCuidador
                cuidador = perfil.idCuidador
                if not cuidador.verificado:
                    continue
                precio = PrecioServicio.objects.filter(
                    idCuidador=cuidador,
                    tipoServicio=TipoServicio.PASEO,
                    activo=True,
                ).first()
                if not precio:
                    continue

                tipos_pref = (perfil.tiposMascotaPreferidos or "ambos").lower().strip()
                if tipos_pref != "ambos" and mascota.tipo not in tipos_pref.split(","):
                    continue

                distancia_km = None
                if usar_radio and cuidador.latitud and cuidador.longitud:
                    distancia_km = _haversine_km(dueño_lat, dueño_lon, cuidador.latitud, cuidador.longitud)
                    if cuidador.radioKm and distancia_km > float(cuidador.radioKm):
                        continue
                    if not cuidador.radioKm and dueño.ciudad and cuidador.ciudad != dueño.ciudad:
                        continue
                elif usar_radio and (not cuidador.latitud or not cuidador.longitud):
                    if dueño.ciudad and cuidador.ciudad != dueño.ciudad:
                        continue

                hi_m = _time_to_minutes(bloque.horaInicio)
                hf_m = _time_to_minutes(bloque.horaFin)
                req_hi_m = _time_to_minutes(hora_inicio)
                req_hf_m = _time_to_minutes(hora_fin)

                inicio_sugerido_m = max(req_hi_m, hi_m)
                fin_sugerido_m = min(req_hf_m, hf_m)
                if fin_sugerido_m - inicio_sugerido_m < duracion_minutos:
                    continue

                hora_sugerida = _minutes_to_time(inicio_sugerido_m)
                distancia_m = abs(inicio_sugerido_m - req_hi_m)

                duracion_horas = duracion_minutos / 60.0
                prom, cnt = _calificacion_promedio_count(cuidador)
                resultado.append({
                    "bloque": bloque,
                    "cuidador": cuidador,
                    "perfil": perfil,
                    "tarifa_total": int(precio.precioCOP * duracion_horas),
                    "tarifa_hora": precio.precioCOP,
                    "duracion_minutos": duracion_minutos,
                    "duracion_horas": duracion_horas,
                    "hora_sugerida": hora_sugerida,
                    "distancia_minutos": distancia_m,
                    "distancia_km": round(distancia_km, 1) if distancia_km is not None else None,
                    "calificacion_promedio": prom,
                    "calificacion_count": cnt,
                    "tipo_servicio": TipoServicio.PASEO,
                    "descripcion_servicio": precio.descripcion or (perfil.descripcion or ""),
                })

            resultado.sort(key=lambda x: (
                (x["distancia_km"] if x["distancia_km"] is not None else 9999),
                x["distancia_minutos"],
                x["hora_sugerida"],
            ))

        return resultado

    def buscar_cuidado(
        self,
        dueño: Usuario,
        mascota_id: str,
        fecha_inicio_str: str,
        fecha_fin_str: str,
        solo_ciudad: bool = True,
    ) -> list:
        """Busca cuidadores con servicio de guardería disponibles en el rango de fechas."""
        if dueño.rol != "dueño":
            raise DomainValidationError("el usuario no tiene rol de dueño")
        if not mascota_id or not str(mascota_id).strip():
            raise DomainValidationError("debes seleccionar una mascota")
        try:
            fecha_inicio = datetime.strptime(fecha_inicio_str.strip(), "%Y-%m-%d").date()
            fecha_fin = datetime.strptime(fecha_fin_str.strip(), "%Y-%m-%d").date()
        except ValueError:
            raise DomainValidationError("formato de fecha inválido, use AAAA-MM-DD")
        if fecha_inicio < date.today():
            raise DomainValidationError("la fecha de inicio no puede ser en el pasado")
        if fecha_fin < fecha_inicio:
            raise DomainValidationError("la fecha fin debe ser igual o posterior a la de inicio")
        try:
            mascota = Mascota.objects.get(idMascota=mascota_id, idDueño=dueño)
        except Mascota.DoesNotExist:
            raise ResourceNotFoundError("la mascota no existe o no te pertenece")

        num_days = (fecha_fin - fecha_inicio).days + 1
        dias_set = set()
        d = fecha_inicio
        while d <= fecha_fin:
            dias_set.add(self._DIAS[d.weekday()])
            d += timedelta(days=1)

        perfiles = PerfilCuidador.objects.select_related("idCuidador")
        dueño_lat = dueño.latitud
        dueño_lon = dueño.longitud
        usar_radio = solo_ciudad and dueño_lat and dueño_lon

        if solo_ciudad and not usar_radio and dueño.ciudad:
            perfiles = perfiles.filter(idCuidador__ciudad=dueño.ciudad)

        resultado = []
        for perfil in perfiles:
            cuidador = perfil.idCuidador
            if not cuidador.verificado:
                continue
            precio = PrecioServicio.objects.filter(
                idCuidador=cuidador,
                tipoServicio=TipoServicio.GUARDERIA,
                activo=True,
            ).first()
            if not precio:
                continue

            # Filtro por tipo de mascota preferido
            tipos_pref = (perfil.tiposMascotaPreferidos or "ambos").lower().strip()
            if tipos_pref != "ambos" and mascota.tipo not in [t.strip() for t in tipos_pref.split(",")]:
                continue

            # Filtro por radio km cuando ambos tienen coordenadas
            distancia_km_val = None
            if usar_radio and cuidador.latitud and cuidador.longitud:
                distancia_km_val = _haversine_km(dueño_lat, dueño_lon, cuidador.latitud, cuidador.longitud)
                if cuidador.radioKm and distancia_km_val > float(cuidador.radioKm):
                    continue
                if not cuidador.radioKm and dueño.ciudad and cuidador.ciudad != dueño.ciudad:
                    continue
            elif usar_radio and (not cuidador.latitud or not cuidador.longitud):
                if dueño.ciudad and cuidador.ciudad != dueño.ciudad:
                    continue

            evento_obj = (
                Evento.objects.filter(
                    idCuidador=perfil,
                    tipoServicio=TipoServicio.GUARDERIA,
                    diaSemana__in=list(dias_set),
                    disponible=True,
                )
                .order_by("diaSemana", "horaInicio")
                .first()
            )
            bloque = (
                BloqueTiempo.objects.filter(
                    idCuidador=perfil,
                    tipoServicio=TipoServicio.GUARDERIA,
                    diaSemana__in=list(dias_set),
                    disponible=True,
                )
                .order_by("diaSemana", "horaInicio")
                .first()
            ) if evento_obj is None else None
            if evento_obj is None and bloque is None:
                continue
            ref = evento_obj or bloque
            tarifa_dia = ref.precioCOP if ref.precioCOP else precio.precioCOP
            tarifa_total = tarifa_dia * num_days
            prom, cnt = _calificacion_promedio_count(cuidador)
            resultado.append({
                "evento": evento_obj,
                "bloque": bloque,
                "cuidador": cuidador,
                "perfil": perfil,
                "tarifa_total": tarifa_total,
                "tarifa_dia": tarifa_dia,
                "num_dias": num_days,
                "fecha_inicio": fecha_inicio,
                "fecha_fin": fecha_fin,
                "distancia_km": round(distancia_km_val, 1) if distancia_km_val is not None else None,
                "calificacion_promedio": prom,
                "calificacion_count": cnt,
                "tipo_servicio": TipoServicio.GUARDERIA,
                "descripcion_servicio": precio.descripcion or (perfil.descripcion or ""),
            })

        resultado.sort(key=lambda x: (x["distancia_km"] if x["distancia_km"] is not None else 9999))
        return resultado


class CrearReservaDesdeSeleccionService:
    """Crea la solicitud cuando el dueño acepta un cuidador de la búsqueda."""

    def __init__(
        self,
        solicitud_service: SolicitudServicioService | None = None,
        solicitud_con_asignacion: CrearSolicitudConAsignacionService | None = None,
        solicitud_con_asignacion_evento: CrearSolicitudConAsignacionEventoService | None = None,
    ):
        self._solicitud_service = solicitud_service or SolicitudServicioService()
        self._solicitud_con_asignacion = solicitud_con_asignacion or CrearSolicitudConAsignacionService()
        self._solicitud_con_asignacion_evento = solicitud_con_asignacion_evento or CrearSolicitudConAsignacionEventoService()

    def crear(
        self,
        dueño: Usuario,
        mascota_id: str,
        bloque_id: str | None = None,
        ventana_id: str | None = None,
        evento_id: str | None = None,
        slot_id: str | None = None,
        fecha_str: str = "",
        tipo_servicio: str = "",
        fecha_fin_str: str | None = None,
    ) -> SolicitudServicio:
        if tipo_servicio not in {TipoServicio.PASEO, TipoServicio.GUARDERIA}:
            raise DomainValidationError("tipo de servicio inválido para la reserva")

        try:
            fecha = datetime.strptime(fecha_str, "%Y-%m-%d").date()
        except ValueError:
            raise DomainValidationError("formato de fecha inválido")
        if fecha < date.today():
            raise DomainValidationError("la fecha no puede ser en el pasado")

        fecha_fin = None
        if fecha_fin_str:
            try:
                fecha_fin = datetime.strptime(fecha_fin_str, "%Y-%m-%d").date()
            except ValueError:
                raise DomainValidationError("formato de fecha fin inválido")
            if fecha_fin < fecha:
                raise DomainValidationError("la fecha fin debe ser igual o posterior a la de inicio")
        if tipo_servicio == TipoServicio.GUARDERIA and fecha_fin is None:
            raise DomainValidationError("para guardería debes indicar fecha fin")
        if tipo_servicio == TipoServicio.PASEO:
            fecha_fin = None

        try:
            mascota = Mascota.objects.get(idMascota=mascota_id, idDueño=dueño)
        except Mascota.DoesNotExist:
            raise ResourceNotFoundError("la mascota no existe o no te pertenece")

        if tipo_servicio == TipoServicio.PASEO and evento_id:
            evento = Evento.objects.select_related("idCuidador__idCuidador").get(idEvento=evento_id)
            datos = {
                "idDueño": dueño,
                "idCuidador_id": str(evento.idCuidador.idCuidador.idUsuario),
                "idMascota_id": str(mascota.idMascota),
                "tipoServicio": tipo_servicio,
                "fecha": fecha,
                "idEvento_id": evento_id,
            }
            if evento.duracionSlotMinutos is not None:
                return self._solicitud_con_asignacion_evento.crear(datos)
            return self._solicitud_service.crear_solicitud_evento(datos)

        if tipo_servicio == TipoServicio.PASEO and ventana_id:
            datos = {
                "idDueño": dueño,
                "idCuidador_id": None,
                "idMascota_id": str(mascota.idMascota),
                "tipoServicio": tipo_servicio,
                "fecha": fecha,
                "idVentana_id": ventana_id,
            }
            ventana = VentanaDisponibilidad.objects.select_related("idCuidador__idCuidador").get(idVentana=ventana_id)
            datos["idCuidador_id"] = str(ventana.idCuidador.idCuidador.idUsuario)
            return self._solicitud_con_asignacion.crear(datos)

        if evento_id and tipo_servicio == TipoServicio.GUARDERIA:
            try:
                evento = Evento.objects.select_related("idCuidador__idCuidador").get(idEvento=evento_id)
            except Evento.DoesNotExist:
                raise ResourceNotFoundError("el evento no existe")
            if not evento.disponible:
                raise ConflictError("el evento ya no está disponible")
            if evento.tipoServicio != tipo_servicio:
                raise ConflictError("el evento no corresponde al tipo de servicio solicitado")

            cuidador = evento.idCuidador.idCuidador
            if not PrecioServicio.objects.filter(
                idCuidador=cuidador,
                tipoServicio=tipo_servicio,
                activo=True,
            ).exists():
                raise ConflictError("el cuidador no ofrece ese tipo de servicio actualmente")

            datos = {
                "idDueño": dueño,
                "idCuidador_id": str(cuidador.idUsuario),
                "idMascota_id": str(mascota.idMascota),
                "tipoServicio": tipo_servicio,
                "fecha": fecha,
                "idEvento_id": str(evento.idEvento),
            }
            if fecha_fin is not None:
                datos["fechaFin"] = fecha_fin
            return self._solicitud_service.crear_solicitud_evento(datos)

        if bloque_id:
            try:
                bloque = BloqueTiempo.objects.select_related("idCuidador__idCuidador").get(idBloque=bloque_id)
            except BloqueTiempo.DoesNotExist:
                raise ResourceNotFoundError("el bloque no existe")
            if not bloque.disponible:
                raise ConflictError("el bloque ya no está disponible")
            if bloque.tipoServicio != tipo_servicio:
                raise ConflictError("el bloque no corresponde al tipo de servicio solicitado")

            cuidador = bloque.idCuidador.idCuidador
            if not PrecioServicio.objects.filter(
                idCuidador=cuidador,
                tipoServicio=tipo_servicio,
                activo=True,
            ).exists():
                raise ConflictError("el cuidador no ofrece ese tipo de servicio actualmente")

            datos = {
                "idDueño": dueño,
                "idCuidador_id": str(cuidador.idUsuario),
                "idMascota_id": str(mascota.idMascota),
                "tipoServicio": tipo_servicio,
                "fecha": fecha,
                "idBloqueHorario_id": str(bloque.idBloque),
            }
            if fecha_fin is not None:
                datos["fechaFin"] = fecha_fin
            return self._solicitud_service.crear_solicitud(datos)

        if tipo_servicio == TipoServicio.PASEO:
            raise DomainValidationError("debes indicar evento_id, ventana_id o bloque_id")
        raise DomainValidationError("debes indicar evento_id o bloque_id para guardería")


class ListarSolicitudesDueñoService:
    # lista solicitudes de un dueño

    def listar(self, dueño: Usuario) -> dict:
        if dueño.rol != "dueño":
            raise DomainValidationError("el usuario no tiene rol de dueño")

        hoy = date.today()
        qs = SolicitudServicio.objects.filter(idDueño=dueño).select_related(
            "idCuidador", "idMascota", "idBloqueHorario", "idVentana", "idSlot", "idEvento", "idSlotEvento"
        ).prefetch_related("calificacion", "mensajes_chat__idDe").order_by("-fecha", "-created_at")
        futuras = qs.filter(
            fecha__gte=hoy,
            estado__in=[EstadoSolicitud.PENDIENTE, EstadoSolicitud.ACEPTADO],
        )
        pasadas = qs.filter(fecha__lt=hoy)
        return {
            "solicitudes_futuras": futuras,
            "solicitudes_pasadas": pasadas,
        }


def _calificacion_promedio_count(cuidador: Usuario) -> tuple[float | None, int]:
    """Retorna (promedio_estrellas, cantidad) para un cuidador."""
    from django.db.models import Avg, Count
    agg = Calificacion.objects.filter(idParaCuidador=cuidador).aggregate(
        prom=Avg("estrellas"), cnt=Count("idCalificación")
    )
    prom = float(agg["prom"]) if agg["prom"] is not None else None
    cnt = agg["cnt"] or 0
    return (round(prom, 1) if prom is not None else None, cnt)


class CrearCalificacionService:

    def crear(self, dueño: Usuario, solicitud_id: str, estrellas: int, comentario: str = "") -> Calificacion:
        if dueño.rol != "dueño":
            raise DomainValidationError("el usuario no tiene rol de dueño")
        try:
            solicitud = SolicitudServicio.objects.get(idSolicitud=solicitud_id, idDueño=dueño)
        except SolicitudServicio.DoesNotExist:
            raise ResourceNotFoundError("la solicitud no existe o no te pertenece")
        if solicitud.estado != EstadoSolicitud.COMPLETADO:
            raise DomainValidationError("solo puedes calificar servicios completados")
        if hasattr(solicitud, "calificacion") and solicitud.calificacion:
            raise ConflictError("ya calificaste este servicio")
        if estrellas < 1 or estrellas > 5:
            raise DomainValidationError("las estrellas deben ser entre 1 y 5")
        return Calificacion.objects.create(
            idDe=dueño,
            idParaCuidador=solicitud.idCuidador,
            idSolicitud=solicitud,
            estrellas=estrellas,
            comentario=(comentario or "").strip()[:500],
        )


class ListarMascotasDeDueñoService:
    # lista mascotas asociadas a un dueño

    def listar(self, dueño: Usuario):
        if dueño.rol != "dueño":
            raise DomainValidationError("el usuario no tiene rol de dueño")
        return Mascota.objects.filter(idDueño=dueño).order_by("nombreMascota")


class ListarAgendamientosCuidadorService:
    # lista solicitudes asociadas a un cuidador

    def listar(self, cuidador: Usuario):
        if cuidador.rol != "cuidador":
            raise DomainValidationError("el usuario no tiene rol de cuidador")

        try:
            perfil = PerfilCuidador.objects.get(idCuidador=cuidador)
        except PerfilCuidador.DoesNotExist:
            raise ResourceNotFoundError("el cuidador no tiene perfil configurado")

        hoy = date.today()
        qs = SolicitudServicio.objects.filter(
            Q(idBloqueHorario__idCuidador=perfil) | Q(idVentana__idCuidador=perfil) | Q(idEvento__idCuidador=perfil),
            estado__in=[
                EstadoSolicitud.PENDIENTE,
                EstadoSolicitud.ACEPTADO,
                EstadoSolicitud.COMPLETADO,
                EstadoSolicitud.CANCELADO,
                EstadoSolicitud.RECHAZADO,
            ],
        ).select_related("idDueño", "idMascota", "idBloqueHorario", "idVentana", "idSlot", "idEvento", "idSlotEvento").prefetch_related("mensajes_chat__idDe")
        qs = qs.order_by("fecha", "horaRecogidaAsignada", "idBloqueHorario__horaInicio")

        futuros = qs.filter(fecha__gte=hoy, estado__in=[EstadoSolicitud.PENDIENTE, EstadoSolicitud.ACEPTADO])
        pasados = qs.filter(fecha__lt=hoy)
        pendientes = futuros.filter(estado=EstadoSolicitud.PENDIENTE)
        futuros_aceptados = futuros.filter(estado=EstadoSolicitud.ACEPTADO)
        return {
            "agendamientos_futuros": futuros_aceptados,
            "agendamientos_pasados": pasados,
            "solicitudes_pendientes": pendientes,
        }


class ObtenerPerfilCuidadorService:
    # obtiene perfil de cuidador para UI

    def obtener(self, cuidador: Usuario) -> PerfilCuidador:
        if cuidador.rol != "cuidador":
            raise DomainValidationError("el usuario no tiene rol de cuidador")
        try:
            return PerfilCuidador.objects.get(idCuidador=cuidador)
        except PerfilCuidador.DoesNotExist:
            raise ResourceNotFoundError("el cuidador no tiene perfil configurado")


class ActualizarPerfilCuidadorService:

    def actualizar(self, cuidador: Usuario, datos: dict) -> PerfilCuidador:
        if cuidador.rol != "cuidador":
            raise DomainValidationError("el usuario no tiene rol de cuidador")

        perfil, _ = PerfilCuidador.objects.get_or_create(
            idCuidador=cuidador,
        )

        # Nuevo esquema: varios servicios activos por cuidador.
        servicios = datos.get("servicios")
        if servicios is None:
            legacy_tipo = datos.get("tipoServicio")
            servicios = [legacy_tipo] if legacy_tipo else []
        servicios = [s for s in servicios if s]
        validos = {TipoServicio.PASEO, TipoServicio.GUARDERIA, TipoServicio.ENTRENAMIENTO}
        if not servicios:
            raise DomainValidationError("debes seleccionar al menos un tipo de servicio")
        if any(s not in validos for s in servicios):
            raise DomainValidationError("tipo de servicio inválido")

        tarifas = datos.get("tarifas") or {}
        descripciones = datos.get("descripciones") or {}
        if "tarifaHora" in datos and not tarifas:
            # Compatibilidad con UI legacy de un solo tipo.
            tarifas = {
                servicio: datos.get("tarifaHora")
                for servicio in servicios
            }

        lugares_entrenamiento = datos.get("lugaresEntrenamiento") or {}
        for servicio in servicios:
            tarifa = tarifas.get(servicio)
            try:
                tarifa = int(tarifa)
            except (ValueError, TypeError):
                raise DomainValidationError(f"la tarifa para {servicio} debe ser un número entero")
            if tarifa <= 0:
                raise DomainValidationError(f"la tarifa para {servicio} debe ser mayor a 0")
            descripcion = descripciones.get(servicio) or ""
            defaults = {"precioCOP": tarifa, "descripcion": descripcion, "activo": True}
            if servicio == TipoServicio.ENTRENAMIENTO:
                lugar = (lugares_entrenamiento.get(servicio) or "").strip() or None
                if lugar and lugar not in ("cuidador", "dueño"):
                    raise DomainValidationError("lugar de entrenamiento debe ser 'cuidador' o 'dueño'")
                defaults["lugarEntrenamiento"] = lugar
            else:
                defaults["lugarEntrenamiento"] = None
            PrecioServicio.objects.update_or_create(
                idCuidador=cuidador,
                tipoServicio=servicio,
                defaults=defaults,
            )

        PrecioServicio.objects.filter(idCuidador=cuidador).exclude(
            tipoServicio__in=servicios
        ).update(activo=False)

        precios_activos = PrecioServicio.objects.filter(idCuidador=cuidador, activo=True)
        perfil.tarifaHora = precios_activos.first().precioCOP if precios_activos.exists() else 0

        tipos_mascota = datos.get("tiposMascotaPreferidos", "").strip().lower()
        if tipos_mascota in ("perro", "gato", "ambos") or "," in tipos_mascota:
            perfil.tiposMascotaPreferidos = tipos_mascota if tipos_mascota else "ambos"
        elif tipos_mascota:
            validos = ["perro", "gato"]
            parts = [p.strip() for p in tipos_mascota.split(",") if p.strip() in validos]
            perfil.tiposMascotaPreferidos = ",".join(sorted(set(parts))) if parts else "ambos"

        perfil.save()
        return perfil


class EditarPerfilUsuarioService:

    _CAMPOS_NO_EDITABLES = {"cedula", "username", "rol"}

    def editar(self, usuario: Usuario, datos: dict) -> Usuario:
        nombre = datos.get("nombre")
        if nombre:
            if len(nombre) > 50:
                raise DomainValidationError("el nombre no puede superar 50 caracteres")
            usuario.nombre = nombre

        apellido = datos.get("apellido")
        if apellido:
            if len(apellido) > 50:
                raise DomainValidationError("el apellido no puede superar 50 caracteres")
            usuario.apellido = apellido

        correo = datos.get("correo")
        if correo:
            import re
            if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", correo):
                raise DomainValidationError("el correo no tiene un formato válido")
            usuario.correo = correo

        telefono = datos.get("telefono")
        if telefono:
            if len(telefono) > 20:
                raise DomainValidationError("el teléfono no puede superar 20 caracteres")
            usuario.telefono = telefono

        ciudad = datos.get("ciudad")
        if ciudad:
            if len(ciudad) > 100:
                raise DomainValidationError("la ciudad no puede superar 100 caracteres")
            usuario.ciudad = ciudad

        lat = datos.get("latitud")
        if lat is not None and str(lat).strip() != "":
            try:
                usuario.latitud = Decimal(str(lat).strip())
            except Exception:
                usuario.latitud = None
        lon = datos.get("longitud")
        if lon is not None and str(lon).strip() != "":
            try:
                usuario.longitud = Decimal(str(lon).strip())
            except Exception:
                usuario.longitud = None
        if datos.get("latitud") is not None and str(datos.get("latitud", "")).strip() == "":
            usuario.latitud = None
        if datos.get("longitud") is not None and str(datos.get("longitud", "")).strip() == "":
            usuario.longitud = None

        radio = datos.get("radioKm")
        if radio is not None and str(radio).strip() != "" and usuario.rol == "cuidador":
            try:
                r = Decimal(str(radio).strip())
                if r < 1 or r > 100:
                    raise DomainValidationError("el radio debe estar entre 1 y 100 km")
                usuario.radioKm = r
            except DomainValidationError:
                raise
            except Exception:
                usuario.radioKm = None
        elif datos.get("radioKm") is not None and str(datos.get("radioKm", "")).strip() == "" and usuario.rol == "cuidador":
            usuario.radioKm = None

        foto = datos.get("fotoPerfil")
        if foto is not None:
            if usuario.fotoPerfil:
                usuario.fotoPerfil.delete(save=False)
            usuario.fotoPerfil = foto if foto else None

        usuario.save()
        return usuario


class AgregarMascotaService:

    def agregar(self, dueño: Usuario, datos: dict) -> Mascota:
        if dueño.rol != "dueño":
            raise DomainValidationError("el usuario no tiene rol de dueño")

        nombre_mascota = datos.get("nombreMascota", "").strip()
        tipo = datos.get("tipo", "").strip()
        raza = datos.get("raza", "").strip()
        notas = datos.get("notas", "").strip()

        if not nombre_mascota:
            raise DomainValidationError("el nombre de la mascota es requerido")
        if not tipo:
            raise DomainValidationError("el tipo de mascota es requerido")

        opciones_tipo = [c[0] for c in TipoMascota.choices]
        if tipo not in opciones_tipo:
            raise DomainValidationError(f"tipo de mascota inválido: {tipo}")

        try:
            edad = int(datos.get("edad", 0))
        except (ValueError, TypeError):
            raise DomainValidationError("la edad debe ser un número entero")
        if edad < 0:
            raise DomainValidationError("la edad no puede ser negativa")

        peso = datos.get("peso")
        peso_val = None
        if peso:
            try:
                peso_val = float(peso)
            except (ValueError, TypeError):
                raise DomainValidationError("el peso debe ser un número")
            if peso_val < 0:
                raise DomainValidationError("el peso no puede ser negativo")

        foto = datos.get("foto")
        mascota = Mascota.objects.create(
            idDueño=dueño,
            nombreMascota=nombre_mascota,
            tipo=tipo,
            raza=raza,
            edad=edad,
            peso=peso_val,
            notas=notas,
            foto=foto if foto else None,
        )
        return mascota


class EliminarMascotaService:

    def eliminar(self, dueño: Usuario, mascota_id: str):
        if dueño.rol != "dueño":
            raise DomainValidationError("el usuario no tiene rol de dueño")
        try:
            mascota = Mascota.objects.get(idMascota=mascota_id, idDueño=dueño)
        except Mascota.DoesNotExist:
            raise ResourceNotFoundError("mascota no encontrada")
        mascota.delete()


class ActualizarFotoMascotaService:

    def actualizar(self, dueño: Usuario, mascota_id: str, foto) -> Mascota:
        if dueño.rol != "dueño":
            raise DomainValidationError("el usuario no tiene rol de dueño")
        if not foto:
            raise DomainValidationError("debes seleccionar una imagen")
        try:
            mascota = Mascota.objects.get(idMascota=mascota_id, idDueño=dueño)
        except Mascota.DoesNotExist:
            raise ResourceNotFoundError("mascota no encontrada")
        if mascota.foto:
            mascota.foto.delete(save=False)
        mascota.foto = foto
        mascota.save(update_fields=["foto"])
        return mascota


class AgregarBloqueTiempoService:

    def agregar(self, cuidador: Usuario, datos: dict) -> BloqueTiempo:
        if cuidador.rol != "cuidador":
            raise DomainValidationError("el usuario no tiene rol de cuidador")

        perfil, _ = PerfilCuidador.objects.get_or_create(
            idCuidador=cuidador,
        )

        dia = datos.get("diaSemana", "").strip()
        hora_inicio_str = datos.get("horaInicio", "").strip()
        hora_fin_str = datos.get("horaFin", "").strip()

        if not dia or not hora_inicio_str or not hora_fin_str:
            raise DomainValidationError("día, hora inicio y hora fin son requeridos")

        opciones_dia = [c[0] for c in DiaSemana.choices]
        if dia not in opciones_dia:
            raise DomainValidationError(f"día inválido: {dia}")

        from datetime import time as time_cls
        try:
            partes_i = hora_inicio_str.split(":")
            hora_inicio = time_cls(int(partes_i[0]), int(partes_i[1]))
            partes_f = hora_fin_str.split(":")
            hora_fin = time_cls(int(partes_f[0]), int(partes_f[1]))
        except (ValueError, IndexError):
            raise DomainValidationError("formato de hora inválido (HH:MM)")

        if hora_fin <= hora_inicio:
            raise DomainValidationError("la hora fin debe ser posterior a la hora inicio")

        tipo = datos.get("tipoServicio", "").strip()
        validos = {TipoServicio.PASEO, TipoServicio.GUARDERIA}
        if tipo not in validos:
            raise DomainValidationError("tipo de servicio inválido para el bloque")
        if not PrecioServicio.objects.filter(
            idCuidador=cuidador, tipoServicio=tipo, activo=True
        ).exists():
            raise DomainValidationError("debes tener el servicio activo antes de agregar horarios")

        nombre_lugar = (datos.get("nombreLugar") or "").strip()
        lat = datos.get("latitud")
        lng = datos.get("longitud")
        precio = datos.get("precioCOP")
        lat_dec = lng_dec = None
        if lat is not None and str(lat).strip():
            try:
                lat_dec = Decimal(str(lat))
            except Exception:
                pass
        if lng is not None and str(lng).strip():
            try:
                lng_dec = Decimal(str(lng))
            except Exception:
                pass
        precio_int = None
        if precio is not None and str(precio).strip():
            try:
                precio_int = int(precio)
                if precio_int < 1:
                    precio_int = None
            except (ValueError, TypeError):
                pass

        existe = BloqueTiempo.objects.filter(
            idCuidador=perfil, tipoServicio=tipo, diaSemana=dia,
            horaInicio=hora_inicio, horaFin=hora_fin, nombreLugar=nombre_lugar or "",
        ).exists()
        if existe:
            raise ConflictError("ya existe un bloque con ese horario y lugar")

        bloque = BloqueTiempo.objects.create(
            idCuidador=perfil,
            tipoServicio=tipo,
            diaSemana=dia,
            horaInicio=hora_inicio,
            horaFin=hora_fin,
            nombreLugar=nombre_lugar or "",
            latitud=lat_dec,
            longitud=lng_dec,
            precioCOP=precio_int,
        )
        return bloque


PRESET_DIAS = {
    "todos": [c[0] for c in DiaSemana.choices],
    "fines_semana": ["sabado", "domingo"],
    "entre_semana": ["lunes", "martes", "miercoles", "jueves", "viernes"],
}


class AgregarEventosRapidoService:
    """Agrega múltiples eventos a la vez según un preset (todos, fines_semana, entre_semana)."""

    def agregar(self, cuidador: Usuario, datos: dict) -> int:
        preset = datos.get("preset", "").strip()
        if preset not in PRESET_DIAS:
            raise DomainValidationError("preset inválido")
        dias = PRESET_DIAS[preset]
        tipo = datos.get("tipoServicio", "").strip()
        hora_inicio_str = datos.get("horaInicio", "").strip()
        hora_fin_str = datos.get("horaFin", "").strip()
        if not tipo or not hora_inicio_str or not hora_fin_str:
            raise DomainValidationError("tipo, hora inicio y hora fin son requeridos")
        validos = {TipoServicio.PASEO, TipoServicio.GUARDERIA}
        if tipo not in validos:
            raise DomainValidationError("tipo de servicio inválido")
        if not PrecioServicio.objects.filter(
            idCuidador=cuidador, tipoServicio=tipo, activo=True
        ).exists():
            raise DomainValidationError("debes tener el servicio activo antes de agregar horarios")
        perfil, _ = PerfilCuidador.objects.get_or_create(idCuidador=cuidador)
        try:
            pi = hora_inicio_str.split(":")
            hora_inicio = time(int(pi[0]), int(pi[1]))
            pf = hora_fin_str.split(":")
            hora_fin = time(int(pf[0]), int(pf[1]))
        except (ValueError, IndexError):
            raise DomainValidationError("formato de hora inválido (HH:MM)")
        if hora_fin <= hora_inicio:
            raise DomainValidationError("la hora fin debe ser posterior a la hora inicio")
        nombre_lugar = (datos.get("nombreLugar") or "").strip()
        lat = datos.get("latitud")
        lng = datos.get("longitud")
        precio = datos.get("precioCOP")
        lat_dec = lng_dec = None
        if lat is not None and str(lat).strip():
            try:
                lat_dec = Decimal(str(lat))
            except Exception:
                pass
        if lng is not None and str(lng).strip():
            try:
                lng_dec = Decimal(str(lng))
            except Exception:
                pass
        precio_int = None
        if precio is not None and str(precio).strip():
            try:
                precio_int = int(precio)
                if precio_int < 1:
                    precio_int = None
            except (ValueError, TypeError):
                pass
        creados = 0
        for dia in dias:
            if Evento.objects.filter(
                idCuidador=perfil, tipoServicio=tipo, diaSemana=dia,
                horaInicio=hora_inicio, horaFin=hora_fin, nombreLugar=nombre_lugar or "",
            ).exists():
                continue
            Evento.objects.create(
                idCuidador=perfil,
                tipoServicio=tipo,
                diaSemana=dia,
                horaInicio=hora_inicio,
                horaFin=hora_fin,
                nombreLugar=nombre_lugar or "",
                latitud=lat_dec,
                longitud=lng_dec,
                precioCOP=precio_int,
                capacidadMaxima=1,
                duracionSlotMinutos=None,
                disponible=True,
            )
            creados += 1
        return creados


class AgregarBloquesRapidoService:
    """Agrega múltiples bloques a la vez según un preset (legacy)."""

    def agregar(self, cuidador: Usuario, datos: dict) -> int:
        preset = datos.get("preset", "").strip()
        if preset not in PRESET_DIAS:
            raise DomainValidationError("preset inválido")
        dias = PRESET_DIAS[preset]
        tipo = datos.get("tipoServicio", "").strip()
        hora_inicio_str = datos.get("horaInicio", "").strip()
        hora_fin_str = datos.get("horaFin", "").strip()
        if not tipo or not hora_inicio_str or not hora_fin_str:
            raise DomainValidationError("tipo, hora inicio y hora fin son requeridos")
        validos = {TipoServicio.PASEO, TipoServicio.GUARDERIA}
        if tipo not in validos:
            raise DomainValidationError("tipo de servicio inválido")
        if not PrecioServicio.objects.filter(
            idCuidador=cuidador, tipoServicio=tipo, activo=True
        ).exists():
            raise DomainValidationError("debes tener el servicio activo antes de agregar horarios")
        perfil, _ = PerfilCuidador.objects.get_or_create(idCuidador=cuidador)
        from datetime import time as time_cls
        try:
            pi = hora_inicio_str.split(":")
            hora_inicio = time_cls(int(pi[0]), int(pi[1]))
            pf = hora_fin_str.split(":")
            hora_fin = time_cls(int(pf[0]), int(pf[1]))
        except (ValueError, IndexError):
            raise DomainValidationError("formato de hora inválido (HH:MM)")
        if hora_fin <= hora_inicio:
            raise DomainValidationError("la hora fin debe ser posterior a la hora inicio")
        nombre_lugar = (datos.get("nombreLugar") or "").strip()
        lat = datos.get("latitud")
        lng = datos.get("longitud")
        precio = datos.get("precioCOP")
        lat_dec = lng_dec = None
        if lat is not None and str(lat).strip():
            try:
                lat_dec = Decimal(str(lat))
            except Exception:
                pass
        if lng is not None and str(lng).strip():
            try:
                lng_dec = Decimal(str(lng))
            except Exception:
                pass
        precio_int = None
        if precio is not None and str(precio).strip():
            try:
                precio_int = int(precio)
                if precio_int < 1:
                    precio_int = None
            except (ValueError, TypeError):
                pass
        creados = 0
        for dia in dias:
            if BloqueTiempo.objects.filter(
                idCuidador=perfil, tipoServicio=tipo, diaSemana=dia,
                horaInicio=hora_inicio, horaFin=hora_fin, nombreLugar=nombre_lugar or "",
            ).exists():
                continue
            BloqueTiempo.objects.create(
                idCuidador=perfil,
                tipoServicio=tipo,
                diaSemana=dia,
                horaInicio=hora_inicio,
                horaFin=hora_fin,
                nombreLugar=nombre_lugar or "",
                latitud=lat_dec,
                longitud=lng_dec,
                precioCOP=precio_int,
            )
            creados += 1
        return creados


class EliminarBloqueTiempoService:

    def eliminar(self, cuidador: Usuario, bloque_id: str):
        if cuidador.rol != "cuidador":
            raise DomainValidationError("el usuario no tiene rol de cuidador")
        try:
            perfil = PerfilCuidador.objects.get(idCuidador=cuidador)
        except PerfilCuidador.DoesNotExist:
            raise ResourceNotFoundError("perfil de cuidador no encontrado")
        try:
            bloque = BloqueTiempo.objects.get(idBloque=bloque_id, idCuidador=perfil)
        except BloqueTiempo.DoesNotExist:
            raise ResourceNotFoundError("bloque no encontrado")
        if bloque.solicitudes.filter(estado__in=["pendiente", "aceptado"]).exists():
            raise ConflictError("no puedes eliminar un horario con reservas pendientes o aceptadas")
        bloque.delete()


class ListarBloquesCuidadorService:

    def listar(self, cuidador: Usuario, tipo_servicio: str | None = None):
        if cuidador.rol != "cuidador":
            raise DomainValidationError("el usuario no tiene rol de cuidador")
        try:
            perfil = PerfilCuidador.objects.get(idCuidador=cuidador)
        except PerfilCuidador.DoesNotExist:
            return []
        qs = BloqueTiempo.objects.filter(idCuidador=perfil)
        if tipo_servicio:
            qs = qs.filter(tipoServicio=tipo_servicio)
        return qs.order_by("tipoServicio", "diaSemana", "horaInicio")


class ListarVentanasCuidadorService:

    def listar(self, cuidador: Usuario, tipo_servicio: str | None = None):
        if cuidador.rol != "cuidador":
            raise DomainValidationError("el usuario no tiene rol de cuidador")
        try:
            perfil = PerfilCuidador.objects.get(idCuidador=cuidador)
        except PerfilCuidador.DoesNotExist:
            return []
        qs = VentanaDisponibilidad.objects.filter(idCuidador=perfil).prefetch_related("slots")
        if tipo_servicio:
            qs = qs.filter(tipoServicio=tipo_servicio)
        return qs.order_by("tipoServicio", "diaSemana", "horaInicio")


class EliminarVentanaDisponibilidadService:

    def eliminar(self, cuidador: Usuario, ventana_id: str):
        if cuidador.rol != "cuidador":
            raise DomainValidationError("el usuario no tiene rol de cuidador")
        try:
            perfil = PerfilCuidador.objects.get(idCuidador=cuidador)
        except PerfilCuidador.DoesNotExist:
            raise ResourceNotFoundError("perfil de cuidador no encontrado")
        try:
            ventana = VentanaDisponibilidad.objects.get(idVentana=ventana_id, idCuidador=perfil)
        except VentanaDisponibilidad.DoesNotExist:
            raise ResourceNotFoundError("ventana no encontrada")
        if ventana.solicitudes.filter(estado__in=["pendiente", "aceptado"]).exists():
            raise ConflictError("no puedes eliminar una ventana con reservas pendientes o aceptadas")
        ventana.delete()
