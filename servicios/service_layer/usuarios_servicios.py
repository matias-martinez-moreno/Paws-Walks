# modulo de servicios: autenticacion, perfil y flujos de usuario
from __future__ import annotations

from datetime import date, datetime

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.db import transaction

from servicios.domain.exceptions import ConflictError, DomainValidationError, ResourceNotFoundError
from servicios.models import EstadoSolicitud, Evento, PerfilCuidador, SolicitudServicio, Usuario, VentanaDisponibilidad

class FormatearTelefonoService:
    """Normaliza y separa teléfonos para formularios de perfil."""

    PREFIJOS_TELEFONO = ("+57", "+1", "+34", "+52", "+54", "+56", "+58")

    @classmethod
    def separar_prefijo_numero(cls, telefono) -> tuple[str, str]:
        raw = str(telefono or "").strip()
        if not raw:
            return "+57", ""
        if raw.startswith("+"):
            solo_digitos = "".join(ch for ch in raw[1:] if ch.isdigit())
            for prefijo in sorted(cls.PREFIJOS_TELEFONO, key=len, reverse=True):
                sin_mas = prefijo.lstrip("+")
                if solo_digitos.startswith(sin_mas):
                    return prefijo, solo_digitos[len(sin_mas):]
            for size in range(4, 0, -1):
                candidato = solo_digitos[:size]
                if candidato:
                    return f"+{candidato}", solo_digitos[size:]
        return "+57", raw.lstrip("+")

    @classmethod
    def componer(cls, prefijo, numero) -> str:
        p = str(prefijo or "+57").strip()
        n = "".join(ch for ch in str(numero or "") if ch.isdigit())
        if not p.startswith("+"):
            p = f"+{p}"
        if p == "+":
            p = "+57"
        return f"{p}{n}" if n else ""


class ConstruirDatosRegistroUsuarioFormularioService:
    """Normaliza campos y payload del formulario de registro."""

    def __init__(self, telefono_service: FormatearTelefonoService | None = None):
        self._telefono_service = telefono_service or FormatearTelefonoService()

    def construir(self, source) -> tuple[dict, dict]:
        prefijo = source.get("prefijo", "+57")
        telefono_local = source.get("telefono", "")
        telefono = self._telefono_service.componer(prefijo, telefono_local)

        campos = {
            "nombre": source.get("nombre"),
            "apellido": source.get("apellido"),
            "username": source.get("username"),
            "correo": source.get("correo"),
            "cedula": source.get("cedula"),
            "telefono": telefono_local,
            "prefijo": prefijo,
            "fechaNacimiento_str": source.get("fechaNacimiento"),
            "ciudad": source.get("ciudad"),
            "rol": source.get("rol"),
        }

        payload = {
            "nombre": campos["nombre"],
            "apellido": campos["apellido"],
            "username": campos["username"],
            "correo": campos["correo"],
            "cedula": campos["cedula"],
            "telefono": telefono,
            "fechaNacimiento_str": campos["fechaNacimiento_str"],
            "ciudad": campos["ciudad"],
            "password1": source.get("password1"),
            "password2": source.get("password2"),
            "rol": campos["rol"],
        }
        return campos, payload


class BuscarUsuarioPorIdentificadorService:
    """Busca un usuario por correo o username para flujos de recuperación."""

    def buscar(self, identificador: str | None) -> Usuario | None:
        ident = str(identificador or "").strip()
        if not ident:
            return None
        return (
            Usuario.objects.filter(correo=ident).first()
            or Usuario.objects.filter(username=ident).first()
        )


class ResolverRutaPostLoginService:
    """Resuelve la ruta de dashboard posterior al login según rol."""

    _RUTAS_DASHBOARD = {
        "dueño": "dashboard_dueño",
        "cuidador": "dashboard_cuidador",
    }

    def resolver(self, usuario: Usuario) -> str:
        ruta = self._RUTAS_DASHBOARD.get(usuario.rol)
        if not ruta:
            raise DomainValidationError("el rol del usuario no tiene dashboard configurado")
        return ruta


class ResolverRutaNotificacionesService:
    """Resuelve la ruta de notificaciones según rol."""

    _RUTAS_NOTIFICACIONES = {
        "dueño": "dueño_notificaciones",
        "cuidador": "cuidador_notificaciones",
    }

    def resolver(self, usuario: Usuario) -> str:
        ruta = self._RUTAS_NOTIFICACIONES.get(usuario.rol)
        if not ruta:
            raise DomainValidationError("el rol del usuario no tiene notificaciones configuradas")
        return ruta


class ConstruirContextoRecuperacionPasswordService:
    """Centraliza validación y mensajes del formulario de recuperación."""

    def __init__(self, buscador: BuscarUsuarioPorIdentificadorService | None = None):
        self._buscador = buscador or BuscarUsuarioPorIdentificadorService()

    def construir(self, identificador: str | None) -> dict:
        identificador_norm = str(identificador or "").strip()
        ctx = {"identificador": identificador_norm}
        if not identificador_norm:
            ctx["error"] = "Escribe tu correo o usuario para continuar."
            return ctx

        usuario = self._buscador.buscar(identificador_norm)
        if usuario:
            ctx["success"] = "Usuario encontrado. Enviaremos instrucciones a tu correo para recuperar tu contraseña."
        else:
            ctx["error"] = "No encontramos ninguna cuenta con ese correo o usuario."
        return ctx


class ContarSlotsDisponiblesService:
    """Cuenta slots disponibles por entidad sin usar lógica en modelos."""

    @staticmethod
    def para_evento(evento: Evento) -> int:
        if not evento.duracionSlotMinutos:
            return 0
        return evento.slots.filter(disponible=True).count()

    @staticmethod
    def para_ventana(ventana: VentanaDisponibilidad) -> int:
        return ventana.slots.filter(disponible=True).count()


class ConstruirDatosPerfilUsuarioFormularioService:
    """Normaliza payload de formularios de perfil para dueño y cuidador."""

    def __init__(self, telefono_service: FormatearTelefonoService | None = None):
        self._telefono_service = telefono_service or FormatearTelefonoService()

    def construir_dueño(self, source, files) -> tuple[dict, str]:
        telefono = self._telefono_service.componer(
            source.get("prefijo", "+57"),
            source.get("telefono"),
        )
        datos = {
            "nombre": source.get("nombre"),
            "apellido": source.get("apellido"),
            "cedula": source.get("cedula"),
            "correo": source.get("correo"),
            "telefono": telefono,
            "ciudad": source.get("ciudad"),
            "direccion": source.get("direccion"),
            "latitud": source.get("latitud"),
            "longitud": source.get("longitud"),
            "fotoPerfil": files.get("fotoPerfil") if files is not None else None,
        }
        return datos, telefono

    def construir_cuidador(self, source, files) -> tuple[dict, str, str]:
        telefono = self._telefono_service.componer(
            source.get("prefijo", "+57"),
            source.get("telefono"),
        )
        experiencia = (source.get("experiencia") or "").strip()
        datos = {
            "nombre": source.get("nombre"),
            "apellido": source.get("apellido"),
            "cedula": source.get("cedula"),
            "correo": source.get("correo"),
            "telefono": telefono,
            "ciudad": source.get("ciudad"),
            "direccion": source.get("direccion"),
            "latitud": source.get("latitud"),
            "longitud": source.get("longitud"),
            "radioKm": source.get("radioKm"),
            "fotoPerfil": files.get("fotoPerfil") if files is not None else None,
            "experiencia": experiencia,
        }
        return datos, telefono, experiencia


class ResolverAccionPerfilCuidadorService:
    """Resuelve la acción permitida en POST de perfil de cuidador."""

    @staticmethod
    def resolver(source) -> dict:
        action = str(source.get("action") or "").strip()
        if action != "datos_personales":
            return {
                "modo": "redirect",
                "ruta": "cuidador_mi_perfil",
            }
        return {
            "modo": "continuar",
        }


class FiltrarHistorialSolicitudesService:
    """Orquesta filtros de historial y resolución de reseñas pendientes."""

    def normalizar_filtro(self, valor, validos: set[str], predeterminado: str) -> str:
        normalizado = str(valor or predeterminado).strip().lower()
        return normalizado if normalizado in validos else predeterminado

    def filtrar(self, items, estado: str, servicio: str):
        filtrados = list(items or [])
        if estado != "todas":
            filtrados = [item for item in filtrados if item.estado == estado]
        if servicio != "todos":
            filtrados = [item for item in filtrados if item.tipoServicio == servicio]
        return filtrados

    def resolver_resena_pendiente(
        self,
        solicitud_id,
        objetivo,
        items,
        objetivos_validos: set[str],
    ) -> tuple[str, str]:
        solicitud_id_norm = str(solicitud_id or "").strip()
        objetivo_norm = str(objetivo or "").strip().lower()
        if not solicitud_id_norm or objetivo_norm not in objetivos_validos:
            return "", ""

        for item in items or []:
            if str(item.idSolicitud) != solicitud_id_norm:
                continue
            if item.estado != EstadoSolicitud.COMPLETADO:
                return "", ""
            if objetivo_norm == "cuidador" and not getattr(item, "calificacion_mia", None):
                return solicitud_id_norm, objetivo_norm
            if objetivo_norm == "dueno" and not getattr(item, "calificacion_dueño_mia", None):
                return solicitud_id_norm, objetivo_norm
            if objetivo_norm == "mascota" and not getattr(item, "calificacion_mascota_mia", None):
                return solicitud_id_norm, objetivo_norm
            return "", ""

        return "", ""


class ConstruirContextoHistorialSolicitudesService:
    """Construye filtros y contexto de reseñas pendientes para historiales."""

    def __init__(self, historial: FiltrarHistorialSolicitudesService | None = None):
        self._historial = historial or FiltrarHistorialSolicitudesService()

    def construir(
        self,
        items_pasados,
        source,
        objetivos_validos: set[str],
        estado_opciones: list[tuple[str, str]],
        servicio_opciones: list[tuple[str, str]],
    ) -> dict:
        items = list(items_pasados or [])
        estados_validos = {valor for valor, _ in estado_opciones}
        servicios_validos = {valor for valor, _ in servicio_opciones}

        historial_estado = self._historial.normalizar_filtro(
            source.get("hist_estado"),
            estados_validos,
            "todas",
        )
        historial_servicio = self._historial.normalizar_filtro(
            source.get("hist_servicio"),
            servicios_validos,
            "todos",
        )
        items_filtrados = self._historial.filtrar(
            items,
            historial_estado,
            historial_servicio,
        )
        resena_pendiente_solicitud_id, resena_pendiente_objetivo = self._historial.resolver_resena_pendiente(
            source.get("resena_solicitud"),
            source.get("resena_objetivo"),
            items,
            objetivos_validos,
        )

        return {
            "items_filtrados": items_filtrados,
            "historial_estado_actual": historial_estado,
            "historial_servicio_actual": historial_servicio,
            "historial_filtrado_total": len(items_filtrados),
            "resena_pendiente_solicitud_id": resena_pendiente_solicitud_id,
            "resena_pendiente_objetivo": resena_pendiente_objetivo,
        }



class ObtenerPerfilPublicoService:
    """Carga información pública de perfil para vistas de consulta entre usuarios."""

    def obtener_usuario(self, usuario_id) -> Usuario:
        if not usuario_id:
            raise DomainValidationError("usuario_id es requerido")
        try:
            return Usuario.objects.get(idUsuario=usuario_id)
        except Usuario.DoesNotExist:
            raise ResourceNotFoundError("usuario no encontrado")

    def obtener_perfil_cuidador(self, usuario: Usuario) -> PerfilCuidador | None:
        if usuario.rol != "cuidador":
            return None
        return PerfilCuidador.objects.filter(idCuidador=usuario).first()

    def obtener_solicitud_relacionada(
        self,
        solicitud_id,
        cuidador: Usuario,
        dueño: Usuario,
    ) -> SolicitudServicio | None:
        if not solicitud_id:
            return None
        return SolicitudServicio.objects.select_related("idMascota").filter(
            idSolicitud=solicitud_id,
            idCuidador=cuidador,
            idDueño=dueño,
        ).first()


class ConstruirContextoPerfilPublicoService:
    """Construye el contexto de visualización de perfil de terceros."""

    def __init__(
        self,
        perfil_publico_service: ObtenerPerfilPublicoService | None = None,
        listar_mascotas_service=None,
    ):
        self._perfil_publico_service = perfil_publico_service or ObtenerPerfilPublicoService()
        if listar_mascotas_service is None:
            from servicios.service_layer.perfiles_mascotas import ListarMascotasDeDueñoService

            listar_mascotas_service = ListarMascotasDeDueñoService()
        self._listar_mascotas_service = listar_mascotas_service

    def construir(self, actor: Usuario, usuario_id, solicitud_id: str | None) -> dict:
        otro = self._perfil_publico_service.obtener_usuario(usuario_id)
        perfil_cuidador = self._perfil_publico_service.obtener_perfil_cuidador(otro)

        mascota_asignada = None
        solicitud_relacionada = None
        solicitud_id_norm = str(solicitud_id or "").strip()

        if solicitud_id_norm and actor.rol == "cuidador" and otro.rol == "dueño":
            solicitud_relacionada = self._perfil_publico_service.obtener_solicitud_relacionada(
                solicitud_id_norm,
                cuidador=actor,
                dueño=otro,
            )
            if solicitud_relacionada:
                mascotas_dueño = self._listar_mascotas_service.listar(otro)
                mascota_asignada = next(
                    (mascota for mascota in mascotas_dueño if mascota.idMascota == solicitud_relacionada.idMascota_id),
                    solicitud_relacionada.idMascota,
                )

        return {
            "otro": otro,
            "perfil_cuidador": perfil_cuidador,
            "mascota_asignada": mascota_asignada,
            "solicitud_relacionada": solicitud_relacionada,
        }


class ObtenerTipoServicioEventoService:
    """Resuelve tipo de servicio de un evento del cuidador para navegación UI."""

    def obtener(self, cuidador: Usuario, evento_id: str | None) -> str | None:
        if cuidador.rol != "cuidador":
            raise DomainValidationError("el usuario no tiene rol de cuidador")
        if not evento_id:
            return None

        try:
            perfil = PerfilCuidador.objects.get(idCuidador=cuidador)
        except PerfilCuidador.DoesNotExist:
            return None

        return Evento.objects.filter(idEvento=evento_id, idCuidador=perfil).values_list(
            "tipoServicio",
            flat=True,
        ).first()


class CrearUsuarioAppService:
    # app service para registro de usuarios

    _MAX_NOMBRE = 50
    _MAX_USERNAME = 30
    _MAX_CEDULA = 20
    _MAX_TELEFONO = 20

    def crear_usuario(self, datos: dict) -> Usuario:
        nombre = datos.get("nombre")
        apellido = datos.get("apellido")
        username = datos.get("username")
        correo = datos.get("correo")
        cedula = datos.get("cedula")
        telefono = datos.get("telefono")
        ciudad = datos.get("ciudad")
        rol = datos.get("rol")

        # Contraseña: acepta password o (password1, password2); validación en capa de aplicación
        password = datos.get("password")
        if password is None and "password1" in datos and "password2" in datos:
            if datos.get("password1") != datos.get("password2"):
                raise DomainValidationError("las contraseñas no coinciden")
            password = datos.get("password1")
        if not password:
            raise DomainValidationError("la contraseña es requerida")

        # Fecha nacimiento: acepta date o fechaNacimiento_str (yyyy-mm-dd)
        fecha_nacimiento = datos.get("fechaNacimiento")
        if fecha_nacimiento is None and datos.get("fechaNacimiento_str"):
            try:
                fecha_nacimiento = datetime.strptime(datos["fechaNacimiento_str"], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                raise DomainValidationError("formato de fecha de nacimiento inválido, use AAAA-MM-DD")
        if not fecha_nacimiento:
            raise DomainValidationError("la fecha de nacimiento es requerida")

        campos_requeridos = [
            nombre, apellido, username, correo, cedula,
            telefono, ciudad, rol,
        ]
        if not all(campos_requeridos):
            raise DomainValidationError(
                "todos los campos del registro son requeridos"
            )

        self._validar_longitudes(nombre, apellido, username, cedula, telefono)
        self._validar_correo(correo)
        self._validar_password(password)

        hoy = date.today()
        edad = (
            hoy.year - fecha_nacimiento.year
            - ((hoy.month, hoy.day) < (fecha_nacimiento.month, fecha_nacimiento.day))
        )
        if edad < 15:
            raise DomainValidationError("debes tener al menos 15 años para registrarte")

        if Usuario.objects.filter(username=username).exists():
            raise ConflictError("ya existe un usuario con ese nombre de usuario")
        if User.objects.filter(username=username).exists():
            raise ConflictError("ya existe una cuenta con ese nombre de usuario")
        if Usuario.objects.filter(cedula=cedula).exists():
            raise ConflictError("ya existe un usuario con esa cédula")

        opciones_rol = [choice[0] for choice in Usuario._meta.get_field("rol").choices]
        if rol not in opciones_rol:
            raise DomainValidationError(f"rol inválido: {rol}")

        with transaction.atomic():
            user = User.objects.create_user(
                username=username,
                email=correo,
                password=password,
            )
            usuario = Usuario.objects.create(
                user=user,
                nombre=nombre,
                apellido=apellido,
                username=username,
                correo=correo,
                cedula=cedula,
                telefono=telefono,
                fechaNacimiento=fecha_nacimiento,
                ciudad=ciudad,
                rol=rol,
                verificado=True,
            )
        return usuario

    def _validar_longitudes(self, nombre, apellido, username, cedula, telefono):
        if len(nombre) > self._MAX_NOMBRE:
            raise DomainValidationError(f"el nombre no puede superar {self._MAX_NOMBRE} caracteres")
        if len(apellido) > self._MAX_NOMBRE:
            raise DomainValidationError(f"el apellido no puede superar {self._MAX_NOMBRE} caracteres")
        if len(username) > self._MAX_USERNAME:
            raise DomainValidationError(f"el username no puede superar {self._MAX_USERNAME} caracteres")
        if len(cedula) > self._MAX_CEDULA:
            raise DomainValidationError(f"la cédula no puede superar {self._MAX_CEDULA} caracteres")
        if len(telefono) > self._MAX_TELEFONO:
            raise DomainValidationError(f"el teléfono no puede superar {self._MAX_TELEFONO} caracteres")

    @staticmethod
    def _validar_correo(correo: str):
        import re
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", correo):
            raise DomainValidationError("el correo no tiene un formato válido")

    @staticmethod
    def _validar_password(password: str):
        import re
        if len(password) < 8:
            raise DomainValidationError("la contraseña debe tener al menos 8 caracteres")
        if not re.search(r"[A-Z]", password):
            raise DomainValidationError("la contraseña debe tener al menos una mayúscula")
        if not re.search(r"[0-9]", password):
            raise DomainValidationError("la contraseña debe tener al menos un número")
        if not re.search(r"[^A-Za-z0-9]", password):
            raise DomainValidationError("la contraseña debe tener al menos un carácter especial")


class AutenticacionService:
    # reglas de autenticacion de dominio

    def autenticar(self, username: str, password: str) -> Usuario:
        if not username or not password:
            raise DomainValidationError("username y password son requeridos")

        user = authenticate(username=username, password=password)
        if user is None:
            raise DomainValidationError("credenciales inválidas")

        try:
            usuario = (
                Usuario.objects.only("idUsuario", "rol", "user")
                .select_related("user")
                .get(user=user)
            )
        except Usuario.DoesNotExist:
            raise ResourceNotFoundError("el usuario no existe en el dominio")

        # regla: cuidadores deben estar verificados para usar la plataforma
        if usuario.rol == "cuidador" and not usuario.verificado:
            raise DomainValidationError("el cuidador aún no está verificado")

        return usuario


