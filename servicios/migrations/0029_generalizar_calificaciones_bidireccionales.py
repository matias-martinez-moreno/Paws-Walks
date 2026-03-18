from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('servicios', '0028_reduce_radio_max_3km'),
    ]

    operations = [
        migrations.RenameField(
            model_name='calificacion',
            old_name='idParaCuidador',
            new_name='idParaUsuario',
        ),
        migrations.AlterField(
            model_name='calificacion',
            name='idSolicitud',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='calificaciones', to='servicios.solicitudservicio'),
        ),
        migrations.AddConstraint(
            model_name='calificacion',
            constraint=models.UniqueConstraint(fields=('idSolicitud', 'idDe'), name='uniq_calificacion_solicitud_autor'),
        ),
    ]
