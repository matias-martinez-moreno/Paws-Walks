# modulo de servicios: configuracion de eventos y oferta de cuidador
from __future__ import annotations

from datetime import time
from decimal import Decimal

from django.db import transaction

from servicios.domain.exceptions import ConflictError, DomainValidationError, ResourceNotFoundError
from servicios.models import (
    DiaSemana,
    EstadoSolicitud,
    Evento,
    PerfilCuidador,
    PrecioServicio,
    SlotDisponibilidad,
    SlotEvento,
    SolicitudServicio,
    TipoServicio,
    Usuario,
    VentanaDisponibilidad,
)
from servicios.service_layer.utils import minutes_to_time, time_to_minutes
from servicios.service_layer.validacion_servicios import PASEO_DURACIONES_MINUTOS

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
            hi_m = time_to_minutes(hora_inicio)
            hf_m = time_to_minutes(hora_fin)
            m = hi_m
            while m < hf_m:
                SlotDisponibilidad.objects.create(
                    idVentana=ventana,
                    horaInicio=minutes_to_time(m),
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
            fin_minutos = time_to_minutes(hora_inicio) + duracion_minutos
            if fin_minutos > 24 * 60:
                raise DomainValidationError("la duración supera el final del día")
            hora_fin = minutes_to_time(fin_minutos)

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

        duracion_total = time_to_minutes(hora_fin) - time_to_minutes(hora_inicio)
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
        eventos_paseo = list(
            ListarEventosCuidadorService().listar(cuidador, tipo_servicio=TipoServicio.PASEO)
        )
        eventos_guarderia = list(
            ListarEventosCuidadorService().listar(cuidador, tipo_servicio=TipoServicio.GUARDERIA)
        )

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


