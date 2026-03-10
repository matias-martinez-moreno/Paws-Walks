# Generated for lugares con radio km

from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ('servicios', '0009_usuario_latitud_longitud'),
    ]

    operations = [
        migrations.AddField(
            model_name='usuario',
            name='radioKm',
            field=models.DecimalField(blank=True, decimal_places=1, help_text='Radio de cobertura en km (solo cuidadores)', max_digits=5, null=True, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(100)]),
        ),
    ]
