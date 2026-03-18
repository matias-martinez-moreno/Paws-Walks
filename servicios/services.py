# capa de aplicacion: logica de negocio
from __future__ import annotations

import json
import logging
import math
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models import Avg, Case, Count, IntegerField, Q, When
from django.db import transaction
from django.utils import timezone

from servicios.domain.builder import SolicitudServicioBuilder
from servicios.domain.exceptions import (
    ConflictError,
    DomainError,
    DomainValidationError,
    ResourceNotFoundError,
)
from servicios.infra.factory import NotificadorFactory
from servicios.models import (
    BloqueTiempo,
    Calificacion,
    CalificacionMascota,
    CategoriaNotificacion,
    DiaSemana,
    EstadoSolicitud,
    Evento,
    Mascota,
    MensajeChat,
    Notificacion,
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


PASEO_DURACIONES_MINUTOS = (60, 90, 120, 150, 180)
ESTADOS_OCUPAN_CUPO = (
    EstadoSolicitud.PENDIENTE,
    EstadoSolicitud.ACEPTADO,
    EstadoSolicitud.COMPLETADO,
)


def _validar_tipo_servicio_solicitud(tipo_servicio: str) -> str:
    tipo = str(tipo_servicio or "").strip()
    if tipo not in (TipoServicio.PASEO, TipoServicio.GUARDERIA):
        raise DomainValidationError("tipo de servicio inválido")
    return tipo


def _resolver_cuidador_verificado(cuidador_id) -> Usuario:
    try:
        cuidador = Usuario.objects.get(idUsuario=cuidador_id)
    except Usuario.DoesNotExist:
        raise ResourceNotFoundError("el cuidador no existe")
    if cuidador.rol != "cuidador":
        raise DomainValidationError("el usuario no es cuidador")
    if not cuidador.verificado:
        raise DomainValidationError("el cuidador no está verificado")
    return cuidador


def _resolver_mascota_de_dueño(dueño: Usuario, mascota_id) -> Mascota:
    if not isinstance(dueño, Usuario):
        raise DomainValidationError("el dueño debe ser un usuario válido")
    try:
        return Mascota.objects.get(idMascota=mascota_id, idDueño=dueño)
    except Mascota.DoesNotExist:
        raise ResourceNotFoundError("la mascota no existe o no te pertenece")


def _validar_fechas_solicitud(fecha: date, fecha_fin: date | None = None) -> None:
    if fecha < date.today():
        raise DomainValidationError("la fecha del servicio no puede ser en el pasado")
    if fecha_fin is None:
        return
    if fecha_fin < date.today():
        raise DomainValidationError("la fecha fin no puede ser en el pasado")
    if fecha_fin < fecha:
        raise DomainValidationError("la fecha fin debe ser igual o posterior a la fecha de inicio")


def _normalizar_duracion_guarderia_minutos(duracion_minutos) -> int | None:
    if duracion_minutos is None or str(duracion_minutos).strip() == "":
        return None
    try:
        minutos = int(duracion_minutos)
    except (TypeError, ValueError):
        raise DomainValidationError("la duración de guardería debe ser un número entero")
    if minutos < 60:
        raise DomainValidationError("la duración mínima de guardería es 1 hora")
    if minutos % 30 != 0:
        raise DomainValidationError("la duración de guardería debe ser en múltiplos de 30 minutos")
    return minutos


def _resolver_precio_activo(cuidador: Usuario, tipo_servicio: str) -> PrecioServicio:
    precio = PrecioServicio.objects.filter(
        idCuidador=cuidador,
        tipoServicio=tipo_servicio,
        activo=True,
    ).first()
    if not precio:
        raise DomainValidationError("el cuidador no ofrece ese tipo de servicio")
    return precio


def _calcular_monto_pago_solicitud(
    *,
    tipo_servicio: str,
    precio_base_hora: int,
    fecha: date,
    fecha_fin: date | None = None,
    evento: Evento | None = None,
    ventana: VentanaDisponibilidad | None = None,
    bloque: BloqueTiempo | None = None,
    duracion_guarderia_minutos: int | None = None,
) -> int | None:
    if tipo_servicio == TipoServicio.GUARDERIA:
        if evento is not None:
            duracion_min = duracion_guarderia_minutos
            if duracion_min is None:
                duracion_min = (_time_to_minutes(evento.horaFin) - _time_to_minutes(evento.horaInicio))
            tarifa_hora = int(evento.precioCOP) if evento.precioCOP else int(precio_base_hora)
            monto = int(tarifa_hora * (duracion_min / 60.0))
            return monto if monto > 0 else None

        if fecha_fin is None:
            return None
        num_days = (fecha_fin - fecha).days + 1
        monto = int(int(precio_base_hora) * num_days)
        return monto if monto > 0 else None

    if evento is not None:
        if evento.precioCOP:
            return int(evento.precioCOP)
        duracion_min = evento.duracionSlotMinutos
        if duracion_min is None:
            duracion_min = _time_to_minutes(evento.horaFin) - _time_to_minutes(evento.horaInicio)
    elif ventana is not None:
        duracion_min = int(ventana.duracionSlotMinutos)
    elif bloque is not None:
        duracion_min = _time_to_minutes(bloque.horaFin) - _time_to_minutes(bloque.horaInicio)
    else:
        return None

    monto = int(int(precio_base_hora) * (duracion_min / 60.0))
    return monto if monto > 0 else None


class FormatearTelefonoService:
    """Normaliza y separa teléfonos para formularios de perfil."""

    PREFIJOS_TELEFONO = ("+57", "+1", "+34", "+52", "+54", "+56", "+58")

    @classmethod
    def separar_prefijo_numero(cls, telefono) -> tuple[str, str]:
        raw = str(telefono or "").strip()
        if not raw:
            return "+57", ""
        if raw.startswith("+"):
            solo_digitos = "".join(ch for ch in raw[1:] if ch.isdigit())
            for prefijo in sorted(cls.PREFIJOS_TELEFONO, key=len, reverse=True):
                sin_mas = prefijo.lstrip("+")
                if solo_digitos.startswith(sin_mas):
                    return prefijo, solo_digitos[len(sin_mas):]
            for size in range(4, 0, -1):
                candidato = solo_digitos[:size]
                if candidato:
                    return f"+{candidato}", solo_digitos[size:]
        return "+57", raw.lstrip("+")

    @classmethod
    def componer(cls, prefijo, numero) -> str:
        p = str(prefijo or "+57").strip()
        n = "".join(ch for ch in str(numero or "") if ch.isdigit())
        if not p.startswith("+"):
            p = f"+{p}"
        if p == "+":
            p = "+57"
        return f"{p}{n}" if n else ""


class ConstruirDatosRegistroUsuarioFormularioService:
    """Normaliza campos y payload del formulario de registro."""

    def __init__(self, telefono_service: FormatearTelefonoService | None = None):
        self._telefono_service = telefono_service or FormatearTelefonoService()

    def construir(self, source) -> tuple[dict, dict]:
        prefijo = source.get("prefijo", "+57")
        telefono_local = source.get("telefono", "")
        telefono = self._telefono_service.componer(prefijo, telefono_local)

        campos = {
            "nombre": source.get("nombre"),
            "apellido": source.get("apellido"),
            "username": source.get("username"),
            "correo": source.get("correo"),
            "cedula": source.get("cedula"),
            "telefono": telefono_local,
            "prefijo": prefijo,
            "fechaNacimiento_str": source.get("fechaNacimiento"),
            "ciudad": source.get("ciudad"),
            "rol": source.get("rol"),
        }

        payload = {
            "nombre": campos["nombre"],
            "apellido": campos["apellido"],
            "username": campos["username"],
            "correo": campos["correo"],
            "cedula": campos["cedula"],
            "telefono": telefono,
            "fechaNacimiento_str": campos["fechaNacimiento_str"],
            "ciudad": campos["ciudad"],
            "password1": source.get("password1"),
            "password2": source.get("password2"),
            "rol": campos["rol"],
        }
        return campos, payload


class BuscarUsuarioPorIdentificadorService:
    """Busca un usuario por correo o username para flujos de recuperación."""

    def buscar(self, identificador: str | None) -> Usuario | None:
        ident = str(identificador or "").strip()
        if not ident:
            return None
        return (
            Usuario.objects.filter(correo=ident).first()
            or Usuario.objects.filter(username=ident).first()
        )


class ResolverRutaPostLoginService:
    """Resuelve la ruta de dashboard posterior al login según rol."""

    _RUTAS_DASHBOARD = {
        "dueño": "dashboard_dueño",
        "cuidador": "dashboard_cuidador",
    }

    def resolver(self, usuario: Usuario) -> str:
        ruta = self._RUTAS_DASHBOARD.get(usuario.rol)
        if not ruta:
            raise DomainValidationError("el rol del usuario no tiene dashboard configurado")
        return ruta


class ResolverRutaNotificacionesService:
    """Resuelve la ruta de notificaciones según rol."""

    _RUTAS_NOTIFICACIONES = {
        "dueño": "dueño_notificaciones",
        "cuidador": "cuidador_notificaciones",
    }

    def resolver(self, usuario: Usuario) -> str:
        ruta = self._RUTAS_NOTIFICACIONES.get(usuario.rol)
        if not ruta:
            raise DomainValidationError("el rol del usuario no tiene notificaciones configuradas")
        return ruta


class ConstruirContextoRecuperacionPasswordService:
    """Centraliza validación y mensajes del formulario de recuperación."""

    def __init__(self, buscador: BuscarUsuarioPorIdentificadorService | None = None):
        self._buscador = buscador or BuscarUsuarioPorIdentificadorService()

    def construir(self, identificador: str | None) -> dict:
        identificador_norm = str(identificador or "").strip()
        ctx = {"identificador": identificador_norm}
        if not identificador_norm:
            ctx["error"] = "Escribe tu correo o usuario para continuar."
            return ctx

        usuario = self._buscador.buscar(identificador_norm)
        if usuario:
            ctx["success"] = "Usuario encontrado. Enviaremos instrucciones a tu correo para recuperar tu contraseña."
        else:
            ctx["error"] = "No encontramos ninguna cuenta con ese correo o usuario."
        return ctx


class ContarSlotsDisponiblesService:
    """Cuenta slots disponibles por entidad sin usar lógica en modelos."""

    @staticmethod
    def para_evento(evento: Evento) -> int:
        if not evento.duracionSlotMinutos:
            return 0
        return evento.slots.filter(disponible=True).count()

    @staticmethod
    def para_ventana(ventana: VentanaDisponibilidad) -> int:
        return ventana.slots.filter(disponible=True).count()


class ConstruirDatosPerfilUsuarioFormularioService:
    """Normaliza payload de formularios de perfil para dueño y cuidador."""

    def __init__(self, telefono_service: FormatearTelefonoService | None = None):
        self._telefono_service = telefono_service or FormatearTelefonoService()

    def construir_dueño(self, source, files) -> tuple[dict, str]:
        telefono = self._telefono_service.componer(
            source.get("prefijo", "+57"),
            source.get("telefono"),
        )
        datos = {
            "nombre": source.get("nombre"),
            "apellido": source.get("apellido"),
            "cedula": source.get("cedula"),
            "correo": source.get("correo"),
            "telefono": telefono,
            "ciudad": source.get("ciudad"),
            "direccion": source.get("direccion"),
            "latitud": source.get("latitud"),
            "longitud": source.get("longitud"),
            "fotoPerfil": files.get("fotoPerfil") if files is not None else None,
        }
        return datos, telefono

    def construir_cuidador(self, source, files) -> tuple[dict, str, str]:
        telefono = self._telefono_service.componer(
            source.get("prefijo", "+57"),
            source.get("telefono"),
        )
        experiencia = (source.get("experiencia") or "").strip()
        datos = {
            "nombre": source.get("nombre"),
            "apellido": source.get("apellido"),
            "cedula": source.get("cedula"),
            "correo": source.get("correo"),
            "telefono": telefono,
            "ciudad": source.get("ciudad"),
            "direccion": source.get("direccion"),
            "latitud": source.get("latitud"),
            "longitud": source.get("longitud"),
            "radioKm": source.get("radioKm"),
            "fotoPerfil": files.get("fotoPerfil") if files is not None else None,
            "experiencia": experiencia,
        }
        return datos, telefono, experiencia


class ResolverAccionPerfilCuidadorService:
    """Resuelve la acción permitida en POST de perfil de cuidador."""

    @staticmethod
    def resolver(source) -> dict:
        action = str(source.get("action") or "").strip()
        if action != "datos_personales":
            return {
                "modo": "redirect",
                "ruta": "cuidador_mi_perfil",
            }
        return {
            "modo": "continuar",
        }


class FiltrarHistorialSolicitudesService:
    """Orquesta filtros de historial y resolución de reseñas pendientes."""

    def normalizar_filtro(self, valor, validos: set[str], predeterminado: str) -> str:
        normalizado = str(valor or predeterminado).strip().lower()
        return normalizado if normalizado in validos else predeterminado

    def filtrar(self, items, estado: str, servicio: str):
        filtrados = list(items or [])
        if estado != "todas":
            filtrados = [item for item in filtrados if item.estado == estado]
        if servicio != "todos":
            filtrados = [item for item in filtrados if item.tipoServicio == servicio]
        return filtrados

    def resolver_resena_pendiente(
        self,
        solicitud_id,
        objetivo,
        items,
        objetivos_validos: set[str],
    ) -> tuple[str, str]:
        solicitud_id_norm = str(solicitud_id or "").strip()
        objetivo_norm = str(objetivo or "").strip().lower()
        if not solicitud_id_norm or objetivo_norm not in objetivos_validos:
            return "", ""

        for item in items or []:
            if str(item.idSolicitud) != solicitud_id_norm:
                continue
            if item.estado != EstadoSolicitud.COMPLETADO:
                return "", ""
            if objetivo_norm == "cuidador" and not getattr(item, "calificacion_mia", None):
                return solicitud_id_norm, objetivo_norm
            if objetivo_norm == "dueno" and not getattr(item, "calificacion_dueño_mia", None):
                return solicitud_id_norm, objetivo_norm
            if objetivo_norm == "mascota" and not getattr(item, "calificacion_mascota_mia", None):
                return solicitud_id_norm, objetivo_norm
            return "", ""

        return "", ""


class ConstruirContextoHistorialSolicitudesService:
    """Construye filtros y contexto de reseñas pendientes para historiales."""

    def __init__(self, historial: FiltrarHistorialSolicitudesService | None = None):
        self._historial = historial or FiltrarHistorialSolicitudesService()

    def construir(
        self,
        items_pasados,
        source,
        objetivos_validos: set[str],
        estado_opciones: list[tuple[str, str]],
        servicio_opciones: list[tuple[str, str]],
    ) -> dict:
        items = list(items_pasados or [])
        estados_validos = {valor for valor, _ in estado_opciones}
        servicios_validos = {valor for valor, _ in servicio_opciones}

        historial_estado = self._historial.normalizar_filtro(
            source.get("hist_estado"),
            estados_validos,
            "todas",
        )
        historial_servicio = self._historial.normalizar_filtro(
            source.get("hist_servicio"),
            servicios_validos,
            "todos",
        )
        items_filtrados = self._historial.filtrar(
            items,
            historial_estado,
            historial_servicio,
        )
        resena_pendiente_solicitud_id, resena_pendiente_objetivo = self._historial.resolver_resena_pendiente(
            source.get("resena_solicitud"),
            source.get("resena_objetivo"),
            items,
            objetivos_validos,
        )

        return {
            "items_filtrados": items_filtrados,
            "historial_estado_actual": historial_estado,
            "historial_servicio_actual": historial_servicio,
            "historial_filtrado_total": len(items_filtrados),
            "resena_pendiente_solicitud_id": resena_pendiente_solicitud_id,
            "resena_pendiente_objetivo": resena_pendiente_objetivo,
        }


class SolicitudServicioService:
    # orquesta builder y factory

    def __init__(self, notificador=None):
        # inyeccion de dependencias
        self.notificador = notificador or NotificadorFactory.crear()

    def crear_solicitud(self, datos):
        dueño = datos["idDueño"]
        tipo_servicio = _validar_tipo_servicio_solicitud(datos.get("tipoServicio"))
        fecha = datos["fecha"]
        fecha_fin = datos.get("fechaFin")
        _validar_fechas_solicitud(fecha, fecha_fin)

        cuidador = _resolver_cuidador_verificado(datos.get("idCuidador_id"))
        mascota = _resolver_mascota_de_dueño(dueño, datos.get("idMascota_id"))
        precio = _resolver_precio_activo(cuidador, tipo_servicio)

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

            monto_pago = _calcular_monto_pago_solicitud(
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

            solicitud = builder.build()

            solicitud.save()
            bloque.disponible = False
            bloque.save(update_fields=["disponible"])

        # envia notificacion al cuidador (nueva solicitud pendiente)
        self.notificador.enviar_nueva_solicitud(solicitud)

        return solicitud

    def crear_solicitud_evento(self, datos):
        """Crea solicitud usando Evento (nuevo flujo unificado)."""
        dueño = datos["idDueño"]
        tipo_servicio = _validar_tipo_servicio_solicitud(datos.get("tipoServicio"))
        fecha = datos["fecha"]
        fecha_fin = datos.get("fechaFin")
        _validar_fechas_solicitud(fecha, fecha_fin)

        cuidador = _resolver_cuidador_verificado(datos.get("idCuidador_id"))
        mascota = _resolver_mascota_de_dueño(dueño, datos.get("idMascota_id"))
        precio = _resolver_precio_activo(cuidador, tipo_servicio)
        duracion_guarderia = _normalizar_duracion_guarderia_minutos(datos.get("duracionMinutosSolicitados"))

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
                cupos_disponibles, _ = _cupos_disponibles_evento_en_fecha(evento, fecha)
                if cupos_disponibles < 1:
                    raise ConflictError("el evento ya no tiene cupos disponibles para ese día")

            monto_pago = _calcular_monto_pago_solicitud(
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
            if duracion_guarderia is not None:
                builder = builder.con_duracion_guarderia(duracion_guarderia)

            solicitud = builder.build()

            solicitud.save()
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
        tipo_servicio = _validar_tipo_servicio_solicitud(datos["tipoServicio"])
        fecha = datos["fecha"]
        id_evento = datos.get("idEvento_id")
        _validar_fechas_solicitud(fecha, datos.get("fechaFin"))

        if tipo_servicio == TipoServicio.GUARDERIA:
            raise DomainValidationError("use el flujo de guardería para este tipo de servicio")

        cuidador = _resolver_cuidador_verificado(cuidador_id)
        mascota = _resolver_mascota_de_dueño(dueño, mascota_id)
        precio = _resolver_precio_activo(cuidador, tipo_servicio)

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

            monto_pago = _calcular_monto_pago_solicitud(
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

        dia = str(datos.get("diaSemana") or "").strip()
        hora_inicio_str = str(datos.get("horaInicio") or "").strip()
        hora_fin_str = str(datos.get("horaFin") or "").strip()
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

        tipo = str(datos.get("tipoServicio") or "").strip()
        validos = {TipoServicio.PASEO, TipoServicio.GUARDERIA}
        if tipo == TipoServicio.PASEO and (capacidad < 1 or capacidad > 4):
            raise DomainValidationError("capacidadMaxima para Paseo debe estar entre 1 y 4 perros")
        if tipo == TipoServicio.GUARDERIA and (capacidad < 1 or capacidad > 5):
            raise DomainValidationError("capacidadMaxima para Guardería debe estar entre 1 y 5")
        if tipo not in validos:
            raise DomainValidationError("tipo de servicio inválido para la ventana")

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

        dia = str(datos.get("diaSemana") or "").strip()
        hora_inicio_str = str(datos.get("horaInicio") or "").strip()
        hora_fin_str = str(datos.get("horaFin") or "").strip()
        duracion_str = str(datos.get("duracionMinutos") or "").strip()

        if not dia or not hora_inicio_str:
            raise DomainValidationError("día y hora inicio son requeridos")

        opciones_dia = [c[0] for c in DiaSemana.choices]
        if dia not in opciones_dia:
            raise DomainValidationError(f"día inválido: {dia}")

        try:
            partes_i = hora_inicio_str.replace(".", ":").split(":")
            hora_inicio = time(int(partes_i[0]), int(partes_i[1]))
        except (ValueError, IndexError):
            raise DomainValidationError("formato de hora inválido (HH:MM)")

        if hora_fin_str:
            try:
                partes_f = hora_fin_str.replace(".", ":").split(":")
                hora_fin = time(int(partes_f[0]), int(partes_f[1]))
            except (ValueError, IndexError):
                raise DomainValidationError("formato de hora inválido (HH:MM)")
        else:
            if not duracion_str:
                raise DomainValidationError("la duración es requerida")
            try:
                duracion_minutos = int(duracion_str)
            except (ValueError, TypeError):
                raise DomainValidationError("la duración debe ser un número entero en minutos")
            if duracion_minutos <= 0:
                raise DomainValidationError("la duración debe ser mayor a 0")
            fin_minutos = _time_to_minutes(hora_inicio) + duracion_minutos
            if fin_minutos > 24 * 60:
                raise DomainValidationError("la duración supera el final del día")
            hora_fin = _minutes_to_time(fin_minutos)

        if hora_fin <= hora_inicio:
            raise DomainValidationError("la hora fin debe ser posterior a la hora inicio")

        tipo = str(datos.get("tipoServicio") or "").strip()
        validos = {TipoServicio.PASEO, TipoServicio.GUARDERIA}
        if tipo not in validos:
            raise DomainValidationError("tipo de servicio inválido para el evento")

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

        capacidad = datos.get("capacidadMaxima")
        if tipo == TipoServicio.PASEO:
            capacidad_raw = str(capacidad).strip() if capacidad is not None else ""
            if not capacidad_raw:
                capacidad_val = 4
            else:
                try:
                    capacidad_val = int(capacidad_raw)
                except (ValueError, TypeError):
                    raise DomainValidationError("capacidadMaxima para Paseo debe ser un entero")
            if capacidad_val < 1 or capacidad_val > 4:
                raise DomainValidationError("capacidadMaxima para Paseo debe estar entre 1 y 4 perros")
        else:
            capacidad_raw = str(capacidad).strip() if capacidad is not None else ""
            if not capacidad_raw:
                capacidad_val = 1
            else:
                try:
                    capacidad_val = int(capacidad_raw)
                except (ValueError, TypeError):
                    raise DomainValidationError("capacidadMaxima para Guardería debe ser un entero")
            if capacidad_val < 1 or capacidad_val > 5:
                raise DomainValidationError("capacidadMaxima para Guardería debe estar entre 1 y 5 mascotas")

        duracion_total = _time_to_minutes(hora_fin) - _time_to_minutes(hora_inicio)
        if tipo == TipoServicio.PASEO and duracion_total not in PASEO_DURACIONES_MINUTOS:
            raise DomainValidationError("en paseo la duración debe ser de 1h, 1.5h, 2h, 2.5h o 3h")
        if tipo == TipoServicio.GUARDERIA and duracion_total < 60:
            raise DomainValidationError("en guardería la duración mínima por bloque es 1 hora")

        existe = Evento.objects.filter(
            idCuidador=perfil, tipoServicio=tipo, diaSemana=dia,
            horaInicio=hora_inicio, horaFin=hora_fin, nombreLugar=nombre_lugar or "",
        ).exists()
        if existe:
            raise ConflictError("ya existe un evento con ese horario y lugar")

        return Evento.objects.create(
            idCuidador=perfil,
            tipoServicio=tipo,
            diaSemana=dia,
            horaInicio=hora_inicio,
            horaFin=hora_fin,
            nombreLugar=nombre_lugar or "",
            latitud=lat_dec,
            longitud=lng_dec,
            precioCOP=precio_int,
            capacidadMaxima=capacidad_val,
            duracionSlotMinutos=None,
            disponible=True,
        )


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


class EliminarServicioCuidadorService:
    """Elimina un servicio del cuidador preservando trazabilidad histórica."""

    def eliminar(self, cuidador: Usuario, tipo_servicio: str) -> dict:
        if cuidador.rol != "cuidador":
            raise DomainValidationError("el usuario no tiene rol de cuidador")

        tipo = str(tipo_servicio or "").strip()
        if tipo not in (TipoServicio.PASEO, TipoServicio.GUARDERIA):
            raise DomainValidationError("servicio inválido")

        if SolicitudServicio.objects.filter(
            idCuidador=cuidador,
            tipoServicio=tipo,
            estado__in=[EstadoSolicitud.PENDIENTE, EstadoSolicitud.ACEPTADO],
        ).exists():
            raise ConflictError(
                "no puedes eliminar este servicio porque tienes reservas pendientes o aceptadas"
            )

        eventos_con_historial_ids: list[str] = []
        eventos_eliminados = 0

        try:
            perfil = PerfilCuidador.objects.get(idCuidador=cuidador)
        except PerfilCuidador.DoesNotExist:
            perfil = None

        with transaction.atomic():
            if perfil is not None:
                eventos_servicio = Evento.objects.filter(idCuidador=perfil, tipoServicio=tipo)
                eventos_con_historial_ids = list(
                    SolicitudServicio.objects.filter(idEvento__in=eventos_servicio)
                    .values_list("idEvento_id", flat=True)
                    .distinct()
                )

                if eventos_con_historial_ids:
                    SlotEvento.objects.filter(idEvento_id__in=eventos_con_historial_ids).update(
                        disponible=False
                    )
                    Evento.objects.filter(idEvento__in=eventos_con_historial_ids).update(
                        disponible=False
                    )

                eventos_eliminables = eventos_servicio.exclude(idEvento__in=eventos_con_historial_ids)
                eventos_eliminados = eventos_eliminables.count()
                if eventos_eliminados:
                    SlotEvento.objects.filter(idEvento__in=eventos_eliminables).delete()
                    eventos_eliminables.delete()

            PrecioServicio.objects.filter(idCuidador=cuidador, tipoServicio=tipo).delete()

        return {
            "eventos_eliminados": eventos_eliminados,
            "eventos_historicos": len(eventos_con_historial_ids),
        }


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


class ObtenerPreciosActivosCuidadorService:
    """Expone precios activos del cuidador sin acceso ORM en la vista."""

    def obtener(self, cuidador: Usuario) -> dict:
        if cuidador.rol != "cuidador":
            raise DomainValidationError("el usuario no tiene rol de cuidador")
        return {
            precio.tipoServicio: precio
            for precio in cuidador.precios_servicio.filter(activo=True)
        }


class ObtenerContextoServiciosCuidadorService:
    """Construye el contexto operativo de servicios para vistas de cuidador."""

    @staticmethod
    def _agrupar_por_dia(eventos):
        orden_dias = [c[0] for c in DiaSemana.choices]
        display_por_dia = {c[0]: c[1] for c in DiaSemana.choices}
        por_dia = {d: [] for d in orden_dias}
        for evento in (eventos or []):
            por_dia.setdefault(evento.diaSemana, []).append(evento)
        return [
            (dia, display_por_dia.get(dia, dia), por_dia[dia])
            for dia in orden_dias
            if por_dia[dia]
        ]

    @staticmethod
    def _resumen_eventos_activos(eventos):
        orden_dias = [c[0] for c in DiaSemana.choices]
        display_por_dia = {c[0]: c[1] for c in DiaSemana.choices}
        eventos = list(eventos or [])
        if not eventos:
            return {
                "dias_labels": [],
                "dias_resumen": "Sin dias activos",
                "hora_inicio_min": None,
                "hora_fin_max": None,
                "capacidad_maxima": 0,
            }

        dias_unicos = sorted(
            {evento.diaSemana for evento in eventos},
            key=lambda d: orden_dias.index(d) if d in orden_dias else 999,
        )
        dias_labels = [display_por_dia.get(d, d).capitalize() for d in dias_unicos]
        dias_resumen = ", ".join(dias_labels) if len(dias_labels) <= 3 else f"{', '.join(dias_labels[:3])} +{len(dias_labels) - 3}"

        return {
            "dias_labels": dias_labels,
            "dias_resumen": dias_resumen,
            "hora_inicio_min": min(evento.horaInicio for evento in eventos),
            "hora_fin_max": max(evento.horaFin for evento in eventos),
            "capacidad_maxima": max(int(evento.capacidadMaxima or 1) for evento in eventos),
        }

    def obtener(self, cuidador: Usuario) -> dict:
        if cuidador.rol != "cuidador":
            raise DomainValidationError("el usuario no tiene rol de cuidador")

        perfil = PerfilCuidador.objects.filter(idCuidador=cuidador).first()
        servicio_ciudad = (perfil.ciudadServicio if perfil else "") or cuidador.ciudad or ""
        servicio_latitud = (
            perfil.latitudServicio if perfil and perfil.latitudServicio is not None else cuidador.latitud
        ) or ""
        servicio_longitud = (
            perfil.longitudServicio if perfil and perfil.longitudServicio is not None else cuidador.longitud
        ) or ""
        servicio_radio_km = (
            perfil.radioKmServicio if perfil and perfil.radioKmServicio is not None else cuidador.radioKm
        ) or ""

        precios = {p.tipoServicio: p for p in cuidador.precios_servicio.filter(activo=True)}
        eventos_paseo = [
            evento
            for evento in ListarEventosCuidadorService().listar(cuidador, tipo_servicio=TipoServicio.PASEO)
            if evento.disponible
        ]
        eventos_guarderia = [
            evento
            for evento in ListarEventosCuidadorService().listar(cuidador, tipo_servicio=TipoServicio.GUARDERIA)
            if evento.disponible
        ]

        return {
            "perfil": perfil,
            "precios_activos": precios,
            "eventos_paseo": eventos_paseo,
            "eventos_guarderia": eventos_guarderia,
            "horarios_paseo_por_dia": self._agrupar_por_dia(eventos_paseo),
            "horarios_guarderia_por_dia": self._agrupar_por_dia(eventos_guarderia),
            "dias_semana": DiaSemana.choices,
            "tipos_servicio": [
                c
                for c in TipoServicio.choices
                if c[0] in {TipoServicio.PASEO, TipoServicio.GUARDERIA}
            ],
            "total_horarios_paseo": len(eventos_paseo),
            "total_horarios_guarderia": len(eventos_guarderia),
            "resumen_paseo": self._resumen_eventos_activos(eventos_paseo),
            "resumen_guarderia": self._resumen_eventos_activos(eventos_guarderia),
            "servicio_ciudad": servicio_ciudad,
            "servicio_latitud": servicio_latitud,
            "servicio_longitud": servicio_longitud,
            "servicio_radio_km": servicio_radio_km,
        }


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
        tipo_servicio = _validar_tipo_servicio_solicitud(datos["tipoServicio"])
        fecha = datos["fecha"]
        id_ventana = datos.get("idVentana_id")
        _validar_fechas_solicitud(fecha, datos.get("fechaFin"))

        if tipo_servicio == TipoServicio.GUARDERIA:
            raise DomainValidationError("use el flujo de guardería para este tipo de servicio")

        cuidador = _resolver_cuidador_verificado(cuidador_id)
        mascota = _resolver_mascota_de_dueño(dueño, mascota_id)
        precio = _resolver_precio_activo(cuidador, tipo_servicio)

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

            monto_pago = _calcular_monto_pago_solicitud(
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
    """Marca una solicitud aceptada como finalizada (solo cuidador)."""

    def __init__(self, notificador=None):
        self.notificador = notificador or NotificadorFactory.crear()

    def marcar(self, solicitud_id: str, actor: Usuario, forzar: bool = False) -> SolicitudServicio:
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
                if not _ya_paso_fin_programado_paseo(solicitud):
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
    """Consulta una solicitud con sus relaciones para exposición API."""

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
    """Resuelve solicitud para chat validando pertenencia según rol."""

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


class ObtenerPerfilPublicoService:
    """Carga información pública de perfil para vistas de consulta entre usuarios."""

    def obtener_usuario(self, usuario_id) -> Usuario:
        if not usuario_id:
            raise DomainValidationError("usuario_id es requerido")
        try:
            return Usuario.objects.get(idUsuario=usuario_id)
        except Usuario.DoesNotExist:
            raise ResourceNotFoundError("usuario no encontrado")

    def obtener_perfil_cuidador(self, usuario: Usuario) -> PerfilCuidador | None:
        if usuario.rol != "cuidador":
            return None
        return PerfilCuidador.objects.filter(idCuidador=usuario).first()

    def obtener_solicitud_relacionada(
        self,
        solicitud_id,
        cuidador: Usuario,
        dueño: Usuario,
    ) -> SolicitudServicio | None:
        if not solicitud_id:
            return None
        return SolicitudServicio.objects.select_related("idMascota").filter(
            idSolicitud=solicitud_id,
            idCuidador=cuidador,
            idDueño=dueño,
        ).first()


class ConstruirContextoPerfilPublicoService:
    """Construye el contexto de visualización de perfil de terceros."""

    def __init__(
        self,
        perfil_publico_service: ObtenerPerfilPublicoService | None = None,
        listar_mascotas_service: ListarMascotasDeDueñoService | None = None,
    ):
        self._perfil_publico_service = perfil_publico_service or ObtenerPerfilPublicoService()
        self._listar_mascotas_service = listar_mascotas_service or ListarMascotasDeDueñoService()

    def construir(self, actor: Usuario, usuario_id, solicitud_id: str | None) -> dict:
        otro = self._perfil_publico_service.obtener_usuario(usuario_id)
        perfil_cuidador = self._perfil_publico_service.obtener_perfil_cuidador(otro)

        mascota_asignada = None
        solicitud_relacionada = None
        solicitud_id_norm = str(solicitud_id or "").strip()

        if solicitud_id_norm and actor.rol == "cuidador" and otro.rol == "dueño":
            solicitud_relacionada = self._perfil_publico_service.obtener_solicitud_relacionada(
                solicitud_id_norm,
                cuidador=actor,
                dueño=otro,
            )
            if solicitud_relacionada:
                mascotas_dueño = self._listar_mascotas_service.listar(otro)
                mascota_asignada = next(
                    (mascota for mascota in mascotas_dueño if mascota.idMascota == solicitud_relacionada.idMascota_id),
                    solicitud_relacionada.idMascota,
                )

        return {
            "otro": otro,
            "perfil_cuidador": perfil_cuidador,
            "mascota_asignada": mascota_asignada,
            "solicitud_relacionada": solicitud_relacionada,
        }


class ObtenerTipoServicioEventoService:
    """Resuelve tipo de servicio de un evento del cuidador para navegación UI."""

    def obtener(self, cuidador: Usuario, evento_id: str | None) -> str | None:
        if cuidador.rol != "cuidador":
            raise DomainValidationError("el usuario no tiene rol de cuidador")
        if not evento_id:
            return None

        try:
            perfil = PerfilCuidador.objects.get(idCuidador=cuidador)
        except PerfilCuidador.DoesNotExist:
            return None

        return Evento.objects.filter(idEvento=evento_id, idCuidador=perfil).values_list(
            "tipoServicio",
            flat=True,
        ).first()


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


def _cupos_disponibles_evento_en_fecha(evento: Evento, fecha_servicio: date) -> tuple[int, int]:
    capacidad_total = max(1, int(evento.capacidadMaxima or 1))
    if evento.tipoServicio == TipoServicio.PASEO:
        capacidad_total = min(capacidad_total, 4)

    ocupados = SolicitudServicio.objects.filter(
        idEvento=evento,
        fecha=fecha_servicio,
        estado__in=ESTADOS_OCUPAN_CUPO,
    ).count()
    cupos = max(0, capacidad_total - ocupados)
    return cupos, capacidad_total


def _fecha_hora_fin_programada_solicitud(solicitud: SolicitudServicio):
    """Retorna la fecha/hora de fin programada para decidir cierres automáticos."""
    fecha_base = solicitud.fechaFin or solicitud.fecha

    hora_fin = None
    if solicitud.idEvento and solicitud.idEvento.horaFin:
        hora_fin = solicitud.idEvento.horaFin
    elif solicitud.idBloqueHorario and solicitud.idBloqueHorario.horaFin:
        hora_fin = solicitud.idBloqueHorario.horaFin
    elif solicitud.idVentana and solicitud.idVentana.horaFin:
        hora_fin = solicitud.idVentana.horaFin

    if hora_fin is None:
        return None

    zona = timezone.get_current_timezone()
    fin_naive = datetime.combine(fecha_base, hora_fin)
    return timezone.make_aware(fin_naive, zona)


def _ya_paso_fin_programado_paseo(solicitud: SolicitudServicio, ahora=None) -> bool:
    """Determina si un paseo aceptado ya superó su hora de fin."""
    if solicitud.tipoServicio != TipoServicio.PASEO:
        return False

    ahora_local = timezone.localtime(ahora or timezone.now())
    fin_programado = _fecha_hora_fin_programada_solicitud(solicitud)
    if fin_programado is None:
        fecha_base = solicitud.fechaFin or solicitud.fecha
        return fecha_base < ahora_local.date()

    return ahora_local >= fin_programado


def _puede_finalizar_solicitud(solicitud: SolicitudServicio, ahora=None) -> bool:
    """Evalúa si la solicitud puede marcarse como finalizada en UI/servicios."""
    if solicitud.estado != EstadoSolicitud.ACEPTADO:
        return False

    ahora_local = timezone.localtime(ahora or timezone.now())
    if solicitud.tipoServicio == TipoServicio.PASEO:
        return _ya_paso_fin_programado_paseo(solicitud, ahora=ahora_local)

    fecha_limite = solicitud.fechaFin or solicitud.fecha
    return fecha_limite <= ahora_local.date()


def _auto_finalizar_paseos_expirados(
    solicitudes: list[SolicitudServicio],
    notificador=None,
    ahora=None,
) -> int:
    """Finaliza automáticamente paseos aceptados cuando su hora ya pasó."""
    if not solicitudes:
        return 0

    ahora_local = timezone.localtime(ahora or timezone.now())
    ahora_db = timezone.now()
    notificador_local = notificador
    total = 0

    for solicitud in solicitudes:
        if solicitud.estado != EstadoSolicitud.ACEPTADO:
            continue
        if not _ya_paso_fin_programado_paseo(solicitud, ahora=ahora_local):
            continue

        actualizada = SolicitudServicio.objects.filter(
            idSolicitud=solicitud.idSolicitud,
            estado=EstadoSolicitud.ACEPTADO,
        ).update(
            estado=EstadoSolicitud.COMPLETADO,
            updated_at=ahora_db,
        )
        if not actualizada:
            continue

        solicitud.estado = EstadoSolicitud.COMPLETADO
        solicitud.updated_at = ahora_db
        if notificador_local is None:
            notificador_local = NotificadorFactory.crear()
        notificador_local.enviar_servicio_completado(solicitud)
        notificador_local.enviar_resena_pendiente(solicitud)
        total += 1

    return total


def _normalizar_ciudad(ciudad: str | None) -> str:
    return " ".join(str(ciudad or "").strip().lower().split())


def _cobertura_operativa_cuidador(perfil: PerfilCuidador, cuidador: Usuario):
    """Obtiene la ubicación/radio operativos del cuidador para búsquedas de servicios."""
    ciudad = (perfil.ciudadServicio or "").strip() or (cuidador.ciudad or "").strip()
    latitud = perfil.latitudServicio if perfil.latitudServicio is not None else cuidador.latitud
    longitud = perfil.longitudServicio if perfil.longitudServicio is not None else cuidador.longitud
    radio_km = perfil.radioKmServicio if perfil.radioKmServicio is not None else cuidador.radioKm
    return ciudad, latitud, longitud, radio_km


class BuscarCuidadoresDisponiblesService:
    """Busca cuidadores disponibles usando eventos (flujo principal)."""

    _DIAS = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
    _DURACIONES_VALIDAS = list(PASEO_DURACIONES_MINUTOS)

    def buscar(
        self,
        dueño: Usuario,
        mascota_id: str,
        fecha_o_str,
        duracion_minutos: int | None = None,
        solo_ciudad: bool = True,
        ciudad_referencia: str | None = None,
        latitud_referencia=None,
        longitud_referencia=None,
    ) -> list:
        """Busca cuidadores para paseo por fecha, con duración opcional."""
        if dueño.rol != "dueño":
            raise DomainValidationError("el usuario no tiene rol de dueño")
        if not mascota_id or not str(mascota_id).strip():
            raise DomainValidationError("debes seleccionar una mascota")

        duracion_filtrada = None
        if duracion_minutos is not None and str(duracion_minutos).strip() != "":
            try:
                duracion_filtrada = int(duracion_minutos)
            except (TypeError, ValueError):
                raise DomainValidationError("la duración del paseo es inválida")
            if duracion_filtrada not in self._DURACIONES_VALIDAS:
                raise DomainValidationError("la duración debe ser de 60, 90, 120, 150 o 180 minutos")

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
        if mascota.tipo != TipoMascota.PERRO:
            raise DomainValidationError("el paseo solo está disponible para perros")

        if fecha < date.today():
            raise DomainValidationError("la fecha no puede ser en el pasado")

        dia_semana = self._DIAS[fecha.weekday()]

        ref_lat = dueño.latitud
        ref_lon = dueño.longitud
        if latitud_referencia is not None and str(latitud_referencia).strip() != "":
            try:
                ref_lat = Decimal(str(latitud_referencia).strip())
            except Exception:
                ref_lat = None
        if longitud_referencia is not None and str(longitud_referencia).strip() != "":
            try:
                ref_lon = Decimal(str(longitud_referencia).strip())
            except Exception:
                ref_lon = None

        ciudad_ref = (ciudad_referencia or "").strip() or dueño.ciudad
        usar_radio = solo_ciudad and ref_lat and ref_lon

        resultado = []

        eventos = (
            Evento.objects.filter(
                tipoServicio=TipoServicio.PASEO,
                diaSemana=dia_semana,
                duracionSlotMinutos__isnull=True,
                disponible=True,
            )
            .select_related("idCuidador__idCuidador")
            .order_by("horaInicio")
        )

        for evento in eventos:
            perfil = evento.idCuidador
            cuidador = perfil.idCuidador
            if not cuidador.verificado:
                continue

            ciudad_operativa, lat_operativa, lng_operativa, radio_operativo = _cobertura_operativa_cuidador(perfil, cuidador)

            duracion_evento = _time_to_minutes(evento.horaFin) - _time_to_minutes(evento.horaInicio)
            if duracion_filtrada is not None and duracion_evento != duracion_filtrada:
                continue

            cupos_disponibles, capacidad_total = _cupos_disponibles_evento_en_fecha(evento, fecha)
            if cupos_disponibles < 1:
                continue

            precio = PrecioServicio.objects.filter(
                idCuidador=cuidador,
                tipoServicio=TipoServicio.PASEO,
                activo=True,
            ).first()
            if not precio:
                continue

            distancia_km = None
            if usar_radio and lat_operativa and lng_operativa:
                distancia_km = _haversine_km(ref_lat, ref_lon, lat_operativa, lng_operativa)
                if radio_operativo and distancia_km > float(radio_operativo):
                    continue
                if not radio_operativo and ciudad_ref and _normalizar_ciudad(ciudad_operativa) != _normalizar_ciudad(ciudad_ref):
                    continue
            elif usar_radio and (not lat_operativa or not lng_operativa):
                if ciudad_ref and _normalizar_ciudad(ciudad_operativa) != _normalizar_ciudad(ciudad_ref):
                    continue
            elif solo_ciudad and ciudad_ref and _normalizar_ciudad(ciudad_operativa) != _normalizar_ciudad(ciudad_ref):
                continue

            distancia_m = _time_to_minutes(evento.horaInicio)

            duracion_horas = duracion_evento / 60.0
            tarifa_hora = evento.precioCOP or precio.precioCOP
            prom, cnt = _calificacion_promedio_count(cuidador)
            resultado.append({
                "evento": evento,
                "eventos_disponibles": [{"id": str(evento.idEvento), "texto": f"{evento.diaSemana} {evento.horaInicio}-{evento.horaFin}"}],
                "cuidador": cuidador,
                "perfil": perfil,
                "tarifa_total": int(tarifa_hora * duracion_horas),
                "tarifa_hora": tarifa_hora,
                "duracion_minutos": duracion_evento,
                "duracion_horas": duracion_horas,
                "hora_sugerida": evento.horaInicio,
                "distancia_minutos": distancia_m,
                "distancia_km": round(distancia_km, 1) if distancia_km is not None else None,
                "calificacion_promedio": prom,
                "calificacion_count": cnt,
                "tipo_servicio": TipoServicio.PASEO,
                "descripcion_servicio": precio.descripcion or (perfil.descripcion or ""),
                "cupo_maximo": capacidad_total,
                "cupos_disponibles": cupos_disponibles,
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
        hora_inicio_str: str | None = None,
        hora_fin_str: str | None = None,
        solo_ciudad: bool = True,
        ciudad_referencia: str | None = None,
        latitud_referencia=None,
        longitud_referencia=None,
        radio_busqueda_km=None,
    ) -> list:
        """Busca cuidadores de guardería y devuelve slots seleccionables con cupos por fecha."""
        if dueño.rol != "dueño":
            raise DomainValidationError("el usuario no tiene rol de dueño")
        if not mascota_id or not str(mascota_id).strip():
            raise DomainValidationError("debes seleccionar una mascota")

        try:
            fecha_inicio = datetime.strptime((fecha_inicio_str or "").strip(), "%Y-%m-%d").date()
        except ValueError:
            raise DomainValidationError("formato de fecha inicio inválido, use AAAA-MM-DD")

        fecha_fin_raw = (fecha_fin_str or "").strip()
        if fecha_fin_raw:
            try:
                fecha_fin = datetime.strptime(fecha_fin_raw, "%Y-%m-%d").date()
            except ValueError:
                raise DomainValidationError("formato de fecha fin inválido, use AAAA-MM-DD")
        else:
            fecha_fin = fecha_inicio

        if fecha_inicio < date.today():
            raise DomainValidationError("la fecha inicio no puede ser en el pasado")
        if fecha_fin < fecha_inicio:
            raise DomainValidationError("la fecha fin debe ser igual o posterior a la fecha inicio")

        num_days = (fecha_fin - fecha_inicio).days + 1
        dias_requeridos = set()
        d_cursor = fecha_inicio
        while d_cursor <= fecha_fin:
            dias_requeridos.add(self._DIAS[d_cursor.weekday()])
            d_cursor += timedelta(days=1)

        try:
            mascota = Mascota.objects.get(idMascota=mascota_id, idDueño=dueño)
        except Mascota.DoesNotExist:
            raise ResourceNotFoundError("la mascota no existe o no te pertenece")

        eventos = Evento.objects.filter(
            tipoServicio=TipoServicio.GUARDERIA,
            diaSemana__in=list(dias_requeridos),
            duracionSlotMinutos__isnull=True,
            disponible=True,
        ).select_related("idCuidador__idCuidador").order_by("idCuidador__idCuidador__idUsuario", "horaInicio")

        ref_lat = dueño.latitud
        ref_lon = dueño.longitud
        if latitud_referencia is not None and str(latitud_referencia).strip() != "":
            try:
                ref_lat = Decimal(str(latitud_referencia).strip())
            except Exception:
                ref_lat = None
        if longitud_referencia is not None and str(longitud_referencia).strip() != "":
            try:
                ref_lon = Decimal(str(longitud_referencia).strip())
            except Exception:
                ref_lon = None

        ciudad_ref = (ciudad_referencia or "").strip() or dueño.ciudad
        usar_radio = solo_ciudad and ref_lat and ref_lon

        radio_busqueda = None
        if radio_busqueda_km is not None and str(radio_busqueda_km).strip() != "":
            try:
                radio_busqueda = float(str(radio_busqueda_km).strip())
            except (TypeError, ValueError):
                raise DomainValidationError("el km de proximidad para guardería es inválido")
            if radio_busqueda < 0.5 or radio_busqueda > 50:
                raise DomainValidationError("el km de proximidad para guardería debe estar entre 0.5 y 50")

        eventos_por_cuidador = {}
        for evento in eventos:
            cuidador_id = evento.idCuidador.idCuidador.idUsuario
            if cuidador_id not in eventos_por_cuidador:
                eventos_por_cuidador[cuidador_id] = {}
            eventos_por_cuidador[cuidador_id].setdefault(evento.diaSemana, []).append(evento)

        resultado = []
        for _, eventos_por_dia in eventos_por_cuidador.items():
            evento_base = next(iter(eventos_por_dia.values()))[0]
            perfil = evento_base.idCuidador
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
            ciudad_operativa, lat_operativa, lng_operativa, radio_operativo = _cobertura_operativa_cuidador(perfil, cuidador)
            if usar_radio and lat_operativa and lng_operativa:
                distancia_km_val = _haversine_km(ref_lat, ref_lon, lat_operativa, lng_operativa)
                if radio_operativo and distancia_km_val > float(radio_operativo):
                    continue
                if radio_busqueda is not None and distancia_km_val > radio_busqueda:
                    continue
                if not radio_operativo and ciudad_ref and _normalizar_ciudad(ciudad_operativa) != _normalizar_ciudad(ciudad_ref):
                    continue
            elif usar_radio and (not lat_operativa or not lng_operativa):
                if ciudad_ref and _normalizar_ciudad(ciudad_operativa) != _normalizar_ciudad(ciudad_ref):
                    continue
            elif solo_ciudad and ciudad_ref and _normalizar_ciudad(ciudad_operativa) != _normalizar_ciudad(ciudad_ref):
                continue

            slots_guarderia = []
            d_cursor = fecha_inicio
            while d_cursor <= fecha_fin:
                dia = self._DIAS[d_cursor.weekday()]
                opciones_dia = eventos_por_dia.get(dia, [])
                if not opciones_dia:
                    d_cursor += timedelta(days=1)
                    continue

                opciones_ordenadas = sorted(
                    opciones_dia,
                    key=lambda ev: (
                        _time_to_minutes(ev.horaFin) - _time_to_minutes(ev.horaInicio),
                        -_time_to_minutes(ev.horaInicio),
                    ),
                    reverse=True,
                )

                for candidato in opciones_ordenadas:
                    cupos_disponibles, cupo_maximo = _cupos_disponibles_evento_en_fecha(candidato, d_cursor)
                    if cupos_disponibles < 1:
                        continue

                    duracion_maxima_minutos = _time_to_minutes(candidato.horaFin) - _time_to_minutes(candidato.horaInicio)
                    if duracion_maxima_minutos < 60:
                        continue

                    duracion_opciones = list(range(60, duracion_maxima_minutos + 1, 30))
                    if not duracion_opciones:
                        continue

                    texto_slot = (
                        f"{dia} {d_cursor.strftime('%d/%m')} "
                        f"{candidato.horaInicio.strftime('%H:%M')}-{candidato.horaFin.strftime('%H:%M')}"
                    )
                    slots_guarderia.append(
                        {
                            "evento": candidato,
                            "evento_id": str(candidato.idEvento),
                            "fecha": d_cursor,
                            "fecha_iso": d_cursor.isoformat(),
                            "dia_semana": dia,
                            "hora_inicio": candidato.horaInicio,
                            "hora_fin": candidato.horaFin,
                            "texto": texto_slot,
                            "cupos_disponibles": cupos_disponibles,
                            "cupo_maximo": cupo_maximo,
                            "duracion_maxima_minutos": duracion_maxima_minutos,
                            "duracion_opciones": duracion_opciones,
                        }
                    )

                d_cursor += timedelta(days=1)

            if not slots_guarderia:
                continue

            slots_guarderia.sort(key=lambda s: (s["fecha"], s["hora_inicio"]))
            slot_default = slots_guarderia[0]
            evento_representativo = slot_default["evento"]
            duracion_maxima_minutos = slot_default["duracion_maxima_minutos"]
            duracion_opciones = slot_default["duracion_opciones"]
            duracion_horas_default = duracion_maxima_minutos / 60.0
            tarifa_hora = evento_representativo.precioCOP or precio.precioCOP
            tarifa_total = int(tarifa_hora * duracion_horas_default)
            prom, cnt = _calificacion_promedio_count(cuidador)
            resultado.append({
                "evento": evento_representativo,
                "eventos_disponibles": slots_guarderia,
                "slots_guarderia": slots_guarderia,
                "evento_default_id": slot_default["evento_id"],
                "fecha_default": slot_default["fecha"],
                "fecha_default_iso": slot_default["fecha_iso"],
                "cuidador": cuidador,
                "perfil": perfil,
                "tarifa_total": tarifa_total,
                "tarifa_hora": tarifa_hora,
                "duracion_minutos": duracion_maxima_minutos,
                "duracion_horas": duracion_horas_default,
                "duracion_maxima_minutos": duracion_maxima_minutos,
                "duracion_opciones": duracion_opciones,
                "num_dias": num_days,
                "fecha_inicio": fecha_inicio,
                "fecha_fin": fecha_fin,
                "hora_inicio": slot_default["hora_inicio"],
                "hora_fin": slot_default["hora_fin"],
                "cupo_maximo": slot_default["cupo_maximo"],
                "cupos_disponibles": slot_default["cupos_disponibles"],
                "total_slots_disponibles": len(slots_guarderia),
                "distancia_km": round(distancia_km_val, 1) if distancia_km_val is not None else None,
                "calificacion_promedio": prom,
                "calificacion_count": cnt,
                "tipo_servicio": TipoServicio.GUARDERIA,
                "descripcion_servicio": precio.descripcion or (perfil.descripcion or ""),
            })

        resultado.sort(key=lambda x: (
            (x["distancia_km"] if x["distancia_km"] is not None else 9999),
            x["fecha_default"],
            x["hora_inicio"],
        ))
        return resultado


class FiltrarResultadosDisponibilidadService:
    """Filtra resultados de disponibilidad por tarifa por hora y franja horaria."""

    def filtrar(
        self,
        resultados: list,
        precio_min_hora=None,
        precio_max_hora=None,
        hora_inicio=None,
        hora_fin=None,
    ) -> list:
        precio_min = self._coerce_int(precio_min_hora, "precio mínimo")
        precio_max = self._coerce_int(precio_max_hora, "precio máximo")
        hora_inicio_filtro = self._coerce_time(hora_inicio, "hora inicio")
        hora_fin_filtro = self._coerce_time(hora_fin, "hora fin")

        if precio_min is not None and precio_max is not None and precio_min > precio_max:
            raise DomainValidationError("el precio mínimo no puede ser mayor al precio máximo")

        if (
            hora_inicio_filtro is not None
            and hora_fin_filtro is not None
            and hora_fin_filtro <= hora_inicio_filtro
        ):
            raise DomainValidationError("la hora fin debe ser posterior a la hora inicio")

        salida = []
        for item in resultados or []:
            tarifa_hora = self._coerce_item_tarifa(item)
            if precio_min is not None and (tarifa_hora is None or tarifa_hora < precio_min):
                continue
            if precio_max is not None and (tarifa_hora is None or tarifa_hora > precio_max):
                continue

            item_filtrado = self._filtrar_por_hora_item(
                item,
                hora_inicio_filtro,
                hora_fin_filtro,
            )
            if item_filtrado is None:
                continue
            salida.append(item_filtrado)

        return salida

    def _filtrar_por_hora_item(self, item: dict, hora_inicio_filtro: time | None, hora_fin_filtro: time | None):
        if hora_inicio_filtro is None and hora_fin_filtro is None:
            return item

        slots_guarderia = item.get("slots_guarderia") or []
        if slots_guarderia:
            slots_filtrados = []
            for slot in slots_guarderia:
                hi = self._coerce_time(slot.get("hora_inicio"), "hora inicio del slot")
                hf = self._coerce_time(slot.get("hora_fin"), "hora fin del slot")
                if hi is None or hf is None:
                    continue
                if not self._solapa_con_filtro(hi, hf, hora_inicio_filtro, hora_fin_filtro):
                    continue
                slots_filtrados.append(slot)

            if not slots_filtrados:
                return None

            slots_filtrados.sort(key=lambda s: (s["fecha"], s["hora_inicio"]))
            slot_default = slots_filtrados[0]
            tarifa_hora = self._coerce_item_tarifa(item) or 0

            item_nuevo = dict(item)
            item_nuevo["slots_guarderia"] = slots_filtrados
            item_nuevo["eventos_disponibles"] = slots_filtrados
            item_nuevo["evento"] = slot_default.get("evento") or item.get("evento")
            item_nuevo["evento_default_id"] = slot_default["evento_id"]
            item_nuevo["fecha_default"] = slot_default["fecha"]
            item_nuevo["fecha_default_iso"] = slot_default["fecha_iso"]
            item_nuevo["hora_inicio"] = slot_default["hora_inicio"]
            item_nuevo["hora_fin"] = slot_default["hora_fin"]
            item_nuevo["cupo_maximo"] = slot_default["cupo_maximo"]
            item_nuevo["cupos_disponibles"] = slot_default["cupos_disponibles"]
            item_nuevo["duracion_maxima_minutos"] = slot_default["duracion_maxima_minutos"]
            item_nuevo["duracion_opciones"] = slot_default["duracion_opciones"]
            item_nuevo["duracion_minutos"] = slot_default["duracion_maxima_minutos"]
            item_nuevo["duracion_horas"] = slot_default["duracion_maxima_minutos"] / 60.0
            item_nuevo["tarifa_total"] = int(
                tarifa_hora * (slot_default["duracion_maxima_minutos"] / 60.0)
            )
            item_nuevo["total_slots_disponibles"] = len(slots_filtrados)
            return item_nuevo

        evento = item.get("evento")
        hora_inicio_item = item.get("hora_inicio")
        hora_fin_item = item.get("hora_fin")
        if evento is not None:
            hora_inicio_item = hora_inicio_item or evento.horaInicio
            hora_fin_item = hora_fin_item or evento.horaFin

        hi = self._coerce_time(hora_inicio_item, "hora inicio")
        hf = self._coerce_time(hora_fin_item, "hora fin")
        if hi is None or hf is None:
            return None

        if not self._solapa_con_filtro(hi, hf, hora_inicio_filtro, hora_fin_filtro):
            return None

        item_nuevo = dict(item)
        item_nuevo["hora_inicio"] = hi
        item_nuevo["hora_fin"] = hf
        return item_nuevo

    @staticmethod
    def _solapa_con_filtro(
        hora_inicio_item: time,
        hora_fin_item: time,
        hora_inicio_filtro: time | None,
        hora_fin_filtro: time | None,
    ) -> bool:
        """Valida solape de franja horaria para no excluir bloques de día completo."""
        if hora_inicio_filtro is None and hora_fin_filtro is None:
            return True

        hi = _time_to_minutes(hora_inicio_item)
        hf = _time_to_minutes(hora_fin_item)

        if hora_inicio_filtro is not None and hora_fin_filtro is not None:
            fi = _time_to_minutes(hora_inicio_filtro)
            ff = _time_to_minutes(hora_fin_filtro)
            return hi < ff and hf > fi

        if hora_inicio_filtro is not None:
            fi = _time_to_minutes(hora_inicio_filtro)
            return hf > fi

        ff = _time_to_minutes(hora_fin_filtro)
        return hi < ff

    @staticmethod
    def _coerce_item_tarifa(item: dict) -> int | None:
        valor = item.get("tarifa_hora")
        if valor is None:
            return None
        try:
            return int(valor)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coerce_int(valor, nombre: str) -> int | None:
        if valor is None or str(valor).strip() == "":
            return None
        try:
            numero = int(str(valor).strip())
        except (TypeError, ValueError):
            raise DomainValidationError(f"{nombre} inválido")
        if numero < 0:
            raise DomainValidationError(f"{nombre} no puede ser negativo")
        return numero

    @staticmethod
    def _coerce_time(valor, nombre: str) -> time | None:
        if valor is None:
            return None
        if isinstance(valor, time):
            return valor

        texto = str(valor).strip()
        if not texto:
            return None

        formatos = ["%H:%M", "%H:%M:%S"]
        for fmt in formatos:
            try:
                return datetime.strptime(texto, fmt).time()
            except ValueError:
                continue

        raise DomainValidationError(f"{nombre} inválida")


class NormalizarBusquedaReservaService:
    """Normaliza datos del formulario de búsqueda de reservas del dueño."""

    def busqueda_default(self, usuario: Usuario) -> dict:
        return {
            "tipo_servicio": TipoServicio.PASEO,
            "mascota_id": "",
            "fecha": "",
            "duracion": "",
            "ciudad_paseo": usuario.ciudad or "",
            "latitud_paseo": "",
            "longitud_paseo": "",
            "fecha_inicio_guarderia": "",
            "fecha_fin_guarderia": "",
            "ciudad_guarderia": usuario.ciudad or "",
            "latitud_guarderia": "",
            "longitud_guarderia": "",
            "radio_guarderia_km": "",
            "precio_min": "",
            "precio_max": "",
            "hora_inicio_filtro": "",
            "hora_fin_filtro": "",
        }

    def busqueda_from_source(self, source, usuario: Usuario) -> dict:
        data = self.busqueda_default(usuario)
        data.update(
            {
                "tipo_servicio": str(source.get("tipo_servicio") or TipoServicio.PASEO).strip() or TipoServicio.PASEO,
                "mascota_id": source.get("mascota_id", ""),
                "fecha": source.get("fecha", ""),
                "duracion": self._coerce_int_or_blank(source.get("duracion")),
                "ciudad_paseo": (source.get("ciudad_paseo") or "").strip() or (usuario.ciudad or ""),
                "latitud_paseo": source.get("latitud_paseo", ""),
                "longitud_paseo": source.get("longitud_paseo", ""),
                "fecha_inicio_guarderia": source.get("fecha_guarderia_inicio", ""),
                "fecha_fin_guarderia": source.get("fecha_guarderia_fin", "")
                or source.get("fecha_guarderia_inicio", ""),
                "ciudad_guarderia": (source.get("ciudad_guarderia") or "").strip() or (usuario.ciudad or ""),
                "latitud_guarderia": source.get("latitud_guarderia", ""),
                "longitud_guarderia": source.get("longitud_guarderia", ""),
                "radio_guarderia_km": (source.get("radio_guarderia_km") or "").strip(),
                "precio_min": (source.get("precio_min") or "").strip(),
                "precio_max": (source.get("precio_max") or "").strip(),
                "hora_inicio_filtro": (source.get("hora_inicio_filtro") or "").strip(),
                "hora_fin_filtro": (source.get("hora_fin_filtro") or "").strip(),
            }
        )
        return data

    @staticmethod
    def filtros_disponibilidad(source) -> dict:
        return {
            "precio_min_hora": source.get("precio_min"),
            "precio_max_hora": source.get("precio_max"),
            "hora_inicio": source.get("hora_inicio_filtro"),
            "hora_fin": source.get("hora_fin_filtro"),
        }

    @staticmethod
    def parametros_guarderia(source) -> dict:
        return {
            "mascota_id": source.get("mascota_id"),
            "fecha_inicio": source.get("fecha_guarderia_inicio"),
            "fecha_fin": source.get("fecha_guarderia_fin"),
            "ciudad": (source.get("ciudad_guarderia") or "").strip(),
            "latitud": source.get("latitud_guarderia"),
            "longitud": source.get("longitud_guarderia"),
            "radio_km": (source.get("radio_guarderia_km") or "").strip(),
        }

    def parametros_paseo(self, source) -> dict:
        return {
            "mascota_id": source.get("mascota_id"),
            "fecha": source.get("fecha"),
            "duracion_minutos": self._coerce_int_or_none(source.get("duracion")),
            "ciudad": (source.get("ciudad_paseo") or "").strip(),
            "latitud": source.get("latitud_paseo"),
            "longitud": source.get("longitud_paseo"),
        }

    @staticmethod
    def _coerce_int_or_none(valor):
        texto = str(valor or "").strip()
        if not texto:
            return None
        try:
            return int(texto)
        except (ValueError, TypeError):
            return None

    def _coerce_int_or_blank(self, valor):
        numero = self._coerce_int_or_none(valor)
        return numero if numero is not None else ""


class BuscarDisponibilidadFormularioReservaService:
    """Orquesta búsqueda y filtrado de disponibilidad desde formulario web."""

    def __init__(
        self,
        buscador: BuscarCuidadoresDisponiblesService | None = None,
        filtrador: FiltrarResultadosDisponibilidadService | None = None,
        normalizador: NormalizarBusquedaReservaService | None = None,
    ):
        self._buscador = buscador or BuscarCuidadoresDisponiblesService()
        self._filtrador = filtrador or FiltrarResultadosDisponibilidadService()
        self._normalizador = normalizador or NormalizarBusquedaReservaService()

    def buscar(self, dueño: Usuario, source) -> tuple[list, dict]:
        tipo_servicio = str(source.get("tipo_servicio") or TipoServicio.PASEO).strip().lower()
        filtros = self._normalizador.filtros_disponibilidad(source)
        busqueda = self._normalizador.busqueda_from_source(source, dueño)

        if tipo_servicio == TipoServicio.GUARDERIA:
            params = self._normalizador.parametros_guarderia(source)
            resultados = self._buscador.buscar_cuidado(
                dueño,
                params["mascota_id"],
                params["fecha_inicio"],
                params["fecha_fin"],
                solo_ciudad=True,
                ciudad_referencia=params["ciudad"],
                latitud_referencia=params["latitud"],
                longitud_referencia=params["longitud"],
                radio_busqueda_km=params["radio_km"],
            )
            busqueda["tipo_servicio"] = TipoServicio.GUARDERIA
        else:
            params = self._normalizador.parametros_paseo(source)
            resultados = self._buscador.buscar(
                dueño,
                params["mascota_id"],
                params["fecha"],
                params["duracion_minutos"],
                solo_ciudad=True,
                ciudad_referencia=params["ciudad"],
                latitud_referencia=params["latitud"],
                longitud_referencia=params["longitud"],
            )
            busqueda["tipo_servicio"] = TipoServicio.PASEO
            busqueda["ciudad_paseo"] = params["ciudad"]
            busqueda["latitud_paseo"] = params["latitud"] or ""
            busqueda["longitud_paseo"] = params["longitud"] or ""

        cuidadores = self._filtrador.filtrar(resultados, **filtros)
        return cuidadores, busqueda


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
        modo_guarderia: str | None = None,
        duracion_guarderia_minutos: str | None = None,
        hora_inicio_guarderia_str: str | None = None,
        hora_fin_guarderia_str: str | None = None,
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
                raise DomainValidationError("la fecha fin debe ser igual o posterior a la fecha de inicio")

        duracion_guarderia_min = None

        try:
            mascota = Mascota.objects.get(idMascota=mascota_id, idDueño=dueño)
        except Mascota.DoesNotExist:
            raise ResourceNotFoundError("la mascota no existe o no te pertenece")

        if not evento_id:
            raise DomainValidationError("debes indicar un evento para reservar")

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

        if tipo_servicio == TipoServicio.GUARDERIA:
            duracion_bloque_min = _time_to_minutes(evento.horaFin) - _time_to_minutes(evento.horaInicio)
            if duracion_bloque_min < 60:
                raise DomainValidationError("el bloque de guardería del cuidador debe ser mínimo de 1 hora")

            modo_guarderia_norm = (modo_guarderia or "").strip().lower()
            duracion_guarderia_raw = (duracion_guarderia_minutos or "").strip()

            if hora_inicio_guarderia_str and hora_fin_guarderia_str:
                try:
                    hora_inicio_guarderia = datetime.strptime(hora_inicio_guarderia_str.strip(), "%H:%M").time()
                    hora_fin_guarderia = datetime.strptime(hora_fin_guarderia_str.strip(), "%H:%M").time()
                except ValueError:
                    raise DomainValidationError("formato de hora inválido, use HH:MM")
                if hora_fin_guarderia <= hora_inicio_guarderia:
                    raise DomainValidationError("la hora fin debe ser posterior a la hora inicio")
                duracion_guarderia_min = _time_to_minutes(hora_fin_guarderia) - _time_to_minutes(hora_inicio_guarderia)
            elif modo_guarderia_norm == "tiempo_personalizado":
                if not duracion_guarderia_raw:
                    raise DomainValidationError("debes indicar el tiempo de guardería personalizado")
                try:
                    duracion_guarderia_min = int(duracion_guarderia_raw)
                except (ValueError, TypeError):
                    raise DomainValidationError("el tiempo personalizado de guardería debe ser un número entero")
            else:
                duracion_guarderia_min = duracion_bloque_min

            if duracion_guarderia_min < 60:
                raise DomainValidationError("la guardería requiere mínimo 1 hora")
            if duracion_guarderia_min % 30 != 0:
                raise DomainValidationError("la guardería se solicita en múltiplos de 30 minutos")
            if duracion_guarderia_min > duracion_bloque_min:
                raise DomainValidationError("el tiempo solicitado excede el bloque disponible del cuidador")

            if fecha_fin is None:
                fecha_fin = fecha

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
        if duracion_guarderia_min is not None:
            datos["duracionMinutosSolicitados"] = duracion_guarderia_min

        if evento.duracionSlotMinutos is not None:
            return self._solicitud_con_asignacion_evento.crear(datos)
        return self._solicitud_service.crear_solicitud_evento(datos)


class ListarSolicitudesDueñoService:
    # lista solicitudes de un dueño

    def listar(self, dueño: Usuario) -> dict:
        if dueño.rol != "dueño":
            raise DomainValidationError("el usuario no tiene rol de dueño")

        hoy = timezone.localdate()
        solicitudes = list(SolicitudServicio.objects.filter(idDueño=dueño).select_related(
            "idCuidador", "idMascota", "idBloqueHorario", "idVentana", "idSlot", "idEvento", "idSlotEvento"
        ).prefetch_related("calificaciones", "mensajes_chat__idDe").order_by("-fecha", "-created_at"))

        _auto_finalizar_paseos_expirados(solicitudes)

        for solicitud in solicitudes:
            solicitud.calificacion_mia = _calificacion_de_autor_en_solicitud(solicitud, dueño)
            solicitud.anotacion_cuidador = ""
            solicitud.anotacion_cuidador_fecha = None
            solicitud.fecha_limite_servicio = solicitud.fechaFin or solicitud.fecha

            solicitud.total_dias_servicio = 1
            if (
                solicitud.tipoServicio == TipoServicio.GUARDERIA
                and solicitud.fechaFin
                and solicitud.fechaFin >= solicitud.fecha
            ):
                solicitud.total_dias_servicio = (solicitud.fechaFin - solicitud.fecha).days + 1

            solicitud.hora_inicio_servicio = None
            solicitud.hora_fin_servicio = None
            solicitud.hora_slot_asignado = None
            solicitud.nombre_lugar_servicio = ""
            solicitud.latitud_servicio = None
            solicitud.longitud_servicio = None
            solicitud.capacidad_evento = None

            if solicitud.idEvento:
                solicitud.hora_inicio_servicio = solicitud.idEvento.horaInicio
                solicitud.hora_fin_servicio = solicitud.idEvento.horaFin
                solicitud.hora_slot_asignado = solicitud.idSlotEvento.horaInicio if solicitud.idSlotEvento else None
                solicitud.nombre_lugar_servicio = solicitud.idEvento.nombreLugar or ""
                solicitud.latitud_servicio = solicitud.idEvento.latitud
                solicitud.longitud_servicio = solicitud.idEvento.longitud
                solicitud.capacidad_evento = solicitud.idEvento.capacidadMaxima
            elif solicitud.idBloqueHorario:
                solicitud.hora_inicio_servicio = solicitud.idBloqueHorario.horaInicio
                solicitud.hora_fin_servicio = solicitud.idBloqueHorario.horaFin
                solicitud.nombre_lugar_servicio = solicitud.idBloqueHorario.nombreLugar or ""
                solicitud.latitud_servicio = solicitud.idBloqueHorario.latitud
                solicitud.longitud_servicio = solicitud.idBloqueHorario.longitud
            elif solicitud.idVentana:
                solicitud.hora_inicio_servicio = solicitud.idVentana.horaInicio
                solicitud.hora_fin_servicio = solicitud.idVentana.horaFin
                solicitud.nombre_lugar_servicio = solicitud.idVentana.nombreLugar or ""
                solicitud.latitud_servicio = solicitud.idVentana.latitud
                solicitud.longitud_servicio = solicitud.idVentana.longitud

            mensajes = list(solicitud.mensajes_chat.all())
            solicitud.total_mensajes = len(mensajes)
            solicitud.ultimo_mensaje_fecha = mensajes[-1].created_at if mensajes else None
            for mensaje in reversed(mensajes):
                if mensaje.idDe_id == solicitud.idCuidador_id and str(mensaje.mensaje or "").strip():
                    solicitud.anotacion_cuidador = str(mensaje.mensaje).strip()
                    solicitud.anotacion_cuidador_fecha = mensaje.created_at
                    break

        futuras = [
            solicitud
            for solicitud in solicitudes
            if solicitud.fecha_limite_servicio >= hoy and solicitud.estado in [EstadoSolicitud.PENDIENTE, EstadoSolicitud.ACEPTADO]
        ]
        pasadas = [
            solicitud
            for solicitud in solicitudes
            if not (
                solicitud.fecha_limite_servicio >= hoy
                and solicitud.estado in [EstadoSolicitud.PENDIENTE, EstadoSolicitud.ACEPTADO]
            )
        ]
        reservas_totales = len(futuras) + len(pasadas)
        reservas_pendientes = sum(1 for solicitud in futuras if solicitud.estado == EstadoSolicitud.PENDIENTE)
        reservas_aceptadas = sum(1 for solicitud in futuras if solicitud.estado == EstadoSolicitud.ACEPTADO)
        return {
            "solicitudes_futuras": futuras,
            "solicitudes_pasadas": pasadas,
            "reservas_totales": reservas_totales,
            "reservas_pendientes": reservas_pendientes,
            "reservas_aceptadas": reservas_aceptadas,
        }


class ProcesarAccionNuevaReservaDueñoService:
    """Orquesta búsqueda o confirmación en el formulario de nueva reserva."""

    def __init__(
        self,
        crear_reserva_service: CrearReservaDesdeSeleccionService | None = None,
        buscar_disponibilidad_service: BuscarDisponibilidadFormularioReservaService | None = None,
    ):
        self._crear_reserva_service = crear_reserva_service or CrearReservaDesdeSeleccionService()
        self._buscar_disponibilidad_service = (
            buscar_disponibilidad_service or BuscarDisponibilidadFormularioReservaService()
        )

    def procesar(self, dueño: Usuario, source) -> dict:
        action = str(source.get("action") or "buscar").strip().lower()
        if action == "confirmar":
            self._crear_reserva_service.crear(
                dueño=dueño,
                mascota_id=source.get("mascota_id"),
                evento_id=source.get("evento_id") or None,
                fecha_str=source.get("fecha", ""),
                fecha_fin_str=source.get("fecha_fin") or None,
                tipo_servicio=source.get("tipo_servicio", ""),
                modo_guarderia=source.get("modo_guarderia") or None,
                duracion_guarderia_minutos=source.get("duracion_guarderia_minutos") or None,
                hora_inicio_guarderia_str=source.get("hora_inicio_guarderia") or None,
                hora_fin_guarderia_str=source.get("hora_fin_guarderia") or None,
            )
            return {
                "modo": "redirect",
                "ruta": "dueño_mis_reservas",
            }

        cuidadores, busqueda = self._buscar_disponibilidad_service.buscar(dueño, source)
        return {
            "modo": "render_resultado",
            "cuidadores_disponibles": cuidadores,
            "busqueda": busqueda,
        }


class EnviarMensajeChatService:
    """Registra mensajes de chat y notifica al receptor de la conversación."""

    def __init__(self, notificador=None):
        self.notificador = notificador or NotificadorFactory.crear()

    def enviar(self, solicitud: SolicitudServicio, emisor: Usuario, mensaje: str) -> MensajeChat:
        texto = str(mensaje or "").strip()
        if not texto:
            raise DomainValidationError("el mensaje no puede estar vacío")

        mensaje_chat = MensajeChat.objects.create(
            idSolicitud=solicitud,
            idDe=emisor,
            mensaje=texto,
        )

        receptor = None
        if emisor.idUsuario == solicitud.idDueño_id:
            receptor = solicitud.idCuidador
        elif emisor.idUsuario == solicitud.idCuidador_id:
            receptor = solicitud.idDueño

        if receptor and receptor.idUsuario != emisor.idUsuario:
            self.notificador.enviar_mensaje_chat(
                solicitud=solicitud,
                actor=emisor,
                receptor=receptor,
                mensaje=texto,
            )

        return mensaje_chat


class NormalizarFiltrosNotificacionesService:
    """Normaliza filtros de notificaciones y selección múltiple."""

    _CATEGORIAS_VALIDAS = {
        "todas",
        CategoriaNotificacion.NEGOCIO,
        CategoriaNotificacion.SISTEMA,
    }
    _ESTADOS_VALIDOS = {"todas", "no_leidas", "leidas"}

    def normalizar(self, categoria: str | None, estado: str | None) -> tuple[str, str]:
        categoria_normalizada = str(categoria or "todas").strip().lower()
        if categoria_normalizada not in self._CATEGORIAS_VALIDAS:
            categoria_normalizada = "todas"

        estado_normalizado = str(estado or "todas").strip().lower()
        if estado_normalizado not in self._ESTADOS_VALIDOS:
            estado_normalizado = "todas"

        return categoria_normalizada, estado_normalizado

    def desde_source(self, source) -> tuple[str, str]:
        return self.normalizar(source.get("categoria"), source.get("estado"))

    @staticmethod
    def parsear_ids(raw_ids: str | None) -> list[str]:
        ids_crudos = str(raw_ids or "").strip()
        return [item.strip() for item in ids_crudos.split(",") if item.strip()]


class ListarNotificacionesUsuarioService:

    _CATEGORIAS_VALIDAS = {CategoriaNotificacion.NEGOCIO, CategoriaNotificacion.SISTEMA}
    _ESTADOS_VALIDOS = {"todas", "no_leidas", "leidas"}

    def listar(self, usuario: Usuario, categoria: str = "todas", estado: str = "todas", limite: int = 100) -> dict:
        if usuario.rol not in ("dueño", "cuidador"):
            raise DomainValidationError("el usuario no puede consultar notificaciones")

        categoria_normalizada = str(categoria or "todas").strip().lower()
        if categoria_normalizada not in self._CATEGORIAS_VALIDAS:
            categoria_normalizada = "todas"

        estado_normalizado = str(estado or "todas").strip().lower()
        if estado_normalizado not in self._ESTADOS_VALIDOS:
            estado_normalizado = "todas"

        try:
            limite_num = int(limite or 100)
        except (TypeError, ValueError):
            limite_num = 100
        limite_final = max(1, min(limite_num, 300))

        qs_base = Notificacion.objects.filter(
            idParaUsuario=usuario,
            eliminada=False,
        ).select_related("idActorUsuario", "idSolicitud", "idMascota")

        total = qs_base.count()
        total_no_leidas = qs_base.filter(leida=False).count()
        total_negocio = qs_base.filter(categoria=CategoriaNotificacion.NEGOCIO).count()
        total_sistema = qs_base.filter(categoria=CategoriaNotificacion.SISTEMA).count()

        qs_filtrado = qs_base
        if categoria_normalizada in self._CATEGORIAS_VALIDAS:
            qs_filtrado = qs_filtrado.filter(categoria=categoria_normalizada)
        if estado_normalizado == "no_leidas":
            qs_filtrado = qs_filtrado.filter(leida=False)
        elif estado_normalizado == "leidas":
            qs_filtrado = qs_filtrado.filter(leida=True)

        items = list(qs_filtrado.order_by("-created_at")[:limite_final])
        return {
            "notificaciones_items": items,
            "notificaciones_total": total,
            "notificaciones_filtradas_total": len(items),
            "notificaciones_no_leidas": total_no_leidas,
            "notificaciones_negocio_total": total_negocio,
            "notificaciones_sistema_total": total_sistema,
            "notificaciones_categoria_actual": categoria_normalizada,
            "notificaciones_estado_actual": estado_normalizado,
        }


class GestionNotificacionesUsuarioService:

    _CATEGORIAS_VALIDAS = {CategoriaNotificacion.NEGOCIO, CategoriaNotificacion.SISTEMA}
    _ESTADOS_VALIDOS = {"todas", "no_leidas", "leidas"}

    def _categoria_normalizada(self, categoria: str | None) -> str:
        categoria_normalizada = str(categoria or "todas").strip().lower()
        return categoria_normalizada if categoria_normalizada in self._CATEGORIAS_VALIDAS else "todas"

    def _estado_normalizado(self, estado: str | None) -> str:
        estado_normalizado = str(estado or "todas").strip().lower()
        return estado_normalizado if estado_normalizado in self._ESTADOS_VALIDOS else "todas"

    def _base_queryset(self, usuario: Usuario, categoria: str | None = None, estado: str | None = None):
        qs = Notificacion.objects.filter(idParaUsuario=usuario, eliminada=False)
        categoria_normalizada = self._categoria_normalizada(categoria)
        if categoria_normalizada in self._CATEGORIAS_VALIDAS:
            qs = qs.filter(categoria=categoria_normalizada)
        estado_normalizado = self._estado_normalizado(estado)
        if estado_normalizado == "no_leidas":
            qs = qs.filter(leida=False)
        elif estado_normalizado == "leidas":
            qs = qs.filter(leida=True)
        return qs

    def marcar_leida(self, usuario: Usuario, notificacion_id: str) -> Notificacion:
        if not notificacion_id:
            raise DomainValidationError("notificacion_id es requerido")
        try:
            notificacion = Notificacion.objects.get(
                idNotificacion=notificacion_id,
                idParaUsuario=usuario,
                eliminada=False,
            )
        except (Notificacion.DoesNotExist, ValidationError, ValueError, TypeError):
            raise ResourceNotFoundError("la notificación no existe")

        if not notificacion.leida:
            notificacion.leida = True
            notificacion.leidaEn = timezone.now()
            notificacion.save(update_fields=["leida", "leidaEn", "updated_at"])
        return notificacion

    def marcar_todas_leidas(self, usuario: Usuario, categoria: str | None = None) -> int:
        ahora = timezone.now()
        return self._base_queryset(usuario, categoria).filter(leida=False).update(
            leida=True,
            leidaEn=ahora,
            updated_at=ahora,
        )

    def eliminar(self, usuario: Usuario, notificacion_id: str) -> None:
        if not notificacion_id:
            raise DomainValidationError("notificacion_id es requerido")
        try:
            notificacion = Notificacion.objects.get(
                idNotificacion=notificacion_id,
                idParaUsuario=usuario,
                eliminada=False,
            )
        except (Notificacion.DoesNotExist, ValidationError, ValueError, TypeError):
            raise ResourceNotFoundError("la notificación no existe")

        notificacion.eliminada = True
        notificacion.save(update_fields=["eliminada", "updated_at"])

    def eliminar_seleccionadas(self, usuario: Usuario, notificaciones_ids: list[str]) -> int:
        ids_validos = []
        for raw in notificaciones_ids or []:
            valor = str(raw or "").strip()
            if not valor:
                continue
            try:
                ids_validos.append(UUID(valor))
            except (ValueError, TypeError, AttributeError):
                continue

        if not ids_validos:
            raise DomainValidationError("debes seleccionar al menos una notificación")

        ahora = timezone.now()
        return Notificacion.objects.filter(
            idParaUsuario=usuario,
            eliminada=False,
            idNotificacion__in=ids_validos,
        ).update(
            eliminada=True,
            updated_at=ahora,
        )

    def eliminar_todas(self, usuario: Usuario, categoria: str | None = None, estado: str | None = None) -> int:
        ahora = timezone.now()
        return self._base_queryset(usuario, categoria=categoria, estado=estado).update(
            eliminada=True,
            updated_at=ahora,
        )

    def eliminar_leidas(self, usuario: Usuario, categoria: str | None = None) -> int:
        ahora = timezone.now()
        return self._base_queryset(usuario, categoria).filter(leida=True).update(
            eliminada=True,
            updated_at=ahora,
        )


class ProcesarAccionesNotificacionesService:
    """Centraliza acciones POST de notificaciones del usuario."""

    def __init__(
        self,
        filtros_service: NormalizarFiltrosNotificacionesService | None = None,
        gestion_service: GestionNotificacionesUsuarioService | None = None,
    ):
        self._filtros_service = filtros_service or NormalizarFiltrosNotificacionesService()
        self._gestion_service = gestion_service or GestionNotificacionesUsuarioService()

    def procesar(self, usuario: Usuario, source) -> dict:
        action = source.get("action")
        categoria, estado = self._filtros_service.desde_source(source)
        ids_seleccionados = self._filtros_service.parsear_ids(source.get("notificacion_ids"))

        resultado = {
            "categoria": categoria,
            "estado": estado,
        }

        try:
            if action == "marcar_leida":
                self._gestion_service.marcar_leida(usuario, source.get("notificacion_id"))
                return resultado

            if action == "marcar_todas_leidas":
                marcadas = self._gestion_service.marcar_todas_leidas(usuario, categoria=categoria)
                return {
                    **resultado,
                    "nivel": "success",
                    "mensaje": f"Se marcaron {marcadas} notificaciones como leídas.",
                }

            if action == "eliminar":
                self._gestion_service.eliminar(usuario, source.get("notificacion_id"))
                return resultado

            if action == "eliminar_seleccionadas":
                eliminadas = self._gestion_service.eliminar_seleccionadas(usuario, ids_seleccionados)
                return {
                    **resultado,
                    "nivel": "success",
                    "mensaje": f"Se eliminaron {eliminadas} notificaciones seleccionadas.",
                }

            if action == "eliminar_todas":
                eliminadas = self._gestion_service.eliminar_todas(usuario, categoria=categoria, estado=estado)
                return {
                    **resultado,
                    "nivel": "success",
                    "mensaje": f"Se eliminaron {eliminadas} notificaciones visibles con este filtro.",
                }

            if action == "abrir":
                notificacion = self._gestion_service.marcar_leida(usuario, source.get("notificacion_id"))
                destino = str(notificacion.urlDestino or "").strip()
                if destino.startswith("/"):
                    return {
                        **resultado,
                        "destino": destino,
                    }
                return resultado
        except DomainError as error:
            return {
                **resultado,
                "nivel": "error",
                "mensaje": str(error),
            }

        return {
            **resultado,
            "nivel": "error",
            "mensaje": "Acción inválida.",
        }


def _calificacion_promedio_count(usuario_destino: Usuario) -> tuple[float | None, int]:
    """Retorna (promedio_estrellas, cantidad) para un usuario destinatario."""
    agg = Calificacion.objects.filter(idParaUsuario=usuario_destino).aggregate(
        prom=Avg("estrellas"), cnt=Count("pk")
    )
    prom = float(agg["prom"]) if agg["prom"] is not None else None
    cnt = agg["cnt"] or 0
    return (round(prom, 1) if prom is not None else None, cnt)


def _calificacion_de_autor_en_solicitud(solicitud: SolicitudServicio, autor: Usuario) -> Calificacion | None:
    for calificacion in solicitud.calificaciones.all():
        if calificacion.idDe_id == autor.idUsuario:
            return calificacion
    return None


def _calificacion_mascota_de_autor_en_solicitud(solicitud: SolicitudServicio, autor: Usuario) -> CalificacionMascota | None:
    for calificacion in solicitud.calificaciones_mascota.all():
        if calificacion.idDe_id == autor.idUsuario:
            return calificacion
    return None


def _resenas_mascotas_por_ids(mascotas_ids: list) -> dict:
    """Retorna métricas y comentarios recientes por mascota para IDs dados."""
    if not mascotas_ids:
        return {}

    agregados: dict = {}
    for row in (
        CalificacionMascota.objects.filter(
            idParaMascota_id__in=mascotas_ids,
            idDe__rol="cuidador",
        )
        .values("idParaMascota_id")
        .annotate(prom=Avg("estrellas"), cnt=Count("pk"))
    ):
        mascota_id = row["idParaMascota_id"]
        prom_raw = row.get("prom")
        agregados[mascota_id] = {
            "prom": round(float(prom_raw), 1) if prom_raw is not None else None,
            "cnt": int(row.get("cnt") or 0),
            "comentarios": [],
        }

    comentarios_por_mascota: dict = {}
    comentarios_qs = (
        CalificacionMascota.objects.filter(
            idParaMascota_id__in=mascotas_ids,
            idDe__rol="cuidador",
        )
        .exclude(comentario__isnull=True)
        .exclude(comentario="")
        .select_related("idDe", "idParaMascota")
        .order_by("-created_at", "-pk")
    )
    max_comentarios_por_mascota = 20
    for calificacion in comentarios_qs:
        mascota_id = calificacion.idParaMascota_id
        comentarios_por_mascota.setdefault(mascota_id, [])
        if len(comentarios_por_mascota[mascota_id]) >= max_comentarios_por_mascota:
            continue
        comentarios_por_mascota[mascota_id].append(
            {
                "autor": calificacion.idDe.nombre,
                "estrellas": int(calificacion.estrellas),
                "comentario": str(calificacion.comentario or "").strip(),
            }
        )

    for mascota_id in mascotas_ids:
        base = agregados.get(
            mascota_id,
            {
                "prom": None,
                "cnt": 0,
                "comentarios": [],
            },
        )
        base["comentarios"] = comentarios_por_mascota.get(mascota_id, [])
        agregados[mascota_id] = base

    return agregados


class ListarResenasRecibidasService:
    """Lista reseñas recibidas por usuario, con orden y métricas para UI."""

    _ORDENES = {
        "recientes": {
            "label": "Mas recientes",
            "ordering": ("-created_at", "-pk"),
        },
        "antiguas": {
            "label": "Mas antiguas",
            "ordering": ("created_at", "pk"),
        },
        "estrellas_desc": {
            "label": "Mayor puntaje",
            "ordering": ("-estrellas", "-created_at", "-pk"),
        },
        "estrellas_asc": {
            "label": "Menor puntaje",
            "ordering": ("estrellas", "-created_at", "-pk"),
        },
        "comentadas": {
            "label": "Con comentario primero",
            "ordering": ("-tiene_comentario", "-created_at", "-pk"),
        },
    }

    def listar(self, usuario: Usuario, orden: str = "recientes", limite: int = 100) -> dict:
        orden_normalizado = str(orden or "recientes").strip().lower()
        if orden_normalizado not in self._ORDENES:
            orden_normalizado = "recientes"

        qs_base = Calificacion.objects.filter(idParaUsuario=usuario).select_related(
            "idDe",
            "idSolicitud",
            "idSolicitud__idMascota",
        )

        qs_ordenable = qs_base.annotate(
            tiene_comentario=Case(
                When(Q(comentario__isnull=False) & ~Q(comentario=""), then=1),
                default=0,
                output_field=IntegerField(),
            )
        )

        agg = qs_base.aggregate(
            total=Count("pk"),
            promedio=Avg("estrellas"),
            con_comentario=Count("pk", filter=Q(comentario__isnull=False) & ~Q(comentario="")),
        )
        total = int(agg.get("total") or 0)
        promedio_raw = agg.get("promedio")
        promedio = round(float(promedio_raw), 1) if promedio_raw is not None else None
        con_comentario = int(agg.get("con_comentario") or 0)

        conteo_por_estrellas = {
            int(item["estrellas"]): int(item["total"])
            for item in qs_base.values("estrellas").annotate(total=Count("pk"))
        }
        distribucion = []
        for estrellas in range(5, 0, -1):
            total_estrellas = conteo_por_estrellas.get(estrellas, 0)
            porcentaje = round((total_estrellas * 100.0 / total), 1) if total > 0 else 0
            distribucion.append(
                {
                    "estrellas": estrellas,
                    "total": total_estrellas,
                    "porcentaje": porcentaje,
                }
            )

        ordering = self._ORDENES[orden_normalizado]["ordering"]
        resenas = list(qs_ordenable.order_by(*ordering)[: max(1, int(limite or 1))])

        opciones = [
            {"value": key, "label": data["label"]}
            for key, data in self._ORDENES.items()
        ]

        return {
            "resenas_items": resenas,
            "resenas_total": total,
            "resenas_promedio": promedio,
            "resenas_con_comentario": con_comentario,
            "resenas_distribucion": distribucion,
            "resenas_orden_actual": orden_normalizado,
            "resenas_orden_opciones": opciones,
        }


class CrearCalificacionService:

    def crear(self, autor: Usuario, solicitud_id: str, estrellas: int, comentario: str = "") -> Calificacion:
        if autor.rol not in ("dueño", "cuidador"):
            raise DomainValidationError("el usuario no puede calificar este servicio")

        try:
            estrellas_num = int(estrellas)
        except (ValueError, TypeError):
            raise DomainValidationError("las estrellas deben ser entre 1 y 5")

        filtros = {"idSolicitud": solicitud_id}
        if autor.rol == "dueño":
            filtros["idDueño"] = autor
        else:
            filtros["idCuidador"] = autor

        try:
            solicitud = SolicitudServicio.objects.select_related("idDueño", "idCuidador").get(**filtros)
        except SolicitudServicio.DoesNotExist:
            raise ResourceNotFoundError("la solicitud no existe o no te pertenece")

        if solicitud.estado != EstadoSolicitud.COMPLETADO:
            raise DomainValidationError("solo puedes calificar servicios finalizados")

        if Calificacion.objects.filter(idSolicitud=solicitud, idDe=autor).exists():
            raise ConflictError("ya calificaste este servicio")

        if estrellas_num < 1 or estrellas_num > 5:
            raise DomainValidationError("las estrellas deben ser entre 1 y 5")

        destinatario = solicitud.idCuidador if autor.idUsuario == solicitud.idDueño_id else solicitud.idDueño

        return Calificacion.objects.create(
            idDe=autor,
            idParaUsuario=destinatario,
            idSolicitud=solicitud,
            estrellas=estrellas_num,
            comentario=(comentario or "").strip()[:500],
        )


class CrearCalificacionMascotaService:

    def crear(self, autor: Usuario, solicitud_id: str, estrellas: int, comentario: str = "") -> CalificacionMascota:
        if autor.rol != "cuidador":
            raise DomainValidationError("solo un cuidador puede calificar mascotas")

        try:
            estrellas_num = int(estrellas)
        except (ValueError, TypeError):
            raise DomainValidationError("las estrellas deben ser entre 1 y 5")

        try:
            solicitud = SolicitudServicio.objects.select_related("idMascota").get(
                idSolicitud=solicitud_id,
                idCuidador=autor,
            )
        except SolicitudServicio.DoesNotExist:
            raise ResourceNotFoundError("la solicitud no existe o no te pertenece")

        if solicitud.estado != EstadoSolicitud.COMPLETADO:
            raise DomainValidationError("solo puedes calificar servicios finalizados")

        if CalificacionMascota.objects.filter(idSolicitud=solicitud, idDe=autor).exists():
            raise ConflictError("ya calificaste a la mascota en este servicio")

        if estrellas_num < 1 or estrellas_num > 5:
            raise DomainValidationError("las estrellas deben ser entre 1 y 5")

        return CalificacionMascota.objects.create(
            idDe=autor,
            idParaMascota=solicitud.idMascota,
            idSolicitud=solicitud,
            estrellas=estrellas_num,
            comentario=(comentario or "").strip()[:500],
        )


class ProcesarAccionesDueñoReservasService:
    """Centraliza acciones POST de reservas del dueño."""

    def __init__(
        self,
        calificacion_service: CrearCalificacionService | None = None,
        cancelar_service: CancelarSolicitudService | None = None,
        obtener_chat_service: ObtenerSolicitudParaChatService | None = None,
        enviar_chat_service: EnviarMensajeChatService | None = None,
    ):
        self._calificacion_service = calificacion_service or CrearCalificacionService()
        self._cancelar_service = cancelar_service or CancelarSolicitudService()
        self._obtener_chat_service = obtener_chat_service or ObtenerSolicitudParaChatService()
        self._enviar_chat_service = enviar_chat_service or EnviarMensajeChatService()

    def procesar(self, dueño: Usuario, source) -> dict:
        action = source.get("action")
        solicitud_id = source.get("solicitud_id")

        try:
            if action in ("calificar", "calificar_cuidador"):
                self._calificacion_service.crear(
                    dueño,
                    solicitud_id,
                    source.get("estrellas", 5),
                    source.get("comentario", ""),
                )
                return {
                    "nivel": "success",
                    "mensaje": "Calificación enviada. ¡Gracias!",
                }

            if action == "cancelar":
                self._cancelar_service.cancelar(solicitud_id, dueño)
                return {
                    "nivel": "success",
                    "mensaje": "Reserva cancelada.",
                }

            if action == "completar":
                return {
                    "nivel": "info",
                    "mensaje": "El arrendamiento debe ser finalizado por el cuidador para habilitar calificación.",
                }

            if action == "enviar_mensaje":
                mensaje = str(source.get("mensaje") or "").strip()
                if mensaje and solicitud_id:
                    solicitud = self._obtener_chat_service.obtener_para_dueño(solicitud_id, dueño)
                    self._enviar_chat_service.enviar(solicitud, dueño, mensaje)
                return {}
        except DomainError as error:
            return {
                "nivel": "error",
                "mensaje": str(error),
            }

        return {}


class ProcesarAccionesCuidadorCalendarioService:
    """Centraliza acciones POST del calendario del cuidador."""

    _ACCIONES_VALIDAS = (
        "aceptar",
        "rechazar",
        "completar",
        "finalizar",
        "finalizar_prueba",
        "cancelar",
        "enviar_mensaje",
        "calificar",
        "calificar_dueno",
        "calificar_mascota",
    )

    def __init__(
        self,
        estado_service: CambiarEstadoSolicitudService | None = None,
        completar_service: MarcarServicioCompletadoService | None = None,
        cancelar_service: CancelarSolicitudService | None = None,
        calificacion_service: CrearCalificacionService | None = None,
        calificacion_mascota_service: CrearCalificacionMascotaService | None = None,
        obtener_chat_service: ObtenerSolicitudParaChatService | None = None,
        enviar_chat_service: EnviarMensajeChatService | None = None,
    ):
        self._estado_service = estado_service or CambiarEstadoSolicitudService()
        self._completar_service = completar_service or MarcarServicioCompletadoService()
        self._cancelar_service = cancelar_service or CancelarSolicitudService()
        self._calificacion_service = calificacion_service or CrearCalificacionService()
        self._calificacion_mascota_service = calificacion_mascota_service or CrearCalificacionMascotaService()
        self._obtener_chat_service = obtener_chat_service or ObtenerSolicitudParaChatService()
        self._enviar_chat_service = enviar_chat_service or EnviarMensajeChatService()

    def procesar(self, cuidador: Usuario, source) -> dict:
        action = source.get("action")
        solicitud_id = source.get("solicitud_id")
        if not solicitud_id or action not in self._ACCIONES_VALIDAS:
            return {
                "nivel": "error",
                "mensaje": "Acción inválida.",
            }

        try:
            if action == "aceptar":
                self._estado_service.aceptar(solicitud_id, cuidador)
                return {
                    "nivel": "success",
                    "mensaje": "Solicitud aceptada correctamente.",
                }

            if action == "rechazar":
                self._estado_service.rechazar(solicitud_id, cuidador)
                return {
                    "nivel": "success",
                    "mensaje": "Solicitud rechazada.",
                }

            if action in ("completar", "finalizar"):
                self._completar_service.marcar(solicitud_id, cuidador)
                return {
                    "nivel": "success",
                    "mensaje": "Arrendamiento finalizado correctamente.",
                }

            if action == "finalizar_prueba":
                self._completar_service.marcar(solicitud_id, cuidador, forzar=True)
                return {
                    "nivel": "success",
                    "mensaje": "Arrendamiento finalizado en modo prueba.",
                }

            if action == "cancelar":
                self._cancelar_service.cancelar(solicitud_id, cuidador)
                return {
                    "nivel": "success",
                    "mensaje": "Reserva cancelada.",
                }

            if action == "enviar_mensaje":
                mensaje = str(source.get("mensaje") or "").strip()
                if mensaje:
                    solicitud = self._obtener_chat_service.obtener_para_cuidador(solicitud_id, cuidador)
                    self._enviar_chat_service.enviar(solicitud, cuidador, mensaje)
                return {}

            if action in ("calificar", "calificar_dueno"):
                self._calificacion_service.crear(
                    cuidador,
                    solicitud_id,
                    source.get("estrellas", 5),
                    source.get("comentario", ""),
                )
                return {
                    "nivel": "success",
                    "mensaje": "Reseña del dueño enviada. ¡Gracias!",
                }

            if action == "calificar_mascota":
                self._calificacion_mascota_service.crear(
                    cuidador,
                    solicitud_id,
                    source.get("estrellas", 5),
                    source.get("comentario", ""),
                )
                return {
                    "nivel": "success",
                    "mensaje": "Reseña de la mascota enviada. ¡Gracias!",
                }
        except DomainError as error:
            return {
                "nivel": "error",
                "mensaje": str(error),
            }

        return {
            "nivel": "error",
            "mensaje": "Acción inválida.",
        }


class ListarMascotasDeDueñoService:
    # lista mascotas asociadas a un dueño

    def listar(self, dueño: Usuario):
        if dueño.rol != "dueño":
            raise DomainValidationError("el usuario no tiene rol de dueño")

        mascotas = list(Mascota.objects.filter(idDueño=dueño).order_by("nombreMascota"))
        mascotas_ids = [m.idMascota for m in mascotas]

        agregados = _resenas_mascotas_por_ids(mascotas_ids)

        for mascota in mascotas:
            metrica = agregados.get(mascota.idMascota, {"prom": None, "cnt": 0, "comentarios": []})
            mascota.calificacion_promedio = metrica["prom"]
            mascota.calificacion_count = metrica["cnt"]
            mascota.calificacion_comentarios = metrica.get("comentarios", [])

        return mascotas


class ListarAgendamientosCuidadorService:
    # lista solicitudes asociadas a un cuidador

    def listar(self, cuidador: Usuario):
        if cuidador.rol != "cuidador":
            raise DomainValidationError("el usuario no tiene rol de cuidador")

        try:
            perfil = PerfilCuidador.objects.get(idCuidador=cuidador)
        except PerfilCuidador.DoesNotExist:
            raise ResourceNotFoundError("el cuidador no tiene perfil configurado")

        ahora_local = timezone.localtime()
        hoy = ahora_local.date()
        qs = SolicitudServicio.objects.filter(
            Q(idBloqueHorario__idCuidador=perfil) | Q(idVentana__idCuidador=perfil) | Q(idEvento__idCuidador=perfil),
            estado__in=[
                EstadoSolicitud.PENDIENTE,
                EstadoSolicitud.ACEPTADO,
                EstadoSolicitud.COMPLETADO,
                EstadoSolicitud.CANCELADO,
                EstadoSolicitud.RECHAZADO,
            ],
        ).select_related("idDueño", "idMascota", "idBloqueHorario", "idVentana", "idSlot", "idEvento", "idSlotEvento").prefetch_related(
            "mensajes_chat__idDe",
            "calificaciones",
            "calificaciones_mascota",
        )
        agendamientos = list(qs.order_by("fecha", "horaRecogidaAsignada", "idBloqueHorario__horaInicio"))

        _auto_finalizar_paseos_expirados(agendamientos, ahora=ahora_local)

        for solicitud in agendamientos:
            solicitud.calificacion_mia = _calificacion_de_autor_en_solicitud(solicitud, cuidador)
            solicitud.calificacion_dueño_mia = solicitud.calificacion_mia
            solicitud.calificacion_mascota_mia = _calificacion_mascota_de_autor_en_solicitud(solicitud, cuidador)
            solicitud.fecha_limite_servicio = solicitud.fechaFin or solicitud.fecha
            solicitud.puede_finalizar = _puede_finalizar_solicitud(solicitud, ahora=ahora_local)

        dueños_ids = {solicitud.idDueño_id for solicitud in agendamientos}
        agregados_dueños = {}
        if dueños_ids:
            for row in (
                Calificacion.objects.filter(idParaUsuario_id__in=dueños_ids)
                .values("idParaUsuario_id")
                .annotate(prom=Avg("estrellas"), cnt=Count("pk"))
            ):
                prom = row.get("prom")
                agregados_dueños[row["idParaUsuario_id"]] = (
                    round(float(prom), 1) if prom is not None else None,
                    int(row.get("cnt") or 0),
                )

        for solicitud in agendamientos:
            prom_dueño, cnt_dueño = agregados_dueños.get(solicitud.idDueño_id, (None, 0))
            solicitud.calificacion_dueño_promedio = prom_dueño
            solicitud.calificacion_dueño_count = cnt_dueño

        mascotas_ids = list({solicitud.idMascota_id for solicitud in agendamientos if solicitud.idMascota_id})
        resenas_por_mascota = _resenas_mascotas_por_ids(mascotas_ids)
        for solicitud in agendamientos:
            metrica_mascota = resenas_por_mascota.get(
                solicitud.idMascota_id,
                {"prom": None, "cnt": 0, "comentarios": []},
            )
            solicitud.calificacion_mascota_promedio = metrica_mascota["prom"]
            solicitud.calificacion_mascota_count = metrica_mascota["cnt"]
            solicitud.calificacion_mascota_comentarios = metrica_mascota.get("comentarios", [])

        futuros = [
            solicitud
            for solicitud in agendamientos
            if solicitud.fecha_limite_servicio >= hoy and solicitud.estado in [EstadoSolicitud.PENDIENTE, EstadoSolicitud.ACEPTADO]
        ]
        pasados = [
            solicitud
            for solicitud in agendamientos
            if solicitud.fecha_limite_servicio < hoy
            or solicitud.estado in [
                EstadoSolicitud.COMPLETADO,
                EstadoSolicitud.CANCELADO,
                EstadoSolicitud.RECHAZADO,
            ]
        ]
        pendientes = [solicitud for solicitud in futuros if solicitud.estado == EstadoSolicitud.PENDIENTE]
        futuros_aceptados = [solicitud for solicitud in futuros if solicitud.estado == EstadoSolicitud.ACEPTADO]
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

    def __init__(self, notificador=None):
        self.notificador = notificador or NotificadorFactory.crear()

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
        validos = {TipoServicio.PASEO, TipoServicio.GUARDERIA}
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

        tipos_mascota = str(datos.get("tiposMascotaPreferidos") or "").strip().lower()
        if tipos_mascota in ("perro", "gato", "ambos") or "," in tipos_mascota:
            perfil.tiposMascotaPreferidos = tipos_mascota if tipos_mascota else "ambos"
        elif tipos_mascota:
            validos = ["perro", "gato"]
            parts = [p.strip() for p in tipos_mascota.split(",") if p.strip() in validos]
            perfil.tiposMascotaPreferidos = ",".join(sorted(set(parts))) if parts else "ambos"

        ciudad_servicio = datos.get("ciudadServicio")
        if ciudad_servicio is not None:
            ciudad_servicio = str(ciudad_servicio).strip()
            if len(ciudad_servicio) > 100:
                raise DomainValidationError("la ciudad operativa no puede superar 100 caracteres")
            perfil.ciudadServicio = ciudad_servicio

        lat_servicio = datos.get("latitudServicio")
        if lat_servicio is not None:
            lat_raw = str(lat_servicio).strip()
            if lat_raw == "":
                perfil.latitudServicio = None
            else:
                try:
                    perfil.latitudServicio = Decimal(lat_raw)
                except Exception:
                    raise DomainValidationError("latitud operativa inválida")

        lng_servicio = datos.get("longitudServicio")
        if lng_servicio is not None:
            lng_raw = str(lng_servicio).strip()
            if lng_raw == "":
                perfil.longitudServicio = None
            else:
                try:
                    perfil.longitudServicio = Decimal(lng_raw)
                except Exception:
                    raise DomainValidationError("longitud operativa inválida")

        radio_servicio = datos.get("radioKmServicio")
        if radio_servicio is not None:
            radio_raw = str(radio_servicio).strip()
            if radio_raw:
                try:
                    radio_val = Decimal(radio_raw)
                except Exception:
                    raise DomainValidationError("el radio operativo debe ser numérico")
                if radio_val < 1 or radio_val > 3:
                    raise DomainValidationError("el radio operativo debe estar entre 1 y 3 km")
                perfil.radioKmServicio = radio_val

        perfil.save()
        self.notificador.enviar_perfil_actualizado(cuidador)
        return perfil


class EditarPerfilUsuarioService:

    _CAMPOS_NO_EDITABLES = {"username", "rol"}

    def __init__(self, notificador=None):
        self.notificador = notificador or NotificadorFactory.crear()

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

        cedula = datos.get("cedula")
        if cedula:
            cedula = str(cedula).strip()
            if len(cedula) > 20:
                raise DomainValidationError("la cédula no puede superar 20 caracteres")
            if Usuario.objects.filter(cedula=cedula).exclude(idUsuario=usuario.idUsuario).exists():
                raise DomainValidationError("la cédula ya está registrada")
            usuario.cedula = cedula

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

        direccion = datos.get("direccion")
        if direccion is not None:
            direccion = str(direccion).strip()
            if len(direccion) > 200:
                raise DomainValidationError("la dirección no puede superar 200 caracteres")
            usuario.direccion = direccion

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
                if r < 1 or r > 3:
                    raise DomainValidationError("el radio debe estar entre 1 y 3 km")
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

        experiencia = datos.get("experiencia")

        with transaction.atomic():
            usuario.save()
            if usuario.rol == "cuidador" and experiencia is not None:
                perfil, _ = PerfilCuidador.objects.get_or_create(idCuidador=usuario)
                perfil.descripcion = str(experiencia).strip()
                perfil.save(update_fields=["descripcion"])

        self.notificador.enviar_perfil_actualizado(usuario)
        return usuario


class AgregarMascotaService:

    def __init__(self, notificador=None):
        self.notificador = notificador or NotificadorFactory.crear()

    def agregar(self, dueño: Usuario, datos: dict) -> Mascota:
        if dueño.rol != "dueño":
            raise DomainValidationError("el usuario no tiene rol de dueño")

        nombre_mascota = str(datos.get("nombreMascota") or "").strip()
        tipo = str(datos.get("tipo") or "").strip()
        raza = str(datos.get("raza") or "").strip()
        sexo = (datos.get("sexo") or "").strip().lower()
        tamano = (datos.get("tamano") or "").strip().lower()
        notas = str(datos.get("notas") or "").strip()
        condiciones_medicas = (datos.get("condicionesMedicas") or "").strip()
        esterilizado_raw = (datos.get("esterilizado") or "").strip().lower()
        vacunas_raw = (datos.get("vacunasAlDia") or "").strip().lower()

        if not nombre_mascota:
            raise DomainValidationError("el nombre de la mascota es requerido")
        if not tipo:
            raise DomainValidationError("el tipo de mascota es requerido")
        if not raza:
            raise DomainValidationError("la raza de la mascota es requerida")
        if not sexo:
            raise DomainValidationError("el sexo de la mascota es requerido")
        if not tamano:
            raise DomainValidationError("el tamaño de la mascota es requerido")
        if not condiciones_medicas:
            raise DomainValidationError("las condiciones médicas son requeridas")
        if not notas:
            raise DomainValidationError("las notas de comportamiento son requeridas")

        foto = datos.get("foto")
        if not foto:
            raise DomainValidationError("la foto de la mascota es requerida")

        opciones_tipo = [c[0] for c in TipoMascota.choices]
        if tipo not in opciones_tipo:
            raise DomainValidationError(f"tipo de mascota inválido: {tipo}")

        if sexo not in {"macho", "hembra"}:
            raise DomainValidationError("el sexo de la mascota es inválido")
        if tamano not in {"pequeno", "mediano", "grande"}:
            raise DomainValidationError("el tamaño de la mascota es inválido")
        if len(raza) > 100:
            raise DomainValidationError("la raza no puede superar 100 caracteres")
        if len(condiciones_medicas) > 500:
            raise DomainValidationError("las condiciones médicas no pueden superar 500 caracteres")

        opciones_si = {"si", "sí", "true", "1", "on"}
        opciones_no = {"no", "false", "0", "off"}

        if not esterilizado_raw:
            raise DomainValidationError("debes indicar si la mascota está esterilizada")
        if not vacunas_raw:
            raise DomainValidationError("debes indicar si la mascota tiene vacunas al día")

        if esterilizado_raw not in opciones_si | opciones_no:
            raise DomainValidationError("la opción de esterilizado es inválida")
        if vacunas_raw not in opciones_si | opciones_no:
            raise DomainValidationError("la opción de vacunas al día es inválida")

        esterilizado = esterilizado_raw in opciones_si
        vacunas_al_dia = vacunas_raw in opciones_si

        try:
            edad = int(datos.get("edad", 0))
        except (ValueError, TypeError):
            raise DomainValidationError("la edad debe ser un número entero")
        if edad < 0:
            raise DomainValidationError("la edad no puede ser negativa")

        peso = str(datos.get("peso") or "").strip()
        if not peso:
            raise DomainValidationError("el peso de la mascota es requerido")
        try:
            peso_val = float(peso)
        except (ValueError, TypeError):
            raise DomainValidationError("el peso debe ser un número")
        if peso_val < 0:
            raise DomainValidationError("el peso no puede ser negativo")

        mascota = Mascota.objects.create(
            idDueño=dueño,
            nombreMascota=nombre_mascota,
            tipo=tipo,
            raza=raza,
            sexo=sexo,
            tamano=tamano,
            edad=edad,
            peso=peso_val,
            esterilizado=esterilizado,
            vacunasAlDia=vacunas_al_dia,
            condicionesMedicas=condiciones_medicas,
            notas=notas,
            foto=foto if foto else None,
        )
        self.notificador.enviar_mascota_creada(mascota, actor=dueño)
        return mascota


class EditarMascotaService:

    def __init__(self, notificador=None):
        self.notificador = notificador or NotificadorFactory.crear()

    def editar(self, dueño: Usuario, mascota_id: str, datos: dict) -> Mascota:
        if dueño.rol != "dueño":
            raise DomainValidationError("el usuario no tiene rol de dueño")

        try:
            mascota = Mascota.objects.get(idMascota=mascota_id, idDueño=dueño)
        except Mascota.DoesNotExist:
            raise ResourceNotFoundError("mascota no encontrada")

        nombre_mascota = str(datos.get("nombreMascota") or "").strip()
        tipo = str(datos.get("tipo") or "").strip()
        raza = str(datos.get("raza") or "").strip()
        sexo = (datos.get("sexo") or "").strip().lower()
        tamano = (datos.get("tamano") or "").strip().lower()
        notas = str(datos.get("notas") or "").strip()
        condiciones_medicas = (datos.get("condicionesMedicas") or "").strip()
        esterilizado_raw = (datos.get("esterilizado") or "").strip().lower()
        vacunas_raw = (datos.get("vacunasAlDia") or "").strip().lower()

        if not nombre_mascota:
            raise DomainValidationError("el nombre de la mascota es requerido")
        if not tipo:
            raise DomainValidationError("el tipo de mascota es requerido")

        opciones_tipo = [c[0] for c in TipoMascota.choices]
        if tipo not in opciones_tipo:
            raise DomainValidationError(f"tipo de mascota inválido: {tipo}")

        if sexo and sexo not in {"macho", "hembra"}:
            raise DomainValidationError("el sexo de la mascota es inválido")
        if tamano and tamano not in {"pequeno", "mediano", "grande"}:
            raise DomainValidationError("el tamaño de la mascota es inválido")
        if len(raza) > 100:
            raise DomainValidationError("la raza no puede superar 100 caracteres")
        if len(condiciones_medicas) > 500:
            raise DomainValidationError("las condiciones médicas no pueden superar 500 caracteres")

        esterilizado = esterilizado_raw in {"si", "sí", "true", "1", "on"}
        vacunas_al_dia = vacunas_raw in {"si", "sí", "true", "1", "on"}

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

        mascota.nombreMascota = nombre_mascota
        mascota.tipo = tipo
        mascota.raza = raza
        mascota.sexo = sexo
        mascota.tamano = tamano
        mascota.edad = edad
        mascota.peso = peso_val
        mascota.esterilizado = esterilizado
        mascota.vacunasAlDia = vacunas_al_dia
        mascota.condicionesMedicas = condiciones_medicas
        mascota.notas = notas
        mascota.save(
            update_fields=[
                "nombreMascota",
                "tipo",
                "raza",
                "sexo",
                "tamano",
                "edad",
                "peso",
                "esterilizado",
                "vacunasAlDia",
                "condicionesMedicas",
                "notas",
            ]
        )
        self.notificador.enviar_mascota_editada(mascota, actor=dueño)
        return mascota


class EliminarMascotaService:

    def __init__(self, notificador=None):
        self.notificador = notificador or NotificadorFactory.crear()

    def eliminar(self, dueño: Usuario, mascota_id: str):
        if dueño.rol != "dueño":
            raise DomainValidationError("el usuario no tiene rol de dueño")
        try:
            mascota = Mascota.objects.get(idMascota=mascota_id, idDueño=dueño)
        except Mascota.DoesNotExist:
            raise ResourceNotFoundError("mascota no encontrada")
        nombre_mascota = mascota.nombreMascota
        mascota.delete()
        self.notificador.enviar_mascota_eliminada(nombre_mascota, dueño, actor=dueño)


class ActualizarFotoMascotaService:

    def __init__(self, notificador=None):
        self.notificador = notificador or NotificadorFactory.crear()

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
        self.notificador.enviar_mascota_editada(mascota, actor=dueño)
        return mascota


class ConstruirDatosMascotaFormularioService:
    """Construye payload de mascota desde formulario web."""

    @staticmethod
    def construir(source, files=None, incluir_foto: bool = False) -> dict:
        datos = {
            "nombreMascota": source.get("nombreMascota"),
            "tipo": source.get("tipo"),
            "raza": source.get("raza", ""),
            "sexo": source.get("sexo", ""),
            "tamano": source.get("tamano", ""),
            "edad": source.get("edad"),
            "peso": source.get("peso"),
            "esterilizado": source.get("esterilizado", ""),
            "vacunasAlDia": source.get("vacunasAlDia", ""),
            "condicionesMedicas": source.get("condicionesMedicas", ""),
            "notas": source.get("notas", ""),
        }
        if incluir_foto:
            datos["foto"] = files.get("foto") if files is not None else None
        return datos


class ProcesarAccionesDueñoMascotasService:
    """Centraliza acciones POST del módulo de mascotas del dueño."""

    def __init__(
        self,
        eliminar_service: EliminarMascotaService | None = None,
        foto_service: ActualizarFotoMascotaService | None = None,
        editar_service: EditarMascotaService | None = None,
        agregar_service: AgregarMascotaService | None = None,
        datos_service: ConstruirDatosMascotaFormularioService | None = None,
    ):
        self._eliminar_service = eliminar_service or EliminarMascotaService()
        self._foto_service = foto_service or ActualizarFotoMascotaService()
        self._editar_service = editar_service or EditarMascotaService()
        self._agregar_service = agregar_service or AgregarMascotaService()
        self._datos_service = datos_service or ConstruirDatosMascotaFormularioService()

    def procesar(self, dueño: Usuario, action: str | None, source, files) -> dict:
        action_norm = str(action or "").strip()
        try:
            if action_norm == "eliminar":
                self._eliminar_service.eliminar(dueño, source.get("mascota_id"))
                return {"ok": True}

            if action_norm == "cambiar_foto":
                self._foto_service.actualizar(dueño, source.get("mascota_id"), files.get("foto"))
                return {"ok": True}

            if action_norm == "editar":
                datos = self._datos_service.construir(source)
                self._editar_service.editar(dueño, source.get("mascota_id"), datos)
                return {"ok": True}

            datos = self._datos_service.construir(source, files=files, incluir_foto=True)
            self._agregar_service.agregar(dueño, datos)
            return {"ok": True}
        except DomainError as error:
            return {
                "ok": False,
                "error": str(error),
            }


class AgregarBloqueTiempoService:

    def agregar(self, cuidador: Usuario, datos: dict) -> BloqueTiempo:
        if cuidador.rol != "cuidador":
            raise DomainValidationError("el usuario no tiene rol de cuidador")

        perfil, _ = PerfilCuidador.objects.get_or_create(
            idCuidador=cuidador,
        )

        dia = str(datos.get("diaSemana") or "").strip()
        hora_inicio_str = str(datos.get("horaInicio") or "").strip()
        hora_fin_str = str(datos.get("horaFin") or "").strip()

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

        tipo = str(datos.get("tipoServicio") or "").strip()
        validos = {TipoServicio.PASEO, TipoServicio.GUARDERIA}
        if tipo not in validos:
            raise DomainValidationError("tipo de servicio inválido para el bloque")

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


def _dias_semana_en_rango(dia_inicio: str, dia_fin: str) -> list[str]:
    orden = [c[0] for c in DiaSemana.choices]
    if dia_inicio not in orden or dia_fin not in orden:
        raise DomainValidationError("día inválido para rango semanal")

    idx_inicio = orden.index(dia_inicio)
    idx_fin = orden.index(dia_fin)
    if idx_inicio <= idx_fin:
        return orden[idx_inicio:idx_fin + 1]
    return orden[idx_inicio:] + orden[:idx_fin + 1]


class AgregarEventosRapidoService:
    """Agrega múltiples eventos a la vez según un preset (todos, fines_semana, entre_semana)."""

    def agregar(self, cuidador: Usuario, datos: dict) -> int:
        preset = str(datos.get("preset") or "").strip()
        if preset not in PRESET_DIAS:
            raise DomainValidationError("preset inválido")
        dias = PRESET_DIAS[preset]
        tipo = str(datos.get("tipoServicio") or "").strip()
        hora_inicio_str = str(datos.get("horaInicio") or "").strip()
        hora_fin_str = str(datos.get("horaFin") or "").strip()
        duracion_str = str(datos.get("duracionMinutos") or "").strip()
        if not tipo or not hora_inicio_str:
            raise DomainValidationError("tipo y hora inicio son requeridos")
        validos = {TipoServicio.PASEO, TipoServicio.GUARDERIA}
        if tipo not in validos:
            raise DomainValidationError("tipo de servicio inválido")
        perfil, _ = PerfilCuidador.objects.get_or_create(idCuidador=cuidador)
        try:
            pi = hora_inicio_str.split(":")
            hora_inicio = time(int(pi[0]), int(pi[1]))
        except (ValueError, IndexError):
            raise DomainValidationError("formato de hora inválido (HH:MM)")

        if hora_fin_str:
            try:
                pf = hora_fin_str.split(":")
                hora_fin = time(int(pf[0]), int(pf[1]))
            except (ValueError, IndexError):
                raise DomainValidationError("formato de hora inválido (HH:MM)")
        else:
            if not duracion_str:
                raise DomainValidationError("la duración es requerida")
            try:
                duracion_minutos = int(duracion_str)
            except (ValueError, TypeError):
                raise DomainValidationError("la duración debe ser un número entero en minutos")
            if duracion_minutos <= 0:
                raise DomainValidationError("la duración debe ser mayor a 0")
            fin_minutos = _time_to_minutes(hora_inicio) + duracion_minutos
            if fin_minutos > 24 * 60:
                raise DomainValidationError("la duración supera el final del día")
            hora_fin = _minutes_to_time(fin_minutos)

        if hora_fin <= hora_inicio:
            raise DomainValidationError("la hora fin debe ser posterior a la hora inicio")

        duracion_total = _time_to_minutes(hora_fin) - _time_to_minutes(hora_inicio)
        if tipo == TipoServicio.PASEO and duracion_total not in PASEO_DURACIONES_MINUTOS:
            raise DomainValidationError("en paseo la duración debe ser de 1h, 1.5h, 2h, 2.5h o 3h")
        if tipo == TipoServicio.GUARDERIA and duracion_total < 60:
            raise DomainValidationError("en guardería la duración mínima por bloque es 1 hora")

        capacidad = datos.get("capacidadMaxima")
        if tipo == TipoServicio.PASEO:
            capacidad_raw = str(capacidad).strip() if capacidad is not None else ""
            if not capacidad_raw:
                capacidad_val = 4
            else:
                try:
                    capacidad_val = int(capacidad_raw)
                except (ValueError, TypeError):
                    raise DomainValidationError("capacidadMaxima para Paseo debe ser un entero")
            if capacidad_val < 1 or capacidad_val > 4:
                raise DomainValidationError("capacidadMaxima para Paseo debe estar entre 1 y 4 perros")
        else:
            capacidad_raw = str(capacidad).strip() if capacidad is not None else ""
            if not capacidad_raw:
                capacidad_val = 1
            else:
                try:
                    capacidad_val = int(capacidad_raw)
                except (ValueError, TypeError):
                    raise DomainValidationError("capacidadMaxima para Guardería debe ser un entero")
            if capacidad_val < 1 or capacidad_val > 5:
                raise DomainValidationError("capacidadMaxima para Guardería debe estar entre 1 y 5 mascotas")

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
                capacidadMaxima=capacidad_val,
                duracionSlotMinutos=None,
                disponible=True,
            )
            creados += 1
        return creados


class AgregarEventosGuarderiaRangoService:
    """Agrega bloques de guardería para un rango de días de semana (inicio-fin)."""

    def agregar(self, cuidador: Usuario, datos: dict) -> int:
        tipo = str(datos.get("tipoServicio") or "").strip()
        if tipo != TipoServicio.GUARDERIA:
            raise DomainValidationError("este flujo solo aplica para guardería")

        dia_inicio = str(datos.get("diaSemana") or "").strip()
        dia_fin = str(datos.get("diaSemanaFin") or "").strip() or dia_inicio
        if not dia_inicio:
            raise DomainValidationError("debes indicar el día inicial")

        dias = _dias_semana_en_rango(dia_inicio, dia_fin)
        creados = 0
        servicio_evento = AgregarEventoService()

        for dia in dias:
            datos_dia = dict(datos)
            datos_dia["diaSemana"] = dia
            datos_dia.pop("diaSemanaFin", None)
            try:
                servicio_evento.agregar(cuidador, datos_dia)
                creados += 1
            except ConflictError:
                # Si el bloque ya existe para ese día, continuamos con el resto.
                continue

        return creados


class ParsearBloquesPendientesService:
    """Valida y normaliza el payload JSON de bloques pendientes del cuidador."""

    def parsear(self, raw_payload: str | None) -> list[dict]:
        payload = (raw_payload or "").strip()
        if not payload:
            return []
        try:
            data = json.loads(payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            raise DomainValidationError("el formato de bloques pendientes es inválido")

        if not isinstance(data, list):
            raise DomainValidationError("los bloques pendientes deben enviarse como lista")

        bloques: list[dict] = []
        tipos_validos = {TipoServicio.PASEO, TipoServicio.GUARDERIA}
        for item in data:
            if not isinstance(item, dict):
                raise DomainValidationError("un bloque pendiente tiene formato inválido")
            tipo = str(item.get("tipoServicio") or "").strip()
            if tipo not in tipos_validos:
                raise DomainValidationError("tipo de servicio inválido en bloques pendientes")
            bloques.append(item)

        return bloques


class ConstruirDatosPerfilCuidadorFormularioService:
    """Compone datos de configuración de servicios del cuidador desde formulario."""

    @staticmethod
    def _servicios_desde_source(source) -> list[str]:
        if hasattr(source, "getlist"):
            servicios_post = source.getlist("servicios")
        else:
            raw = source.get("servicios")
            if isinstance(raw, list):
                servicios_post = raw
            elif raw is None:
                servicios_post = []
            else:
                servicios_post = [raw]
        return list(dict.fromkeys(servicios_post))

    def construir(self, source, perfil_actual: PerfilCuidador | None, editar_tipo: str | None) -> dict:
        tipos_pref = (perfil_actual.tiposMascotaPreferidos if perfil_actual else "perro")
        if editar_tipo == "guarderia":
            seleccionado = (source.get("tipoMascotaGuarderia") or "").strip().lower()
            tipos_pref = seleccionado if seleccionado in ("perro", "gato") else "perro"

        return {
            "servicios": self._servicios_desde_source(source),
            "tiposMascotaPreferidos": tipos_pref,
            "descripciones": {
                TipoServicio.PASEO: source.get("descripcionPaseo", ""),
                TipoServicio.GUARDERIA: source.get("descripcionGuarderia", ""),
            },
            "tarifas": {
                TipoServicio.PASEO: source.get("tarifaPaseo"),
                TipoServicio.GUARDERIA: source.get("tarifaGuarderia"),
            },
            "ciudadServicio": source.get("ciudad"),
            "latitudServicio": source.get("latitud"),
            "longitudServicio": source.get("longitud"),
            "radioKmServicio": source.get("radioKm"),
        }


class ProcesarAgregarEventoCuidadorService:
    """Define la estrategia de creación de eventos para el cuidador."""

    def __init__(
        self,
        agregar_evento=None,
        agregar_rapido=None,
        agregar_guarderia_rango=None,
    ):
        self._agregar_evento = agregar_evento or AgregarEventoService()
        self._agregar_rapido = agregar_rapido or AgregarEventosRapidoService()
        self._agregar_guarderia_rango = (
            agregar_guarderia_rango or AgregarEventosGuarderiaRangoService()
        )

    def procesar(self, cuidador: Usuario, datos: dict) -> dict:
        preset = str(datos.get("preset") or "").strip()
        if preset:
            creados = self._agregar_rapido.agregar(cuidador, datos)
            return {
                "modo": "preset",
                "creados": creados,
            }

        if (
            str(datos.get("tipoServicio") or "").strip() == TipoServicio.GUARDERIA
            and str(datos.get("diaSemanaFin") or "").strip()
        ):
            creados = self._agregar_guarderia_rango.agregar(cuidador, datos)
            return {
                "modo": "guarderia_rango",
                "creados": creados,
            }

        self._agregar_evento.agregar(cuidador, datos)
        return {
            "modo": "evento",
            "creados": 1,
        }


class GuardarBloquesPendientesService:
    """Persiste bloques pendientes delegando en los servicios de creación existentes."""

    def __init__(self, agregar_evento=None, agregar_rapido=None, agregar_guarderia_rango=None):
        self._agregar_evento = agregar_evento or AgregarEventoService()
        self._agregar_rapido = agregar_rapido or AgregarEventosRapidoService()
        self._agregar_guarderia_rango = (
            agregar_guarderia_rango or AgregarEventosGuarderiaRangoService()
        )

    def guardar(self, cuidador: Usuario, bloques_pendientes: list[dict]) -> int:
        creados_total = 0

        for bloque in bloques_pendientes:
            datos = {
                "tipoServicio": bloque.get("tipoServicio"),
                "diaSemana": bloque.get("diaSemana"),
                "diaSemanaFin": bloque.get("diaSemanaFin"),
                "horaInicio": bloque.get("horaInicio"),
                "horaFin": bloque.get("horaFin"),
                "duracionMinutos": bloque.get("duracionMinutos"),
                "capacidadMaxima": bloque.get("capacidadMaxima"),
                "nombreLugar": bloque.get("nombreLugar"),
                "latitud": bloque.get("latitud"),
                "longitud": bloque.get("longitud"),
                "precioCOP": bloque.get("precioCOP"),
            }

            preset = str(bloque.get("preset") or "").strip()
            if preset:
                datos["preset"] = preset
                creados_total += self._agregar_rapido.agregar(cuidador, datos)
                continue

            if (
                str(datos.get("tipoServicio") or "").strip() == TipoServicio.GUARDERIA
                and str(datos.get("diaSemanaFin") or "").strip()
            ):
                creados_total += self._agregar_guarderia_rango.agregar(cuidador, datos)
                continue

            self._agregar_evento.agregar(cuidador, datos)
            creados_total += 1

        return creados_total


class ProcesarBloquesPendientesService:
    """Orquesta parseo + persistencia de bloques pendientes."""

    def __init__(self, parser=None, saver=None):
        self._parser = parser or ParsearBloquesPendientesService()
        self._saver = saver or GuardarBloquesPendientesService()

    def procesar(self, cuidador: Usuario, raw_payload: str | None) -> int:
        bloques = self._parser.parsear(raw_payload)
        return self._saver.guardar(cuidador, bloques)


class GuardarConfiguracionServiciosCuidadorService:
    """Encapsula la unidad de trabajo de configuración + bloques pendientes."""

    def __init__(
        self,
        actualizar_perfil_service: ActualizarPerfilCuidadorService | None = None,
        bloques_service: ProcesarBloquesPendientesService | None = None,
    ):
        self._actualizar_perfil_service = actualizar_perfil_service or ActualizarPerfilCuidadorService()
        self._bloques_service = bloques_service or ProcesarBloquesPendientesService()

    def guardar(self, cuidador: Usuario, datos_perfil: dict, bloques_pendientes_raw: str | None) -> int:
        with transaction.atomic():
            self._actualizar_perfil_service.actualizar(cuidador, datos_perfil)
            return self._bloques_service.procesar(cuidador, bloques_pendientes_raw)


class ProcesarAccionesCuidadorServiciosService:
    """Centraliza acciones POST de configuración de servicios del cuidador."""

    _TIPOS_EDITABLES = ("paseo", "guarderia")

    def __init__(
        self,
        construir_datos_service: ConstruirDatosPerfilCuidadorFormularioService | None = None,
        guardar_config_service: GuardarConfiguracionServiciosCuidadorService | None = None,
        eliminar_servicio_service: EliminarServicioCuidadorService | None = None,
        obtener_tipo_evento_service: ObtenerTipoServicioEventoService | None = None,
        eliminar_evento_service: EliminarEventoService | None = None,
        agregar_evento_service: ProcesarAgregarEventoCuidadorService | None = None,
    ):
        self._construir_datos_service = construir_datos_service or ConstruirDatosPerfilCuidadorFormularioService()
        self._guardar_config_service = guardar_config_service or GuardarConfiguracionServiciosCuidadorService()
        self._eliminar_servicio_service = eliminar_servicio_service or EliminarServicioCuidadorService()
        self._obtener_tipo_evento_service = obtener_tipo_evento_service or ObtenerTipoServicioEventoService()
        self._eliminar_evento_service = eliminar_evento_service or EliminarEventoService()
        self._agregar_evento_service = agregar_evento_service or ProcesarAgregarEventoCuidadorService()

    def procesar(self, cuidador: Usuario, source, perfil_actual: PerfilCuidador | None = None) -> dict:
        action = source.get("action")

        if action == "servicio":
            editar_tipo = str(source.get("editar_tipo") or "").strip()
            if editar_tipo not in self._TIPOS_EDITABLES:
                editar_tipo = None

            datos = self._construir_datos_service.construir(source, perfil_actual, editar_tipo)
            try:
                total_bloques_creados = self._guardar_config_service.guardar(
                    cuidador,
                    datos,
                    source.get("bloquesPendientes"),
                )
            except DomainError as error:
                return {
                    "modo": "render_error",
                    "error": str(error),
                    "editar_tipo": editar_tipo,
                }

            if total_bloques_creados:
                mensaje = (
                    f"Configuración guardada y {total_bloques_creados} bloque(s) creados correctamente."
                )
            else:
                mensaje = "Configuración guardada correctamente."
            return {
                "modo": "redirect",
                "ruta": "cuidador_servicios",
                "nivel": "success",
                "mensaje": mensaje,
            }

        if action == "eliminar_servicio":
            tipo = str(source.get("tipoServicio") or "").strip()
            try:
                resultado = self._eliminar_servicio_service.eliminar(cuidador, tipo)
            except DomainError as error:
                return {
                    "modo": "redirect",
                    "ruta": "cuidador_servicios",
                    "nivel": "error",
                    "mensaje": str(error),
                }

            mensaje = "Servicio eliminado correctamente."
            if resultado.get("eventos_historicos"):
                mensaje = (
                    "Servicio eliminado. Los eventos con historial fueron desactivados para conservar trazabilidad."
                )
            return {
                "modo": "redirect",
                "ruta": "cuidador_servicios",
                "nivel": "success",
                "mensaje": mensaje,
            }

        if action == "eliminar_evento":
            editar_tipo = str(source.get("editar_tipo") or "").strip()
            if editar_tipo not in self._TIPOS_EDITABLES:
                evento_tipo = self._obtener_tipo_evento_service.obtener(cuidador, source.get("evento_id"))
                if evento_tipo in (TipoServicio.PASEO, TipoServicio.GUARDERIA):
                    editar_tipo = evento_tipo
                else:
                    editar_tipo = None

            try:
                self._eliminar_evento_service.eliminar(cuidador, source.get("evento_id"))
            except DomainError as error:
                return {
                    "modo": "render_error",
                    "error": str(error),
                    "editar_tipo": editar_tipo,
                }

            return {
                "modo": "redirect",
                "ruta": "cuidador_servicios",
                "editar_tipo": editar_tipo,
                "nivel": "success",
                "mensaje": "Evento eliminado.",
            }

        if action == "agregar":
            editar_tipo = str(source.get("editar_tipo") or source.get("tipoServicio") or "").strip()
            if editar_tipo not in self._TIPOS_EDITABLES:
                editar_tipo = None

            datos = {
                "tipoServicio": source.get("tipoServicio"),
                "diaSemana": source.get("diaSemana"),
                "diaSemanaFin": source.get("diaSemanaFin"),
                "horaInicio": source.get("horaInicio"),
                "horaFin": source.get("horaFin"),
                "duracionMinutos": source.get("duracionMinutos"),
                "capacidadMaxima": source.get("capacidadMaxima"),
                "nombreLugar": source.get("nombreLugar"),
                "latitud": source.get("latitud"),
                "longitud": source.get("longitud"),
                "precioCOP": source.get("precioCOP"),
            }
            preset = str(source.get("preset") or "").strip()
            if preset:
                datos["preset"] = preset

            try:
                resultado = self._agregar_evento_service.procesar(cuidador, datos)
            except DomainError as error:
                return {
                    "modo": "render_error",
                    "error": str(error),
                    "editar_tipo": editar_tipo,
                }

            if resultado.get("modo") == "preset":
                creados = resultado.get("creados") or 0
                if creados:
                    nivel = "success"
                    mensaje = f"Se agregaron {creados} bloques correctamente."
                else:
                    nivel = "info"
                    mensaje = "No se agregaron bloques nuevos porque ya existían."
            elif resultado.get("modo") == "guarderia_rango":
                creados = resultado.get("creados") or 0
                if creados:
                    nivel = "success"
                    mensaje = f"Se agregaron {creados} bloque(s) de guardería."
                else:
                    nivel = "info"
                    mensaje = "No se agregaron bloques porque ya existían para ese rango."
            else:
                nivel = "success"
                mensaje = "Evento agregado correctamente."

            return {
                "modo": "redirect",
                "ruta": "cuidador_servicios",
                "editar_tipo": editar_tipo,
                "nivel": nivel,
                "mensaje": mensaje,
            }

        return {
            "modo": "redirect",
            "ruta": "cuidador_servicios",
        }


class AgregarBloquesRapidoService:
    """Agrega múltiples bloques a la vez según un preset (legacy)."""

    def agregar(self, cuidador: Usuario, datos: dict) -> int:
        preset = str(datos.get("preset") or "").strip()
        if preset not in PRESET_DIAS:
            raise DomainValidationError("preset inválido")
        dias = PRESET_DIAS[preset]
        tipo = str(datos.get("tipoServicio") or "").strip()
        hora_inicio_str = str(datos.get("horaInicio") or "").strip()
        hora_fin_str = str(datos.get("horaFin") or "").strip()
        if not tipo or not hora_inicio_str or not hora_fin_str:
            raise DomainValidationError("tipo, hora inicio y hora fin son requeridos")
        validos = {TipoServicio.PASEO, TipoServicio.GUARDERIA}
        if tipo not in validos:
            raise DomainValidationError("tipo de servicio inválido")
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
