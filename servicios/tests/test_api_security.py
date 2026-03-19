from datetime import date
from uuid import uuid4

from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from servicios.models import Mascota, SolicitudServicio, TipoMascota, TipoServicio, Usuario


class ServiciosApiSecurityTests(APITestCase):
    def setUp(self):
        self.owner = self._crear_usuario("owner_user", "dueño")
        self.other_owner = self._crear_usuario("other_owner", "dueño")
        self.caregiver = self._crear_usuario("caregiver_user", "cuidador")
        self.third_user = self._crear_usuario("third_user", "dueño")

        self.mascota = Mascota.objects.create(
            idDueño=self.owner,
            nombreMascota="Luna",
            tipo=TipoMascota.PERRO,
            edad=3,
        )

        self.solicitud = SolicitudServicio.objects.create(
            idDueño=self.owner,
            idCuidador=self.caregiver,
            idMascota=self.mascota,
            tipoServicio=TipoServicio.PASEO,
            fecha=date.today(),
        )

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

    def _payload_crear(self, dueño_id: str) -> dict:
        return {
            "idDueño_id": dueño_id,
            "idCuidador_id": str(self.caregiver.idUsuario),
            "idMascota_id": str(self.mascota.idMascota),
            "tipoServicio": TipoServicio.PASEO,
            "fecha": date.today().isoformat(),
            "idEvento_id": str(uuid4()),
        }

    def test_create_requires_authentication(self):
        response = self.client.post(
            reverse("api:crear_solicitud"),
            data=self._payload_crear(str(self.owner.idUsuario)),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_blocks_owner_spoofing(self):
        self.client.force_authenticate(user=self.owner.user)

        response = self.client.post(
            reverse("api:crear_solicitud"),
            data=self._payload_crear(str(self.other_owner.idUsuario)),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_requires_dueño_role(self):
        self.client.force_authenticate(user=self.caregiver.user)

        response = self.client.post(
            reverse("api:crear_solicitud"),
            data=self._payload_crear(str(self.caregiver.idUsuario)),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cancel_blocks_actor_spoofing(self):
        self.client.force_authenticate(user=self.owner.user)

        response = self.client.post(
            reverse("api:cancelar_solicitud", kwargs={"solicitud_id": self.solicitud.idSolicitud}),
            data={"actor_id": str(self.other_owner.idUsuario)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_disponibilidad_requires_dueño_role(self):
        self.client.force_authenticate(user=self.caregiver.user)

        response = self.client.post(
            reverse("api:disponibilidad_cuidadores"),
            data={},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_detail_blocks_third_party_access(self):
        self.client.force_authenticate(user=self.third_user.user)

        response = self.client.get(
            reverse("api:detalle_solicitud", kwargs={"solicitud_id": self.solicitud.idSolicitud}),
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_detail_allows_owner_participant(self):
        self.client.force_authenticate(user=self.owner.user)

        response = self.client.get(
            reverse("api:detalle_solicitud", kwargs={"solicitud_id": self.solicitud.idSolicitud}),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
