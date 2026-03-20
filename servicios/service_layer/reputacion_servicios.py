# modulo de servicios: utilidades compartidas de reseñas y reputación
from __future__ import annotations

from django.db.models import Avg, Count

from servicios.models import Calificacion, CalificacionMascota, SolicitudServicio, Usuario


def calificacion_promedio_count(usuario_destino: Usuario) -> tuple[float | None, int]:
    """Retorna (promedio_estrellas, cantidad) para un usuario destinatario."""
    agg = Calificacion.objects.filter(idParaUsuario=usuario_destino).aggregate(
        prom=Avg("estrellas"), cnt=Count("pk")
    )
    prom = float(agg["prom"]) if agg["prom"] is not None else None
    cnt = agg["cnt"] or 0
    return (round(prom, 1) if prom is not None else None, cnt)


def calificacion_de_autor_en_solicitud(
    solicitud: SolicitudServicio,
    autor: Usuario,
) -> Calificacion | None:
    for calificacion in solicitud.calificaciones.all():
        if calificacion.idDe_id == autor.idUsuario:
            return calificacion
    return None


def calificacion_mascota_de_autor_en_solicitud(
    solicitud: SolicitudServicio,
    autor: Usuario,
) -> CalificacionMascota | None:
    for calificacion in solicitud.calificaciones_mascota.all():
        if calificacion.idDe_id == autor.idUsuario:
            return calificacion
    return None


def resenas_mascotas_por_ids(mascotas_ids: list) -> dict:
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
