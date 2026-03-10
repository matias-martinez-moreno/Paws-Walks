# Data migration: BloqueTiempo and VentanaDisponibilidad -> Evento

from django.db import migrations


def migrate_bloques_to_eventos(apps, schema_editor):
    BloqueTiempo = apps.get_model('servicios', 'BloqueTiempo')
    VentanaDisponibilidad = apps.get_model('servicios', 'VentanaDisponibilidad')
    SlotDisponibilidad = apps.get_model('servicios', 'SlotDisponibilidad')
    Evento = apps.get_model('servicios', 'Evento')
    SlotEvento = apps.get_model('servicios', 'SlotEvento')
    SolicitudServicio = apps.get_model('servicios', 'SolicitudServicio')

    bloque_to_evento = {}  # idBloque -> idEvento
    ventana_to_evento = {}  # idVentana -> idEvento
    slot_to_slotevento = {}  # idSlot -> idSlotEvento

    # 1. Migrate BloqueTiempo -> Evento
    for bt in BloqueTiempo.objects.all():
        evento = Evento.objects.create(
            idCuidador_id=bt.idCuidador_id,
            tipoServicio=bt.tipoServicio,
            nombreLugar=bt.nombreLugar or '',
            latitud=bt.latitud,
            longitud=bt.longitud,
            diaSemana=bt.diaSemana,
            horaInicio=bt.horaInicio,
            horaFin=bt.horaFin,
            precioCOP=bt.precioCOP,
            capacidadMaxima=1,
            duracionSlotMinutos=None,
            disponible=bt.disponible,
        )
        bloque_to_evento[str(bt.idBloque)] = evento.idEvento

    # 2. Migrate VentanaDisponibilidad -> Evento + SlotEvento
    for vd in VentanaDisponibilidad.objects.all():
        evento = Evento.objects.create(
            idCuidador_id=vd.idCuidador_id,
            tipoServicio=vd.tipoServicio,
            nombreLugar=vd.nombreLugar or '',
            latitud=vd.latitud,
            longitud=vd.longitud,
            diaSemana=vd.diaSemana,
            horaInicio=vd.horaInicio,
            horaFin=vd.horaFin,
            precioCOP=vd.precioCOP,
            capacidadMaxima=vd.capacidadMaxima,
            duracionSlotMinutos=vd.duracionSlotMinutos,
            disponible=True,
        )
        ventana_to_evento[str(vd.idVentana)] = evento.idEvento

        for slot in SlotDisponibilidad.objects.filter(idVentana=vd):
            se = SlotEvento.objects.create(
                idEvento=evento,
                horaInicio=slot.horaInicio,
                disponible=slot.disponible,
            )
            slot_to_slotevento[str(slot.idSlot)] = se.idSlot

    # 3. Update SolicitudServicio: idBloqueHorario -> idEvento
    for sol in SolicitudServicio.objects.filter(idBloqueHorario__isnull=False):
        bid = str(sol.idBloqueHorario_id)
        if bid in bloque_to_evento:
            sol.idEvento_id = bloque_to_evento[bid]
            sol.save(update_fields=['idEvento_id'])

    # 4. Update SolicitudServicio: idVentana -> idEvento, idSlot -> idSlotEvento
    for sol in SolicitudServicio.objects.filter(idVentana__isnull=False):
        vid = str(sol.idVentana_id)
        if vid in ventana_to_evento:
            sol.idEvento_id = ventana_to_evento[vid]
            sol.save(update_fields=['idEvento_id'])

    for sol in SolicitudServicio.objects.filter(idSlot__isnull=False):
        sid = str(sol.idSlot_id)
        if sid in slot_to_slotevento:
            sol.idSlotEvento_id = slot_to_slotevento[sid]
            sol.save(update_fields=['idSlotEvento_id'])


def reverse_migrate(apps, schema_editor):
    # Cannot easily reverse data migration; new Eventos would need to be removed
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('servicios', '0020_add_evento_slot_evento'),
    ]

    operations = [
        migrations.RunPython(migrate_bloques_to_eventos, reverse_migrate),
    ]
