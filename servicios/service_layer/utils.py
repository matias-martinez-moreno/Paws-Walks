# utilidades puras del service layer (sin dependencias de modelos)
import math
from datetime import time


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    """Distancia en km entre dos puntos (Haversine)."""
    R = 6371
    lat1, lon1, lat2, lon2 = map(math.radians, [float(lat1), float(lon1), float(lat2), float(lon2)])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    return R * c


def time_to_minutes(t: time) -> int:
    """Convierte time a minutos desde medianoche."""
    return t.hour * 60 + t.minute


def minutes_to_time(m: int) -> time:
    """Convierte minutos desde medianoche a time (HH:MM, sin segundos)."""
    h, mn = divmod(m % (24 * 60), 60)
    return time(h, mn, 0)


def normalizar_ciudad(ciudad: str | None) -> str:
    return " ".join(str(ciudad or "").strip().lower().split())
