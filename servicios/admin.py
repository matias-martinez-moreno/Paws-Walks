from django.contrib import admin

from servicios.models import (
    BloqueTiempo,
    Calificacion,
    Mascota,
    PerfilCuidador,
    PrecioServicio,
    SlotDisponibilidad,
    SolicitudServicio,
    Usuario,
    VentanaDisponibilidad,
)


@admin.register(Usuario)
class UsuarioAdmin(admin.ModelAdmin):
    list_display = ("nombre", "apellido", "username", "rol", "ciudad", "verificado", "created_at")
    list_filter = ("rol", "verificado")
    search_fields = ("nombre", "apellido", "username", "correo", "ciudad")
    readonly_fields = ("idUsuario", "created_at")
    list_editable = ("verificado",)


@admin.register(PerfilCuidador)
class PerfilCuidadorAdmin(admin.ModelAdmin):
    list_display = ("idCuidador", "tiposMascotaPreferidos", "tarifaHora", "created_at")
    search_fields = ("idCuidador__nombre", "idCuidador__apellido")


@admin.register(Mascota)
class MascotaAdmin(admin.ModelAdmin):
    list_display = ("nombreMascota", "tipo", "idDueño", "edad", "created_at")
    list_filter = ("tipo",)
    search_fields = ("nombreMascota", "idDueño__nombre")


@admin.register(BloqueTiempo)
class BloqueTiempoAdmin(admin.ModelAdmin):
    list_display = ("idCuidador", "tipoServicio", "diaSemana", "horaInicio", "horaFin", "disponible")
    list_filter = ("tipoServicio", "diaSemana", "disponible")


@admin.register(VentanaDisponibilidad)
class VentanaDisponibilidadAdmin(admin.ModelAdmin):
    list_display = ("idCuidador", "tipoServicio", "diaSemana", "horaInicio", "horaFin", "duracionSlotMinutos", "capacidadMaxima")
    list_filter = ("tipoServicio", "diaSemana")


@admin.register(SlotDisponibilidad)
class SlotDisponibilidadAdmin(admin.ModelAdmin):
    list_display = ("idVentana", "horaInicio", "disponible")
    list_filter = ("disponible",)


@admin.register(PrecioServicio)
class PrecioServicioAdmin(admin.ModelAdmin):
    list_display = ("idCuidador", "tipoServicio", "precioCOP", "activo")
    list_filter = ("tipoServicio", "activo")


@admin.register(SolicitudServicio)
class SolicitudServicioAdmin(admin.ModelAdmin):
    list_display = ("idSolicitud", "idDueño", "idCuidador", "idMascota", "tipoServicio", "fecha", "estado", "estado_pago")
    list_filter = ("estado", "estado_pago", "tipoServicio")
    search_fields = ("idDueño__nombre", "idCuidador__nombre")


@admin.register(Calificacion)
class CalificacionAdmin(admin.ModelAdmin):
    list_display = ("idDe", "idParaCuidador", "estrellas", "fecha")
    list_filter = ("estrellas",)
