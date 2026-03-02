# capa de aplicacion: logica de negocio
from __future__ import annotations

import json
from datetime import datetime

from django.db import transaction

from servicios.domain.builder import SolicitudServicioBuilder
from servicios.domain.exceptions import (
    ConflictError,
    DomainValidationError,
    ResourceNotFoundError,
)
from servicios.infra.factory import NotificadorFactory
from servicios.models import BloqueTiempo, Mascota, Usuario


class SolicitudServicioService:
    # orquesta builder y factory

    def __init__(self, notificador=None):
        # inyeccion de dependencias
        self.notificador = notificador or NotificadorFactory.crear()

    def crear_solicitud(self, datos):
        # construye y valida con builder
        with transaction.atomic():
            solicitud = (
                SolicitudServicioBuilder()
                .para_dueño(datos['idDueño'])
                .para_cuidador(datos['idCuidador_id'])
                .para_mascota(datos['idMascota_id'])
                .con_servicio(datos['tipoServicio'])
                .en_fecha(datos['fecha'])
                .en_bloque(datos['idBloqueHorario_id'])
                .build()
            )

            # bloquea el bloque para evitar carrera de reservas
            bloque = BloqueTiempo.objects.select_for_update().get(
                idBloque=solicitud.idBloqueHorario.idBloque
            )
            if not bloque.disponible:
                raise ConflictError("el bloque no esta disponible")

            solicitud.idBloqueHorario = bloque
            solicitud.save()
            bloque.disponible = False
            bloque.save(update_fields=["disponible"])

        # envia notificacion segun entorno
        self.notificador.enviar_confirmacion(solicitud)
        
        return solicitud


class CrearSolicitudServicioAppService:
    # app service del flujo crear solicitud

    def __init__(self, solicitud_service: SolicitudServicioService | None = None):
        self._solicitud_service = solicitud_service or SolicitudServicioService()

    def get_form_context(self) -> dict:
        # carga datos para el formulario
        dueños = Usuario.objects.filter(rol__in=["dueño", "ambos"])
        cuidadores = Usuario.objects.filter(rol__in=["cuidador", "ambos"], verificado=True)
        mascotas = Mascota.objects.all()
        bloques = (
            BloqueTiempo.objects.filter(disponible=True)
            .select_related("idCuidador__idCuidador")
        )

        bloques_por_cuidador: dict[str, list[dict[str, str]]] = {}
        for bloque in bloques:
            cuidador_id = str(bloque.idCuidador.idCuidador.idUsuario)
            bloques_por_cuidador.setdefault(cuidador_id, []).append(
                {
                    "id": str(bloque.idBloque),
                    "dia": bloque.diaSemana,
                    "texto": f"{bloque.diaSemana} {bloque.horaInicio}-{bloque.horaFin}",
                }
            )

        return {
            "dueños": dueños,
            "cuidadores": cuidadores,
            "mascotas": mascotas,
            "bloques_por_cuidador": json.dumps(bloques_por_cuidador),
        }

    def crear_desde_form(self, post_data) -> object:
        # convierte datos del form y delega
        dueño = self._resolver_dueño(post_data.get("idDueño_id"))

        fecha_str = post_data.get("fecha")
        if not fecha_str:
            raise DomainValidationError("fecha es requerida")

        try:
            fecha = datetime.strptime(fecha_str, "%Y-%m-%d").date()
        except ValueError:
            raise DomainValidationError("formato de fecha invalido, use yyyy-mm-dd")

        datos = {
            "idDueño": dueño,
            "idCuidador_id": post_data.get("idCuidador_id"),
            "idMascota_id": post_data.get("idMascota_id"),
            "tipoServicio": post_data.get("tipoServicio"),
            "fecha": fecha,
            "idBloqueHorario_id": post_data.get("idBloqueHorario_id"),
        }
        return self._solicitud_service.crear_solicitud(datos)

    def crear_desde_api(self, validated_data: dict) -> object:
        # recibe datos validados por drf y delega
        dueño = self._resolver_dueño(validated_data.get("idDueño_id"))
        datos = {
            "idDueño": dueño,
            "idCuidador_id": validated_data.get("idCuidador_id"),
            "idMascota_id": validated_data.get("idMascota_id"),
            "tipoServicio": validated_data.get("tipoServicio"),
            "fecha": validated_data.get("fecha"),
            "idBloqueHorario_id": validated_data.get("idBloqueHorario_id"),
        }
        return self._solicitud_service.crear_solicitud(datos)

    def _resolver_dueño(self, dueño_id) -> Usuario:
        # exige dueño explicito para evitar defaults ocultos
        if not dueño_id:
            raise DomainValidationError("idDueño_id es requerido")
        try:
            dueño = Usuario.objects.get(idUsuario=dueño_id)
        except Usuario.DoesNotExist:
            raise ResourceNotFoundError("el dueño no existe")
        if dueño.rol not in ["dueño", "ambos"]:
            raise DomainValidationError("el usuario no tiene rol de dueño")
        return dueño
