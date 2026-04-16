# modulo de servicios: disponibilidad para endpoints API
from servicios.domain.exceptions import DomainValidationError, ResourceNotFoundError
from servicios.models import TipoServicio, Usuario
from servicios.service_layer.disponibilidad import (
    BuscarCuidadoresDisponiblesService,
    FiltrarResultadosDisponibilidadService,
)


class BuscarDisponibilidadDesdeApiService:
    """Orquesta busqueda de disponibilidad para capa DRF sin logica en views."""

    def __init__(
        self,
        buscador: BuscarCuidadoresDisponiblesService | None = None,
        filtro: FiltrarResultadosDisponibilidadService | None = None,
    ):
        self._buscador = buscador or BuscarCuidadoresDisponiblesService()
        self._filtro = filtro or FiltrarResultadosDisponibilidadService()

    def buscar(self, data: dict) -> list:
        try:
            dueno = Usuario.objects.get(idUsuario=data["idDueño_id"])
        except Usuario.DoesNotExist:
            raise ResourceNotFoundError("el dueño no existe")

        tipo_servicio = data.get("tipoServicio")

        if tipo_servicio == TipoServicio.PASEO:
            fecha = data.get("fecha")
            if fecha is None:
                raise DomainValidationError("fecha es requerida para paseo")

            duracion = data.get("duracionMinutos")

            resultados = self._buscador.buscar(
                dueño=dueno,
                mascota_id=str(data["idMascota_id"]),
                fecha_o_str=fecha,
                duracion_minutos=duracion,
                solo_ciudad=True,
                ciudad_referencia=data.get("ciudadPaseo"),
                latitud_referencia=data.get("latitudPaseo"),
                longitud_referencia=data.get("longitudPaseo"),
            )
        elif tipo_servicio == TipoServicio.GUARDERIA:
            fecha_inicio = data.get("fechaInicioGuarderia")
            if fecha_inicio is None:
                raise DomainValidationError("fechaInicioGuarderia es requerida para guarderia")

            fecha_fin = data.get("fechaFinGuarderia") or fecha_inicio
            if fecha_fin < fecha_inicio:
                raise DomainValidationError(
                    "fechaFinGuarderia debe ser igual o posterior a fechaInicioGuarderia"
                )

            resultados = self._buscador.buscar_cuidado(
                dueño=dueno,
                mascota_id=str(data["idMascota_id"]),
                fecha_inicio_str=fecha_inicio.isoformat(),
                fecha_fin_str=fecha_fin.isoformat(),
                solo_ciudad=True,
            )
        else:
            raise DomainValidationError("tipoServicio invalido")

        return self._filtro.filtrar(
            resultados,
            precio_min_hora=data.get("precioMinHora"),
            precio_max_hora=data.get("precioMaxHora"),
            hora_inicio=data.get("horaInicio"),
            hora_fin=data.get("horaFin"),
        )
