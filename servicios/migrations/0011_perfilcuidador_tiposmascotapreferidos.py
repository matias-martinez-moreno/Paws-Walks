# Generated for tipo animal preferido

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('servicios', '0010_usuario_radiokm'),
    ]

    operations = [
        migrations.AddField(
            model_name='perfilcuidador',
            name='tiposMascotaPreferidos',
            field=models.CharField(default='ambos', help_text='perro, gato o ambos', max_length=50),
        ),
    ]
