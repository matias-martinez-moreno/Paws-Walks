# capa de aplicacion: logica de negocio
from __future__ import annotations

import json
from datetime import datetime

from django.core.exceptions import ValidationError

from servicios.domain.builder import SolicitudServicioBuilder
from servicios.infra.factory import NotificadorFactory
from servicios.models import BloqueTiempo, Mascota, Usuario


class SolicitudServicioService:
    # orquesta builder y factory

    def __init__(self, notificador=None):
        # inyeccion de dependencias
        self.notificador = notificador or NotificadorFactory.crear()

    def crear_solicitud(self, datos):
        # construye y valida con builder
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
        solicitud.save()
        
        # marca bloque como ocupado
        bloque = solicitud.idBloqueHorario
        bloque.disponible = False
        bloque.save()
        
        # envia notificacion segun entorno
        self.notificador.enviar_confirmacion(solicitud)
        
        return solicitud


class CrearSolicitudServicioAppService:
    # app service del flujo crear solicitud

    def __init__(self, solicitud_service: SolicitudServicioService | None = None):
        self._solicitud_service = solicitud_service or SolicitudServicioService()

    def get_form_context(self) -> dict:
        # carga datos para el formulario
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
                    "texto": f"{bloque.diaSemana} {bloque.horaInicio}-{bloque.horaFin}",
                }
            )

        return {
            "cuidadores": cuidadores,
            "mascotas": mascotas,
            "bloques_por_cuidador": json.dumps(bloques_por_cuidador),
        }

    def crear_desde_form(self, post_data) -> object:
        # convierte datos del form y delega
        dueño = self._resolver_dueño_por_defecto()

        fecha_str = post_data.get("fecha")
        if not fecha_str:
            raise ValidationError("fecha es requerida")

        datos = {
            "idDueño": dueño,
            "idCuidador_id": post_data.get("idCuidador_id"),
            "idMascota_id": post_data.get("idMascota_id"),
            "tipoServicio": post_data.get("tipoServicio"),
            "fecha": datetime.strptime(fecha_str, "%Y-%m-%d").date(),
            "idBloqueHorario_id": post_data.get("idBloqueHorario_id"),
        }
        return self._solicitud_service.crear_solicitud(datos)

    def crear_desde_api(self, validated_data: dict) -> object:
        # recibe datos validados por drf y delega
        dueño = self._resolver_dueño_por_defecto()
        datos = {
            "idDueño": dueño,
            "idCuidador_id": validated_data.get("idCuidador_id"),
            "idMascota_id": validated_data.get("idMascota_id"),
            "tipoServicio": validated_data.get("tipoServicio"),
            "fecha": validated_data.get("fecha"),
            "idBloqueHorario_id": validated_data.get("idBloqueHorario_id"),
        }
        return self._solicitud_service.crear_solicitud(datos)

    def _resolver_dueño_por_defecto(self) -> Usuario:
        # en produccion esto vendria del usuario autenticado
        dueño = Usuario.objects.first()
        if not dueño:
            raise ValidationError("no hay usuarios en la base de datos")
        return dueño
