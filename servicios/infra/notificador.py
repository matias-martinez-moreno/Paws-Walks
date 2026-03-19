# notificador - interfaz y implementaciones
from abc import ABC, abstractmethod


def _crear_notificacion(
    *,
    para_usuario,
    tipo_evento,
    categoria,
    titulo,
    descripcion="",
    actor_usuario=None,
    solicitud=None,
    mascota=None,
    url_destino="",
):
    from servicios.models import Notificacion

    Notificacion.objects.create(
        idParaUsuario=para_usuario,
        idActorUsuario=actor_usuario,
        idSolicitud=solicitud,
        idMascota=mascota,
        categoria=categoria,
        tipoEvento=tipo_evento,
        titulo=titulo,
        descripcion=descripcion,
        urlDestino=url_destino,
    )


def _resumen_mensaje_chat(texto: str, limite: int = 120) -> str:
    limpio = " ".join(str(texto or "").strip().split())
    if len(limpio) <= limite:
        return limpio
    return f"{limpio[: limite - 3].rstrip()}..."


class NotificadorBase(ABC):
    """interfaz para notificadores"""

    @abstractmethod
    def enviar_confirmacion(self, solicitud):
        pass

    @abstractmethod
    def enviar_nueva_solicitud(self, solicitud):
        pass

    @abstractmethod
    def enviar_solicitud_aceptada(self, solicitud):
        pass

    @abstractmethod
    def enviar_solicitud_rechazada(self, solicitud):
        pass

    @abstractmethod
    def enviar_servicio_completado(self, solicitud):
        pass

    @abstractmethod
    def enviar_resena_pendiente(self, solicitud):
        pass

    @abstractmethod
    def enviar_reserva_cancelada(self, solicitud, actor=None, receptor=None, destino=None):
        pass

    @abstractmethod
    def enviar_mascota_creada(self, mascota, actor):
        pass

    @abstractmethod
    def enviar_mascota_editada(self, mascota, actor):
        pass

    @abstractmethod
    def enviar_mascota_eliminada(self, nombre_mascota, dueño, actor=None):
        pass

    @abstractmethod
    def enviar_perfil_actualizado(self, usuario):
        pass

    @abstractmethod
    def enviar_mensaje_chat(self, solicitud, actor, receptor, mensaje):
        pass


class NotificadorMock(NotificadorBase):
    """mock - imprime en consola para desarrollo"""

    def enviar_confirmacion(self, solicitud):
        print(f"[MOCK] confirmación enviada: solicitud {solicitud.idSolicitud}")

    def enviar_nueva_solicitud(self, solicitud):
        print(f"[MOCK] nueva solicitud → cuidador {solicitud.idCuidador.correo}: {solicitud.idSolicitud}")
        from servicios.models import CategoriaNotificacion, TipoNotificacion

        _crear_notificacion(
            para_usuario=solicitud.idCuidador,
            actor_usuario=solicitud.idDueño,
            solicitud=solicitud,
            tipo_evento=TipoNotificacion.NUEVA_RESERVA,
            categoria=CategoriaNotificacion.NEGOCIO,
            titulo=f"Nueva reserva de {solicitud.idDueño.nombre}",
            descripcion=f"{solicitud.get_tipoServicio_display()} para {solicitud.idMascota.nombreMascota} el {solicitud.fecha}",
            url_destino="/cuidador/calendario/",
        )

    def enviar_solicitud_aceptada(self, solicitud):
        print(f"[MOCK] solicitud aceptada → dueño {solicitud.idDueño.correo}: {solicitud.idSolicitud}")
        from servicios.models import CategoriaNotificacion, TipoNotificacion

        _crear_notificacion(
            para_usuario=solicitud.idDueño,
            actor_usuario=solicitud.idCuidador,
            solicitud=solicitud,
            tipo_evento=TipoNotificacion.RESERVA_ACEPTADA,
            categoria=CategoriaNotificacion.NEGOCIO,
            titulo="Tu reserva fue aceptada",
            descripcion=f"{solicitud.idCuidador.nombre} aceptó tu reserva de {solicitud.get_tipoServicio_display()}.",
            url_destino="/dueño/mis-reservas/",
        )

    def enviar_solicitud_rechazada(self, solicitud):
        print(f"[MOCK] solicitud rechazada → dueño {solicitud.idDueño.correo}: {solicitud.idSolicitud}")
        from servicios.models import CategoriaNotificacion, TipoNotificacion

        _crear_notificacion(
            para_usuario=solicitud.idDueño,
            actor_usuario=solicitud.idCuidador,
            solicitud=solicitud,
            tipo_evento=TipoNotificacion.RESERVA_RECHAZADA,
            categoria=CategoriaNotificacion.NEGOCIO,
            titulo="Tu reserva fue rechazada",
            descripcion=f"{solicitud.idCuidador.nombre} rechazó la reserva de {solicitud.get_tipoServicio_display()}.",
            url_destino="/dueño/mis-reservas/",
        )

    def enviar_servicio_completado(self, solicitud):
        print(f"[MOCK] servicio finalizado → dueño {solicitud.idDueño.correo}, cuidador {solicitud.idCuidador.correo}")
        from servicios.models import CategoriaNotificacion, TipoNotificacion

        _crear_notificacion(
            para_usuario=solicitud.idDueño,
            actor_usuario=solicitud.idCuidador,
            solicitud=solicitud,
            tipo_evento=TipoNotificacion.SERVICIO_COMPLETADO,
            categoria=CategoriaNotificacion.NEGOCIO,
            titulo="Servicio finalizado",
            descripcion=f"El servicio de {solicitud.get_tipoServicio_display()} fue marcado como finalizado.",
            url_destino="/dueño/mis-reservas/",
        )
        _crear_notificacion(
            para_usuario=solicitud.idCuidador,
            actor_usuario=solicitud.idDueño,
            solicitud=solicitud,
            tipo_evento=TipoNotificacion.SERVICIO_COMPLETADO,
            categoria=CategoriaNotificacion.NEGOCIO,
            titulo="Servicio finalizado",
            descripcion=f"El servicio de {solicitud.get_tipoServicio_display()} fue marcado como finalizado.",
            url_destino="/cuidador/calendario/",
        )

    def enviar_resena_pendiente(self, solicitud):
        from servicios.models import CategoriaNotificacion, TipoNotificacion

        url_owner = f"/dueño/mis-reservas/?resena_objetivo=cuidador&resena_solicitud={solicitud.idSolicitud}"
        url_caregiver_owner = f"/cuidador/calendario/?resena_objetivo=dueno&resena_solicitud={solicitud.idSolicitud}"
        url_caregiver_pet = f"/cuidador/calendario/?resena_objetivo=mascota&resena_solicitud={solicitud.idSolicitud}"

        _crear_notificacion(
            para_usuario=solicitud.idDueño,
            actor_usuario=solicitud.idCuidador,
            solicitud=solicitud,
            mascota=solicitud.idMascota,
            tipo_evento=TipoNotificacion.RESENA_PENDIENTE,
            categoria=CategoriaNotificacion.NEGOCIO,
            titulo="Reseña pendiente del cuidador",
            descripcion=f"El servicio finalizó. Califica a {solicitud.idCuidador.nombre} para completar tu experiencia.",
            url_destino=url_owner,
        )
        _crear_notificacion(
            para_usuario=solicitud.idCuidador,
            actor_usuario=solicitud.idDueño,
            solicitud=solicitud,
            mascota=solicitud.idMascota,
            tipo_evento=TipoNotificacion.RESENA_PENDIENTE,
            categoria=CategoriaNotificacion.NEGOCIO,
            titulo="Reseña pendiente del dueño",
            descripcion=f"Califica a {solicitud.idDueño.nombre} para cerrar este servicio.",
            url_destino=url_caregiver_owner,
        )
        _crear_notificacion(
            para_usuario=solicitud.idCuidador,
            actor_usuario=solicitud.idDueño,
            solicitud=solicitud,
            mascota=solicitud.idMascota,
            tipo_evento=TipoNotificacion.RESENA_PENDIENTE,
            categoria=CategoriaNotificacion.NEGOCIO,
            titulo="Reseña pendiente de mascota",
            descripcion=f"Califica a {solicitud.idMascota.nombreMascota} para completar la reseña del servicio.",
            url_destino=url_caregiver_pet,
        )

    def enviar_reserva_cancelada(self, solicitud, actor=None, receptor=None, destino=None):
        print(f"[MOCK] reserva cancelada: {solicitud.idSolicitud}")
        from servicios.models import CategoriaNotificacion, TipoNotificacion

        if receptor is None:
            raise ValueError("receptor es requerido para notificar cancelación")

        destino_url = str(destino or "").strip()
        if not destino_url:
            raise ValueError("destino es requerido para notificar cancelación")

        quien = actor.nombre if actor else "El sistema"
        _crear_notificacion(
            para_usuario=receptor,
            actor_usuario=actor,
            solicitud=solicitud,
            tipo_evento=TipoNotificacion.RESERVA_CANCELADA,
            categoria=CategoriaNotificacion.NEGOCIO,
            titulo="Reserva cancelada",
            descripcion=f"{quien} canceló la reserva de {solicitud.get_tipoServicio_display()}.",
            url_destino=destino_url,
        )

    def enviar_mascota_creada(self, mascota, actor):
        from servicios.models import CategoriaNotificacion, TipoNotificacion

        _crear_notificacion(
            para_usuario=mascota.idDueño,
            actor_usuario=actor,
            mascota=mascota,
            tipo_evento=TipoNotificacion.MASCOTA_CREADA,
            categoria=CategoriaNotificacion.SISTEMA,
            titulo="Mascota creada",
            descripcion=f"Se agregó la mascota {mascota.nombreMascota} correctamente.",
            url_destino="/dueño/mis-mascotas/",
        )

    def enviar_mascota_editada(self, mascota, actor):
        from servicios.models import CategoriaNotificacion, TipoNotificacion

        _crear_notificacion(
            para_usuario=mascota.idDueño,
            actor_usuario=actor,
            mascota=mascota,
            tipo_evento=TipoNotificacion.MASCOTA_EDITADA,
            categoria=CategoriaNotificacion.SISTEMA,
            titulo="Mascota actualizada",
            descripcion=f"Se actualizó la información de {mascota.nombreMascota}.",
            url_destino="/dueño/mis-mascotas/",
        )

    def enviar_mascota_eliminada(self, nombre_mascota, dueño, actor=None):
        from servicios.models import CategoriaNotificacion, TipoNotificacion

        _crear_notificacion(
            para_usuario=dueño,
            actor_usuario=actor,
            tipo_evento=TipoNotificacion.MASCOTA_ELIMINADA,
            categoria=CategoriaNotificacion.SISTEMA,
            titulo="Mascota eliminada",
            descripcion=f"Se eliminó la mascota {nombre_mascota}.",
            url_destino="/dueño/mis-mascotas/",
        )

    def enviar_perfil_actualizado(self, usuario):
        from servicios.models import CategoriaNotificacion, TipoNotificacion

        destino = "/cuidador/mi-perfil/" if usuario.rol == "cuidador" else "/dueño/mi-perfil/"
        _crear_notificacion(
            para_usuario=usuario,
            actor_usuario=usuario,
            tipo_evento=TipoNotificacion.PERFIL_ACTUALIZADO,
            categoria=CategoriaNotificacion.SISTEMA,
            titulo="Perfil actualizado",
            descripcion="Tus datos de perfil fueron actualizados correctamente.",
            url_destino=destino,
        )

    def enviar_mensaje_chat(self, solicitud, actor, receptor, mensaje):
        from servicios.models import CategoriaNotificacion, TipoNotificacion

        if not receptor:
            return

        destino = "/cuidador/calendario/" if receptor.rol == "cuidador" else "/dueño/mis-reservas/"
        nombre_actor = actor.nombre if actor else "Alguien"
        descripcion = _resumen_mensaje_chat(mensaje)

        _crear_notificacion(
            para_usuario=receptor,
            actor_usuario=actor,
            solicitud=solicitud,
            tipo_evento=TipoNotificacion.MENSAJE_CHAT,
            categoria=CategoriaNotificacion.NEGOCIO,
            titulo=f"Nuevo mensaje de {nombre_actor}",
            descripcion=descripcion or "Tienes un nuevo mensaje en tu conversación.",
            url_destino=destino,
        )


class NotificadorReal(NotificadorBase):
    """real - aquí se integraría email real (sendgrid, ses, etc)"""

    def enviar_confirmacion(self, solicitud):
        print(f"[REAL] enviando email a {solicitud.idDueño.correo}: solicitud {solicitud.idSolicitud}")

    def enviar_nueva_solicitud(self, solicitud):
        print(f"[REAL] enviando email a cuidador {solicitud.idCuidador.correo}: nueva solicitud {solicitud.idSolicitud}")
        from servicios.models import CategoriaNotificacion, TipoNotificacion

        _crear_notificacion(
            para_usuario=solicitud.idCuidador,
            actor_usuario=solicitud.idDueño,
            solicitud=solicitud,
            tipo_evento=TipoNotificacion.NUEVA_RESERVA,
            categoria=CategoriaNotificacion.NEGOCIO,
            titulo=f"Nueva reserva de {solicitud.idDueño.nombre}",
            descripcion=f"{solicitud.get_tipoServicio_display()} para {solicitud.idMascota.nombreMascota} el {solicitud.fecha}",
            url_destino="/cuidador/calendario/",
        )

    def enviar_solicitud_aceptada(self, solicitud):
        print(f"[REAL] enviando email a dueño {solicitud.idDueño.correo}: solicitud aceptada {solicitud.idSolicitud}")
        from servicios.models import CategoriaNotificacion, TipoNotificacion

        _crear_notificacion(
            para_usuario=solicitud.idDueño,
            actor_usuario=solicitud.idCuidador,
            solicitud=solicitud,
            tipo_evento=TipoNotificacion.RESERVA_ACEPTADA,
            categoria=CategoriaNotificacion.NEGOCIO,
            titulo="Tu reserva fue aceptada",
            descripcion=f"{solicitud.idCuidador.nombre} aceptó tu reserva de {solicitud.get_tipoServicio_display()}.",
            url_destino="/dueño/mis-reservas/",
        )

    def enviar_solicitud_rechazada(self, solicitud):
        print(f"[REAL] enviando email a dueño {solicitud.idDueño.correo}: solicitud rechazada {solicitud.idSolicitud}")
        from servicios.models import CategoriaNotificacion, TipoNotificacion

        _crear_notificacion(
            para_usuario=solicitud.idDueño,
            actor_usuario=solicitud.idCuidador,
            solicitud=solicitud,
            tipo_evento=TipoNotificacion.RESERVA_RECHAZADA,
            categoria=CategoriaNotificacion.NEGOCIO,
            titulo="Tu reserva fue rechazada",
            descripcion=f"{solicitud.idCuidador.nombre} rechazó la reserva de {solicitud.get_tipoServicio_display()}.",
            url_destino="/dueño/mis-reservas/",
        )

    def enviar_servicio_completado(self, solicitud):
        print(f"[REAL] enviando email a dueño y cuidador: servicio finalizado {solicitud.idSolicitud}")
        from servicios.models import CategoriaNotificacion, TipoNotificacion

        _crear_notificacion(
            para_usuario=solicitud.idDueño,
            actor_usuario=solicitud.idCuidador,
            solicitud=solicitud,
            tipo_evento=TipoNotificacion.SERVICIO_COMPLETADO,
            categoria=CategoriaNotificacion.NEGOCIO,
            titulo="Servicio finalizado",
            descripcion=f"El servicio de {solicitud.get_tipoServicio_display()} fue marcado como finalizado.",
            url_destino="/dueño/mis-reservas/",
        )
        _crear_notificacion(
            para_usuario=solicitud.idCuidador,
            actor_usuario=solicitud.idDueño,
            solicitud=solicitud,
            tipo_evento=TipoNotificacion.SERVICIO_COMPLETADO,
            categoria=CategoriaNotificacion.NEGOCIO,
            titulo="Servicio finalizado",
            descripcion=f"El servicio de {solicitud.get_tipoServicio_display()} fue marcado como finalizado.",
            url_destino="/cuidador/calendario/",
        )

    def enviar_resena_pendiente(self, solicitud):
        print(f"[REAL] enviando email: reseña pendiente solicitud {solicitud.idSolicitud}")
        from servicios.models import CategoriaNotificacion, TipoNotificacion

        url_owner = f"/dueño/mis-reservas/?resena_objetivo=cuidador&resena_solicitud={solicitud.idSolicitud}"
        url_caregiver_owner = f"/cuidador/calendario/?resena_objetivo=dueno&resena_solicitud={solicitud.idSolicitud}"
        url_caregiver_pet = f"/cuidador/calendario/?resena_objetivo=mascota&resena_solicitud={solicitud.idSolicitud}"

        _crear_notificacion(
            para_usuario=solicitud.idDueño,
            actor_usuario=solicitud.idCuidador,
            solicitud=solicitud,
            mascota=solicitud.idMascota,
            tipo_evento=TipoNotificacion.RESENA_PENDIENTE,
            categoria=CategoriaNotificacion.NEGOCIO,
            titulo="Reseña pendiente del cuidador",
            descripcion=f"El servicio finalizó. Califica a {solicitud.idCuidador.nombre} para completar tu experiencia.",
            url_destino=url_owner,
        )
        _crear_notificacion(
            para_usuario=solicitud.idCuidador,
            actor_usuario=solicitud.idDueño,
            solicitud=solicitud,
            mascota=solicitud.idMascota,
            tipo_evento=TipoNotificacion.RESENA_PENDIENTE,
            categoria=CategoriaNotificacion.NEGOCIO,
            titulo="Reseña pendiente del dueño",
            descripcion=f"Califica a {solicitud.idDueño.nombre} para cerrar este servicio.",
            url_destino=url_caregiver_owner,
        )
        _crear_notificacion(
            para_usuario=solicitud.idCuidador,
            actor_usuario=solicitud.idDueño,
            solicitud=solicitud,
            mascota=solicitud.idMascota,
            tipo_evento=TipoNotificacion.RESENA_PENDIENTE,
            categoria=CategoriaNotificacion.NEGOCIO,
            titulo="Reseña pendiente de mascota",
            descripcion=f"Califica a {solicitud.idMascota.nombreMascota} para completar la reseña del servicio.",
            url_destino=url_caregiver_pet,
        )

    def enviar_reserva_cancelada(self, solicitud, actor=None, receptor=None, destino=None):
        print(f"[REAL] enviando email: reserva cancelada {solicitud.idSolicitud}")
        from servicios.models import CategoriaNotificacion, TipoNotificacion

        if receptor is None:
            raise ValueError("receptor es requerido para notificar cancelación")

        destino_url = str(destino or "").strip()
        if not destino_url:
            raise ValueError("destino es requerido para notificar cancelación")

        quien = actor.nombre if actor else "El sistema"
        _crear_notificacion(
            para_usuario=receptor,
            actor_usuario=actor,
            solicitud=solicitud,
            tipo_evento=TipoNotificacion.RESERVA_CANCELADA,
            categoria=CategoriaNotificacion.NEGOCIO,
            titulo="Reserva cancelada",
            descripcion=f"{quien} canceló la reserva de {solicitud.get_tipoServicio_display()}.",
            url_destino=destino_url,
        )

    def enviar_mascota_creada(self, mascota, actor):
        print(f"[REAL] enviando email: mascota creada {mascota.idMascota}")
        from servicios.models import CategoriaNotificacion, TipoNotificacion

        _crear_notificacion(
            para_usuario=mascota.idDueño,
            actor_usuario=actor,
            mascota=mascota,
            tipo_evento=TipoNotificacion.MASCOTA_CREADA,
            categoria=CategoriaNotificacion.SISTEMA,
            titulo="Mascota creada",
            descripcion=f"Se agregó la mascota {mascota.nombreMascota} correctamente.",
            url_destino="/dueño/mis-mascotas/",
        )

    def enviar_mascota_editada(self, mascota, actor):
        print(f"[REAL] enviando email: mascota editada {mascota.idMascota}")
        from servicios.models import CategoriaNotificacion, TipoNotificacion

        _crear_notificacion(
            para_usuario=mascota.idDueño,
            actor_usuario=actor,
            mascota=mascota,
            tipo_evento=TipoNotificacion.MASCOTA_EDITADA,
            categoria=CategoriaNotificacion.SISTEMA,
            titulo="Mascota actualizada",
            descripcion=f"Se actualizó la información de {mascota.nombreMascota}.",
            url_destino="/dueño/mis-mascotas/",
        )

    def enviar_mascota_eliminada(self, nombre_mascota, dueño, actor=None):
        print(f"[REAL] enviando email: mascota eliminada {nombre_mascota}")
        from servicios.models import CategoriaNotificacion, TipoNotificacion

        _crear_notificacion(
            para_usuario=dueño,
            actor_usuario=actor,
            tipo_evento=TipoNotificacion.MASCOTA_ELIMINADA,
            categoria=CategoriaNotificacion.SISTEMA,
            titulo="Mascota eliminada",
            descripcion=f"Se eliminó la mascota {nombre_mascota}.",
            url_destino="/dueño/mis-mascotas/",
        )

    def enviar_perfil_actualizado(self, usuario):
        print(f"[REAL] enviando email: perfil actualizado {usuario.idUsuario}")
        from servicios.models import CategoriaNotificacion, TipoNotificacion

        destino = "/cuidador/mi-perfil/" if usuario.rol == "cuidador" else "/dueño/mi-perfil/"
        _crear_notificacion(
            para_usuario=usuario,
            actor_usuario=usuario,
            tipo_evento=TipoNotificacion.PERFIL_ACTUALIZADO,
            categoria=CategoriaNotificacion.SISTEMA,
            titulo="Perfil actualizado",
            descripcion="Tus datos de perfil fueron actualizados correctamente.",
            url_destino=destino,
        )

    def enviar_mensaje_chat(self, solicitud, actor, receptor, mensaje):
        print(f"[REAL] enviando email: nuevo mensaje chat solicitud {solicitud.idSolicitud}")
        from servicios.models import CategoriaNotificacion, TipoNotificacion

        if not receptor:
            return

        destino = "/cuidador/calendario/" if receptor.rol == "cuidador" else "/dueño/mis-reservas/"
        nombre_actor = actor.nombre if actor else "Alguien"
        descripcion = _resumen_mensaje_chat(mensaje)

        _crear_notificacion(
            para_usuario=receptor,
            actor_usuario=actor,
            solicitud=solicitud,
            tipo_evento=TipoNotificacion.MENSAJE_CHAT,
            categoria=CategoriaNotificacion.NEGOCIO,
            titulo=f"Nuevo mensaje de {nombre_actor}",
            descripcion=descripcion or "Tienes un nuevo mensaje en tu conversación.",
            url_destino=destino,
        )
