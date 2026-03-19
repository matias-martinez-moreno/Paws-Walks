from datetime import date, time
from uuid import uuid4

from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from servicios.models import (
    DiaSemana,
    EstadoSolicitud,
    Evento,
    Mascota,
    PerfilCuidador,
    PrecioServicio,
    SolicitudServicio,
    TipoMascota,
    TipoServicio,
    Usuario,
)


class ServiciosApiStatusCodesTests(APITestCase):
    def setUp(self):
        self.owner = self._crear_usuario("status_owner", "dueño")
        self.caregiver = self._crear_usuario("status_caregiver", "cuidador")

        self.pet = Mascota.objects.create(
            idDueño=self.owner,
            nombreMascota="Nala",
            tipo=TipoMascota.PERRO,
            edad=2,
        )

        self.profile = PerfilCuidador.objects.create(
            idCuidador=self.caregiver,
            descripcion="Perfil de prueba",
        )

        PrecioServicio.objects.create(
            idCuidador=self.caregiver,
            tipoServicio=TipoServicio.PASEO,
            precioCOP=20000,
            descripcion="Paseo base",
            activo=True,
        )

        self.event_available = self._crear_evento(hora_inicio=time(9, 0), hora_fin=time(10, 0), capacidad=2)
        self.event_full = self._crear_evento(hora_inicio=time(11, 0), hora_fin=time(12, 0), capacidad=1)

        SolicitudServicio.objects.create(
            idDueño=self.owner,
            idCuidador=self.caregiver,
            idMascota=self.pet,
            tipoServicio=TipoServicio.PASEO,
            fecha=date.today(),
            idEvento=self.event_full,
        )

        self.client.force_authenticate(user=self.owner.user)

    def _crear_usuario(self, username: str, rol: str) -> Usuario:
        user = User.objects.create_user(
            username=username,
            password="Password1!",
        )
        return Usuario.objects.create(
            user=user,
            nombre=username,
            apellido="Test",
            username=username,
            correo=f"{username}@example.com",
            cedula=f"CC-{uuid4().hex[:10]}",
            telefono="+571234567890",
            fechaNacimiento=date(2000, 1, 1),
            ciudad="Medellin",
            rol=rol,
            verificado=True,
        )

    def _crear_evento(self, hora_inicio: time, hora_fin: time, capacidad: int) -> Evento:
        return Evento.objects.create(
            idCuidador=self.profile,
            tipoServicio=TipoServicio.PASEO,
            diaSemana=DiaSemana.LUNES,
            horaInicio=hora_inicio,
            horaFin=hora_fin,
            capacidadMaxima=capacidad,
            disponible=True,
        )

    def _payload_crear(self, event_id: str) -> dict:
        return {
            "idDueño_id": str(self.owner.idUsuario),
            "idCuidador_id": str(self.caregiver.idUsuario),
            "idMascota_id": str(self.pet.idMascota),
            "tipoServicio": TipoServicio.PASEO,
            "fecha": date.today().isoformat(),
            "idEvento_id": event_id,
        }

    def test_create_returns_201_when_payload_is_valid(self):
        response = self.client.post(
            reverse("api:crear_solicitud"),
            data=self._payload_crear(str(self.event_available.idEvento)),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("idSolicitud", response.data)

    def test_create_returns_400_when_payload_is_invalid(self):
        response = self.client.post(
            reverse("api:crear_solicitud"),
            data={"tipoServicio": TipoServicio.PASEO},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_returns_404_when_event_not_found(self):
        response = self.client.post(
            reverse("api:crear_solicitud"),
            data=self._payload_crear(str(uuid4())),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_create_returns_409_when_event_has_no_capacity(self):
        response = self.client.post(
            reverse("api:crear_solicitud"),
            data=self._payload_crear(str(self.event_full.idEvento)),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_detail_returns_404_when_solicitud_not_found(self):
        response = self.client.get(
            reverse("api:detalle_solicitud", kwargs={"solicitud_id": uuid4()}),
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cancel_returns_404_when_solicitud_not_found(self):
        response = self.client.post(
            reverse("api:cancelar_solicitud", kwargs={"solicitud_id": uuid4()}),
            data={"actor_id": str(self.owner.idUsuario)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cancel_returns_400_for_invalid_state(self):
        solicitud_cancelada = SolicitudServicio.objects.create(
            idDueño=self.owner,
            idCuidador=self.caregiver,
            idMascota=self.pet,
            tipoServicio=TipoServicio.PASEO,
            fecha=date.today(),
            estado=EstadoSolicitud.CANCELADO,
        )

        response = self.client.post(
            reverse("api:cancelar_solicitud", kwargs={"solicitud_id": solicitud_cancelada.idSolicitud}),
            data={"actor_id": str(self.owner.idUsuario)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)