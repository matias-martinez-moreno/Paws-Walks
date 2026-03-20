# services.py — fachada de importacion (registry).
#
# IMPORTANTE: este archivo NO contiene logica de negocio.
# Es un punto de entrada unico que re-exporta los servicios
# definidos en service_layer/ para desacoplar las capas de
# presentacion (views, api/views) de la estructura interna
# del service layer.
#
# La logica de negocio real vive en service_layer/:
#   api_gateway.py         → punto de entrada API
#   api_validadores.py     → reglas de negocio API
#   api_servicios.py       → servicios de aplicacion
#   reservas_servicios.py  → ciclo de vida de solicitudes
#   disponibilidad.py      → busqueda de cuidadores
#   usuarios_servicios.py  → gestion de usuarios
#   (y demas modulos por bounded context)

from servicios.service_layer.api_validadores import (
	MapearErroresApiService,
	PoliticaAccesoServiciosApiService,
	ValidarBusquedaDisponibilidadApiService,
	ValidarCrearSolicitudApiService,
)
from servicios.service_layer.api_gateway import (
	ServiciosApiGatewayService,
)
from servicios.service_layer.api_servicios import (
	CrearSolicitudServicioAppService,
)
from servicios.service_layer.catalogo_cuidador_servicios import (
	ObtenerContextoServiciosCuidadorService,
	ObtenerPreciosActivosCuidadorService,
)
from servicios.service_layer.cuidador_servicios import (
	ProcesarAccionesCuidadorServiciosService,
)
from servicios.service_layer.disponibilidad import (
	NormalizarBusquedaReservaService,
)
from servicios.service_layer.interacciones import (
	ListarNotificacionesUsuarioService,
	ListarResenasRecibidasService,
	ListarSolicitudesDueñoService,
	NormalizarFiltrosNotificacionesService,
	ProcesarAccionNuevaReservaDueñoService,
	ProcesarAccionesCuidadorCalendarioService,
	ProcesarAccionesDueñoReservasService,
	ProcesarAccionesNotificacionesService,
)
from servicios.service_layer.perfiles_mascotas import (
	EditarPerfilUsuarioService,
	ListarAgendamientosCuidadorService,
	ListarMascotasDeDueñoService,
	ObtenerPerfilCuidadorService,
	ProcesarAccionesDueñoMascotasService,
)
from servicios.service_layer.usuarios_servicios import (
	AutenticacionService,
	ConstruirContextoHistorialSolicitudesService,
	ConstruirContextoPerfilPublicoService,
	ConstruirContextoRecuperacionPasswordService,
	ConstruirDatosPerfilUsuarioFormularioService,
	ConstruirDatosRegistroUsuarioFormularioService,
	CrearUsuarioAppService,
	FormatearTelefonoService,
	ResolverAccionPerfilCuidadorService,
	ResolverRutaNotificacionesService,
	ResolverRutaPostLoginService,
)
