# Generated for calificaciones link to solicitud

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('servicios', '0011_perfilcuidador_tiposmascotapreferidos'),
    ]

    operations = [
        migrations.AddField(
            model_name='calificacion',
            name='idSolicitud',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='calificacion', to='servicios.solicitudservicio'),
        ),
    ]
