import logging

import requests

from servicios.domain.ports import ClimaPort

_logger = logging.getLogger(__name__)

_OPENWEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"

# Condiciones que NO son aptas para paseo (códigos grupo OpenWeather)
_GRUPOS_NO_APTOS = {
    "Thunderstorm",  # 2xx
    "Drizzle",       # 3xx
    "Rain",          # 5xx
    "Snow",          # 6xx
    "Tornado",       # 781
}


def _es_apto_para_paseo(condicion: str, temp: float) -> bool:
    return condicion not in _GRUPOS_NO_APTOS and 10.0 <= temp <= 35.0


class OpenWeatherAdapter(ClimaPort):
    """Adapter concreto para la API de OpenWeatherMap.

    Implementa ClimaPort — el service layer nunca importa esta clase directamente,
    siempre recibe una instancia de ClimaPort por inyección de dependencias.
    """

    def __init__(self, api_key: str):
        self._api_key = api_key

    def obtener_clima(self, ciudad: str) -> dict:
        try:
            resp = requests.get(
                _OPENWEATHER_URL,
                params={
                    "q": ciudad,
                    "appid": self._api_key,
                    "units": "metric",
                    "lang": "es",
                },
                timeout=5,
            )
            resp.raise_for_status()
            data = resp.json()

            condicion = data["weather"][0]["main"]
            temp = data["main"]["temp"]

            return {
                "ciudad": data.get("name", ciudad),
                "temperatura": round(temp, 1),
                "descripcion": data["weather"][0]["description"].capitalize(),
                "icono": data["weather"][0]["icon"],
                "humedad": data["main"]["humidity"],
                "apto_para_paseo": _es_apto_para_paseo(condicion, temp),
            }
        except Exception as exc:
            _logger.warning("OpenWeather no disponible para '%s': %s", ciudad, exc)
            raise


class ClimaAdapterMock(ClimaPort):
    """Adapter mock para entornos de desarrollo/test — no llama a ninguna API."""

    def obtener_clima(self, ciudad: str) -> dict:
        return {
            "ciudad": ciudad,
            "temperatura": 22.0,
            "descripcion": "Parcialmente nublado",
            "icono": "02d",
            "humedad": 60,
            "apto_para_paseo": True,
        }
