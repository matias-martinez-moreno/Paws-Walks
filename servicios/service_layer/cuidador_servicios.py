# capa de aplicacion: logica de negocio
from __future__ import annotations

import json
from datetime import time
from decimal import Decimal

from django.db import transaction

from servicios.domain.exceptions import (
    ConflictError,
    DomainError,
    DomainValidationError,
    ResourceNotFoundError,
)
from servicios.models import (
    BloqueTiempo,
    DiaSemana,
    Evento,
    PerfilCuidador,
    TipoServicio,
    Usuario,
    VentanaDisponibilidad,
)


PASEO_DURACIONES_MINUTOS = (60, 90, 120, 150, 180)


# modulo de servicios: gestion de servicios de cuidador y bloques
from servicios.service_layer.utils import minutes_to_time as _minutes_to_time, time_to_minutes as _time_to_minutes
from servicios.service_layer.catalogo_cuidador_servicios import (
    AgregarEventoService,
    EliminarEventoService,
    EliminarServicioCuidadorService,
)
from servicios.service_layer.perfiles_mascotas import ActualizarPerfilCuidadorService
from servicios.service_layer.usuarios_servicios import ObtenerTipoServicioEventoService

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


class _AccionCuidadorServiciosBaseService:
    """Base para normalizar utilidades de acciones del módulo de servicios del cuidador."""

    def __init__(self, tipos_editables: tuple[str, ...]):
        self._tipos_editables = tipos_editables

    def _normalizar_editar_tipo(self, valor) -> str | None:
        editar_tipo = str(valor or "").strip()
        if editar_tipo in self._tipos_editables:
            return editar_tipo
        return None


class _AccionCuidadorServiciosGuardarConfigService(_AccionCuidadorServiciosBaseService):
    """Guarda configuración de servicios y bloques pendientes del cuidador."""

    def __init__(
        self,
        construir_datos_service: ConstruirDatosPerfilCuidadorFormularioService | None = None,
        guardar_config_service: GuardarConfiguracionServiciosCuidadorService | None = None,
        tipos_editables: tuple[str, ...] = ("paseo", "guarderia"),
    ):
        super().__init__(tipos_editables)
        self._construir_datos_service = construir_datos_service or ConstruirDatosPerfilCuidadorFormularioService()
        self._guardar_config_service = guardar_config_service or GuardarConfiguracionServiciosCuidadorService()

    def ejecutar(self, cuidador: Usuario, source, perfil_actual: PerfilCuidador | None = None) -> dict:
        editar_tipo = self._normalizar_editar_tipo(source.get("editar_tipo"))
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


class _AccionCuidadorServiciosEliminarServicioService(_AccionCuidadorServiciosBaseService):
    """Elimina un tipo de servicio activo del cuidador."""

    def __init__(
        self,
        eliminar_servicio_service: EliminarServicioCuidadorService | None = None,
        tipos_editables: tuple[str, ...] = ("paseo", "guarderia"),
    ):
        super().__init__(tipos_editables)
        self._eliminar_servicio_service = eliminar_servicio_service or EliminarServicioCuidadorService()

    def ejecutar(self, cuidador: Usuario, source, perfil_actual: PerfilCuidador | None = None) -> dict:
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


class _AccionCuidadorServiciosEliminarEventoService(_AccionCuidadorServiciosBaseService):
    """Elimina un evento puntual y mantiene el contexto de edición."""

    def __init__(
        self,
        obtener_tipo_evento_service: ObtenerTipoServicioEventoService | None = None,
        eliminar_evento_service: EliminarEventoService | None = None,
        tipos_editables: tuple[str, ...] = ("paseo", "guarderia"),
    ):
        super().__init__(tipos_editables)
        self._obtener_tipo_evento_service = obtener_tipo_evento_service or ObtenerTipoServicioEventoService()
        self._eliminar_evento_service = eliminar_evento_service or EliminarEventoService()

    def ejecutar(self, cuidador: Usuario, source, perfil_actual: PerfilCuidador | None = None) -> dict:
        editar_tipo = self._normalizar_editar_tipo(source.get("editar_tipo"))
        if editar_tipo is None:
            evento_tipo = self._obtener_tipo_evento_service.obtener(cuidador, source.get("evento_id"))
            if evento_tipo in (TipoServicio.PASEO, TipoServicio.GUARDERIA):
                editar_tipo = evento_tipo

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


class _AccionCuidadorServiciosAgregarEventoService(_AccionCuidadorServiciosBaseService):
    """Agrega eventos por creación simple, rápida o rango de guardería."""

    def __init__(
        self,
        agregar_evento_service: ProcesarAgregarEventoCuidadorService | None = None,
        tipos_editables: tuple[str, ...] = ("paseo", "guarderia"),
    ):
        super().__init__(tipos_editables)
        self._agregar_evento_service = agregar_evento_service or ProcesarAgregarEventoCuidadorService()

    def ejecutar(self, cuidador: Usuario, source, perfil_actual: PerfilCuidador | None = None) -> dict:
        editar_tipo = self._normalizar_editar_tipo(source.get("editar_tipo") or source.get("tipoServicio"))

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


class ProcesarAccionesCuidadorServiciosService:
    """Fachada de acciones POST del cuidador, delegada a handlers especializados."""

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
        tipos_editables = self._TIPOS_EDITABLES
        self._acciones = {
            "servicio": _AccionCuidadorServiciosGuardarConfigService(
                construir_datos_service,
                guardar_config_service,
                tipos_editables,
            ),
            "eliminar_servicio": _AccionCuidadorServiciosEliminarServicioService(
                eliminar_servicio_service,
                tipos_editables,
            ),
            "eliminar_evento": _AccionCuidadorServiciosEliminarEventoService(
                obtener_tipo_evento_service,
                eliminar_evento_service,
                tipos_editables,
            ),
            "agregar": _AccionCuidadorServiciosAgregarEventoService(
                agregar_evento_service,
                tipos_editables,
            ),
        }

    def procesar(self, cuidador: Usuario, source, perfil_actual: PerfilCuidador | None = None) -> dict:
        action = source.get("action")
        accion_service = self._acciones.get(action)
        if accion_service is None:
            return {
                "modo": "redirect",
                "ruta": "cuidador_servicios",
            }
        return accion_service.ejecutar(cuidador, source, perfil_actual)


class AgregarBloquesRapidoService:
    """Agrega múltiples bloques a la vez según un preset de días."""

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


