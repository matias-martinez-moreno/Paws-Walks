# builder de dominio: construye y persiste la entidad SolicitudServicio
from __future__ import annotations

from servicios.domain.exceptions import DomainValidationError


class SolicitudServicioBuilder:
    """Builder puro: solo ensambla datos ya validados por Service Layer."""

    def __init__(self):
        self._datos = {}

    def para_dueño(self, dueño):
        self._datos["idDueño"] = dueño
        return self

    def para_cuidador(self, cuidador):
        self._datos["idCuidador"] = cuidador
        return self

    def para_mascota(self, mascota):
        self._datos["idMascota"] = mascota
        return self

    def con_servicio(self, tipo_servicio):
        self._datos["tipoServicio"] = tipo_servicio
        return self

    def en_fecha(self, fecha):
        self._datos["fecha"] = fecha
        return self

    def en_fecha_fin(self, fecha_fin):
        self._datos["fechaFin"] = fecha_fin
        return self

    def en_bloque(self, bloque):
        self._datos["idBloqueHorario"] = bloque
        return self

    def en_ventana(self, ventana):
        self._datos["idVentana"] = ventana
        return self

    def en_evento(self, evento, slot=None):
        self._datos["idEvento"] = evento
        if slot is not None:
            self._datos["idSlotEvento"] = slot
        return self

    def con_hora_asignada(self, hora_recogida, orden_ruta, slot):
        self._datos["idSlot"] = slot
        self._datos["horaRecogidaAsignada"] = hora_recogida
        self._datos["ordenEnRuta"] = orden_ruta
        return self

    def con_hora_asignada_evento(self, hora_recogida, orden_ruta, slot):
        self._datos["idSlotEvento"] = slot
        self._datos["horaRecogidaAsignada"] = hora_recogida
        self._datos["ordenEnRuta"] = orden_ruta
        return self

    def con_monto_pago(self, monto_pago):
        self._datos["monto_pago"] = monto_pago
        return self

    def _validar_campos_minimos(self):
        base = ["idDueño", "idCuidador", "idMascota", "tipoServicio", "fecha"]
        faltantes = [campo for campo in base if self._datos.get(campo) is None]
        if faltantes:
            raise DomainValidationError(f"faltan campos para construir la solicitud: {', '.join(faltantes)}")

        if "idEvento" not in self._datos and "idVentana" not in self._datos and "idBloqueHorario" not in self._datos:
            raise DomainValidationError("debes definir un origen de disponibilidad (evento, ventana o bloque)")

    def build(self, *, estado_inicial: str = "pendiente"):
        """Retorna el dict de kwargs validado para crear la SolicitudServicio."""
        self._validar_campos_minimos()
        kwargs = {
            "idDueño": self._datos["idDueño"],
            "idCuidador": self._datos["idCuidador"],
            "idMascota": self._datos["idMascota"],
            "tipoServicio": self._datos["tipoServicio"],
            "fecha": self._datos["fecha"],
            "fechaFin": self._datos.get("fechaFin"),
            "estado": estado_inicial,
            "monto_pago": self._datos.get("monto_pago"),
        }

        if "idEvento" in self._datos:
            kwargs["idEvento"] = self._datos["idEvento"]
            if "idSlotEvento" in self._datos:
                kwargs["idSlotEvento"] = self._datos["idSlotEvento"]
            if "horaRecogidaAsignada" in self._datos:
                kwargs["horaRecogidaAsignada"] = self._datos["horaRecogidaAsignada"]
            if "ordenEnRuta" in self._datos:
                kwargs["ordenEnRuta"] = self._datos["ordenEnRuta"]
        elif "idVentana" in self._datos:
            kwargs["idVentana"] = self._datos["idVentana"]
            if "idSlot" in self._datos:
                kwargs["idSlot"] = self._datos["idSlot"]
            if "horaRecogidaAsignada" in self._datos:
                kwargs["horaRecogidaAsignada"] = self._datos["horaRecogidaAsignada"]
            if "ordenEnRuta" in self._datos:
                kwargs["ordenEnRuta"] = self._datos["ordenEnRuta"]
        else:
            kwargs["idBloqueHorario"] = self._datos["idBloqueHorario"]

        return kwargs
