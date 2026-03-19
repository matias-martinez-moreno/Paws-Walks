class DomainError(Exception):
    # error base de dominio
    pass


class DomainValidationError(DomainError):
    # regla de negocio invalida
    pass


class ResourceNotFoundError(DomainError):
    # recurso no encontrado
    pass


class ConflictError(DomainError):
    # conflicto de estado de negocio
    pass


class AuthorizationError(DomainError):
    # actor autenticado sin permisos para ejecutar la operacion
    pass

