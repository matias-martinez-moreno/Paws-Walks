# factory pattern - crea notificador según entorno
from django.conf import settings
from servicios.infra.notificador import NotificadorMock, NotificadorReal


class NotificadorFactory:
    """factory que decide mock o real según ENV_TYPE"""

    @classmethod
    def crear(cls, env_type=None):
        # lee variable de entorno o usa mock por defecto
        tipo = env_type or getattr(settings, 'ENV_TYPE', 'MOCK')
        tipo = str(tipo).upper()
        
        # devuelve mock o real según configuración
        if tipo in ('MOCK', 'DEV', 'DEVELOPMENT', 'TEST'):
            return NotificadorMock()
        if tipo in ('REAL', 'PROD', 'PRODUCTION'):
            return NotificadorReal()
        
        # por defecto mock
        return NotificadorMock()
