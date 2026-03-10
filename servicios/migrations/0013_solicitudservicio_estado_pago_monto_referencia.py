# Generated for pagos estructura

from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ('servicios', '0012_calificacion_idsolicitud'),
    ]

    operations = [
        migrations.AddField(
            model_name='solicitudservicio',
            name='estado_pago',
            field=models.CharField(choices=[('pendiente', 'Pendiente'), ('procesando', 'Procesando'), ('completado', 'Completado'), ('rechazado', 'Rechazado'), ('reembolsado', 'Reembolsado')], default='pendiente', max_length=20),
        ),
        migrations.AddField(
            model_name='solicitudservicio',
            name='monto_pago',
            field=models.IntegerField(blank=True, null=True, validators=[django.core.validators.MinValueValidator(0)]),
        ),
        migrations.AddField(
            model_name='solicitudservicio',
            name='referencia_pago',
            field=models.CharField(blank=True, default='', max_length=200),
        ),
    ]
