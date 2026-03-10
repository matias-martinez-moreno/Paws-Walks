# Generated manually for lugares cercanos

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('servicios', '0008_add_descripcion_precio_tipo_bloque'),
    ]

    operations = [
        migrations.AddField(
            model_name='usuario',
            name='latitud',
            field=models.DecimalField(blank=True, decimal_places=6, help_text='Para búsqueda por proximidad', max_digits=9, null=True),
        ),
        migrations.AddField(
            model_name='usuario',
            name='longitud',
            field=models.DecimalField(blank=True, decimal_places=6, help_text='Para búsqueda por proximidad', max_digits=9, null=True),
        ),
    ]
