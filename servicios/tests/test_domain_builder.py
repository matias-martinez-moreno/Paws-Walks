from django.test import SimpleTestCase

from servicios.domain.builder import SolicitudServicioBuilder


class SolicitudServicioBuilderTests(SimpleTestCase):
    def test_build_retorna_payload_dict_y_estado_pendiente(self):
        payload = (
            SolicitudServicioBuilder()
            .para_dueño(object())
            .para_cuidador(object())
            .para_mascota(object())
            .con_servicio("paseo")
            .en_fecha("2026-03-18")
            .en_evento(object())
            .build()
        )

        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["estado"], "pendiente")
        self.assertIn("idEvento", payload)
