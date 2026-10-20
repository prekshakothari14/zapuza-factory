from django.apps import AppConfig


class AuditConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "audit"
    verbose_name = "Audit Log"

    # Models tracked by the audit system (extend this list to add more).
    # Never include audit.AuditLog itself.
    TRACKED_MODELS = [
        "core.Factory",
        "core.Machine",
        "core.PartNumber",
        "core.Gauge",
        "inspections.InspectionTemplate",
        "inspections.TemplateField",
        "inspections.Checklist",
        "inspections.Measurement",
        "inspections.DefectPhoto",
        "approvals.ApprovalLog",
    ]

    def ready(self):
        # Register signal handlers once the app registry is ready.
        from . import signals  # noqa: F401
