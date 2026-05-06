import logging

from servicios.domain.ports import AliadoPort

_logger = logging.getLogger(__name__)


class AliadoService:
    """Servicio de dominio para consultar el endpoint del equipo aliado.

    Depende de AliadoPort (abstracción), nunca de un Adapter concreto.
    El caller inyecta la implementación correcta vía AliadoAdapterFactory.
    Cumple D (Dependency Inversion) de SOLID.
    """

    def __init__(self, aliado_port: AliadoPort):
        self._port = aliado_port

    def obtener_estado_aliado(self) -> dict:
        try:
            return self._port.obtener_estado_sistema()
        except Exception as exc:
            _logger.warning("Aliado no disponible: %s", exc)
            return {
                "fuente": "Equipo aliado",
                "disponible": False,
                "datos": {"error": str(exc)},
                "consultado_en": None,
            }
