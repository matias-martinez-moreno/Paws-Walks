# capa de aplicacion: logica de negocio
from __future__ import annotations

import json
from datetime import datetime

from servicios.domain.exceptions import (
    DomainValidationError,
    ResourceNotFoundError,
)
from servicios.models import (
    BloqueTiempo,
    Evento,
    Mascota,
    SolicitudServicio,
    TipoServicio,
    Usuario,
    VentanaDisponibilidad,
)

# modulo de servicios: app services para API
from servicios.service_layer.api_validadores import MapearResultadosDisponibilidadApiService
from servicios.service_layer.api_disponibilidad_servicios import BuscarDisponibilidadDesdeApiService
from servicios.service_layer.reservas_servicios import (
    CancelarSolicitudService,
    CrearSolicitudConAsignacionEventoService,
    CrearSolicitudConAsignacionService,
    ObtenerSolicitudServicioService,
    SolicitudServicioService,
)
from servicios.service_layer.usuarios_servicios import ContarSlotsDisponiblesService

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


class _CrearSolicitudServicioBaseAppService:
    """Base interna: dependencias y utilidades compartidas del caso de uso."""

    def __init__(
        self,
        solicitud_service: SolicitudServicioService | None = None,
        solicitud_con_asignacion: CrearSolicitudConAsignacionService | None = None,
        solicitud_con_asignacion_evento: CrearSolicitudConAsignacionEventoService | None = None,
    ):
        self._solicitud_service = solicitud_service or SolicitudServicioService()
        self._solicitud_con_asignacion = solicitud_con_asignacion or CrearSolicitudConAsignacionService()
        self._solicitud_con_asignacion_evento = solicitud_con_asignacion_evento or CrearSolicitudConAsignacionEventoService()

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


class CrearSolicitudServicioWebAppService(_CrearSolicitudServicioBaseAppService):
    """App service para flujo web/formulario de creación de solicitud."""

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


class CrearSolicitudServicioApiAppService(_CrearSolicitudServicioBaseAppService):
    """App service para flujo API de creación de solicitud."""

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

        # Regla de negocio: si el evento trabaja por slots, el slot es obligatorio.
        # Esta validación vive aquí porque requiere la entidad Evento ya resuelta.
        if evento.duracionSlotMinutos is not None and not datos.get("idSlotEvento_id"):
            raise DomainValidationError(
                {"idSlotEvento_id": "este evento requiere seleccionar un slot"}
            )

        if evento.duracionSlotMinutos is not None:
            return self._solicitud_con_asignacion_evento.crear(datos)
        return self._solicitud_service.crear_solicitud_evento(datos)


class CrearSolicitudServicioAppService:
    """Fachada unificada: delega en servicios específicos web/API."""

    def __init__(
        self,
        solicitud_service: SolicitudServicioService | None = None,
        solicitud_con_asignacion: CrearSolicitudConAsignacionService | None = None,
        solicitud_con_asignacion_evento: CrearSolicitudConAsignacionEventoService | None = None,
    ):
        kwargs = {
            "solicitud_service": solicitud_service,
            "solicitud_con_asignacion": solicitud_con_asignacion,
            "solicitud_con_asignacion_evento": solicitud_con_asignacion_evento,
        }
        self._web = CrearSolicitudServicioWebAppService(**kwargs)
        self._api = CrearSolicitudServicioApiAppService(**kwargs)

    def get_form_context(self) -> dict:
        return self._web.get_form_context()

    def crear_desde_form(self, post_data) -> object:
        return self._web.crear_desde_form(post_data)

    def crear_desde_api(self, validated_data: dict) -> SolicitudServicio:
        return self._api.crear_desde_api(validated_data)


# ServiciosApiGatewayService vive en api_gateway.py (patron Gateway)
