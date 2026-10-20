import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AuditLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("username", models.CharField(help_text="Stored copy of the username so the log survives user deletion.", max_length=150)),
                ("timestamp", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("action", models.CharField(choices=[("CREATE", "Create"), ("UPDATE", "Update"), ("DELETE", "Delete")], db_index=True, max_length=10)),
                ("model_name", models.CharField(db_index=True, max_length=100)),
                ("object_id", models.CharField(blank=True, max_length=64)),
                ("object_repr", models.CharField(blank=True, max_length=255)),
                ("old_values", models.JSONField(blank=True, null=True)),
                ("new_values", models.JSONField(blank=True, null=True)),
                ("changed_fields", models.JSONField(blank=True, null=True)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="audit_logs", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "Audit Log",
                "verbose_name_plural": "Audit Logs",
                "ordering": ["-timestamp"],
            },
        ),
    ]
