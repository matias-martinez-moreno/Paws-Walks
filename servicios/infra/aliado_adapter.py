"""Adapter para consumir el endpoint JSON del equipo aliado.

Cumple Adapter Pattern + Inversión de Dependencias: implementa AliadoPort,
así el service layer no depende del esquema concreto del aliado, solo
de la interfaz uniforme.

Cuando el equipo aliado entregue su URL, basta con setear ALIADO_API_URL
en settings y la fábrica usará el adapter real en lugar del mock.
"""
import logging
from datetime import datetime, timezone

import requests
from django.utils.translation import gettext as _

from servicios.domain.ports import AliadoPort

_logger = logging.getLogger(__name__)


class AliadoHttpAdapter(AliadoPort):
    """Adapter HTTP real para consumir el endpoint del equipo aliado."""

    def __init__(self, base_url: str, timeout: int = 5):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def obtener_estado_sistema(self) -> dict:
        url = f"{self._base_url}/api/v1/sistema/estado/"
        try:
            resp = requests.get(url, timeout=self._timeout)
            resp.raise_for_status()
            data = resp.json()
            return {
                "fuente": data.get("sistema", "Equipo aliado"),
                "disponible": True,
                "datos": data,
                "consultado_en": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            _logger.warning("Aliado no disponible (%s): %s", url, exc)
            return {
                "fuente": _("Partner team"),
                "disponible": False,
                "datos": {"error": str(exc)},
                "consultado_en": datetime.now(timezone.utc).isoformat(),
            }


class AliadoMockAdapter(AliadoPort):
    """Adapter mock para entornos sin URL del aliado configurada.

    Devuelve un payload de demostración con la misma forma que el
    Adapter real, para no bloquear el desarrollo de la integración.
    """

    def obtener_estado_sistema(self) -> dict:
        return {
            "fuente": _("Partner team (mock)"),
            "disponible": True,
            "datos": {
                "sistema": _("Partner demo service"),
                "estado": _("operational"),
                "metricas": {
                    "usuarios_activos": 142,
                    "transacciones_dia": 38,
                },
                "nota": _("Set ALIADO_API_URL in settings to use the real endpoint."),
            },
            "consultado_en": datetime.now(timezone.utc).isoformat(),
        }
