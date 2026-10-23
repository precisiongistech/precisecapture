import django.db.models.deletion
from django.db import migrations, models

import precisecapture.common.ids
from precisecapture.common.rls import enable_rls


class Migration(migrations.Migration):
    dependencies = [("testapp", "0001_initial"), ("orgs", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="Secret",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=precisecapture.common.ids.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("note", models.CharField(max_length=100)),
                (
                    "org",
                    models.ForeignKey(
                        editable=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="orgs.organisation",
                    ),
                ),
            ],
            options={"db_table": "testapp_secret", "ordering": ["id"], "abstract": False},
        ),
        enable_rls("testapp_secret"),
    ]
