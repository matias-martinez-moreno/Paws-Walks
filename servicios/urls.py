from django.urls import path
from django.views.generic.base import RedirectView
from servicios.views import (
    AliadoEstadoView,
    ClimaJsonView,
    CrearSolicitudServicioView,
    CuidadorCalendarioView,
    CuidadorGuiaView,
    CuidadorMiPerfilView,
    CuidadorMisServiciosView,
    DashboardCuidadorView,
    DashboardDueñoView,
    DueñoGuiaView,
    DueñoMiPerfilView,
    DueñoMisMascotasView,
    DueñoMisReservasView,
    DueñoNuevaReservaView,
    LoginView,
    NotificacionesView,
    LogoutView,
    PasswordResetRequestView,
    PoliticaPrivacidadView,
    SignupView,
    TerminosCondicionesView,
    VerPerfilOtroView,
)

urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),
    path("signup/", SignupView.as_view(), name="signup"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("recuperar-contraseña/", PasswordResetRequestView.as_view(), name="password_reset_request"),
    path("terminos-y-condiciones/", TerminosCondicionesView.as_view(), name="terminos_condiciones"),
    path("politica-de-privacidad/", PoliticaPrivacidadView.as_view(), name="politica_privacidad"),

    path("dashboard/dueño/", DashboardDueñoView.as_view(), name="dashboard_dueño"),
    path("dueño/nueva-reserva/", DueñoNuevaReservaView.as_view(), name="dueño_nueva_reserva"),
    path("dueño/mis-reservas/", DueñoMisReservasView.as_view(), name="dueño_mis_reservas"),
    path("dueño/notificaciones/", NotificacionesView.as_view(), name="dueño_notificaciones"),
    path("dueño/mis-mascotas/", DueñoMisMascotasView.as_view(), name="dueño_mis_mascotas"),
    path("dueño/mi-perfil/", DueñoMiPerfilView.as_view(), name="dueño_mi_perfil"),

    path("dashboard/cuidador/", DashboardCuidadorView.as_view(), name="dashboard_cuidador"),
    path("cuidador/calendario/", CuidadorCalendarioView.as_view(), name="cuidador_calendario"),
    path("cuidador/notificaciones/", NotificacionesView.as_view(), name="cuidador_notificaciones"),
    path("cuidador/mi-perfil/", CuidadorMiPerfilView.as_view(), name="cuidador_mi_perfil"),
    path("cuidador/servicios/", CuidadorMisServiciosView.as_view(), name="cuidador_servicios"),
    path("cuidador/guia/", CuidadorGuiaView.as_view(), name="cuidador_guia"),
    path("cuidador/mis-pagos/", RedirectView.as_view(pattern_name="dashboard_cuidador", permanent=False), name="cuidador_mis_pagos"),
    path("cuidador/soporte/", RedirectView.as_view(pattern_name="dashboard_cuidador", permanent=False), name="cuidador_soporte"),

    path("dueño/guia/", DueñoGuiaView.as_view(), name="dueño_guia"),
    path("dueño/soporte/", RedirectView.as_view(pattern_name="dashboard_dueño", permanent=False), name="dueño_soporte"),

    path("perfil/<uuid:usuario_id>/", VerPerfilOtroView.as_view(), name="ver_perfil_otro"),

    path("solicitud/crear/", CrearSolicitudServicioView.as_view(), name="crear_solicitud"),
    path("clima-json/", ClimaJsonView.as_view(), name="clima_json"),
    path("integraciones/aliado/", AliadoEstadoView.as_view(), name="aliado_estado_web"),
]
