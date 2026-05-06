from abc import ABC, abstractmethod


class ClimaPort(ABC):
    """Abstracción para obtener datos del clima.

    El Patrón Adapter (+ Inversión de Dependencias) exige que el service layer
    dependa de esta interfaz, no de una implementación concreta (OpenWeather, etc.).
    Para cambiar de proveedor basta crear otro Adapter que implemente este contrato.
    """

    @abstractmethod
    def obtener_clima(self, ciudad: str) -> dict:
        """Retorna datos del clima para la ciudad dada.

        Returns:
            {
              "ciudad": str,
              "temperatura": float,    # °C
              "descripcion": str,
              "icono": str,            # código de icono del proveedor
              "humedad": int,          # porcentaje
              "apto_para_paseo": bool  # regla de negocio: temp 10-35°C y no llueve
            }
        Raises:
            ExternalServiceError si el proveedor no responde.
        """
