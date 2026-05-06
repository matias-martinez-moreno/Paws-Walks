# Factory Pattern - Crea la implementación de notificador correcta según entorno.
#
# Justificación del patrón:
#   El sistema requiere distintas variantes de notificación según el entorno:
#   - MOCK (dev/test): imprime en consola + persiste en BD → facilita depuración local.
#   - LOG_ONLY (staging/CI): solo persiste en BD → estado real sin ruido en consola.
#   - REAL (producción): envía email externo + persiste en BD → notificación completa.
#
#   La Factory centraliza esta decisión de instanciación. Los servicios que
#   necesitan notificar solo conocen la interfaz NotificadorBase; nunca
#   instancian un Notificador directamente. Esto cumple OCP y DIP (SOLID).

from django.conf import settings
from servicios.infra.notificador import NotificadorAsync, NotificadorLogOnly, NotificadorMock, NotificadorReal
from servicios.infra.weather_adapter import ClimaAdapterMock, OpenWeatherAdapter


class NotificadorFactory:
    """Selecciona y crea la implementación de NotificadorBase según ENV_TYPE.

    ENV_TYPE en settings.py:
        MOCK / DEV / DEVELOPMENT / TEST → NotificadorMock   (consola + BD)
        STAGING / LOG                   → NotificadorLogOnly (solo BD)
        REAL / PROD / PRODUCTION        → NotificadorReal    (email + BD)
    """

    @classmethod
    def crear(cls, env_type=None):
        tipo = env_type or getattr(settings, 'ENV_TYPE', 'MOCK')
        tipo = str(tipo).upper()

        if tipo in ('MOCK', 'DEV', 'DEVELOPMENT', 'TEST'):
            return NotificadorMock()
        if tipo in ('STAGING', 'LOG'):
            return NotificadorLogOnly()
        if tipo in ('REAL', 'PROD', 'PRODUCTION'):
            return NotificadorReal()
        if tipo in ('ASYNC',):
            return NotificadorAsync()

        # por defecto mock (entorno desconocido es siempre seguro)
        return NotificadorMock()


class ClimaAdapterFactory:
    """Crea el adapter de clima correcto según configuración.

    Si OPENWEATHER_API_KEY está definida → OpenWeatherAdapter (real).
    Si no → ClimaAdapterMock (desarrollo/test sin clave).
    """

    @classmethod
    def crear(cls):
        api_key = getattr(settings, "OPENWEATHER_API_KEY", "")
        if api_key:
            return OpenWeatherAdapter(api_key)
        return ClimaAdapterMock()
