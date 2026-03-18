from __future__ import annotations

import json
import logging
from datetime import datetime

from servicios.domain.exceptions import (
    ConflictError,
    DomainValidationError,
    ResourceNotFoundError,
)
from servicios.models import (
    BloqueTiempo,
    Evento,
    Mascota,
    PerfilCuidador,
    SolicitudServicio,
    TipoServicio,
    Usuario,
    VentanaDisponibilidad,
)
from servicios.services import (
    BuscarCuidadoresDisponiblesService,
    CancelarSolicitudService,
    ContarSlotsDisponiblesService,
    CrearSolicitudConAsignacionEventoService,
    CrearSolicitudConAsignacionService,
    FiltrarResultadosDisponibilidadService,
    ObtenerSolicitudServicioService,
    SolicitudServicioService,
)


class ValidarCrearSolicitudApiService:
    """Valida reglas de negocio de creacion de solicitud para capa API."""

    def validar(self, attrs: dict) -> dict:
        tipo_servicio = attrs.get("tipoServicio")
        fecha = attrs.get("fecha")
        fecha_fin = attrs.get("fechaFin")

        if tipo_servicio == TipoServicio.PASEO and fecha_fin is not None and fecha_fin != fecha:
            raise DomainValidationError(
                {"fechaFin": "para paseo la fecha fin debe coincidir con la fecha seleccionada"}
            )

        if tipo_servicio == TipoServicio.GUARDERIA and fecha_fin is not None and fecha_fin < fecha:
            raise DomainValidationError(
                {"fechaFin": "la fecha fin debe ser igual o posterior a la fecha"}
            )

        duracion = attrs.get("duracionMinutosSolicitados")
        if duracion is not None and (duracion < 60 or duracion % 30 != 0):
            raise DomainValidationError(
                {
                    "duracionMinutosSolicitados": (
                        "la duracion de guarderia debe ser minimo 60 minutos y en multiplos de 30"
                    )
                }
            )

        evento_id = attrs.get("idEvento_id")
        if evento_id:
            evento = Evento.objects.filter(idEvento=evento_id).only("duracionSlotMinutos").first()
            if evento and evento.duracionSlotMinutos is not None and not attrs.get("idSlotEvento_id"):
                raise DomainValidationError(
                    {"idSlotEvento_id": "este evento requiere seleccionar un slot"}
                )

        return attrs


class ValidarBusquedaDisponibilidadApiService:
    """Valida reglas de busqueda de disponibilidad para capa API."""

    def validar(self, attrs: dict) -> dict:
        tipo_servicio = attrs.get("tipoServicio")

        if tipo_servicio == TipoServicio.PASEO:
            if attrs.get("fecha") is None:
                raise DomainValidationError({"fecha": "fecha es requerida para paseo"})
            if attrs.get("duracionMinutos") is None:
                raise DomainValidationError(
                    {"duracionMinutos": "duracionMinutos es requerida para paseo"}
                )

            ciudad = str(attrs.get("ciudadPaseo") or "").strip()
            latitud = attrs.get("latitudPaseo")
            longitud = attrs.get("longitudPaseo")

            if (latitud is None) != (longitud is None):
                raise DomainValidationError("latitudPaseo y longitudPaseo deben enviarse juntas")

            if not ciudad and (latitud is None or longitud is None):
                raise DomainValidationError(
                    "para paseo debes enviar ciudadPaseo o coordenadas de referencia"
                )

        if tipo_servicio == TipoServicio.GUARDERIA:
            fecha_inicio = attrs.get("fechaInicioGuarderia")
            fecha_fin = attrs.get("fechaFinGuarderia")
            if fecha_inicio is None:
                raise DomainValidationError(
                    {"fechaInicioGuarderia": "fechaInicioGuarderia es requerida para guarderia"}
                )
            if fecha_fin is not None and fecha_fin < fecha_inicio:
                raise DomainValidationError(
                    {
                        "fechaFinGuarderia": (
                            "fechaFinGuarderia debe ser igual o posterior a fechaInicioGuarderia"
                        )
                    }
                )

        precio_min = attrs.get("precioMinHora")
        precio_max = attrs.get("precioMaxHora")
        if precio_min is not None and precio_max is not None and precio_min > precio_max:
            raise DomainValidationError(
                {"precioMinHora": "precioMinHora no puede ser mayor que precioMaxHora"}
            )

        hora_inicio = attrs.get("horaInicio")
        hora_fin = attrs.get("horaFin")
        if hora_inicio is not None and hora_fin is not None and hora_fin <= hora_inicio:
            raise DomainValidationError({"horaFin": "horaFin debe ser posterior a horaInicio"})

        return attrs


class MapearResultadosDisponibilidadApiService:
    """Transforma resultados de disponibilidad de dominio a payload API."""

    @staticmethod
    def _map_slot_guarderia(slot: dict) -> dict:
        return {
            "eventoId": slot["evento_id"],
            "fecha": slot["fecha"],
            "horaInicio": slot["hora_inicio"],
            "horaFin": slot["hora_fin"],
            "cuposDisponibles": int(slot["cupos_disponibles"]),
            "cupoMaximo": int(slot["cupo_maximo"]),
            "duracionOpciones": list(slot.get("duracion_opciones") or []),
        }

    def mapear_item(self, item: dict, tipo_servicio: str, data: dict) -> dict:
        cuidador = item["cuidador"]
        evento = item.get("evento")
        evento_id = None
        fecha = None
        hora_inicio = item.get("hora_inicio")
        hora_fin = item.get("hora_fin")
        slots_guarderia = []

        if tipo_servicio == TipoServicio.PASEO:
            fecha = data.get("fecha")
            if evento is not None:
                evento_id = str(evento.idEvento)
                hora_inicio = hora_inicio or evento.horaInicio
                hora_fin = hora_fin or evento.horaFin
        else:
            evento_id = item.get("evento_default_id")
            fecha = item.get("fecha_default")
            if evento is not None:
                evento_id = evento_id or str(evento.idEvento)
                hora_inicio = hora_inicio or evento.horaInicio
                hora_fin = hora_fin or evento.horaFin
            slots_guarderia = [
                self._map_slot_guarderia(slot)
                for slot in (item.get("slots_guarderia") or [])
            ]

        payload = {
            "cuidadorId": str(cuidador.idUsuario),
            "cuidadorNombre": cuidador.nombre,
            "cuidadorApellido": cuidador.apellido,
            "tipoServicio": tipo_servicio,
            "eventoId": evento_id,
            "fecha": fecha,
            "horaInicio": hora_inicio,
            "horaFin": hora_fin,
            "tarifaHora": int(item.get("tarifa_hora") or 0),
            "tarifaTotal": int(item.get("tarifa_total") or 0),
            "cupoMaximo": item.get("cupo_maximo"),
            "cuposDisponibles": item.get("cupos_disponibles"),
            "totalSlotsDisponibles": int(item.get("total_slots_disponibles") or 0),
            "distanciaKm": item.get("distancia_km"),
            "calificacionPromedio": item.get("calificacion_promedio"),
            "calificacionCount": int(item.get("calificacion_count") or 0),
            "descripcionServicio": item.get("descripcion_servicio") or "",
        }

        if slots_guarderia:
            payload["slotsGuarderia"] = slots_guarderia

        return payload

    def mapear(self, resultados: list, tipo_servicio: str, data: dict) -> list[dict]:
        return [self.mapear_item(item, tipo_servicio, data) for item in (resultados or [])]


class MapearErroresApiService:
    """Normaliza excepciones de dominio a respuestas HTTP para DRF."""

    def __init__(self, logger_name: str = __name__):
        self._logger = logging.getLogger(logger_name)

    def mapear(self, exc: Exception, operacion: str) -> tuple[dict, int]:
        if isinstance(exc, ResourceNotFoundError):
            return {"detail": str(exc)}, 404
        if isinstance(exc, ConflictError):
            return {"detail": str(exc)}, 409
        if isinstance(exc, DomainValidationError):
            return {"detail": str(exc)}, 400

        self._logger.exception("Error interno inesperado en API de servicios (%s)", operacion)
        return {"detail": "ocurrio un error interno inesperado"}, 500


class CancelarSolicitudDesdeApiService:
    """Orquesta el flujo API de cancelacion: actor -> solicitud."""

    def __init__(self, cancelar_service: CancelarSolicitudService | None = None):
        self._cancelar_service = cancelar_service or CancelarSolicitudService()

    def cancelar(self, solicitud_id: str, actor_id) -> SolicitudServicio:
        if not actor_id:
            raise DomainValidationError("actor_id es requerido")
        try:
            actor = Usuario.objects.get(idUsuario=actor_id)
        except Usuario.DoesNotExist:
            raise ResourceNotFoundError("el actor no existe")
        return self._cancelar_service.cancelar(solicitud_id, actor)


class CrearSolicitudServicioAppService:
    """App service del flujo crear solicitud para web y API."""

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
        dueños = Usuario.objects.filter(rol="dueño")
        cuidadores = Usuario.objects.filter(rol="cuidador", verificado=True)
        mascotas = Mascota.objects.all()
        eventos = Evento.objects.filter(disponible=True).select_related("idCuidador__idCuidador").prefetch_related("slots")
        ventanas = VentanaDisponibilidad.objects.select_related("idCuidador__idCuidador").prefetch_related("slots")
        bloques = BloqueTiempo.objects.filter(disponible=True).select_related("idCuidador__idCuidador")

        eventos_por_cuidador: dict[str, dict[str, list[dict]]] = {}
        for evento in eventos:
            cuidador_id = str(evento.idCuidador.idCuidador.idUsuario)
            if cuidador_id not in eventos_por_cuidador:
                eventos_por_cuidador[cuidador_id] = {"paseo": [], "guarderia": []}
            slots_libres = ContarSlotsDisponiblesService.para_evento(evento)
            texto = f"{evento.diaSemana} {evento.horaInicio}-{evento.horaFin}"
            if slots_libres:
                texto += f" ({slots_libres} slots)"
            eventos_por_cuidador[cuidador_id][evento.tipoServicio].append(
                {
                    "id": str(evento.idEvento),
                    "dia": evento.diaSemana,
                    "texto": texto,
                }
            )

        ventanas_por_cuidador: dict[str, dict[str, list[dict]]] = {}
        for ventana in ventanas:
            cuidador_id = str(ventana.idCuidador.idCuidador.idUsuario)
            if cuidador_id not in ventanas_por_cuidador:
                ventanas_por_cuidador[cuidador_id] = {"paseo": [], "guarderia": []}
            slots_libres = ContarSlotsDisponiblesService.para_ventana(ventana)
            ventanas_por_cuidador[cuidador_id][ventana.tipoServicio].append(
                {
                    "id": str(ventana.idVentana),
                    "dia": ventana.diaSemana,
                    "texto": f"{ventana.diaSemana} {ventana.horaInicio}-{ventana.horaFin} ({slots_libres} slots)",
                }
            )

        bloques_por_cuidador: dict[str, dict[str, list[dict[str, str]]]] = {}
        for bloque in bloques:
            cuidador_id = str(bloque.idCuidador.idCuidador.idUsuario)
            if cuidador_id not in bloques_por_cuidador:
                bloques_por_cuidador[cuidador_id] = {"paseo": [], "guarderia": []}
            bloques_por_cuidador[cuidador_id][bloque.tipoServicio].append(
                {
                    "id": str(bloque.idBloque),
                    "dia": bloque.diaSemana,
                    "texto": f"{bloque.diaSemana} {bloque.horaInicio}-{bloque.horaFin}",
                }
            )

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

        raise DomainValidationError("debes seleccionar un evento valido")

    def crear_desde_api(self, validated_data: dict) -> SolicitudServicio:
        dueño = self._resolver_dueño(validated_data.get("idDueño_id"))
        tipo_servicio = validated_data.get("tipoServicio")
        fecha_fin = validated_data.get("fechaFin")
        id_evento = validated_data.get("idEvento_id")
        if not id_evento:
            raise DomainValidationError("debes indicar idEvento_id")

        datos = {
            "idDueño": dueño,
            "idCuidador_id": validated_data.get("idCuidador_id"),
            "idMascota_id": validated_data.get("idMascota_id"),
            "tipoServicio": tipo_servicio,
            "fecha": validated_data.get("fecha"),
            "idEvento_id": id_evento,
            "idSlotEvento_id": validated_data.get("idSlotEvento_id"),
        }
        if fecha_fin:
            datos["fechaFin"] = fecha_fin

        duracion_solicitada = validated_data.get("duracionMinutosSolicitados")
        if duracion_solicitada is not None:
            datos["duracionMinutosSolicitados"] = duracion_solicitada

        try:
            evento = Evento.objects.get(idEvento=id_evento)
        except Evento.DoesNotExist:
            raise ResourceNotFoundError("el evento no existe")
        if evento.duracionSlotMinutos is not None:
            return self._solicitud_con_asignacion_evento.crear(datos)
        return self._solicitud_service.crear_solicitud_evento(datos)

    def _resolver_dueño(self, dueño_id) -> Usuario:
        if not dueño_id:
            raise DomainValidationError("idDueño_id es requerido")
        try:
            dueño = Usuario.objects.get(idUsuario=dueño_id)
        except Usuario.DoesNotExist:
            raise ResourceNotFoundError("el dueño no existe")
        if dueño.rol != "dueño":
            raise DomainValidationError("el usuario no tiene rol de dueño")
        return dueño


class BuscarDisponibilidadDesdeApiService:
    """Orquesta busqueda de disponibilidad para capa DRF sin logica en views."""

    def __init__(
        self,
        buscador: BuscarCuidadoresDisponiblesService | None = None,
        filtro: FiltrarResultadosDisponibilidadService | None = None,
    ):
        self._buscador = buscador or BuscarCuidadoresDisponiblesService()
        self._filtro = filtro or FiltrarResultadosDisponibilidadService()

    def buscar(self, data: dict) -> list:
        try:
            dueño = Usuario.objects.get(idUsuario=data["idDueño_id"])
        except Usuario.DoesNotExist:
            raise ResourceNotFoundError("el dueño no existe")

        tipo_servicio = data.get("tipoServicio")

        if tipo_servicio == TipoServicio.PASEO:
            fecha = data.get("fecha")
            if fecha is None:
                raise DomainValidationError("fecha es requerida para paseo")

            duracion = data.get("duracionMinutos")
            if duracion is None:
                raise DomainValidationError("duracionMinutos es requerida para paseo")

            resultados = self._buscador.buscar(
                dueño=dueño,
                mascota_id=str(data["idMascota_id"]),
                fecha_o_str=fecha,
                duracion_minutos=duracion,
                solo_ciudad=True,
                ciudad_referencia=data.get("ciudadPaseo"),
                latitud_referencia=data.get("latitudPaseo"),
                longitud_referencia=data.get("longitudPaseo"),
            )
        elif tipo_servicio == TipoServicio.GUARDERIA:
            fecha_inicio = data.get("fechaInicioGuarderia")
            if fecha_inicio is None:
                raise DomainValidationError("fechaInicioGuarderia es requerida para guarderia")

            fecha_fin = data.get("fechaFinGuarderia") or fecha_inicio
            if fecha_fin < fecha_inicio:
                raise DomainValidationError(
                    "fechaFinGuarderia debe ser igual o posterior a fechaInicioGuarderia"
                )

            resultados = self._buscador.buscar_cuidado(
                dueño=dueño,
                mascota_id=str(data["idMascota_id"]),
                fecha_inicio_str=fecha_inicio.isoformat(),
                fecha_fin_str=fecha_fin.isoformat(),
                solo_ciudad=True,
            )
        else:
            raise DomainValidationError("tipoServicio invalido")

        return self._filtro.filtrar(
            resultados,
            precio_min_hora=data.get("precioMinHora"),
            precio_max_hora=data.get("precioMaxHora"),
            hora_inicio=data.get("horaInicio"),
            hora_fin=data.get("horaFin"),
        )


class ServiciosApiGatewayService:
    """Fachada de entrada para operaciones HTTP de la API v1 de servicios."""

    def __init__(
        self,
        crear_solicitud_service: CrearSolicitudServicioAppService | None = None,
        obtener_solicitud_service: ObtenerSolicitudServicioService | None = None,
        cancelar_solicitud_service: CancelarSolicitudDesdeApiService | None = None,
        buscar_disponibilidad_service: BuscarDisponibilidadDesdeApiService | None = None,
        resultado_mapper: MapearResultadosDisponibilidadApiService | None = None,
    ):
        self._crear_solicitud_service = crear_solicitud_service or CrearSolicitudServicioAppService()
        self._obtener_solicitud_service = obtener_solicitud_service or ObtenerSolicitudServicioService()
        self._cancelar_solicitud_service = cancelar_solicitud_service or CancelarSolicitudDesdeApiService()
        self._buscar_disponibilidad_service = buscar_disponibilidad_service or BuscarDisponibilidadDesdeApiService()
        self._resultado_mapper = resultado_mapper or MapearResultadosDisponibilidadApiService()

    def crear_solicitud(self, payload: dict) -> SolicitudServicio:
        return self._crear_solicitud_service.crear_desde_api(payload)

    def obtener_solicitud(self, solicitud_id: str) -> SolicitudServicio:
        return self._obtener_solicitud_service.obtener(solicitud_id)

    def cancelar_solicitud(self, solicitud_id: str, actor_id) -> SolicitudServicio:
        return self._cancelar_solicitud_service.cancelar(solicitud_id, actor_id)

    def buscar_disponibilidad(self, payload: dict) -> list[dict]:
        resultados = self._buscar_disponibilidad_service.buscar(payload)
        return self._resultado_mapper.mapear(resultados, payload["tipoServicio"], payload)
