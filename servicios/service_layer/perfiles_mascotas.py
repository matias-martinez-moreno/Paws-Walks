# capa de aplicacion: logica de negocio
from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import Avg, Count, Q
from django.utils import timezone

from servicios.domain.exceptions import (
    DomainError,
    DomainValidationError,
    ResourceNotFoundError,
)
from servicios.infra.factory import NotificadorFactory
from servicios.models import (
    Calificacion,
    EstadoSolicitud,
    Mascota,
    PerfilCuidador,
    PrecioServicio,
    SolicitudServicio,
    TipoMascota,
    TipoServicio,
    Usuario,
)


# modulo de servicios: perfiles y mascotas
from servicios.service_layer.disponibilidad import (
    _auto_finalizar_paseos_expirados,
    _puede_finalizar_solicitud,
)
from servicios.service_layer.reputacion_servicios import (
    calificacion_de_autor_en_solicitud as _calificacion_de_autor_en_solicitud,
    calificacion_mascota_de_autor_en_solicitud as _calificacion_mascota_de_autor_en_solicitud,
    resenas_mascotas_por_ids as _resenas_mascotas_por_ids,
)

class ListarMascotasDeDueñoService:
    # lista mascotas asociadas a un dueño

    def listar(self, dueño: Usuario):
        if dueño.rol != "dueño":
            raise DomainValidationError("el usuario no tiene rol de dueño")

        mascotas = list(Mascota.objects.filter(idDueño=dueño).order_by("nombreMascota"))
        mascotas_ids = [m.idMascota for m in mascotas]

        agregados = _resenas_mascotas_por_ids(mascotas_ids)

        for mascota in mascotas:
            metrica = agregados.get(mascota.idMascota, {"prom": None, "cnt": 0, "comentarios": []})
            mascota.calificacion_promedio = metrica["prom"]
            mascota.calificacion_count = metrica["cnt"]
            mascota.calificacion_comentarios = metrica.get("comentarios", [])

        return mascotas


class ListarAgendamientosCuidadorService:
    # lista solicitudes asociadas a un cuidador

    def listar(self, cuidador: Usuario):
        if cuidador.rol != "cuidador":
            raise DomainValidationError("el usuario no tiene rol de cuidador")

        try:
            perfil = PerfilCuidador.objects.get(idCuidador=cuidador)
        except PerfilCuidador.DoesNotExist:
            raise ResourceNotFoundError("el cuidador no tiene perfil configurado")

        ahora_local = timezone.localtime()
        hoy = ahora_local.date()
        qs = SolicitudServicio.objects.filter(
            Q(idBloqueHorario__idCuidador=perfil) | Q(idVentana__idCuidador=perfil) | Q(idEvento__idCuidador=perfil),
            estado__in=[
                EstadoSolicitud.PENDIENTE,
                EstadoSolicitud.ACEPTADO,
                EstadoSolicitud.COMPLETADO,
                EstadoSolicitud.CANCELADO,
                EstadoSolicitud.RECHAZADO,
            ],
        ).select_related("idDueño", "idMascota", "idBloqueHorario", "idVentana", "idSlot", "idEvento", "idSlotEvento").prefetch_related(
            "mensajes_chat__idDe",
            "calificaciones",
            "calificaciones_mascota",
        )
        agendamientos = list(qs.order_by("fecha", "horaRecogidaAsignada", "idBloqueHorario__horaInicio"))

        _auto_finalizar_paseos_expirados(agendamientos, ahora=ahora_local)

        for solicitud in agendamientos:
            solicitud.calificacion_mia = _calificacion_de_autor_en_solicitud(solicitud, cuidador)
            solicitud.calificacion_dueño_mia = solicitud.calificacion_mia
            solicitud.calificacion_mascota_mia = _calificacion_mascota_de_autor_en_solicitud(solicitud, cuidador)
            solicitud.fecha_limite_servicio = solicitud.fechaFin or solicitud.fecha
            solicitud.puede_finalizar = _puede_finalizar_solicitud(solicitud, ahora=ahora_local)

        dueños_ids = {solicitud.idDueño_id for solicitud in agendamientos}
        agregados_dueños = {}
        if dueños_ids:
            for row in (
                Calificacion.objects.filter(idParaUsuario_id__in=dueños_ids)
                .values("idParaUsuario_id")
                .annotate(prom=Avg("estrellas"), cnt=Count("pk"))
            ):
                prom = row.get("prom")
                agregados_dueños[row["idParaUsuario_id"]] = (
                    round(float(prom), 1) if prom is not None else None,
                    int(row.get("cnt") or 0),
                )

        for solicitud in agendamientos:
            prom_dueño, cnt_dueño = agregados_dueños.get(solicitud.idDueño_id, (None, 0))
            solicitud.calificacion_dueño_promedio = prom_dueño
            solicitud.calificacion_dueño_count = cnt_dueño

        mascotas_ids = list({solicitud.idMascota_id for solicitud in agendamientos if solicitud.idMascota_id})
        resenas_por_mascota = _resenas_mascotas_por_ids(mascotas_ids)
        for solicitud in agendamientos:
            metrica_mascota = resenas_por_mascota.get(
                solicitud.idMascota_id,
                {"prom": None, "cnt": 0, "comentarios": []},
            )
            solicitud.calificacion_mascota_promedio = metrica_mascota["prom"]
            solicitud.calificacion_mascota_count = metrica_mascota["cnt"]
            solicitud.calificacion_mascota_comentarios = metrica_mascota.get("comentarios", [])

        futuros = [
            solicitud
            for solicitud in agendamientos
            if solicitud.fecha_limite_servicio >= hoy and solicitud.estado in [EstadoSolicitud.PENDIENTE, EstadoSolicitud.ACEPTADO]
        ]
        pasados = [
            solicitud
            for solicitud in agendamientos
            if solicitud.fecha_limite_servicio < hoy
            or solicitud.estado in [
                EstadoSolicitud.COMPLETADO,
                EstadoSolicitud.CANCELADO,
                EstadoSolicitud.RECHAZADO,
            ]
        ]
        pendientes = [solicitud for solicitud in futuros if solicitud.estado == EstadoSolicitud.PENDIENTE]
        futuros_aceptados = [solicitud for solicitud in futuros if solicitud.estado == EstadoSolicitud.ACEPTADO]
        return {
            "agendamientos_futuros": futuros_aceptados,
            "agendamientos_pasados": pasados,
            "solicitudes_pendientes": pendientes,
        }


class ObtenerPerfilCuidadorService:
    # obtiene perfil de cuidador para UI

    def obtener(self, cuidador: Usuario) -> PerfilCuidador:
        if cuidador.rol != "cuidador":
            raise DomainValidationError("el usuario no tiene rol de cuidador")
        try:
            return PerfilCuidador.objects.get(idCuidador=cuidador)
        except PerfilCuidador.DoesNotExist:
            raise ResourceNotFoundError("el cuidador no tiene perfil configurado")


class ActualizarPerfilCuidadorService:

    def __init__(self, notificador=None):
        self.notificador = notificador or NotificadorFactory.crear()

    def actualizar(self, cuidador: Usuario, datos: dict) -> PerfilCuidador:
        if cuidador.rol != "cuidador":
            raise DomainValidationError("el usuario no tiene rol de cuidador")

        perfil, _ = PerfilCuidador.objects.get_or_create(
            idCuidador=cuidador,
        )

        # Nuevo esquema: varios servicios activos por cuidador.
        servicios = datos.get("servicios")
        if servicios is None:
            tipo_unico = datos.get("tipoServicio")
            servicios = [tipo_unico] if tipo_unico else []
        servicios = [s for s in servicios if s]
        validos = {TipoServicio.PASEO, TipoServicio.GUARDERIA}
        if not servicios:
            raise DomainValidationError("debes seleccionar al menos un tipo de servicio")
        if any(s not in validos for s in servicios):
            raise DomainValidationError("tipo de servicio inválido")

        tarifas = datos.get("tarifas") or {}
        descripciones = datos.get("descripciones") or {}
        if "tarifaHora" in datos and not tarifas:
            # Cuando el formulario envía un solo tipo de servicio.
            tarifas = {
                servicio: datos.get("tarifaHora")
                for servicio in servicios
            }

        for servicio in servicios:
            tarifa = tarifas.get(servicio)
            try:
                tarifa = int(tarifa)
            except (ValueError, TypeError):
                raise DomainValidationError(f"la tarifa para {servicio} debe ser un número entero")
            if tarifa <= 0:
                raise DomainValidationError(f"la tarifa para {servicio} debe ser mayor a 0")
            descripcion = descripciones.get(servicio) or ""
            defaults = {"precioCOP": tarifa, "descripcion": descripcion, "activo": True}
            PrecioServicio.objects.update_or_create(
                idCuidador=cuidador,
                tipoServicio=servicio,
                defaults=defaults,
            )

        PrecioServicio.objects.filter(idCuidador=cuidador).exclude(
            tipoServicio__in=servicios
        ).update(activo=False)

        precios_activos = PrecioServicio.objects.filter(idCuidador=cuidador, activo=True)
        perfil.tarifaHora = precios_activos.first().precioCOP if precios_activos.exists() else 0

        tipos_mascota = str(datos.get("tiposMascotaPreferidos") or "").strip().lower()
        if tipos_mascota in ("perro", "gato", "ambos") or "," in tipos_mascota:
            perfil.tiposMascotaPreferidos = tipos_mascota if tipos_mascota else "ambos"
        elif tipos_mascota:
            validos = ["perro", "gato"]
            parts = [p.strip() for p in tipos_mascota.split(",") if p.strip() in validos]
            perfil.tiposMascotaPreferidos = ",".join(sorted(set(parts))) if parts else "ambos"

        ciudad_servicio = datos.get("ciudadServicio")
        if ciudad_servicio is not None:
            ciudad_servicio = str(ciudad_servicio).strip()
            if len(ciudad_servicio) > 100:
                raise DomainValidationError("la ciudad operativa no puede superar 100 caracteres")
            perfil.ciudadServicio = ciudad_servicio

        lat_servicio = datos.get("latitudServicio")
        if lat_servicio is not None:
            lat_raw = str(lat_servicio).strip()
            if lat_raw == "":
                perfil.latitudServicio = None
            else:
                try:
                    perfil.latitudServicio = Decimal(lat_raw)
                except Exception:
                    raise DomainValidationError("latitud operativa inválida")

        lng_servicio = datos.get("longitudServicio")
        if lng_servicio is not None:
            lng_raw = str(lng_servicio).strip()
            if lng_raw == "":
                perfil.longitudServicio = None
            else:
                try:
                    perfil.longitudServicio = Decimal(lng_raw)
                except Exception:
                    raise DomainValidationError("longitud operativa inválida")

        radio_servicio = datos.get("radioKmServicio")
        if radio_servicio is not None:
            radio_raw = str(radio_servicio).strip()
            if radio_raw:
                try:
                    radio_val = Decimal(radio_raw)
                except Exception:
                    raise DomainValidationError("el radio operativo debe ser numérico")
                if radio_val < 1 or radio_val > 3:
                    raise DomainValidationError("el radio operativo debe estar entre 1 y 3 km")
                perfil.radioKmServicio = radio_val

        perfil.save()
        self.notificador.enviar_perfil_actualizado(cuidador)
        return perfil


class EditarPerfilUsuarioService:

    _CAMPOS_NO_EDITABLES = {"username", "rol"}

    def __init__(self, notificador=None):
        self.notificador = notificador or NotificadorFactory.crear()

    def editar(self, usuario: Usuario, datos: dict) -> Usuario:
        nombre = datos.get("nombre")
        if nombre:
            if len(nombre) > 50:
                raise DomainValidationError("el nombre no puede superar 50 caracteres")
            usuario.nombre = nombre

        apellido = datos.get("apellido")
        if apellido:
            if len(apellido) > 50:
                raise DomainValidationError("el apellido no puede superar 50 caracteres")
            usuario.apellido = apellido

        cedula = datos.get("cedula")
        if cedula:
            cedula = str(cedula).strip()
            if len(cedula) > 20:
                raise DomainValidationError("la cédula no puede superar 20 caracteres")
            if Usuario.objects.filter(cedula=cedula).exclude(idUsuario=usuario.idUsuario).exists():
                raise DomainValidationError("la cédula ya está registrada")
            usuario.cedula = cedula

        correo = datos.get("correo")
        if correo:
            import re
            if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", correo):
                raise DomainValidationError("el correo no tiene un formato válido")
            usuario.correo = correo

        telefono = datos.get("telefono")
        if telefono:
            if len(telefono) > 20:
                raise DomainValidationError("el teléfono no puede superar 20 caracteres")
            usuario.telefono = telefono

        ciudad = datos.get("ciudad")
        if ciudad:
            if len(ciudad) > 100:
                raise DomainValidationError("la ciudad no puede superar 100 caracteres")
            usuario.ciudad = ciudad

        direccion = datos.get("direccion")
        if direccion is not None:
            direccion = str(direccion).strip()
            if len(direccion) > 200:
                raise DomainValidationError("la dirección no puede superar 200 caracteres")
            usuario.direccion = direccion

        lat = datos.get("latitud")
        if lat is not None and str(lat).strip() != "":
            try:
                usuario.latitud = Decimal(str(lat).strip())
            except Exception:
                usuario.latitud = None
        lon = datos.get("longitud")
        if lon is not None and str(lon).strip() != "":
            try:
                usuario.longitud = Decimal(str(lon).strip())
            except Exception:
                usuario.longitud = None
        if datos.get("latitud") is not None and str(datos.get("latitud", "")).strip() == "":
            usuario.latitud = None
        if datos.get("longitud") is not None and str(datos.get("longitud", "")).strip() == "":
            usuario.longitud = None

        radio = datos.get("radioKm")
        if radio is not None and str(radio).strip() != "" and usuario.rol == "cuidador":
            try:
                r = Decimal(str(radio).strip())
                if r < 1 or r > 3:
                    raise DomainValidationError("el radio debe estar entre 1 y 3 km")
                usuario.radioKm = r
            except DomainValidationError:
                raise
            except Exception:
                usuario.radioKm = None
        elif datos.get("radioKm") is not None and str(datos.get("radioKm", "")).strip() == "" and usuario.rol == "cuidador":
            usuario.radioKm = None

        foto = datos.get("fotoPerfil")
        if foto is not None:
            if usuario.fotoPerfil:
                usuario.fotoPerfil.delete(save=False)
            usuario.fotoPerfil = foto if foto else None

        experiencia = datos.get("experiencia")

        with transaction.atomic():
            usuario.save()
            if usuario.rol == "cuidador" and experiencia is not None:
                perfil, _ = PerfilCuidador.objects.get_or_create(idCuidador=usuario)
                perfil.descripcion = str(experiencia).strip()
                perfil.save(update_fields=["descripcion"])

        self.notificador.enviar_perfil_actualizado(usuario)
        return usuario


class AgregarMascotaService:

    def __init__(self, notificador=None):
        self.notificador = notificador or NotificadorFactory.crear()

    def agregar(self, dueño: Usuario, datos: dict) -> Mascota:
        if dueño.rol != "dueño":
            raise DomainValidationError("el usuario no tiene rol de dueño")

        nombre_mascota = str(datos.get("nombreMascota") or "").strip()
        tipo = str(datos.get("tipo") or "").strip()
        raza = str(datos.get("raza") or "").strip()
        sexo = (datos.get("sexo") or "").strip().lower()
        tamano = (datos.get("tamano") or "").strip().lower()
        notas = str(datos.get("notas") or "").strip()
        condiciones_medicas = (datos.get("condicionesMedicas") or "").strip()
        esterilizado_raw = (datos.get("esterilizado") or "").strip().lower()
        vacunas_raw = (datos.get("vacunasAlDia") or "").strip().lower()

        if not nombre_mascota:
            raise DomainValidationError("el nombre de la mascota es requerido")
        if not tipo:
            raise DomainValidationError("el tipo de mascota es requerido")
        if not raza:
            raise DomainValidationError("la raza de la mascota es requerida")
        if not sexo:
            raise DomainValidationError("el sexo de la mascota es requerido")
        if not tamano:
            raise DomainValidationError("el tamaño de la mascota es requerido")
        if not condiciones_medicas:
            raise DomainValidationError("las condiciones médicas son requeridas")
        if not notas:
            raise DomainValidationError("las notas de comportamiento son requeridas")

        foto = datos.get("foto")
        if not foto:
            raise DomainValidationError("la foto de la mascota es requerida")

        opciones_tipo = [c[0] for c in TipoMascota.choices]
        if tipo not in opciones_tipo:
            raise DomainValidationError(f"tipo de mascota inválido: {tipo}")

        if sexo not in {"macho", "hembra"}:
            raise DomainValidationError("el sexo de la mascota es inválido")
        if tamano not in {"pequeno", "mediano", "grande"}:
            raise DomainValidationError("el tamaño de la mascota es inválido")
        if len(raza) > 100:
            raise DomainValidationError("la raza no puede superar 100 caracteres")
        if len(condiciones_medicas) > 500:
            raise DomainValidationError("las condiciones médicas no pueden superar 500 caracteres")

        opciones_si = {"si", "sí", "true", "1", "on"}
        opciones_no = {"no", "false", "0", "off"}

        if not esterilizado_raw:
            raise DomainValidationError("debes indicar si la mascota está esterilizada")
        if not vacunas_raw:
            raise DomainValidationError("debes indicar si la mascota tiene vacunas al día")

        if esterilizado_raw not in opciones_si | opciones_no:
            raise DomainValidationError("la opción de esterilizado es inválida")
        if vacunas_raw not in opciones_si | opciones_no:
            raise DomainValidationError("la opción de vacunas al día es inválida")

        esterilizado = esterilizado_raw in opciones_si
        vacunas_al_dia = vacunas_raw in opciones_si

        try:
            edad = int(datos.get("edad", 0))
        except (ValueError, TypeError):
            raise DomainValidationError("la edad debe ser un número entero")
        if edad < 0:
            raise DomainValidationError("la edad no puede ser negativa")

        peso = str(datos.get("peso") or "").strip()
        if not peso:
            raise DomainValidationError("el peso de la mascota es requerido")
        try:
            peso_val = float(peso)
        except (ValueError, TypeError):
            raise DomainValidationError("el peso debe ser un número")
        if peso_val < 0:
            raise DomainValidationError("el peso no puede ser negativo")

        mascota = Mascota.objects.create(
            idDueño=dueño,
            nombreMascota=nombre_mascota,
            tipo=tipo,
            raza=raza,
            sexo=sexo,
            tamano=tamano,
            edad=edad,
            peso=peso_val,
            esterilizado=esterilizado,
            vacunasAlDia=vacunas_al_dia,
            condicionesMedicas=condiciones_medicas,
            notas=notas,
            foto=foto if foto else None,
        )
        self.notificador.enviar_mascota_creada(mascota, actor=dueño)
        return mascota


class EditarMascotaService:

    def __init__(self, notificador=None):
        self.notificador = notificador or NotificadorFactory.crear()

    def editar(self, dueño: Usuario, mascota_id: str, datos: dict) -> Mascota:
        if dueño.rol != "dueño":
            raise DomainValidationError("el usuario no tiene rol de dueño")

        try:
            mascota = Mascota.objects.get(idMascota=mascota_id, idDueño=dueño)
        except Mascota.DoesNotExist:
            raise ResourceNotFoundError("mascota no encontrada")

        nombre_mascota = str(datos.get("nombreMascota") or "").strip()
        tipo = str(datos.get("tipo") or "").strip()
        raza = str(datos.get("raza") or "").strip()
        sexo = (datos.get("sexo") or "").strip().lower()
        tamano = (datos.get("tamano") or "").strip().lower()
        notas = str(datos.get("notas") or "").strip()
        condiciones_medicas = (datos.get("condicionesMedicas") or "").strip()
        esterilizado_raw = (datos.get("esterilizado") or "").strip().lower()
        vacunas_raw = (datos.get("vacunasAlDia") or "").strip().lower()

        if not nombre_mascota:
            raise DomainValidationError("el nombre de la mascota es requerido")
        if not tipo:
            raise DomainValidationError("el tipo de mascota es requerido")

        opciones_tipo = [c[0] for c in TipoMascota.choices]
        if tipo not in opciones_tipo:
            raise DomainValidationError(f"tipo de mascota inválido: {tipo}")

        if sexo and sexo not in {"macho", "hembra"}:
            raise DomainValidationError("el sexo de la mascota es inválido")
        if tamano and tamano not in {"pequeno", "mediano", "grande"}:
            raise DomainValidationError("el tamaño de la mascota es inválido")
        if len(raza) > 100:
            raise DomainValidationError("la raza no puede superar 100 caracteres")
        if len(condiciones_medicas) > 500:
            raise DomainValidationError("las condiciones médicas no pueden superar 500 caracteres")

        esterilizado = esterilizado_raw in {"si", "sí", "true", "1", "on"}
        vacunas_al_dia = vacunas_raw in {"si", "sí", "true", "1", "on"}

        try:
            edad = int(datos.get("edad", 0))
        except (ValueError, TypeError):
            raise DomainValidationError("la edad debe ser un número entero")
        if edad < 0:
            raise DomainValidationError("la edad no puede ser negativa")

        peso = datos.get("peso")
        peso_val = None
        if peso:
            try:
                peso_val = float(peso)
            except (ValueError, TypeError):
                raise DomainValidationError("el peso debe ser un número")
            if peso_val < 0:
                raise DomainValidationError("el peso no puede ser negativo")

        mascota.nombreMascota = nombre_mascota
        mascota.tipo = tipo
        mascota.raza = raza
        mascota.sexo = sexo
        mascota.tamano = tamano
        mascota.edad = edad
        mascota.peso = peso_val
        mascota.esterilizado = esterilizado
        mascota.vacunasAlDia = vacunas_al_dia
        mascota.condicionesMedicas = condiciones_medicas
        mascota.notas = notas
        mascota.save(
            update_fields=[
                "nombreMascota",
                "tipo",
                "raza",
                "sexo",
                "tamano",
                "edad",
                "peso",
                "esterilizado",
                "vacunasAlDia",
                "condicionesMedicas",
                "notas",
            ]
        )
        self.notificador.enviar_mascota_editada(mascota, actor=dueño)
        return mascota


class EliminarMascotaService:

    def __init__(self, notificador=None):
        self.notificador = notificador or NotificadorFactory.crear()

    def eliminar(self, dueño: Usuario, mascota_id: str):
        if dueño.rol != "dueño":
            raise DomainValidationError("el usuario no tiene rol de dueño")
        try:
            mascota = Mascota.objects.get(idMascota=mascota_id, idDueño=dueño)
        except Mascota.DoesNotExist:
            raise ResourceNotFoundError("mascota no encontrada")
        nombre_mascota = mascota.nombreMascota
        mascota.delete()
        self.notificador.enviar_mascota_eliminada(nombre_mascota, dueño, actor=dueño)


class ActualizarFotoMascotaService:

    def __init__(self, notificador=None):
        self.notificador = notificador or NotificadorFactory.crear()

    def actualizar(self, dueño: Usuario, mascota_id: str, foto) -> Mascota:
        if dueño.rol != "dueño":
            raise DomainValidationError("el usuario no tiene rol de dueño")
        if not foto:
            raise DomainValidationError("debes seleccionar una imagen")
        try:
            mascota = Mascota.objects.get(idMascota=mascota_id, idDueño=dueño)
        except Mascota.DoesNotExist:
            raise ResourceNotFoundError("mascota no encontrada")
        if mascota.foto:
            mascota.foto.delete(save=False)
        mascota.foto = foto
        mascota.save(update_fields=["foto"])
        self.notificador.enviar_mascota_editada(mascota, actor=dueño)
        return mascota


class ConstruirDatosMascotaFormularioService:
    """Construye payload de mascota desde formulario web."""

    @staticmethod
    def construir(source, files=None, incluir_foto: bool = False) -> dict:
        datos = {
            "nombreMascota": source.get("nombreMascota"),
            "tipo": source.get("tipo"),
            "raza": source.get("raza", ""),
            "sexo": source.get("sexo", ""),
            "tamano": source.get("tamano", ""),
            "edad": source.get("edad"),
            "peso": source.get("peso"),
            "esterilizado": source.get("esterilizado", ""),
            "vacunasAlDia": source.get("vacunasAlDia", ""),
            "condicionesMedicas": source.get("condicionesMedicas", ""),
            "notas": source.get("notas", ""),
        }
        if incluir_foto:
            datos["foto"] = files.get("foto") if files is not None else None
        return datos


class ProcesarAccionesDueñoMascotasService:
    """Centraliza acciones POST del módulo de mascotas del dueño."""

    def __init__(
        self,
        eliminar_service: EliminarMascotaService | None = None,
        foto_service: ActualizarFotoMascotaService | None = None,
        editar_service: EditarMascotaService | None = None,
        agregar_service: AgregarMascotaService | None = None,
        datos_service: ConstruirDatosMascotaFormularioService | None = None,
    ):
        self._eliminar_service = eliminar_service or EliminarMascotaService()
        self._foto_service = foto_service or ActualizarFotoMascotaService()
        self._editar_service = editar_service or EditarMascotaService()
        self._agregar_service = agregar_service or AgregarMascotaService()
        self._datos_service = datos_service or ConstruirDatosMascotaFormularioService()

    def procesar(self, dueño: Usuario, action: str | None, source, files) -> dict:
        action_norm = str(action or "").strip()
        try:
            if action_norm == "eliminar":
                self._eliminar_service.eliminar(dueño, source.get("mascota_id"))
                return {"ok": True}

            if action_norm == "cambiar_foto":
                self._foto_service.actualizar(dueño, source.get("mascota_id"), files.get("foto"))
                return {"ok": True}

            if action_norm == "editar":
                datos = self._datos_service.construir(source)
                self._editar_service.editar(dueño, source.get("mascota_id"), datos)
                return {"ok": True}

            datos = self._datos_service.construir(source, files=files, incluir_foto=True)
            self._agregar_service.agregar(dueño, datos)
            return {"ok": True}
        except DomainError as error:
            return {
                "ok": False,
                "error": str(error),
            }


