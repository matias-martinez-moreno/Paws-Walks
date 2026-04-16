from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.utils import timezone

from servicios.domain.exceptions import (
    ConflictError,
    DomainValidationError,
    ResourceNotFoundError,
)
from servicios.infra.factory import NotificadorFactory
from servicios.models import (
    EstadoSolicitud,
    Evento,
    Mascota,
    PerfilCuidador,
    PrecioServicio,
    SolicitudServicio,
    TipoMascota,
    TipoServicio,
    Usuario,
)


PASEO_DURACIONES_MINUTOS = (60, 90, 120, 150, 180)
ESTADOS_OCUPAN_CUPO = (
    EstadoSolicitud.PENDIENTE,
    EstadoSolicitud.ACEPTADO,
    EstadoSolicitud.COMPLETADO,
)


# modulo de servicios: disponibilidad y busqueda de reservas
from servicios.service_layer.utils import haversine_km as _haversine_km, time_to_minutes as _time_to_minutes
from servicios.service_layer.reputacion_servicios import (
    calificacion_promedio_count as _calificacion_promedio_count,
)
from servicios.service_layer.reservas_servicios import (
    CrearSolicitudConAsignacionService,
    CrearSolicitudConAsignacionEventoService,
    SolicitudServicioService,
)

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


def ya_paso_fin_programado_paseo(solicitud: SolicitudServicio) -> bool:
    """Verifica si ya pasó la hora de fin del paseo programado."""
    if not solicitud.idEvento or solicitud.tipoServicio != TipoServicio.PASEO:
        return False

    evento = solicitud.idEvento
    hora_fin = evento.horaFin

    if not hora_fin:
        return False

    ahora = timezone.localtime().time()
    return ahora >= hora_fin



