import math


DIAS = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371
    lat1, lon1, lat2, lon2 = map(math.radians, [float(lat1), float(lon1), float(lat2), float(lon2)])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def time_to_minutes(t) -> int:
    """Acepta time object o string 'HH:MM' o 'HH:MM:SS'."""
    if t is None:
        return 0
    if hasattr(t, "hour"):
        return t.hour * 60 + t.minute
    parts = str(t).split(":")
    return int(parts[0]) * 60 + int(parts[1])


def normalizar_ciudad(ciudad) -> str:
    return " ".join(str(ciudad or "").strip().lower().split())


def tiempo_str(t) -> str | None:
    """Convierte time o string a formato HH:MM:SS serializable."""
    if t is None:
        return None
    if hasattr(t, "strftime"):
        return t.strftime("%H:%M:%S")
    return str(t)
