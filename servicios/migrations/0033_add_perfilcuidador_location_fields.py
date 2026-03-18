from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("servicios", "0032_alter_notificacion_tipoevento_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="perfilcuidador",
            name="ciudadServicio",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Ciudad operativa usada en busqueda de servicios",
                max_length=100,
            ),
        ),
        migrations.AddField(
            model_name="perfilcuidador",
            name="latitudServicio",
            field=models.DecimalField(
                blank=True,
                decimal_places=6,
                help_text="Ubicacion operativa para servicios",
                max_digits=9,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="perfilcuidador",
            name="longitudServicio",
            field=models.DecimalField(
                blank=True,
                decimal_places=6,
                help_text="Ubicacion operativa para servicios",
                max_digits=9,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="perfilcuidador",
            name="radioKmServicio",
            field=models.DecimalField(
                blank=True,
                decimal_places=1,
                help_text="Radio de cobertura operativo en km (1-3)",
                max_digits=5,
                null=True,
                validators=[MinValueValidator(1), MaxValueValidator(3)],
            ),
        ),
    ]
