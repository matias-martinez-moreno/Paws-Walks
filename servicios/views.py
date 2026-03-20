from urllib.parse import urlencode

from django.contrib.auth import login, logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View

from servicios.domain.exceptions import DomainError
from servicios.models import SexoMascota, TamanoMascota, TipoMascota, Usuario
from servicios.services import (
    AutenticacionService,
    ConstruirContextoHistorialSolicitudesService,
    ConstruirContextoPerfilPublicoService,
    ConstruirContextoRecuperacionPasswordService,
    ConstruirDatosRegistroUsuarioFormularioService,
    ConstruirDatosPerfilUsuarioFormularioService,
    CrearUsuarioAppService,
    CrearSolicitudServicioAppService,
    EditarPerfilUsuarioService,
    ListarAgendamientosCuidadorService,
    FormatearTelefonoService,
    ListarMascotasDeDueñoService,
    ListarNotificacionesUsuarioService,
    NormalizarBusquedaReservaService,
    NormalizarFiltrosNotificacionesService,
    ObtenerContextoServiciosCuidadorService,
    ObtenerPreciosActivosCuidadorService,
    ListarResenasRecibidasService,
    ListarSolicitudesDueñoService,
    ObtenerPerfilCuidadorService,
    ProcesarAccionNuevaReservaDueñoService,
    ProcesarAccionesCuidadorCalendarioService,
    ProcesarAccionesCuidadorServiciosService,
    ProcesarAccionesDueñoMascotasService,
    ProcesarAccionesDueñoReservasService,
    ProcesarAccionesNotificacionesService,
    ResolverAccionPerfilCuidadorService,
    ResolverRutaNotificacionesService,
    ResolverRutaPostLoginService,
)


class SignupView(View):
    _registro_form_service = ConstruirDatosRegistroUsuarioFormularioService()
    _crear_usuario_service = CrearUsuarioAppService()

    def get(self, request):
        return render(request, "servicios/signup.html")

    def post(self, request):
        campos, payload = self._registro_form_service.construir(request.POST)

        try:
            self._crear_usuario_service.crear_usuario(payload)
        except DomainError as e:
            return render(request, "servicios/signup.html", {**campos, "error": str(e)})

        return redirect("login")


class LoginView(View):
    _auth_service = AutenticacionService()
    _ruta_post_login_service = ResolverRutaPostLoginService()

    def get(self, request):
        return render(request, "servicios/login.html")

    def post(self, request):
        username = request.POST.get("username")
        password = request.POST.get("password")
        try:
            usuario = self._auth_service.autenticar(username, password)
        except DomainError as e:
            return render(request, "servicios/login.html", {"error": str(e), "username": username})
        login(request, usuario.user)
        return redirect(self._ruta_post_login_service.resolver(usuario))


class LogoutView(View):
    def post(self, request):
        logout(request)
        return redirect("login")


class PasswordResetRequestView(View):
    def get(self, request):
        return render(request, "servicios/password_reset_request.html")

    def post(self, request):
        ctx = ConstruirContextoRecuperacionPasswordService().construir(
            request.POST.get("identificador")
        )
        return render(request, "servicios/password_reset_request.html", ctx)


class TerminosCondicionesView(View):
    """Página pública con los términos y condiciones y marco legal aplicable."""
    
    def get(self, request):
        return render(request, "servicios/terminos_condiciones.html")


class PoliticaPrivacidadView(View):
    """Página pública con política de privacidad y tratamiento de datos personales."""

    def get(self, request):
        return render(request, "servicios/politica_privacidad.html")


def _get_usuario(request):
    return getattr(request.user, "perfil_usuario", None)


PREFIJOS_TELEFONO = list(FormatearTelefonoService.PREFIJOS_TELEFONO)


def _get_resenas_context(request, usuario):
    orden_resenas = (
        request.GET.get("orden_resenas")
        or request.POST.get("orden_resenas")
        or "recientes"
    )
    return ListarResenasRecibidasService().listar(usuario, orden=orden_resenas)


from servicios.presentation_constants import HISTORIAL_ESTADO_OPCIONES, HISTORIAL_SERVICIO_OPCIONES


# ── Dueño ─────────────────────────────────────────────────

class DashboardDueñoView(LoginRequiredMixin, View):
    def get(self, request):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        try:
            ctx_sol = ListarSolicitudesDueñoService().listar(usuario)
            mascotas = ListarMascotasDeDueñoService().listar(usuario)
            notificaciones_ctx = ListarNotificacionesUsuarioService().listar(usuario, limite=6)
        except DomainError as e:
            return render(request, "servicios/dashboard_dueño.html", {"error": str(e), "usuario": usuario})

        solicitudes_futuras = list(ctx_sol.get("solicitudes_futuras", []))

        return render(
            request,
            "servicios/dashboard_dueño.html",
            {
                **ctx_sol,
                **notificaciones_ctx,
                "mascotas": mascotas,
                "mascotas_resumen": mascotas[:4],
                "solicitudes_futuras_resumen": solicitudes_futuras[:5],
                "reservas_totales": ctx_sol.get("reservas_totales", 0),
                "reservas_pendientes": ctx_sol.get("reservas_pendientes", 0),
                "reservas_aceptadas": ctx_sol.get("reservas_aceptadas", 0),
                "usuario": usuario,
            },
        )


class DueñoNuevaReservaView(LoginRequiredMixin, View):
    _normalizador_busqueda = NormalizarBusquedaReservaService()
    _procesador_accion = ProcesarAccionNuevaReservaDueñoService()

    def _busqueda_default(self, usuario):
        return self._normalizador_busqueda.busqueda_default(usuario)

    def _busqueda_from_post(self, request, usuario):
        return self._normalizador_busqueda.busqueda_from_source(request.POST, usuario)

    def get(self, request):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        mascotas = ListarMascotasDeDueñoService().listar(usuario)
        return render(
            request,
            "servicios/dueño_nueva_reserva.html",
            {
                "mascotas": mascotas,
                "usuario": usuario,
                "busqueda": self._busqueda_default(usuario),
                "cuidadores_disponibles": None,
            },
        )

    def post(self, request):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        mascotas = ListarMascotasDeDueñoService().listar(usuario)
        try:
            resultado = self._procesador_accion.procesar(usuario, request.POST)
        except DomainError as e:
            return render(
                request,
                "servicios/dueño_nueva_reserva.html",
                {
                    "mascotas": mascotas,
                    "usuario": usuario,
                    "error": str(e),
                    "busqueda": self._busqueda_from_post(request, usuario),
                    "cuidadores_disponibles": None,
                },
            )

        if resultado.get("modo") == "redirect":
            return redirect(resultado.get("ruta", "dueño_mis_reservas"))

        return render(request, "servicios/dueño_nueva_reserva.html", {
            "mascotas": mascotas,
            "usuario": usuario,
            "cuidadores_disponibles": resultado.get("cuidadores_disponibles"),
            "busqueda": resultado.get("busqueda"),
        })


class DueñoMisReservasView(LoginRequiredMixin, View):
    def get(self, request):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        try:
            ctx_sol = ListarSolicitudesDueñoService().listar(usuario)
        except DomainError as e:
            return render(request, "servicios/dueño_mis_reservas.html", {"error": str(e), "usuario": usuario})

        historial_ctx = ConstruirContextoHistorialSolicitudesService().construir(
            ctx_sol.get("solicitudes_pasadas", []),
            request.GET,
            {"cuidador"},
            HISTORIAL_ESTADO_OPCIONES,
            HISTORIAL_SERVICIO_OPCIONES,
        )

        return render(
            request,
            "servicios/dueño_mis_reservas.html",
            {
                **ctx_sol,
                "solicitudes_pasadas": historial_ctx["items_filtrados"],
                "historial_estado_actual": historial_ctx["historial_estado_actual"],
                "historial_servicio_actual": historial_ctx["historial_servicio_actual"],
                "historial_estado_opciones": HISTORIAL_ESTADO_OPCIONES,
                "historial_servicio_opciones": HISTORIAL_SERVICIO_OPCIONES,
                "historial_filtrado_total": historial_ctx["historial_filtrado_total"],
                "resena_pendiente_solicitud_id": historial_ctx["resena_pendiente_solicitud_id"],
                "resena_pendiente_objetivo": historial_ctx["resena_pendiente_objetivo"],
                "usuario": usuario,
            },
        )

    def post(self, request):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        resultado = ProcesarAccionesDueñoReservasService().procesar(usuario, request.POST)
        nivel = resultado.get("nivel")
        mensaje = resultado.get("mensaje")
        if mensaje and nivel == "success":
            messages.success(request, mensaje)
        elif mensaje and nivel == "info":
            messages.info(request, mensaje)
        elif mensaje and nivel == "error":
            messages.error(request, mensaje)
        return redirect("dueño_mis_reservas")


class NotificacionesView(LoginRequiredMixin, View):
    template_name = "servicios/notificaciones.html"
    _filtros_service = NormalizarFiltrosNotificacionesService()
    _ruta_notificaciones_service = ResolverRutaNotificacionesService()

    def _ruta_por_rol(self, usuario: Usuario) -> str:
        return self._ruta_notificaciones_service.resolver(usuario)

    def _redirect_filtrado(self, usuario: Usuario, categoria: str, estado: str):
        ruta = self._ruta_por_rol(usuario)
        query = urlencode({"categoria": categoria, "estado": estado})
        return redirect(f"{reverse(ruta)}?{query}")

    def get(self, request):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        try:
            self._ruta_por_rol(usuario)
        except DomainError:
            return redirect("login")

        categoria, estado = self._filtros_service.desde_source(request.GET)
        try:
            ctx_notificaciones = ListarNotificacionesUsuarioService().listar(
                usuario,
                categoria=categoria,
                estado=estado,
            )
        except DomainError as e:
            return render(request, self.template_name, {"error": str(e), "usuario": usuario})

        return render(request, self.template_name, {**ctx_notificaciones, "usuario": usuario})

    def post(self, request):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        try:
            self._ruta_por_rol(usuario)
        except DomainError:
            return redirect("login")

        resultado = ProcesarAccionesNotificacionesService().procesar(usuario, request.POST)
        nivel = resultado.get("nivel")
        mensaje = resultado.get("mensaje")
        if mensaje and nivel == "success":
            messages.success(request, mensaje)
        elif mensaje and nivel == "error":
            messages.error(request, mensaje)

        destino = resultado.get("destino")
        if destino:
            return redirect(destino)

        return self._redirect_filtrado(
            usuario,
            resultado.get("categoria", "todas"),
            resultado.get("estado", "todas"),
        )


class DueñoMisMascotasView(LoginRequiredMixin, View):
    @staticmethod
    def _render_con_error(request, usuario, error_texto):
        mascotas = ListarMascotasDeDueñoService().listar(usuario)
        return render(request, "servicios/dueño_mis_mascotas.html", {
            "mascotas": mascotas,
            "tipos_mascota": TipoMascota.choices,
            "sexos_mascota": SexoMascota.choices,
            "tamanos_mascota": TamanoMascota.choices,
            "usuario": usuario,
            "error": error_texto,
        })

    def get(self, request):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        try:
            mascotas = ListarMascotasDeDueñoService().listar(usuario)
        except DomainError as e:
            return render(request, "servicios/dueño_mis_mascotas.html", {"error": str(e), "usuario": usuario})
        return render(request, "servicios/dueño_mis_mascotas.html", {
            "mascotas": mascotas,
            "tipos_mascota": TipoMascota.choices,
            "sexos_mascota": SexoMascota.choices,
            "tamanos_mascota": TamanoMascota.choices,
            "usuario": usuario,
        })

    def post(self, request):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        resultado = ProcesarAccionesDueñoMascotasService().procesar(
            usuario,
            request.POST.get("action"),
            request.POST,
            request.FILES,
        )
        if not resultado.get("ok"):
            return self._render_con_error(request, usuario, resultado.get("error", "Error al procesar la mascota."))
        return redirect("dueño_mis_mascotas")


class DueñoMiPerfilView(LoginRequiredMixin, View):
    def get(self, request):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        editing = request.GET.get("edit") == "1"
        prefijo, telefono_local = FormatearTelefonoService().separar_prefijo_numero(usuario.telefono)
        resenas_ctx = _get_resenas_context(request, usuario)
        return render(
            request,
            "servicios/dueño_mi_perfil.html",
            {
                "usuario": usuario,
                "editing": editing,
                "prefijo_telefono": prefijo,
                "telefono_local": telefono_local,
                "prefijos_telefono": PREFIJOS_TELEFONO,
                **resenas_ctx,
            },
        )

    def post(self, request):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        resenas_ctx = _get_resenas_context(request, usuario)
        datos, telefono = ConstruirDatosPerfilUsuarioFormularioService().construir_dueño(
            request.POST,
            request.FILES,
        )
        try:
            EditarPerfilUsuarioService().editar(usuario, datos)
        except DomainError as e:
            prefijo, telefono_local = FormatearTelefonoService().separar_prefijo_numero(telefono)
            return render(
                request,
                "servicios/dueño_mi_perfil.html",
                {
                    "usuario": usuario,
                    "editing": True,
                    "error": str(e),
                    "prefijo_telefono": prefijo,
                    "telefono_local": telefono_local,
                    "prefijos_telefono": PREFIJOS_TELEFONO,
                    **resenas_ctx,
                },
            )
        prefijo, telefono_local = FormatearTelefonoService().separar_prefijo_numero(usuario.telefono)
        return render(
            request,
            "servicios/dueño_mi_perfil.html",
            {
                "usuario": usuario,
                "editing": False,
                "mensaje": "Perfil actualizado.",
                "prefijo_telefono": prefijo,
                "telefono_local": telefono_local,
                "prefijos_telefono": PREFIJOS_TELEFONO,
                **resenas_ctx,
            },
        )


# ── Cuidador ──────────────────────────────────────────────

class DashboardCuidadorView(LoginRequiredMixin, View):
    def get(self, request):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        try:
            agendamientos = ListarAgendamientosCuidadorService().listar(usuario)
            perfil = ObtenerPerfilCuidadorService().obtener(usuario)
        except DomainError:
            agendamientos = {"agendamientos_futuros": [], "agendamientos_pasados": [], "solicitudes_pendientes": []}
            perfil = None

        try:
            notificaciones_ctx = ListarNotificacionesUsuarioService().listar(usuario, limite=6)
        except DomainError:
            notificaciones_ctx = {
                "notificaciones_items": [],
                "notificaciones_no_leidas": 0,
                "notificaciones_total": 0,
                "notificaciones_filtradas_total": 0,
                "notificaciones_negocio_total": 0,
                "notificaciones_sistema_total": 0,
                "notificaciones_categoria_actual": "todas",
                "notificaciones_estado_actual": "todas",
            }

        try:
            precios = ObtenerPreciosActivosCuidadorService().obtener(usuario)
        except DomainError:
            precios = {}
        solicitudes_pendientes = list(agendamientos.get("solicitudes_pendientes", []))
        agendamientos_futuros = list(agendamientos.get("agendamientos_futuros", []))

        return render(
            request,
            "servicios/dashboard_cuidador.html",
            {
                **agendamientos,
                **notificaciones_ctx,
                "perfil": perfil,
                "precios_activos": precios,
                "servicios_activos_total": len(precios),
                "solicitudes_pendientes_resumen": solicitudes_pendientes[:5],
                "agendamientos_futuros_resumen": agendamientos_futuros[:6],
                "usuario": usuario,
            },
        )


class CuidadorCalendarioView(LoginRequiredMixin, View):
    def get(self, request):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        try:
            agendamientos = ListarAgendamientosCuidadorService().listar(usuario)
        except DomainError:
            agendamientos = {"agendamientos_futuros": [], "agendamientos_pasados": [], "solicitudes_pendientes": []}

        historial_ctx = ConstruirContextoHistorialSolicitudesService().construir(
            agendamientos.get("agendamientos_pasados", []),
            request.GET,
            {"dueno", "mascota"},
            HISTORIAL_ESTADO_OPCIONES,
            HISTORIAL_SERVICIO_OPCIONES,
        )

        return render(
            request,
            "servicios/cuidador_calendario.html",
            {
                **agendamientos,
                "agendamientos_pasados": historial_ctx["items_filtrados"],
                "historial_estado_actual": historial_ctx["historial_estado_actual"],
                "historial_servicio_actual": historial_ctx["historial_servicio_actual"],
                "historial_estado_opciones": HISTORIAL_ESTADO_OPCIONES,
                "historial_servicio_opciones": HISTORIAL_SERVICIO_OPCIONES,
                "historial_filtrado_total": historial_ctx["historial_filtrado_total"],
                "resena_pendiente_solicitud_id": historial_ctx["resena_pendiente_solicitud_id"],
                "resena_pendiente_objetivo": historial_ctx["resena_pendiente_objetivo"],
                "usuario": usuario,
            },
        )

    def post(self, request):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        resultado = ProcesarAccionesCuidadorCalendarioService().procesar(usuario, request.POST)
        nivel = resultado.get("nivel")
        mensaje = resultado.get("mensaje")
        if mensaje and nivel == "success":
            messages.success(request, mensaje)
        elif mensaje and nivel == "error":
            messages.error(request, mensaje)
        return redirect("cuidador_calendario")


class CuidadorGuiaView(LoginRequiredMixin, View):
    """Guía de uso para cuidadores."""
    def get(self, request):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        return render(request, "servicios/cuidador_guia.html", {"usuario": usuario})


class DueñoGuiaView(LoginRequiredMixin, View):
    """Guía de uso para dueños."""
    def get(self, request):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        return render(request, "servicios/dueño_guia.html", {"usuario": usuario})


class VerPerfilOtroView(LoginRequiredMixin, View):
    """Ver perfil del otro (cuidador o dueño) en modo solo lectura."""
    _ruta_post_login_service = ResolverRutaPostLoginService()

    def get(self, request, usuario_id):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        try:
            contexto_otro = ConstruirContextoPerfilPublicoService().construir(
                usuario,
                usuario_id,
                request.GET.get("solicitud"),
            )
            resenas_ctx = _get_resenas_context(request, contexto_otro["otro"])
            return render(request, "servicios/ver_perfil_otro.html", {
                "usuario": usuario,
                **contexto_otro,
                **resenas_ctx,
            })
        except DomainError:
            messages.error(request, "Usuario no encontrado.")
            try:
                return redirect(self._ruta_post_login_service.resolver(usuario))
            except DomainError:
                return redirect("login")


class CuidadorMiPerfilView(LoginRequiredMixin, View):
    def get(self, request):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        try:
            perfil = ObtenerPerfilCuidadorService().obtener(usuario)
        except DomainError:
            perfil = None
        editing = request.GET.get("edit") == "1"
        prefijo, telefono_local = FormatearTelefonoService().separar_prefijo_numero(usuario.telefono)
        resenas_ctx = _get_resenas_context(request, usuario)
        return render(
            request,
            "servicios/cuidador_mi_perfil.html",
            {
                "perfil": perfil,
                "usuario": usuario,
                "editing": editing,
                "prefijo_telefono": prefijo,
                "telefono_local": telefono_local,
                "prefijos_telefono": PREFIJOS_TELEFONO,
                "experiencia_valor": (perfil.descripcion if perfil else ""),
                **resenas_ctx,
            },
        )

    def post(self, request):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        accion = ResolverAccionPerfilCuidadorService().resolver(request.POST)
        if accion.get("modo") == "redirect":
            return redirect(accion.get("ruta", "cuidador_mi_perfil"))
        resenas_ctx = _get_resenas_context(request, usuario)
        datos, telefono, experiencia = ConstruirDatosPerfilUsuarioFormularioService().construir_cuidador(
            request.POST,
            request.FILES,
        )
        try:
            EditarPerfilUsuarioService().editar(usuario, datos)
        except DomainError as e:
            try:
                perfil = ObtenerPerfilCuidadorService().obtener(usuario)
            except DomainError:
                perfil = None
            prefijo, telefono_local = FormatearTelefonoService().separar_prefijo_numero(telefono)
            return render(
                request,
                "servicios/cuidador_mi_perfil.html",
                {
                    "perfil": perfil,
                    "usuario": usuario,
                    "editing": True,
                    "error": str(e),
                    "prefijo_telefono": prefijo,
                    "telefono_local": telefono_local,
                    "prefijos_telefono": PREFIJOS_TELEFONO,
                    "experiencia_valor": experiencia,
                    **resenas_ctx,
                },
            )
        return redirect("cuidador_mi_perfil")


def _get_servicios_context(usuario):
    return ObtenerContextoServiciosCuidadorService().obtener(usuario)


class CuidadorMisServiciosView(LoginRequiredMixin, View):
    def get(self, request):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        ctx = _get_servicios_context(usuario)
        ctx["usuario"] = usuario
        editar = request.GET.get("editar")
        ctx["editar_tipo"] = editar if editar in ("paseo", "guarderia") else None
        return render(request, "servicios/cuidador_servicios.html", ctx)

    def post(self, request):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        ctx = _get_servicios_context(usuario)
        ctx["usuario"] = usuario
        resultado = ProcesarAccionesCuidadorServiciosService().procesar(
            usuario,
            request.POST,
            perfil_actual=ctx.get("perfil"),
        )

        if resultado.get("modo") == "render_error":
            ctx["error"] = resultado.get("error")
            editar_tipo = resultado.get("editar_tipo")
            if editar_tipo in ("paseo", "guarderia"):
                ctx["editar_tipo"] = editar_tipo
            return render(request, "servicios/cuidador_servicios.html", ctx)

        nivel = resultado.get("nivel")
        mensaje = resultado.get("mensaje")
        if mensaje and nivel == "success":
            messages.success(request, mensaje)
        elif mensaje and nivel == "info":
            messages.info(request, mensaje)
        elif mensaje and nivel == "error":
            messages.error(request, mensaje)

        ruta = resultado.get("ruta", "cuidador_servicios")
        editar_tipo = resultado.get("editar_tipo")
        if ruta == "cuidador_servicios" and editar_tipo in ("paseo", "guarderia"):
            return redirect(f"{request.path}?editar={editar_tipo}")
        return redirect(ruta)

class CrearSolicitudServicioView(LoginRequiredMixin, View):
    def get(self, request):
        return render(request, "servicios/crear_solicitud.html", CrearSolicitudServicioAppService().get_form_context())
    
    def post(self, request):
        try:
            service = CrearSolicitudServicioAppService()
            solicitud = service.crear_desde_form(request.POST)
            ctx = service.get_form_context()
            ctx["mensaje"] = f"Solicitud creada: {solicitud.idSolicitud}"
            return render(request, "servicios/crear_solicitud.html", ctx)
        except DomainError as e:
            ctx = CrearSolicitudServicioAppService().get_form_context()
            ctx["error"] = str(e)
            return render(request, "servicios/crear_solicitud.html", ctx)
        except Exception:
            ctx = CrearSolicitudServicioAppService().get_form_context()
            ctx["error"] = "Ocurrió un error interno inesperado al crear la solicitud."
        return render(request, "servicios/crear_solicitud.html", ctx)
