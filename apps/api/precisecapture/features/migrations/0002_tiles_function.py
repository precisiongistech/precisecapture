from django.db import migrations

from precisecapture.features.tiles import TILES_FUNCTION_REVERSE_SQL, TILES_FUNCTION_SQL


class Migration(migrations.Migration):
    dependencies = [("features", "0001_initial")]
    operations = [migrations.RunSQL(sql=TILES_FUNCTION_SQL, reverse_sql=TILES_FUNCTION_REVERSE_SQL)]
