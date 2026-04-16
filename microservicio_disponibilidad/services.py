"""
Microservicio de Disponibilidad — lógica de búsqueda de cuidadores.
Puerto del BuscarCuidadoresDisponiblesService de Django a SQLAlchemy + raw SQL.
Devuelve JSON ya mapeado al formato final de la API (igual que MapearResultadosDisponibilidadApiService).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import text

from db import engine
from utils import DIAS, haversine_km, normalizar_ciudad, time_to_minutes, tiempo_str

ESTADOS_OCUPAN_CUPO = ("pendiente", "aceptado", "completado")


def _uuid(val) -> str:
    """Normaliza UUID quitando guiones: Django guarda UUIDs en SQLite como hex de 32 chars."""
    return str(val or "").replace("-", "")


def _get_dueño(conn, dueño_id: str):
    row = conn.execute(
        text(
            'SELECT "idUsuario", rol, ciudad, latitud, longitud, "radioKm" '
            'FROM servicios_usuario WHERE "idUsuario" = :id AND rol = \'dueño\''
        ),
        {"id": _uuid(dueño_id)},
    ).fetchone()
    return dict(row._mapping) if row else None


def _get_mascota(conn, mascota_id: str, dueno_id: str):
    row = conn.execute(
        text(
            'SELECT "idMascota", tipo FROM servicios_mascota '
            'WHERE "idMascota" = :mid AND "idDue\u00f1o_id" = :did'
        ),
        {"mid": _uuid(mascota_id), "did": _uuid(dueno_id)},
    ).fetchone()
    return dict(row._mapping) if row else None


def _cupos_disponibles(conn, evento_id: str, fecha_str: str) -> tuple[int, int]:
    capacidad_row = conn.execute(
        text('SELECT "capacidadMaxima", "tipoServicio" FROM servicios_evento WHERE "idEvento" = :eid'),
        {"eid": _uuid(evento_id)},
    ).fetchone()
    if not capacidad_row:
        return 0, 1
    capacidad_total = max(1, int(capacidad_row.capacidadMaxima or 1))
    if capacidad_row.tipoServicio == "paseo":
        capacidad_total = min(capacidad_total, 4)

    ocupados = conn.execute(
        text(
            "SELECT COUNT(*) as cnt FROM servicios_solicitudservicio "
            'WHERE "idEvento_id" = :eid AND fecha = :fecha '
            "AND estado IN ('pendiente', 'aceptado', 'completado')"
        ),
        {"eid": _uuid(evento_id), "fecha": fecha_str},
    ).scalar()
    return max(0, capacidad_total - (ocupados or 0)), capacidad_total


def _get_precio(conn, cuidador_id: str, tipo_servicio: str):
    row = conn.execute(
        text(
            'SELECT "precioCOP", descripcion FROM servicios_precioservicio '
            'WHERE "idCuidador_id" = :cid AND "tipoServicio" = :tipo AND activo LIMIT 1'
        ),
        {"cid": _uuid(cuidador_id), "tipo": tipo_servicio},
    ).fetchone()
    return dict(row._mapping) if row else None


def _get_calificacion(conn, usuario_id: str) -> tuple:
    row = conn.execute(
        text(
            'SELECT AVG(estrellas) as prom, COUNT(*) as cnt '
            'FROM servicios_calificacion WHERE "idParaUsuario_id" = :uid'
        ),
        {"uid": _uuid(usuario_id)},
    ).fetchone()
    if not row or row.cnt == 0:
        return None, 0
    prom = round(float(row.prom), 1) if row.prom is not None else None
    return prom, int(row.cnt)


def _get_eventos_paseo(conn, dia_semana: str):
    rows = conn.execute(
        text(
            'SELECT e."idEvento", e."diaSemana", e."horaInicio", e."horaFin", '
            '       e."capacidadMaxima", e."precioCOP", '
            '       p."ciudadServicio", p."latitudServicio", p."longitudServicio", '
            '       p."radioKmServicio", p."tiposMascotaPreferidos", '
            '       p.descripcion as perfil_descripcion, '
            '       u."idUsuario" as cuidador_id, u.nombre, u.apellido, '
            '       u.ciudad as cuidador_ciudad '
            'FROM servicios_evento e '
            'JOIN servicios_perfilcuidador p ON p."idCuidador_id" = e."idCuidador_id" '
            'JOIN servicios_usuario u ON u."idUsuario" = p."idCuidador_id" '
            'WHERE e."tipoServicio" = \'paseo\' '
            '  AND e."diaSemana" = :dia '
            '  AND e."duracionSlotMinutos" IS NULL '
            '  AND e.disponible '
            '  AND u.verificado '
            'ORDER BY e."horaInicio"'
        ),
        {"dia": dia_semana},
    ).fetchall()
    return [dict(r._mapping) for r in rows]


def _get_eventos_guarderia(conn, dias: list[str]):
    placeholders = ", ".join([f"'{{d}}'" for d in dias])
    # Build with explicit IN list to avoid tuple binding issues
    in_clause = ", ".join([f"'{d}'" for d in dias])
    rows = conn.execute(
        text(
            f'SELECT e."idEvento", e."diaSemana", e."horaInicio", e."horaFin", '
            f'       e."capacidadMaxima", e."precioCOP", e."idCuidador_id" as perfil_id, '
            f'       p."ciudadServicio", p."latitudServicio", p."longitudServicio", '
            f'       p."radioKmServicio", p."tiposMascotaPreferidos", '
            f'       p.descripcion as perfil_descripcion, '
            f'       u."idUsuario" as cuidador_id, u.nombre, u.apellido, '
            f'       u.ciudad as cuidador_ciudad '
            f'FROM servicios_evento e '
            f'JOIN servicios_perfilcuidador p ON p."idCuidador_id" = e."idCuidador_id" '
            f'JOIN servicios_usuario u ON u."idUsuario" = p."idCuidador_id" '
            f'WHERE e."tipoServicio" = \'guarderia\' '
            f'  AND e."diaSemana" IN ({in_clause}) '
            f'  AND e."duracionSlotMinutos" IS NULL '
            f'  AND e.disponible '
            f'  AND u.verificado '
            f'ORDER BY u."idUsuario", e."horaInicio"'
        )
    ).fetchall()
    return [dict(r._mapping) for r in rows]


class BuscarDisponibilidadService:
    """Busca cuidadores disponibles. Devuelve payload final mapeado listo para la API."""

    def buscar(self, data: dict) -> list[dict] | dict:
        tipo = data.get("tipoServicio", "")
        dueño_id = str(data.get("idDueño_id", ""))
        mascota_id = str(data.get("idMascota_id", ""))

        with engine.connect() as conn:
            dueño = _get_dueño(conn, dueño_id)
            if not dueño:
                return {"error": "dueño no encontrado", "status": 404}

            mascota = _get_mascota(conn, mascota_id, dueño_id)
            if not mascota:
                return {"error": "mascota no encontrada", "status": 404}

            if tipo == "paseo":
                return self._buscar_paseo(conn, dueño, mascota, data)
            elif tipo == "guarderia":
                return self._buscar_guarderia(conn, dueño, mascota, data)
            return []

    # ------------------------------------------------------------------
    # PASEO
    # ------------------------------------------------------------------

    def _buscar_paseo(self, conn, dueño: dict, mascota: dict, data: dict) -> list[dict]:
        if mascota["tipo"] != "perro":
            return {"error": "el paseo solo está disponible para perros", "status": 400}

        fecha_str = str(data.get("fecha", ""))
        try:
            fecha = datetime.strptime(fecha_str, "%Y-%m-%d").date()
        except ValueError:
            return {"error": "formato de fecha inválido", "status": 400}

        if fecha < date.today():
            return {"error": "la fecha no puede ser en el pasado", "status": 400}

        duracion_filtrada = data.get("duracionMinutos")
        if duracion_filtrada is not None:
            duracion_filtrada = int(duracion_filtrada)

        dia_semana = DIAS[fecha.weekday()]
        eventos = _get_eventos_paseo(conn, dia_semana)

        ref_lat = dueño.get("latitud")
        ref_lon = dueño.get("longitud")
        if data.get("latitudPaseo"):
            ref_lat = data["latitudPaseo"]
        if data.get("longitudPaseo"):
            ref_lon = data["longitudPaseo"]
        ciudad_ref = str(data.get("ciudadPaseo") or dueño.get("ciudad") or "").strip()
        usar_radio = bool(ref_lat and ref_lon)

        resultado = []
        precio_min = data.get("precioMinHora")
        precio_max = data.get("precioMaxHora")
        hora_inicio_filtro = data.get("horaInicio")
        hora_fin_filtro = data.get("horaFin")

        for ev in eventos:
            dur_evento = time_to_minutes(ev["horaFin"]) - time_to_minutes(ev["horaInicio"])
            if duracion_filtrada is not None and dur_evento != duracion_filtrada:
                continue

            cupos_disp, cupo_max = _cupos_disponibles(conn, ev["idEvento"], fecha_str)
            if cupos_disp < 1:
                continue

            precio = _get_precio(conn, ev["cuidador_id"], "paseo")
            if not precio:
                continue

            tarifa_hora = ev["precioCOP"] or precio["precioCOP"]
            if precio_min is not None and tarifa_hora < precio_min:
                continue
            if precio_max is not None and tarifa_hora > precio_max:
                continue

            if hora_inicio_filtro and tiempo_str(ev["horaInicio"]) < str(hora_inicio_filtro):
                continue
            if hora_fin_filtro and tiempo_str(ev["horaFin"]) > str(hora_fin_filtro):
                continue

            distancia_km = None
            lat_op = ev.get("latitudServicio")
            lon_op = ev.get("longitudServicio")
            radio_op = ev.get("radioKmServicio")
            ciudad_op = ev.get("ciudadServicio") or ev.get("cuidador_ciudad") or ""

            if usar_radio and lat_op and lon_op:
                distancia_km = haversine_km(ref_lat, ref_lon, lat_op, lon_op)
                if radio_op and distancia_km > float(radio_op):
                    continue
                if not radio_op and ciudad_ref and normalizar_ciudad(ciudad_op) != normalizar_ciudad(ciudad_ref):
                    continue
            elif ciudad_ref and normalizar_ciudad(ciudad_op) != normalizar_ciudad(ciudad_ref):
                continue

            duracion_horas = dur_evento / 60.0
            prom, cnt = _get_calificacion(conn, ev["cuidador_id"])

            resultado.append({
                "cuidadorId": str(ev["cuidador_id"]),
                "cuidadorNombre": ev["nombre"],
                "cuidadorApellido": ev["apellido"],
                "tipoServicio": "paseo",
                "eventoId": str(ev["idEvento"]),
                "fecha": fecha_str,
                "horaInicio": tiempo_str(ev["horaInicio"]),
                "horaFin": tiempo_str(ev["horaFin"]),
                "tarifaHora": int(tarifa_hora),
                "tarifaTotal": int(tarifa_hora * duracion_horas),
                "cupoMaximo": cupo_max,
                "cuposDisponibles": cupos_disp,
                "totalSlotsDisponibles": 0,
                "distanciaKm": round(distancia_km, 1) if distancia_km is not None else None,
                "calificacionPromedio": prom,
                "calificacionCount": cnt,
                "descripcionServicio": precio.get("descripcion") or ev.get("perfil_descripcion") or "",
            })

        resultado.sort(key=lambda x: (
            (x["distanciaKm"] if x["distanciaKm"] is not None else 9999),
            x["horaInicio"] or "",
        ))
        return resultado

    # ------------------------------------------------------------------
    # GUARDERIA
    # ------------------------------------------------------------------

    def _buscar_guarderia(self, conn, dueño: dict, mascota: dict, data: dict) -> list[dict]:
        fecha_inicio_str = str(data.get("fechaInicioGuarderia", ""))
        fecha_fin_str = str(data.get("fechaFinGuarderia") or fecha_inicio_str)
        try:
            fecha_inicio = datetime.strptime(fecha_inicio_str, "%Y-%m-%d").date()
            fecha_fin = datetime.strptime(fecha_fin_str, "%Y-%m-%d").date()
        except ValueError:
            return {"error": "formato de fechas inválido", "status": 400}

        if fecha_inicio < date.today():
            return {"error": "la fecha inicio no puede ser en el pasado", "status": 400}

        dias_requeridos = set()
        d = fecha_inicio
        while d <= fecha_fin:
            dias_requeridos.add(DIAS[d.weekday()])
            d += timedelta(days=1)

        num_dias = (fecha_fin - fecha_inicio).days + 1
        eventos = _get_eventos_guarderia(conn, list(dias_requeridos))

        ref_lat = dueño.get("latitud")
        ref_lon = dueño.get("longitud")
        ciudad_ref = str(dueño.get("ciudad") or "").strip()
        usar_radio = bool(ref_lat and ref_lon)
        precio_min = data.get("precioMinHora")
        precio_max = data.get("precioMaxHora")

        # Agrupar eventos por cuidador
        eventos_por_cuidador: dict = {}
        for ev in eventos:
            cid = ev["cuidador_id"]
            if cid not in eventos_por_cuidador:
                eventos_por_cuidador[cid] = {"meta": ev, "por_dia": {}}
            eventos_por_cuidador[cid]["por_dia"].setdefault(ev["diaSemana"], []).append(ev)

        resultado = []
        for cid, info in eventos_por_cuidador.items():
            meta = info["meta"]
            precio = _get_precio(conn, cid, "guarderia")
            if not precio:
                continue

            tipos_pref = (meta.get("tiposMascotaPreferidos") or "ambos").lower().strip()
            if tipos_pref != "ambos" and mascota["tipo"] not in [t.strip() for t in tipos_pref.split(",")]:
                continue

            distancia_km = None
            lat_op = meta.get("latitudServicio")
            lon_op = meta.get("longitudServicio")
            radio_op = meta.get("radioKmServicio")
            ciudad_op = meta.get("ciudadServicio") or meta.get("cuidador_ciudad") or ""

            if usar_radio and lat_op and lon_op:
                distancia_km = haversine_km(ref_lat, ref_lon, lat_op, lon_op)
                if radio_op and distancia_km > float(radio_op):
                    continue
                if not radio_op and ciudad_ref and normalizar_ciudad(ciudad_op) != normalizar_ciudad(ciudad_ref):
                    continue
            elif ciudad_ref and normalizar_ciudad(ciudad_op) != normalizar_ciudad(ciudad_ref):
                continue

            slots_guarderia = []
            d = fecha_inicio
            while d <= fecha_fin:
                dia = DIAS[d.weekday()]
                opciones = info["por_dia"].get(dia, [])
                for ev in sorted(opciones, key=lambda e: time_to_minutes(e["horaFin"]) - time_to_minutes(e["horaInicio"]), reverse=True):
                    cupos_disp, cupo_max = _cupos_disponibles(conn, ev["idEvento"], d.isoformat())
                    if cupos_disp < 1:
                        continue
                    dur_max = time_to_minutes(ev["horaFin"]) - time_to_minutes(ev["horaInicio"])
                    if dur_max < 60:
                        continue
                    duracion_opciones = list(range(60, dur_max + 1, 30))
                    tarifa_hora = ev["precioCOP"] or precio["precioCOP"]
                    if precio_min is not None and tarifa_hora < precio_min:
                        continue
                    if precio_max is not None and tarifa_hora > precio_max:
                        continue
                    slots_guarderia.append({
                        "eventoId": str(ev["idEvento"]),
                        "fecha": d.isoformat(),
                        "horaInicio": tiempo_str(ev["horaInicio"]),
                        "horaFin": tiempo_str(ev["horaFin"]),
                        "cuposDisponibles": cupos_disp,
                        "cupoMaximo": cupo_max,
                        "duracionOpciones": duracion_opciones,
                    })
                d += timedelta(days=1)

            if not slots_guarderia:
                continue

            slot0 = slots_guarderia[0]
            dur_max_slot0 = time_to_minutes(slot0["horaFin"]) - time_to_minutes(slot0["horaInicio"])
            tarifa_hora = meta.get("precioCOP") or precio["precioCOP"]
            prom, cnt = _get_calificacion(conn, cid)
            duracion_opciones_default = slot0.get("duracionOpciones") or []

            resultado.append({
                "cuidadorId": str(cid),
                "cuidadorNombre": meta["nombre"],
                "cuidadorApellido": meta["apellido"],
                "tipoServicio": "guarderia",
                "eventoId": slot0["eventoId"],
                "fecha": slot0["fecha"],
                "horaInicio": slot0["horaInicio"],
                "horaFin": slot0["horaFin"],
                "tarifaHora": int(tarifa_hora),
                "tarifaTotal": int(tarifa_hora * (dur_max_slot0 / 60.0)),
                "cupoMaximo": slot0["cupoMaximo"],
                "cuposDisponibles": slot0["cuposDisponibles"],
                "totalSlotsDisponibles": len(slots_guarderia),
                "distanciaKm": round(distancia_km, 1) if distancia_km is not None else None,
                "calificacionPromedio": prom,
                "calificacionCount": cnt,
                "descripcionServicio": precio.get("descripcion") or meta.get("perfil_descripcion") or "",
                "slotsGuarderia": slots_guarderia,
                "numDias": num_dias,
                "fechaInicio": fecha_inicio_str,
                "fechaFin": fecha_fin_str,
                "duracionOpciones": duracion_opciones_default,
                "duracionMaxima": duracion_opciones_default[-1] if duracion_opciones_default else 0,
            })

        resultado.sort(key=lambda x: (
            x["distanciaKm"] if x["distanciaKm"] is not None else 9999,
            x["fecha"] or "",
            x["horaInicio"] or "",
        ))
        return resultado
