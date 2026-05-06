import logging

from servicios.domain.ports import ClimaPort

_logger = logging.getLogger(__name__)


class ClimaService:
    """Servicio de dominio para consultar el clima de una ciudad.

    Depende de ClimaPort (abstracción), nunca de un Adapter concreto.
    El caller inyecta la implementación correcta via ClimaAdapterFactory.
    Esto cumple D (Dependency Inversion) de SOLID.
    """

    def __init__(self, clima_port: ClimaPort):
        self._port = clima_port

    def obtener_clima_para_paseo(self, ciudad: str) -> dict:
        """Retorna datos del clima y evalúa si es apto para un paseo."""
        if not ciudad or not ciudad.strip():
            return self._clima_no_disponible("ciudad no especificada")

        try:
            return self._port.obtener_clima(ciudad.strip())
        except Exception as exc:
            _logger.warning("No se pudo obtener clima para '%s': %s", ciudad, exc)
            return self._clima_no_disponible(str(exc))

    def _clima_no_disponible(self, motivo: str) -> dict:
        return {
            "ciudad": "No disponible",
            "temperatura": None,
            "descripcion": "Información no disponible",
            "icono": None,
            "humedad": None,
            "apto_para_paseo": None,
            "error": motivo,
        }
