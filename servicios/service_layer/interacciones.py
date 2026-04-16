# capa de aplicacion: logica de negocio
from __future__ import annotations

from uuid import UUID

from django.core.exceptions import ValidationError
from django.db.models import Avg, Case, Count, IntegerField, Q, When
from django.utils import timezone

from servicios.domain.exceptions import (
    ConflictError,
    DomainError,
    DomainValidationError,
    ResourceNotFoundError,
)
from servicios.infra.factory import NotificadorFactory
from servicios.service_layer.api_gateway import ServiciosApiGatewayService
from servicios.models import (
    Calificacion,
    CalificacionMascota,
    CategoriaNotificacion,
    EstadoSolicitud,
    MensajeChat,
    Notificacion,
    SolicitudServicio,
    TipoServicio,
    Usuario,
)


# modulo de servicios: notificaciones, resenas y acciones calendario/reservas
from servicios.service_layer.disponibilidad import (
    BuscarDisponibilidadFormularioReservaService,
    CrearReservaDesdeSeleccionService,
    NormalizarBusquedaReservaService,
    _auto_finalizar_paseos_expirados,
)
from servicios.service_layer.reputacion_servicios import (
    calificacion_de_autor_en_solicitud as _calificacion_de_autor_en_solicitud,
    calificacion_mascota_de_autor_en_solicitud as _calificacion_mascota_de_autor_en_solicitud,
)
from servicios.service_layer.reservas_servicios import (
    CambiarEstadoSolicitudService,
    CancelarSolicitudService,
    MarcarServicioCompletadoService,
    ObtenerSolicitudParaChatService,
)

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
        gateway: ServiciosApiGatewayService | None = None,
    ):
        self._crear_reserva_service = crear_reserva_service or CrearReservaDesdeSeleccionService()
        self._buscar_disponibilidad_service = (
            buscar_disponibilidad_service or BuscarDisponibilidadFormularioReservaService()
        )
        self._gateway = gateway or ServiciosApiGatewayService()

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

        # Usa Gateway (que puede llamar Flask microservicio) en lugar del servicio directo
        tipo_servicio = str(source.get("tipo_servicio") or "paseo").strip().lower()
        payload_gateway = {
            "tipoServicio": tipo_servicio,
            "idDueño_id": str(dueño.idUsuario),
            "idMascota_id": source.get("mascota_id", ""),
        }
        if tipo_servicio == "paseo":
            payload_paseo = {
                "fecha": source.get("fecha", ""),
                "ciudadPaseo": (source.get("ciudad_paseo") or "").strip(),
                "latitudPaseo": source.get("latitud_paseo"),
                "longitudPaseo": source.get("longitud_paseo"),
            }
            duracion = self._coerce_int_or_none(source.get("duracion"))
            if duracion is not None:
                payload_paseo["duracionMinutos"] = duracion
            payload_gateway.update(payload_paseo)
        else:
            payload_gateway.update({
                "fechaInicioGuarderia": source.get("fecha_guarderia_inicio", ""),
                "fechaFinGuarderia": source.get("fecha_guarderia_fin") or source.get("fecha_guarderia_inicio", ""),
            })
        payload_gateway.update({
            "precioMinHora": self._coerce_int_or_none(source.get("precio_min")),
            "precioMaxHora": self._coerce_int_or_none(source.get("precio_max")),
        })

        cuidadores = self._gateway.buscar_disponibilidad(payload_gateway)
        busqueda = NormalizarBusquedaReservaService().busqueda_from_source(source, dueño)
        return {
            "modo": "render_resultado",
            "cuidadores_disponibles": cuidadores,
            "busqueda": busqueda,
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


class _AccionDueñoReservasCalificarService:
    """Ejecuta la calificación del cuidador desde el flujo de dueño."""

    def __init__(self, calificacion_service: CrearCalificacionService | None = None):
        self._calificacion_service = calificacion_service or CrearCalificacionService()

    def ejecutar(self, dueño: Usuario, solicitud_id: str | None, source) -> dict:
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


class _AccionDueñoReservasCancelarService:
    """Ejecuta la cancelación de reserva desde el flujo de dueño."""

    def __init__(self, cancelar_service: CancelarSolicitudService | None = None):
        self._cancelar_service = cancelar_service or CancelarSolicitudService()

    def ejecutar(self, dueño: Usuario, solicitud_id: str | None, source) -> dict:
        self._cancelar_service.cancelar(solicitud_id, dueño)
        return {
            "nivel": "success",
            "mensaje": "Reserva cancelada.",
        }


class _AccionDueñoReservasCompletarInfoService:
    """Retorna mensaje informativo cuando el dueño intenta completar una reserva."""

    @staticmethod
    def ejecutar(dueño: Usuario, solicitud_id: str | None, source) -> dict:
        return {
            "nivel": "info",
            "mensaje": "El arrendamiento debe ser finalizado por el cuidador para habilitar calificación.",
        }


class _AccionDueñoReservasEnviarMensajeService:
    """Envía un mensaje de chat desde la vista de reservas del dueño."""

    def __init__(
        self,
        obtener_chat_service: ObtenerSolicitudParaChatService | None = None,
        enviar_chat_service: EnviarMensajeChatService | None = None,
    ):
        self._obtener_chat_service = obtener_chat_service or ObtenerSolicitudParaChatService()
        self._enviar_chat_service = enviar_chat_service or EnviarMensajeChatService()

    def ejecutar(self, dueño: Usuario, solicitud_id: str | None, source) -> dict:
        mensaje = str(source.get("mensaje") or "").strip()
        if mensaje and solicitud_id:
            solicitud = self._obtener_chat_service.obtener_para_dueño(solicitud_id, dueño)
            self._enviar_chat_service.enviar(solicitud, dueño, mensaje)
        return {}


class ProcesarAccionesDueñoReservasService:
    """Orquesta acciones del dueño delegando cada responsabilidad en un handler."""

    def __init__(
        self,
        calificacion_service: CrearCalificacionService | None = None,
        cancelar_service: CancelarSolicitudService | None = None,
        obtener_chat_service: ObtenerSolicitudParaChatService | None = None,
        enviar_chat_service: EnviarMensajeChatService | None = None,
    ):
        accion_calificar = _AccionDueñoReservasCalificarService(calificacion_service)

        self._acciones = {
            "calificar": accion_calificar,
            "calificar_cuidador": accion_calificar,
            "cancelar": _AccionDueñoReservasCancelarService(cancelar_service),
            "completar": _AccionDueñoReservasCompletarInfoService(),
            "enviar_mensaje": _AccionDueñoReservasEnviarMensajeService(
                obtener_chat_service,
                enviar_chat_service,
            ),
        }

    def procesar(self, dueño: Usuario, source) -> dict:
        action = source.get("action")
        solicitud_id = source.get("solicitud_id")
        accion_service = self._acciones.get(action)
        if accion_service is None:
            return {}

        try:
            return accion_service.ejecutar(dueño, solicitud_id, source)
        except DomainError as error:
            return {
                "nivel": "error",
                "mensaje": str(error),
            }


class _AccionCuidadorCalendarioAceptarService:
    """Acepta una solicitud pendiente del calendario del cuidador."""

    def __init__(self, estado_service: CambiarEstadoSolicitudService | None = None):
        self._estado_service = estado_service or CambiarEstadoSolicitudService()

    def ejecutar(self, cuidador: Usuario, solicitud_id: str, source) -> dict:
        self._estado_service.aceptar(solicitud_id, cuidador)
        return {
            "nivel": "success",
            "mensaje": "Solicitud aceptada correctamente.",
        }


class _AccionCuidadorCalendarioRechazarService:
    """Rechaza una solicitud pendiente del calendario del cuidador."""

    def __init__(self, estado_service: CambiarEstadoSolicitudService | None = None):
        self._estado_service = estado_service or CambiarEstadoSolicitudService()

    def ejecutar(self, cuidador: Usuario, solicitud_id: str, source) -> dict:
        self._estado_service.rechazar(solicitud_id, cuidador)
        return {
            "nivel": "success",
            "mensaje": "Solicitud rechazada.",
        }


class _AccionCuidadorCalendarioCompletarService:
    """Finaliza una solicitud aceptada del calendario del cuidador."""

    def __init__(
        self,
        completar_service: MarcarServicioCompletadoService | None = None,
        *,
        forzar: bool = False,
        mensaje_exito: str,
    ):
        self._completar_service = completar_service or MarcarServicioCompletadoService()
        self._forzar = forzar
        self._mensaje_exito = mensaje_exito

    def ejecutar(self, cuidador: Usuario, solicitud_id: str, source) -> dict:
        self._completar_service.marcar(solicitud_id, cuidador, forzar=self._forzar)
        return {
            "nivel": "success",
            "mensaje": self._mensaje_exito,
        }


class _AccionCuidadorCalendarioCancelarService:
    """Cancela una solicitud desde calendario del cuidador."""

    def __init__(self, cancelar_service: CancelarSolicitudService | None = None):
        self._cancelar_service = cancelar_service or CancelarSolicitudService()

    def ejecutar(self, cuidador: Usuario, solicitud_id: str, source) -> dict:
        self._cancelar_service.cancelar(solicitud_id, cuidador)
        return {
            "nivel": "success",
            "mensaje": "Reserva cancelada.",
        }


class _AccionCuidadorCalendarioEnviarMensajeService:
    """Envía un mensaje de chat desde el calendario del cuidador."""

    def __init__(
        self,
        obtener_chat_service: ObtenerSolicitudParaChatService | None = None,
        enviar_chat_service: EnviarMensajeChatService | None = None,
    ):
        self._obtener_chat_service = obtener_chat_service or ObtenerSolicitudParaChatService()
        self._enviar_chat_service = enviar_chat_service or EnviarMensajeChatService()

    def ejecutar(self, cuidador: Usuario, solicitud_id: str, source) -> dict:
        mensaje = str(source.get("mensaje") or "").strip()
        if mensaje:
            solicitud = self._obtener_chat_service.obtener_para_cuidador(solicitud_id, cuidador)
            self._enviar_chat_service.enviar(solicitud, cuidador, mensaje)
        return {}


class _AccionCuidadorCalendarioCalificarDueñoService:
    """Registra reseña del dueño desde el calendario del cuidador."""

    def __init__(self, calificacion_service: CrearCalificacionService | None = None):
        self._calificacion_service = calificacion_service or CrearCalificacionService()

    def ejecutar(self, cuidador: Usuario, solicitud_id: str, source) -> dict:
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


class _AccionCuidadorCalendarioCalificarMascotaService:
    """Registra reseña de mascota desde el calendario del cuidador."""

    def __init__(self, calificacion_mascota_service: CrearCalificacionMascotaService | None = None):
        self._calificacion_mascota_service = calificacion_mascota_service or CrearCalificacionMascotaService()

    def ejecutar(self, cuidador: Usuario, solicitud_id: str, source) -> dict:
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


class ProcesarAccionesCuidadorCalendarioService:
    """Orquesta acciones del calendario delegando cada caso de uso a un handler."""

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
        estado = estado_service or CambiarEstadoSolicitudService()
        completar = completar_service or MarcarServicioCompletadoService()
        calificar_dueño = _AccionCuidadorCalendarioCalificarDueñoService(calificacion_service)

        self._acciones = {
            "aceptar": _AccionCuidadorCalendarioAceptarService(estado),
            "rechazar": _AccionCuidadorCalendarioRechazarService(estado),
            "completar": _AccionCuidadorCalendarioCompletarService(
                completar,
                forzar=False,
                mensaje_exito="Arrendamiento finalizado correctamente.",
            ),
            "finalizar": _AccionCuidadorCalendarioCompletarService(
                completar,
                forzar=False,
                mensaje_exito="Arrendamiento finalizado correctamente.",
            ),
            "finalizar_prueba": _AccionCuidadorCalendarioCompletarService(
                completar,
                forzar=True,
                mensaje_exito="Arrendamiento finalizado en modo prueba.",
            ),
            "cancelar": _AccionCuidadorCalendarioCancelarService(cancelar_service),
            "enviar_mensaje": _AccionCuidadorCalendarioEnviarMensajeService(
                obtener_chat_service,
                enviar_chat_service,
            ),
            "calificar": calificar_dueño,
            "calificar_dueno": calificar_dueño,
            "calificar_mascota": _AccionCuidadorCalendarioCalificarMascotaService(
                calificacion_mascota_service,
            ),
        }

    def procesar(self, cuidador: Usuario, source) -> dict:
        action = source.get("action")
        solicitud_id = source.get("solicitud_id")
        if not solicitud_id or action not in self._acciones:
            return {
                "nivel": "error",
                "mensaje": "Acción inválida.",
            }

        try:
            return self._acciones[action].ejecutar(cuidador, solicitud_id, source)
        except DomainError as error:
            return {
                "nivel": "error",
                "mensaje": str(error),
            }


