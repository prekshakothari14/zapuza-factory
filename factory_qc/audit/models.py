from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models


class ImmutableAuditQuerySet(models.QuerySet):
    """Block bulk mutations on the audit log."""

    def update(self, **kwargs):
        raise PermissionDenied("Audit log is immutable: queryset.update() is not allowed.")

    def delete(self):
        raise PermissionDenied("Audit log is immutable: queryset.delete() is not allowed.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise PermissionDenied("Audit log is immutable: bulk_update() is not allowed.")


class ImmutableAuditManager(models.Manager):
    def get_queryset(self):
        return ImmutableAuditQuerySet(self.model, using=self._db)

    def bulk_create(self, objs, **kwargs):
        # Allow initial inserts (signals create rows one at a time via .save()).
        return super().bulk_create(objs, **kwargs)


class AuditLog(models.Model):
    class Action(models.TextChoices):
        CREATE = "CREATE", "Create"
        UPDATE = "UPDATE", "Update"
        DELETE = "DELETE", "Delete"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
    )
    username = models.CharField(
        max_length=150,
        help_text="Stored copy of the username so the log survives user deletion.",
    )
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    action = models.CharField(max_length=10, choices=Action.choices, db_index=True)
    model_name = models.CharField(max_length=100, db_index=True)
    object_id = models.CharField(max_length=64, blank=True)
    object_repr = models.CharField(max_length=255, blank=True)
    old_values = models.JSONField(null=True, blank=True)
    new_values = models.JSONField(null=True, blank=True)
    changed_fields = models.JSONField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    objects = ImmutableAuditManager()

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = "Audit Log"
        verbose_name_plural = "Audit Logs"

    def __str__(self):
        return f"[{self.timestamp:%Y-%m-%d %H:%M:%S}] {self.action} {self.model_name}#{self.object_id} by {self.username}"

    def save(self, *args, **kwargs):
        # Immutability: allow only INSERT (no pk yet). Block any UPDATE.
        if self.pk is not None:
            raise PermissionDenied("Audit log is immutable: existing rows cannot be updated.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionDenied("Audit log is immutable: rows cannot be deleted.")
