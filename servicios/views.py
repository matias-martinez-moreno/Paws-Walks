from django.contrib.auth import login, logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.shortcuts import redirect, render
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from django.db.models import Sum
from django.db.models.functions import TruncMonth, TruncDate

from servicios.domain.exceptions import DomainError
from servicios.models import DiaSemana, MensajeChat, PerfilCuidador, PrecioServicio, RolUsuario, SolicitudServicio, TipoMascota, TipoServicio, Usuario
from servicios.services import (
    ActualizarFotoMascotaService,
    ActualizarPerfilCuidadorService,
    AgregarBloquesRapidoService,
    AgregarBloqueTiempoService,
    AgregarEventoService,
    AgregarEventosRapidoService,
    AgregarMascotaService,
    AgregarVentanaDisponibilidadService,
    AutenticacionService,
    BuscarCuidadoresDisponiblesService,
    CambiarEstadoSolicitudService,
    CancelarSolicitudService,
    CrearCalificacionService,
    CrearReservaDesdeSeleccionService,
    CrearSolicitudServicioAppService,
    CrearUsuarioAppService,
    EditarPerfilUsuarioService,
    EliminarBloqueTiempoService,
    EliminarEventoService,
    EliminarMascotaService,
    EliminarVentanaDisponibilidadService,
    ListarAgendamientosCuidadorService,
    ListarBloquesCuidadorService,
    ListarEventosCuidadorService,
    ListarMascotasDeDueñoService,
    ListarSolicitudesDueñoService,
    ListarVentanasCuidadorService,
    MarcarServicioCompletadoService,
    ObtenerPerfilCuidadorService,
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

        usuario = (
            Usuario.objects.filter(correo=identificador).first()
            or Usuario.objects.filter(username=identificador).first()
        )
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


def _get_usuario(request):
    return getattr(request.user, "perfil_usuario", None)


# ── Dueño ─────────────────────────────────────────────────

class DashboardDueñoView(LoginRequiredMixin, View):
    def get(self, request):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        try:
            ctx_sol = ListarSolicitudesDueñoService().listar(usuario)
            mascotas = ListarMascotasDeDueñoService().listar(usuario)
        except DomainError as e:
            return render(request, "servicios/dashboard_dueño.html", {"error": str(e), "usuario": usuario})
        return render(request, "servicios/dashboard_dueño.html", {**ctx_sol, "mascotas": mascotas, "usuario": usuario})


class DueñoNuevaReservaView(LoginRequiredMixin, View):
    def get(self, request):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        mascotas = ListarMascotasDeDueñoService().listar(usuario)
        return render(request, "servicios/dueño_nueva_reserva.html", {"mascotas": mascotas, "usuario": usuario})

    def post(self, request):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        mascotas = ListarMascotasDeDueñoService().listar(usuario)
        action = request.POST.get("action", "buscar")
        tipo_servicio = request.POST.get("tipo_servicio", "paseo")

        if action == "confirmar":
            try:
                CrearReservaDesdeSeleccionService().crear(
                    dueño=usuario,
                    mascota_id=request.POST.get("mascota_id"),
                    bloque_id=request.POST.get("bloque_id") or None,
                    ventana_id=request.POST.get("ventana_id") or None,
                    evento_id=request.POST.get("evento_id") or None,
                    fecha_str=request.POST.get("fecha", ""),
                    tipo_servicio=request.POST.get("tipo_servicio", ""),
                    fecha_fin_str=request.POST.get("fecha_fin") or None,
                )
            except DomainError as e:
                return render(request, "servicios/dueño_nueva_reserva.html", {"mascotas": mascotas, "usuario": usuario, "error": str(e)})
            return redirect("dueño_mis_reservas")

        if tipo_servicio == "guarderia":
            try:
                solo_ciudad = request.POST.get("solo_cercanos", "1") == "1"
                cuidadores = BuscarCuidadoresDisponiblesService().buscar_cuidado(
                    usuario,
                    request.POST.get("mascota_id"),
                    request.POST.get("fecha_inicio"),
                    request.POST.get("fecha_fin"),
                    solo_ciudad=solo_ciudad,
                )
            except (DomainError, ValueError, TypeError) as e:
                return render(request, "servicios/dueño_nueva_reserva.html", {"mascotas": mascotas, "usuario": usuario, "error": str(e)})
            busqueda = {
                "tipo_servicio": "guarderia",
                "mascota_id": request.POST.get("mascota_id"),
                "fecha": request.POST.get("fecha_inicio"),
                "fecha_inicio": request.POST.get("fecha_inicio"),
                "fecha_fin": request.POST.get("fecha_fin"),
                "solo_cercanos": solo_ciudad,
            }
        else:
            try:
                duracion_min = int(request.POST.get("duracion", 60))
                solo_ciudad = request.POST.get("solo_cercanos", "1") == "1"
                cuidadores = BuscarCuidadoresDisponiblesService().buscar(
                    usuario,
                    request.POST.get("mascota_id"),
                    request.POST.get("fecha"),
                    request.POST.get("hora"),
                    duracion_min,
                    solo_ciudad=solo_ciudad,
                )
            except (DomainError, ValueError, TypeError) as e:
                return render(request, "servicios/dueño_nueva_reserva.html", {"mascotas": mascotas, "usuario": usuario, "error": str(e)})
            busqueda = {
                "tipo_servicio": "paseo",
                "mascota_id": request.POST.get("mascota_id"),
                "fecha": request.POST.get("fecha"),
                "hora": request.POST.get("hora"),
                "duracion": duracion_min,
                "solo_cercanos": solo_ciudad,
            }

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
        return render(request, "servicios/dueño_mis_reservas.html", {**ctx_sol, "usuario": usuario})

    def post(self, request):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        action = request.POST.get("action")
        if action == "calificar":
            try:
                CrearCalificacionService().crear(
                    usuario,
                    request.POST.get("solicitud_id"),
                    int(request.POST.get("estrellas", 5)),
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
            try:
                MarcarServicioCompletadoService().marcar(request.POST.get("solicitud_id"), usuario)
                messages.success(request, "Servicio marcado como completado.")
            except DomainError as e:
                messages.error(request, str(e))
        elif action == "enviar_mensaje":
            msg = (request.POST.get("mensaje") or "").strip()
            solicitud_id = request.POST.get("solicitud_id")
            if msg and solicitud_id:
                try:
                    sol = SolicitudServicio.objects.get(idSolicitud=solicitud_id, idDueño=usuario)
                    MensajeChat.objects.create(idSolicitud=sol, idDe=usuario, mensaje=msg)
                except SolicitudServicio.DoesNotExist:
                    messages.error(request, "Solicitud no encontrada.")
        return redirect("dueño_mis_reservas")


class DueñoMisMascotasView(LoginRequiredMixin, View):
    def get(self, request):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        try:
            mascotas = ListarMascotasDeDueñoService().listar(usuario)
        except DomainError as e:
            return render(request, "servicios/dueño_mis_mascotas.html", {"error": str(e), "usuario": usuario})
        return render(request, "servicios/dueño_mis_mascotas.html", {"mascotas": mascotas, "tipos_mascota": TipoMascota.choices, "usuario": usuario})

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
                return render(request, "servicios/dueño_mis_mascotas.html", {"mascotas": mascotas, "tipos_mascota": TipoMascota.choices, "usuario": usuario, "error": str(e)})
            return redirect("dueño_mis_mascotas")
        if action == "cambiar_foto":
            try:
                ActualizarFotoMascotaService().actualizar(usuario, request.POST.get("mascota_id"), request.FILES.get("foto"))
            except DomainError as e:
                mascotas = ListarMascotasDeDueñoService().listar(usuario)
                return render(request, "servicios/dueño_mis_mascotas.html", {"mascotas": mascotas, "tipos_mascota": TipoMascota.choices, "usuario": usuario, "error": str(e)})
            return redirect("dueño_mis_mascotas")
        datos = {
            "nombreMascota": request.POST.get("nombreMascota"),
            "tipo": request.POST.get("tipo"), "raza": request.POST.get("raza", ""),
            "edad": request.POST.get("edad"), "peso": request.POST.get("peso"),
            "notas": request.POST.get("notas", ""),
            "foto": request.FILES.get("foto"),
        }
        try:
            AgregarMascotaService().agregar(usuario, datos)
        except DomainError as e:
            mascotas = ListarMascotasDeDueñoService().listar(usuario)
            return render(request, "servicios/dueño_mis_mascotas.html", {"mascotas": mascotas, "tipos_mascota": TipoMascota.choices, "usuario": usuario, "error": str(e)})
        return redirect("dueño_mis_mascotas")


class DueñoMiPerfilView(LoginRequiredMixin, View):
    def get(self, request):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        editing = request.GET.get("edit") == "1"
        return render(request, "servicios/dueño_mi_perfil.html", {"usuario": usuario, "editing": editing})

    def post(self, request):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        datos = {
            "nombre": request.POST.get("nombre"),
            "apellido": request.POST.get("apellido"),
            "correo": request.POST.get("correo"),
            "telefono": request.POST.get("telefono"),
            "ciudad": request.POST.get("ciudad"),
            "latitud": request.POST.get("latitud"),
            "longitud": request.POST.get("longitud"),
            "fotoPerfil": request.FILES.get("fotoPerfil"),
        }
        try:
            EditarPerfilUsuarioService().editar(usuario, datos)
        except DomainError as e:
            return render(request, "servicios/dueño_mi_perfil.html", {"usuario": usuario, "editing": True, "error": str(e)})
        return render(request, "servicios/dueño_mi_perfil.html", {"usuario": usuario, "editing": False, "mensaje": "Perfil actualizado."})


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
            agendamientos = {"agendamientos_futuros": [], "agendamientos_pasados": []}
            perfil = None
        precios = {p.tipoServicio: p for p in usuario.precios_servicio.filter(activo=True)}
        return render(
            request,
            "servicios/dashboard_cuidador.html",
            {**agendamientos, "perfil": perfil, "precios_activos": precios, "usuario": usuario},
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
        return render(request, "servicios/cuidador_calendario.html", {**agendamientos, "usuario": usuario})

    def post(self, request):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        action = request.POST.get("action")
        solicitud_id = request.POST.get("solicitud_id")
        if not solicitud_id or action not in ("aceptar", "rechazar", "completar", "cancelar", "enviar_mensaje"):
            messages.error(request, "Acción inválida.")
            return redirect("cuidador_calendario")
        try:
            if action == "aceptar":
                CambiarEstadoSolicitudService().aceptar(solicitud_id, usuario)
                messages.success(request, "Solicitud aceptada correctamente.")
            elif action == "rechazar":
                CambiarEstadoSolicitudService().rechazar(solicitud_id, usuario)
                messages.success(request, "Solicitud rechazada.")
            elif action == "completar":
                MarcarServicioCompletadoService().marcar(solicitud_id, usuario)
                messages.success(request, "Servicio marcado como completado.")
            elif action == "enviar_mensaje":
                msg = (request.POST.get("mensaje") or "").strip()
                if msg:
                    sol = SolicitudServicio.objects.get(idSolicitud=solicitud_id, idCuidador=usuario)
                    MensajeChat.objects.create(idSolicitud=sol, idDe=usuario, mensaje=msg)
            else:
                CancelarSolicitudService().cancelar(solicitud_id, usuario)
                messages.success(request, "Reserva cancelada.")
        except DomainError as e:
            messages.error(request, str(e))
        except SolicitudServicio.DoesNotExist:
            messages.error(request, "Solicitud no encontrada.")
        return redirect("cuidador_calendario")


class CuidadorMisPagosView(LoginRequiredMixin, View):
    """Transacciones y resúmenes de pagos del cuidador."""
    def get(self, request):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        if usuario.rol != "cuidador":
            return redirect("dashboard_cuidador")
        transacciones = SolicitudServicio.objects.filter(
            idCuidador=usuario, estado="completado", monto_pago__gt=0
        ).select_related("idDueño", "idMascota").order_by("-fecha", "-created_at")
        por_dia = transacciones.annotate(d=TruncDate("fecha")).values("d").annotate(total=Sum("monto_pago")).order_by("-d")[:30]
        por_mes = transacciones.annotate(m=TruncMonth("fecha")).values("m").annotate(total=Sum("monto_pago")).order_by("-m")[:12]
        total_general = transacciones.aggregate(t=Sum("monto_pago"))["t"] or 0
        return render(request, "servicios/cuidador_mis_pagos.html", {
            "usuario": usuario,
            "transacciones": transacciones[:50],
            "resumen_diario": por_dia,
            "resumen_mensual": por_mes,
            "total_general": total_general,
        })


class CuidadorGuiaView(LoginRequiredMixin, View):
    """Guía de uso para cuidadores."""
    def get(self, request):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        return render(request, "servicios/cuidador_guia.html", {"usuario": usuario})


class CuidadorSoporteView(LoginRequiredMixin, View):
    """Soporte con chat ficticio de ventas."""
    def get(self, request):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        return render(request, "servicios/cuidador_soporte.html", {"usuario": usuario})


class DueñoGuiaView(LoginRequiredMixin, View):
    """Guía de uso para dueños."""
    def get(self, request):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        return render(request, "servicios/dueño_guia.html", {"usuario": usuario})


class DueñoSoporteView(LoginRequiredMixin, View):
    """Soporte con chat ficticio de ventas."""
    def get(self, request):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        return render(request, "servicios/dueño_soporte.html", {"usuario": usuario})


class VerPerfilOtroView(LoginRequiredMixin, View):
    """Ver perfil del otro (cuidador o dueño) en modo solo lectura."""
    def get(self, request, usuario_id):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        try:
            otro = Usuario.objects.get(idUsuario=usuario_id)
            perfil_cuidador = None
            if otro.rol == "cuidador":
                try:
                    perfil_cuidador = PerfilCuidador.objects.get(idCuidador=otro)
                except PerfilCuidador.DoesNotExist:
                    pass
            return render(request, "servicios/ver_perfil_otro.html", {
                "usuario": usuario,
                "otro": otro,
                "perfil_cuidador": perfil_cuidador,
            })
        except Usuario.DoesNotExist:
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
        return render(
            request,
            "servicios/cuidador_mi_perfil.html",
            {"perfil": perfil, "usuario": usuario, "editing": editing},
        )

    def post(self, request):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        action = request.POST.get("action")
        if action != "datos_personales":
            return redirect("cuidador_mi_perfil")
        datos = {
            "nombre": request.POST.get("nombre"),
            "apellido": request.POST.get("apellido"),
            "correo": request.POST.get("correo"),
            "telefono": request.POST.get("telefono"),
            "ciudad": request.POST.get("ciudad"),
            "latitud": request.POST.get("latitud"),
            "longitud": request.POST.get("longitud"),
            "radioKm": request.POST.get("radioKm"),
            "fotoPerfil": request.FILES.get("fotoPerfil"),
        }
        try:
            EditarPerfilUsuarioService().editar(usuario, datos)
        except DomainError as e:
            try:
                perfil = ObtenerPerfilCuidadorService().obtener(usuario)
            except DomainError:
                perfil = None
            return render(
                request,
                "servicios/cuidador_mi_perfil.html",
                {"perfil": perfil, "usuario": usuario, "editing": True, "error": str(e)},
            )
        return redirect("cuidador_mi_perfil")


def _agrupar_por_dia(eventos, ventanas=None, bloques=None):
    """Agrupa eventos (principal), ventanas y bloques por diaSemana. Orden: lunes a domingo."""
    orden_dias = [c[0] for c in DiaSemana.choices]
    display_por_dia = {c[0]: c[1] for c in DiaSemana.choices}
    por_dia = {d: {"eventos": [], "ventanas": [], "bloques": []} for d in orden_dias}
    for e in (eventos or []):
        por_dia.setdefault(e.diaSemana, {"eventos": [], "ventanas": [], "bloques": []})["eventos"].append(e)
    for v in (ventanas or []):
        por_dia.setdefault(v.diaSemana, {"eventos": [], "ventanas": [], "bloques": []})["ventanas"].append(v)
    for b in (bloques or []):
        por_dia.setdefault(b.diaSemana, {"eventos": [], "ventanas": [], "bloques": []})["bloques"].append(b)
    return [(d, display_por_dia.get(d, d), por_dia[d]) for d in orden_dias if por_dia[d]["eventos"] or por_dia[d]["ventanas"] or por_dia[d]["bloques"]]


def _get_servicios_context(usuario):
    try:
        perfil = ObtenerPerfilCuidadorService().obtener(usuario)
    except DomainError:
        perfil = None
    precios = {p.tipoServicio: p for p in usuario.precios_servicio.filter(activo=True)}
    eventos_paseo = ListarEventosCuidadorService().listar(usuario, tipo_servicio=TipoServicio.PASEO)
    ventanas_paseo = ListarVentanasCuidadorService().listar(usuario, tipo_servicio=TipoServicio.PASEO)
    bloques_paseo = ListarBloquesCuidadorService().listar(usuario, tipo_servicio=TipoServicio.PASEO)
    eventos_guarderia = ListarEventosCuidadorService().listar(usuario, tipo_servicio=TipoServicio.GUARDERIA)
    bloques_guarderia = ListarBloquesCuidadorService().listar(usuario, tipo_servicio=TipoServicio.GUARDERIA)
    horarios_por_dia = _agrupar_por_dia(eventos_paseo, ventanas_paseo, bloques_paseo)
    horarios_guarderia_por_dia = _agrupar_eventos_bloques_por_dia(eventos_guarderia, bloques_guarderia)
    total_horarios_paseo = len(eventos_paseo) + len(ventanas_paseo) + len(bloques_paseo)
    total_horarios_guarderia = len(eventos_guarderia) + len(bloques_guarderia)
    return {
        "perfil": perfil,
        "precios_activos": precios,
        "eventos_paseo": eventos_paseo,
        "ventanas_paseo": ventanas_paseo,
        "bloques_paseo": bloques_paseo,
        "eventos_guarderia": eventos_guarderia,
        "bloques_guarderia": bloques_guarderia,
        "horarios_por_dia": horarios_por_dia,
        "horarios_guarderia_por_dia": horarios_guarderia_por_dia,
        "dias_semana": DiaSemana.choices,
        "tipos_servicio": [c for c in TipoServicio.choices if c[0] in {TipoServicio.PASEO, TipoServicio.GUARDERIA, TipoServicio.ENTRENAMIENTO}],
        "total_horarios_paseo": total_horarios_paseo,
        "total_horarios_guarderia": total_horarios_guarderia,
    }


class CuidadorMisServiciosView(LoginRequiredMixin, View):
    def get(self, request):
        usuario = _get_usuario(request)
        if usuario is None:
            return redirect("login")
        ctx = _get_servicios_context(usuario)
        ctx["usuario"] = usuario
        editar = request.GET.get("editar")
        ctx["editar_tipo"] = editar if editar in ("paseo", "guarderia", "entrenamiento") else None
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
            if editar_post in ("paseo", "guarderia", "entrenamiento"):
                ctx["editar_tipo"] = editar_post
            tipos_pref = request.POST.get("tiposMascotaPreferidos", "ambos")
            if request.POST.getlist("tiposMascotaCheck"):
                tipos_pref = ",".join(request.POST.getlist("tiposMascotaCheck"))
            elif not tipos_pref or tipos_pref == "ambos":
                tipos_pref = "ambos"
            servicios_post = request.POST.getlist("servicios")
            precios_act = ctx.get("precios_activos") or {}
            servicios = list(set(servicios_post))
            datos = {
                "servicios": servicios,
                "tiposMascotaPreferidos": tipos_pref,
                "descripciones": {
                    TipoServicio.PASEO: request.POST.get("descripcionPaseo", ""),
                    TipoServicio.GUARDERIA: request.POST.get("descripcionGuarderia", ""),
                    TipoServicio.ENTRENAMIENTO: request.POST.get("descripcionEntrenamiento", ""),
                },
                "tarifas": {
                    TipoServicio.PASEO: request.POST.get("tarifaPaseo"),
                    TipoServicio.GUARDERIA: request.POST.get("tarifaGuarderia"),
                    TipoServicio.ENTRENAMIENTO: request.POST.get("tarifaEntrenamiento"),
                },
                "lugaresEntrenamiento": {
                    TipoServicio.ENTRENAMIENTO: request.POST.get("lugarEntrenamiento"),
                },
            }
            try:
                ActualizarPerfilCuidadorService().actualizar(usuario, datos)
                EditarPerfilUsuarioService().editar(usuario, {
                    "ciudad": request.POST.get("ciudad"),
                    "latitud": request.POST.get("latitud"),
                    "longitud": request.POST.get("longitud"),
                    "radioKm": request.POST.get("radioKm"),
                })
            except DomainError as e:
                ctx["error"] = str(e)
                return render(request, "servicios/cuidador_servicios.html", ctx)
            messages.success(request, "Configuración guardada correctamente.")
            return redirect("cuidador_servicios")

        if action == "eliminar_servicio":
            tipo = (request.POST.get("tipoServicio") or "").strip()
            if tipo not in (TipoServicio.PASEO, TipoServicio.GUARDERIA, TipoServicio.ENTRENAMIENTO):
                ctx["error"] = "Servicio inválido."
                return render(request, "servicios/cuidador_servicios.html", ctx)
            PrecioServicio.objects.filter(idCuidador=usuario, tipoServicio=tipo).update(activo=False)
            messages.success(request, "Servicio eliminado (desactivado).")
            return redirect("cuidador_servicios")

        if action == "eliminar":
            try:
                EliminarBloqueTiempoService().eliminar(usuario, request.POST.get("bloque_id"))
            except DomainError as e:
                ctx["error"] = str(e)
                return render(request, "servicios/cuidador_servicios.html", ctx)
            messages.success(request, "Horario eliminado.")
            return redirect("cuidador_servicios")

        if action == "eliminar_evento":
            try:
                EliminarEventoService().eliminar(usuario, request.POST.get("evento_id"))
            except DomainError as e:
                ctx["error"] = str(e)
                return render(request, "servicios/cuidador_servicios.html", ctx)
            messages.success(request, "Evento eliminado.")
            return redirect("cuidador_servicios")

        if action == "eliminar_ventana":
            try:
                EliminarVentanaDisponibilidadService().eliminar(usuario, request.POST.get("ventana_id"))
            except DomainError as e:
                ctx["error"] = str(e)
                return render(request, "servicios/cuidador_servicios.html", ctx)
            messages.success(request, "Ventana eliminada.")
            return redirect("cuidador_servicios")

        if action == "agregar_ventana":
            datos = {
                "tipoServicio": request.POST.get("tipoServicio"),
                "diaSemana": request.POST.get("diaSemana"),
                "horaInicio": request.POST.get("horaInicio"),
                "horaFin": request.POST.get("horaFin"),
                "duracionSlotMinutos": request.POST.get("duracionSlotMinutos", 30),
                "capacidadMaxima": request.POST.get("capacidadMaxima", 5),
                "nombreLugar": request.POST.get("nombreLugar"),
                "latitud": request.POST.get("latitud"),
                "longitud": request.POST.get("longitud"),
                "precioCOP": request.POST.get("precioCOP"),
            }
            try:
                AgregarEventoService().agregar(usuario, datos)
            except DomainError as e:
                ctx["error"] = str(e)
                return render(request, "servicios/cuidador_servicios.html", ctx)
            messages.success(request, "Evento con slots agregado.")
            return redirect("cuidador_servicios")

        if action == "agregar":
            datos = {
                "tipoServicio": request.POST.get("tipoServicio"),
                "diaSemana": request.POST.get("diaSemana"),
                "horaInicio": request.POST.get("horaInicio"),
                "horaFin": request.POST.get("horaFin"),
                "nombreLugar": request.POST.get("nombreLugar"),
                "latitud": request.POST.get("latitud"),
                "longitud": request.POST.get("longitud"),
                "precioCOP": request.POST.get("precioCOP"),
            }
            try:
                AgregarEventoService().agregar(usuario, datos)
            except DomainError as e:
                ctx["error"] = str(e)
                return render(request, "servicios/cuidador_servicios.html", ctx)
            messages.success(request, "Evento agregado correctamente.")
            return redirect("cuidador_servicios")

        if action == "agregar_rapido":
            datos = {
                "tipoServicio": request.POST.get("tipoServicio"),
                "preset": request.POST.get("preset"),
                "horaInicio": request.POST.get("horaInicio"),
                "horaFin": request.POST.get("horaFin"),
                "nombreLugar": request.POST.get("nombreLugar"),
                "latitud": request.POST.get("latitud"),
                "longitud": request.POST.get("longitud"),
                "precioCOP": request.POST.get("precioCOP"),
            }
            try:
                creados = AgregarEventosRapidoService().agregar(usuario, datos)
            except DomainError as e:
                ctx["error"] = str(e)
                return render(request, "servicios/cuidador_servicios.html", ctx)
            if creados > 0:
                messages.success(request, f"Se agregaron {creados} evento(s).")
            else:
                messages.info(request, "Esos horarios ya estaban configurados.")
            return redirect("cuidador_servicios")

        return redirect("cuidador_servicios")


def _agrupar_eventos_bloques_por_dia(eventos, bloques):
    """Agrupa eventos y bloques por diaSemana. Orden: lunes a domingo."""
    orden_dias = [c[0] for c in DiaSemana.choices]
    display_por_dia = {c[0]: c[1] for c in DiaSemana.choices}
    por_dia = {d: [] for d in orden_dias}
    for e in (eventos or []):
        por_dia.setdefault(e.diaSemana, []).append(("evento", e))
    for b in (bloques or []):
        por_dia.setdefault(b.diaSemana, []).append(("bloque", b))
    return [(d, display_por_dia.get(d, d), por_dia[d]) for d in orden_dias if por_dia[d]]


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
