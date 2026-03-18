from urllib.parse import urlencode

from django.contrib.auth import login, logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from servicios.domain.exceptions import DomainError
from servicios.models import EstadoSolicitud, RolUsuario, SexoMascota, TamanoMascota, TipoMascota, TipoServicio, Usuario
from servicios.services import (
    ActualizarFotoMascotaService,
    ActualizarPerfilCuidadorService,
    AgregarMascotaService,
    AutenticacionService,
    BuscarDisponibilidadFormularioReservaService,
    CambiarEstadoSolicitudService,
    CancelarSolicitudService,
    ConstruirContextoHistorialSolicitudesService,
    ConstruirDatosPerfilCuidadorFormularioService,
    CrearCalificacionService,
    CrearCalificacionMascotaService,
    CrearReservaDesdeSeleccionService,
    CrearSolicitudServicioAppService,
    CrearUsuarioAppService,
    EditarMascotaService,
    EnviarMensajeChatService,
    EditarPerfilUsuarioService,
    EliminarEventoService,
    EliminarServicioCuidadorService,
    EliminarMascotaService,
    GestionNotificacionesUsuarioService,
    ListarAgendamientosCuidadorService,
    BuscarUsuarioPorIdentificadorService,
    FormatearTelefonoService,
    ListarMascotasDeDueñoService,
    ListarNotificacionesUsuarioService,
    NormalizarBusquedaReservaService,
    NormalizarFiltrosNotificacionesService,
    ObtenerContextoServiciosCuidadorService,
    ObtenerPerfilPublicoService,
    ObtenerPreciosActivosCuidadorService,
    ListarResenasRecibidasService,
    ListarSolicitudesDueñoService,
    ObtenerSolicitudParaChatService,
    ObtenerTipoServicioEventoService,
    MarcarServicioCompletadoService,
    ObtenerPerfilCuidadorService,
    ProcesarAgregarEventoCuidadorService,
    ProcesarBloquesPendientesService,
)


class SignupView(View):

    def get(self, request):
        return render(request, "servicios/signup.html")

    def post(self, request):
        prefijo = request.POST.get("prefijo", "+57")
        telefono_num = request.POST.get("telefono", "")
        telefono_full = f"{prefijo}{telefono_num}"

        campos = {
            "nombre": request.POST.get("nombre"),
            "apellido": request.POST.get("apellido"),
            "username": request.POST.get("username"),
            "correo": request.POST.get("correo"),
            "cedula": request.POST.get("cedula"),
            "telefono": telefono_num,
            "prefijo": prefijo,
            "fechaNacimiento_str": request.POST.get("fechaNacimiento"),
            "ciudad": request.POST.get("ciudad"),
            "rol": request.POST.get("rol"),
        }

        try:
            CrearUsuarioAppService().crear_usuario({
                "nombre": campos["nombre"], "apellido": campos["apellido"],
                "username": campos["username"], "correo": campos["correo"],
                "cedula": campos["cedula"], "telefono": telefono_full,
                "fechaNacimiento_str": campos["fechaNacimiento_str"],
                "ciudad": campos["ciudad"],
                "password1": request.POST.get("password1"),
                "password2": request.POST.get("password2"),
                "rol": campos["rol"],
            })
        except DomainError as e:
            return render(request, "servicios/signup.html", {**campos, "error": str(e)})

        return redirect("login")


class LoginView(View):

    def get(self, request):
        return render(request, "servicios/login.html")

    def post(self, request):
        username = request.POST.get("username")
        password = request.POST.get("password")
        service = AutenticacionService()
        try:
            usuario = service.autenticar(username, password)
        except DomainError as e:
            return render(request, "servicios/login.html", {"error": str(e), "username": username})
        login(request, usuario.user)
        if usuario.rol == RolUsuario.DUEÑO:
            return redirect("dashboard_dueño")
        return redirect("dashboard_cuidador")


class LogoutView(View):
    def post(self, request):
        logout(request)
        return redirect("login")


class PasswordResetRequestView(View):
    def get(self, request):
        return render(request, "servicios/password_reset_request.html")

    def post(self, request):
        identificador = (request.POST.get("identificador") or "").strip()
        ctx = {"identificador": identificador}
        if not identificador:
            ctx["error"] = "Escribe tu correo o usuario para continuar."
            return render(request, "servicios/password_reset_request.html", ctx)

        usuario = BuscarUsuarioPorIdentificadorService().buscar(identificador)
        # En una siguiente iteración aquí se generaría un token y se enviaría un correo.
        if usuario:
            ctx["success"] = "Usuario encontrado. Enviaremos instrucciones a tu correo para recuperar tu contraseña."
        else:
            ctx["error"] = "No encontramos ninguna cuenta con ese correo o usuario."
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


HISTORIAL_ESTADO_OPCIONES = [
    ("todas", "Todos los estados"),
    (EstadoSolicitud.COMPLETADO, "Finalizados"),
    (EstadoSolicitud.CANCELADO, "Cancelados"),
    (EstadoSolicitud.RECHAZADO, "Rechazados"),
    (EstadoSolicitud.ACEPTADO, "Aceptados"),
    (EstadoSolicitud.PENDIENTE, "Pendientes"),
]
HISTORIAL_SERVICIO_OPCIONES = [
    ("todos", "Todos los servicios"),
    (TipoServicio.PASEO, "Paseo"),
    (TipoServicio.GUARDERIA, "Guardería"),
]


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
    _buscador_disponibilidad = BuscarDisponibilidadFormularioReservaService()

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
        action = request.POST.get("action", "buscar")

        if action == "confirmar":
            try:
                CrearReservaDesdeSeleccionService().crear(
                    dueño=usuario,
                    mascota_id=request.POST.get("mascota_id"),
                    evento_id=request.POST.get("evento_id") or None,
                    fecha_str=request.POST.get("fecha", ""),
                    fecha_fin_str=request.POST.get("fecha_fin") or None,
                    tipo_servicio=request.POST.get("tipo_servicio", ""),
                    modo_guarderia=request.POST.get("modo_guarderia") or None,
                    duracion_guarderia_minutos=request.POST.get("duracion_guarderia_minutos") or None,
                    hora_inicio_guarderia_str=request.POST.get("hora_inicio_guarderia") or None,
                    hora_fin_guarderia_str=request.POST.get("hora_fin_guarderia") or None,
                )
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
            return redirect("dueño_mis_reservas")

        try:
            cuidadores, busqueda = self._buscador_disponibilidad.buscar(usuario, request.POST)
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

        return render(request, "servicios/dueño_nueva_reserva.html", {
            "mascotas": mascotas,
            "usuario": usuario,
            "cuidadores_disponibles": cuidadores,
            "busqueda": busqueda,
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
        action = request.POST.get("action")
        if action in ("calificar", "calificar_cuidador"):
            try:
                CrearCalificacionService().crear(
                    usuario,
                    request.POST.get("solicitud_id"),
                    request.POST.get("estrellas", 5),
                    request.POST.get("comentario", ""),
                )
                messages.success(request, "Calificación enviada. ¡Gracias!")
            except DomainError as e:
                messages.error(request, str(e))
        elif action == "cancelar":
            try:
                CancelarSolicitudService().cancelar(request.POST.get("solicitud_id"), usuario)
                messages.success(request, "Reserva cancelada.")
            except DomainError as e:
                messages.error(request, str(e))
        elif action == "completar":
            messages.info(request, "El arrendamiento debe ser finalizado por el cuidador para habilitar calificación.")
        elif action == "enviar_mensaje":
            msg = (request.POST.get("mensaje") or "").strip()
            solicitud_id = request.POST.get("solicitud_id")
            if msg and solicitud_id:
                try:
                    sol = ObtenerSolicitudParaChatService().obtener_para_dueño(solicitud_id, usuario)
                    EnviarMensajeChatService().enviar(sol, usuario, msg)
                except DomainError as e:
                    messages.error(request, str(e))
        return redirect("dueño_mis_reservas")


class NotificacionesView(LoginRequiredMixin, View):
    template_name = "servicios/notificaciones.html"
    _filtros_service = NormalizarFiltrosNotificacionesService()

    def _ruta_por_rol(self, usuario: Usuario) -> str:
        return "dueño_notificaciones" if usuario.rol == "dueño" else "cuidador_notificaciones"

    def _redirect_filtrado(self, usuario: Usuario, categoria: str, estado: str):
        ruta = self._ruta_por_rol(usuario)
        query = urlencode({"categoria": categoria, "estado": estado})
        return redirect(f"{reverse(ruta)}?{query}")

    def get(self, request):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        if usuario.rol not in ("dueño", "cuidador"):
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
        if usuario.rol not in ("dueño", "cuidador"):
            return redirect("login")

        action = request.POST.get("action")
        categoria, estado = self._filtros_service.desde_source(request.POST)
        gestor = GestionNotificacionesUsuarioService()

        ids_seleccionados = self._filtros_service.parsear_ids(request.POST.get("notificacion_ids"))

        try:
            if action == "marcar_leida":
                gestor.marcar_leida(usuario, request.POST.get("notificacion_id"))
            elif action == "marcar_todas_leidas":
                marcadas = gestor.marcar_todas_leidas(usuario, categoria=categoria)
                messages.success(request, f"Se marcaron {marcadas} notificaciones como leídas.")
            elif action == "eliminar":
                gestor.eliminar(usuario, request.POST.get("notificacion_id"))
            elif action == "eliminar_seleccionadas":
                eliminadas = gestor.eliminar_seleccionadas(usuario, ids_seleccionados)
                messages.success(request, f"Se eliminaron {eliminadas} notificaciones seleccionadas.")
            elif action == "eliminar_todas":
                eliminadas = gestor.eliminar_todas(usuario, categoria=categoria, estado=estado)
                messages.success(request, f"Se eliminaron {eliminadas} notificaciones visibles con este filtro.")
            elif action == "abrir":
                notificacion = gestor.marcar_leida(usuario, request.POST.get("notificacion_id"))
                destino = (notificacion.urlDestino or "").strip()
                if destino.startswith("/"):
                    return redirect(destino)
            else:
                messages.error(request, "Acción inválida.")
        except DomainError as e:
            messages.error(request, str(e))

        return self._redirect_filtrado(usuario, categoria, estado)


class DueñoMisMascotasView(LoginRequiredMixin, View):
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
        action = request.POST.get("action")
        if action == "eliminar":
            try:
                EliminarMascotaService().eliminar(usuario, request.POST.get("mascota_id"))
            except DomainError as e:
                mascotas = ListarMascotasDeDueñoService().listar(usuario)
                return render(request, "servicios/dueño_mis_mascotas.html", {
                    "mascotas": mascotas,
                    "tipos_mascota": TipoMascota.choices,
                    "sexos_mascota": SexoMascota.choices,
                    "tamanos_mascota": TamanoMascota.choices,
                    "usuario": usuario,
                    "error": str(e),
                })
            return redirect("dueño_mis_mascotas")
        if action == "cambiar_foto":
            try:
                ActualizarFotoMascotaService().actualizar(usuario, request.POST.get("mascota_id"), request.FILES.get("foto"))
            except DomainError as e:
                mascotas = ListarMascotasDeDueñoService().listar(usuario)
                return render(request, "servicios/dueño_mis_mascotas.html", {
                    "mascotas": mascotas,
                    "tipos_mascota": TipoMascota.choices,
                    "sexos_mascota": SexoMascota.choices,
                    "tamanos_mascota": TamanoMascota.choices,
                    "usuario": usuario,
                    "error": str(e),
                })
            return redirect("dueño_mis_mascotas")
        if action == "editar":
            datos = {
                "nombreMascota": request.POST.get("nombreMascota"),
                "tipo": request.POST.get("tipo"),
                "raza": request.POST.get("raza", ""),
                "sexo": request.POST.get("sexo", ""),
                "tamano": request.POST.get("tamano", ""),
                "edad": request.POST.get("edad"),
                "peso": request.POST.get("peso"),
                "esterilizado": request.POST.get("esterilizado", ""),
                "vacunasAlDia": request.POST.get("vacunasAlDia", ""),
                "condicionesMedicas": request.POST.get("condicionesMedicas", ""),
                "notas": request.POST.get("notas", ""),
            }
            try:
                EditarMascotaService().editar(usuario, request.POST.get("mascota_id"), datos)
            except DomainError as e:
                mascotas = ListarMascotasDeDueñoService().listar(usuario)
                return render(request, "servicios/dueño_mis_mascotas.html", {
                    "mascotas": mascotas,
                    "tipos_mascota": TipoMascota.choices,
                    "sexos_mascota": SexoMascota.choices,
                    "tamanos_mascota": TamanoMascota.choices,
                    "usuario": usuario,
                    "error": str(e),
                })
            return redirect("dueño_mis_mascotas")
        datos = {
            "nombreMascota": request.POST.get("nombreMascota"),
            "tipo": request.POST.get("tipo"), "raza": request.POST.get("raza", ""),
            "sexo": request.POST.get("sexo", ""),
            "tamano": request.POST.get("tamano", ""),
            "edad": request.POST.get("edad"), "peso": request.POST.get("peso"),
            "esterilizado": request.POST.get("esterilizado", ""),
            "vacunasAlDia": request.POST.get("vacunasAlDia", ""),
            "condicionesMedicas": request.POST.get("condicionesMedicas", ""),
            "notas": request.POST.get("notas", ""),
            "foto": request.FILES.get("foto"),
        }
        try:
            AgregarMascotaService().agregar(usuario, datos)
        except DomainError as e:
            mascotas = ListarMascotasDeDueñoService().listar(usuario)
            return render(request, "servicios/dueño_mis_mascotas.html", {
                "mascotas": mascotas,
                "tipos_mascota": TipoMascota.choices,
                "sexos_mascota": SexoMascota.choices,
                "tamanos_mascota": TamanoMascota.choices,
                "usuario": usuario,
                "error": str(e),
            })
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
        telefono = FormatearTelefonoService().componer(
            request.POST.get("prefijo", "+57"),
            request.POST.get("telefono"),
        )
        resenas_ctx = _get_resenas_context(request, usuario)
        datos = {
            "nombre": request.POST.get("nombre"),
            "apellido": request.POST.get("apellido"),
            "cedula": request.POST.get("cedula"),
            "correo": request.POST.get("correo"),
            "telefono": telefono,
            "ciudad": request.POST.get("ciudad"),
            "direccion": request.POST.get("direccion"),
            "latitud": request.POST.get("latitud"),
            "longitud": request.POST.get("longitud"),
            "fotoPerfil": request.FILES.get("fotoPerfil"),
        }
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
        action = request.POST.get("action")
        solicitud_id = request.POST.get("solicitud_id")
        if not solicitud_id or action not in (
            "aceptar",
            "rechazar",
            "completar",
            "finalizar",
            "finalizar_prueba",
            "cancelar",
            "enviar_mensaje",
            "calificar",
            "calificar_dueno",
            "calificar_mascota",
        ):
            messages.error(request, "Acción inválida.")
            return redirect("cuidador_calendario")
        try:
            if action == "aceptar":
                CambiarEstadoSolicitudService().aceptar(solicitud_id, usuario)
                messages.success(request, "Solicitud aceptada correctamente.")
            elif action == "rechazar":
                CambiarEstadoSolicitudService().rechazar(solicitud_id, usuario)
                messages.success(request, "Solicitud rechazada.")
            elif action in ("completar", "finalizar"):
                MarcarServicioCompletadoService().marcar(solicitud_id, usuario)
                messages.success(request, "Arrendamiento finalizado correctamente.")
            elif action == "finalizar_prueba":
                MarcarServicioCompletadoService().marcar(solicitud_id, usuario, forzar=True)
                messages.success(request, "Arrendamiento finalizado en modo prueba.")
            elif action == "enviar_mensaje":
                msg = (request.POST.get("mensaje") or "").strip()
                if msg:
                    sol = ObtenerSolicitudParaChatService().obtener_para_cuidador(solicitud_id, usuario)
                    EnviarMensajeChatService().enviar(sol, usuario, msg)
            elif action in ("calificar", "calificar_dueno"):
                CrearCalificacionService().crear(
                    usuario,
                    solicitud_id,
                    request.POST.get("estrellas", 5),
                    request.POST.get("comentario", ""),
                )
                messages.success(request, "Reseña del dueño enviada. ¡Gracias!")
            elif action == "calificar_mascota":
                CrearCalificacionMascotaService().crear(
                    usuario,
                    solicitud_id,
                    request.POST.get("estrellas", 5),
                    request.POST.get("comentario", ""),
                )
                messages.success(request, "Reseña de la mascota enviada. ¡Gracias!")
            else:
                CancelarSolicitudService().cancelar(solicitud_id, usuario)
                messages.success(request, "Reserva cancelada.")
        except DomainError as e:
            messages.error(request, str(e))
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
    def get(self, request, usuario_id):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        try:
            perfil_publico_service = ObtenerPerfilPublicoService()
            otro = perfil_publico_service.obtener_usuario(usuario_id)
            perfil_cuidador = perfil_publico_service.obtener_perfil_cuidador(otro)
            mascota_asignada = None
            solicitud_relacionada = None

            solicitud_id = (request.GET.get("solicitud") or "").strip()
            if solicitud_id and usuario.rol == "cuidador" and otro.rol == "dueño":
                solicitud_relacionada = perfil_publico_service.obtener_solicitud_relacionada(
                    solicitud_id,
                    cuidador=usuario,
                    dueño=otro,
                )
                if solicitud_relacionada:
                    mascotas_dueño = ListarMascotasDeDueñoService().listar(otro)
                    mascota_asignada = next(
                        (m for m in mascotas_dueño if m.idMascota == solicitud_relacionada.idMascota_id),
                        solicitud_relacionada.idMascota,
                    )

            resenas_ctx = _get_resenas_context(request, otro)
            return render(request, "servicios/ver_perfil_otro.html", {
                "usuario": usuario,
                "otro": otro,
                "perfil_cuidador": perfil_cuidador,
                "mascota_asignada": mascota_asignada,
                "solicitud_relacionada": solicitud_relacionada,
                **resenas_ctx,
            })
        except DomainError:
            messages.error(request, "Usuario no encontrado.")
            return redirect("dashboard_cuidador" if usuario.rol == "cuidador" else "dashboard_dueño")


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
        action = request.POST.get("action")
        if action != "datos_personales":
            return redirect("cuidador_mi_perfil")
        telefono = FormatearTelefonoService().componer(
            request.POST.get("prefijo", "+57"),
            request.POST.get("telefono"),
        )
        experiencia = (request.POST.get("experiencia") or "").strip()
        resenas_ctx = _get_resenas_context(request, usuario)
        datos = {
            "nombre": request.POST.get("nombre"),
            "apellido": request.POST.get("apellido"),
            "cedula": request.POST.get("cedula"),
            "correo": request.POST.get("correo"),
            "telefono": telefono,
            "ciudad": request.POST.get("ciudad"),
            "direccion": request.POST.get("direccion"),
            "latitud": request.POST.get("latitud"),
            "longitud": request.POST.get("longitud"),
            "radioKm": request.POST.get("radioKm"),
            "fotoPerfil": request.FILES.get("fotoPerfil"),
            "experiencia": experiencia,
        }
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
        action = request.POST.get("action")
        ctx = _get_servicios_context(usuario)
        ctx["usuario"] = usuario

        if action == "servicio":
            editar_post = request.POST.get("editar_tipo")
            if editar_post in ("paseo", "guarderia"):
                ctx["editar_tipo"] = editar_post

            datos = ConstruirDatosPerfilCuidadorFormularioService().construir(
                request.POST,
                ctx.get("perfil"),
                editar_post,
            )

            try:
                with transaction.atomic():
                    ActualizarPerfilCuidadorService().actualizar(usuario, datos)
                    total_bloques_creados = ProcesarBloquesPendientesService().procesar(
                        usuario,
                        request.POST.get("bloquesPendientes"),
                    )
            except DomainError as e:
                ctx["error"] = str(e)
                return render(request, "servicios/cuidador_servicios.html", ctx)
            if total_bloques_creados:
                messages.success(
                    request,
                    f"Configuración guardada y {total_bloques_creados} bloque(s) creados correctamente.",
                )
            else:
                messages.success(request, "Configuración guardada correctamente.")
            return redirect("cuidador_servicios")

        if action == "eliminar_servicio":
            try:
                tipo = (request.POST.get("tipoServicio") or "").strip()
                resultado = EliminarServicioCuidadorService().eliminar(usuario, tipo)
                if resultado.get("eventos_historicos"):
                    messages.success(
                        request,
                        "Servicio eliminado. Los eventos con historial fueron desactivados para conservar trazabilidad.",
                    )
                else:
                    messages.success(request, "Servicio eliminado correctamente.")
            except DomainError as e:
                messages.error(request, str(e))
            return redirect("cuidador_servicios")

        if action == "eliminar_evento":
            editar_tipo = (request.POST.get("editar_tipo") or "").strip()
            if editar_tipo not in ("paseo", "guarderia"):
                evento_tipo = ObtenerTipoServicioEventoService().obtener(
                    usuario,
                    request.POST.get("evento_id"),
                )
                if evento_tipo in (TipoServicio.PASEO, TipoServicio.GUARDERIA):
                    editar_tipo = evento_tipo
            try:
                EliminarEventoService().eliminar(usuario, request.POST.get("evento_id"))
            except DomainError as e:
                ctx["error"] = str(e)
                if editar_tipo in ("paseo", "guarderia"):
                    ctx["editar_tipo"] = editar_tipo
                return render(request, "servicios/cuidador_servicios.html", ctx)
            messages.success(request, "Evento eliminado.")
            if editar_tipo in ("paseo", "guarderia"):
                return redirect(f"{request.path}?editar={editar_tipo}")
            return redirect("cuidador_servicios")

        if action == "agregar":
            editar_tipo = (request.POST.get("editar_tipo") or request.POST.get("tipoServicio") or "").strip()
            preset = (request.POST.get("preset") or "").strip()
            datos = {
                "tipoServicio": request.POST.get("tipoServicio"),
                "diaSemana": request.POST.get("diaSemana"),
                "diaSemanaFin": request.POST.get("diaSemanaFin"),
                "horaInicio": request.POST.get("horaInicio"),
                "horaFin": request.POST.get("horaFin"),
                "duracionMinutos": request.POST.get("duracionMinutos"),
                "capacidadMaxima": request.POST.get("capacidadMaxima"),
                "nombreLugar": request.POST.get("nombreLugar"),
                "latitud": request.POST.get("latitud"),
                "longitud": request.POST.get("longitud"),
                "precioCOP": request.POST.get("precioCOP"),
            }
            if preset:
                datos["preset"] = preset
            try:
                resultado = ProcesarAgregarEventoCuidadorService().procesar(usuario, datos)
                if resultado.get("modo") == "preset":
                    creados = resultado.get("creados") or 0
                    if creados:
                        messages.success(request, f"Se agregaron {creados} bloques correctamente.")
                    else:
                        messages.info(request, "No se agregaron bloques nuevos porque ya existían.")
                elif resultado.get("modo") == "guarderia_rango":
                    creados = resultado.get("creados") or 0
                    if creados:
                        messages.success(request, f"Se agregaron {creados} bloque(s) de guardería.")
                    else:
                        messages.info(request, "No se agregaron bloques porque ya existían para ese rango.")
                else:
                    messages.success(request, "Evento agregado correctamente.")
            except DomainError as e:
                ctx["error"] = str(e)
                if editar_tipo in ("paseo", "guarderia"):
                    ctx["editar_tipo"] = editar_tipo
                return render(request, "servicios/cuidador_servicios.html", ctx)
            if editar_tipo in ("paseo", "guarderia"):
                return redirect(f"{request.path}?editar={editar_tipo}")
            return redirect("cuidador_servicios")

        return redirect("cuidador_servicios")

@method_decorator(csrf_exempt, name="dispatch")
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
        except Exception as e:
            ctx = CrearSolicitudServicioAppService().get_form_context()
            ctx["error"] = str(e)
        return render(request, "servicios/crear_solicitud.html", ctx)
