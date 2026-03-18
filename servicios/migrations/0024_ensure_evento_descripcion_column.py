from django.db import migrations, models


def _add_evento_descripcion_if_missing(apps, schema_editor):
    table_name = "servicios_evento"
    with schema_editor.connection.cursor() as cursor:
        columns = {
            col.name
            for col in schema_editor.connection.introspection.get_table_description(cursor, table_name)
        }
    if "descripcion" not in columns:
        schema_editor.execute(
            "ALTER TABLE servicios_evento ADD COLUMN descripcion TEXT NOT NULL DEFAULT ''"
        )


class Migration(migrations.Migration):

    dependencies = [
        ("servicios", "0023_remove_precioservicio_lugarentrenamiento_and_more"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(_add_evento_descripcion_if_missing, migrations.RunPython.noop),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="evento",
                    name="descripcion",
                    field=models.TextField(blank=True, default=""),
                ),
            ],
        ),
    ]
