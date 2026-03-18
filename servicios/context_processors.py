from django.db.utils import OperationalError, ProgrammingError

from servicios.models import Notificacion


def notificaciones_no_leidas(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"notificaciones_no_leidas_total": 0}

    usuario = getattr(user, "perfil_usuario", None)
    if usuario is None:
        return {"notificaciones_no_leidas_total": 0}

    try:
        total = Notificacion.objects.filter(
            idParaUsuario=usuario,
            eliminada=False,
            leida=False,
        ).count()
    except (OperationalError, ProgrammingError):
        total = 0

    return {"notificaciones_no_leidas_total": total}
