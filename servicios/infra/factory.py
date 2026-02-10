"""
Patrón Factory para instanciar dependencias externas.
Decide el comportamiento según ENV_TYPE (MOCK vs REAL).
"""
from django.conf import settings

from servicios.infra.notificador import NotificadorMock, NotificadorReal


class NotificadorFactory:
    """
    Factory que crea la implementación del Notificador según el entorno.
    ENV_TYPE:
        - 'MOCK' o 'DEV': NotificadorMock (imprime en consola)
        - 'REAL' o 'PRODUCTION': NotificadorReal (envío real de correos)
    """

    _instancia = None

    @classmethod
    def crear(cls, env_type=None):
        """
        Crea la implementación del Notificador según variables de entorno.

        Args:
            env_type: Override opcional. Si no se pasa, usa settings.ENV_TYPE.

        Returns:
            NotificadorBase: NotificadorMock o NotificadorReal
        """
        tipo = env_type or getattr(
            settings,
            'ENV_TYPE',
            'MOCK'
        )
        tipo = str(tipo).upper()

        if tipo in ('MOCK', 'DEV', 'DEVELOPMENT', 'TEST'):
            return NotificadorMock()
        if tipo in ('REAL', 'PROD', 'PRODUCTION'):
            return NotificadorReal()

        # Por defecto: MOCK en entornos desconocidos (seguro para desarrollo)
        return NotificadorMock()

    @classmethod
    def get_notificador(cls):
        """
        Retorna una instancia singleton del Notificador.
        Útil para inyección de dependencias en el Service.
        """
        if cls._instancia is None:
            cls._instancia = cls.crear()
        return cls._instancia
