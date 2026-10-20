from django.conf import settings
from django.db import models
from django.utils import timezone


class ApprovalLog(models.Model):
    """Immutable audit log entry written every time a checklist changes status."""

    class ReasonCode(models.TextChoices):
        COSMETIC_ONLY = "COSMETIC_ONLY", "Cosmetic only"
        NON_FUNCTIONAL = "NON_FUNCTIONAL", "Non-functional dimension"
        CUSTOMER_WAIVER = "CUSTOMER_WAIVER", "Customer waiver"
        OTHER = "OTHER", "Other"

    checklist = models.ForeignKey(
        "inspections.Checklist",
        on_delete=models.CASCADE,
        related_name="approval_logs",
    )
    from_status = models.CharField(max_length=20)
    to_status = models.CharField(max_length=20)
    action_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="approval_actions",
    )
    reason_code = models.CharField(
        max_length=30,
        choices=ReasonCode.choices,
        blank=True,
        help_text="Required only for Concession decisions.",
    )
    justification = models.TextField(
        blank=True,
        help_text="Justification text required for Concession decisions.",
    )
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["timestamp"]
        verbose_name = "Approval Log"
        verbose_name_plural = "Approval Logs"

    def __str__(self):
        local_ts = timezone.localtime(self.timestamp)
        return (
            f"[{local_ts:%Y-%m-%d %H:%M}] {self.checklist.job_no}: "
            f"{self.from_status} → {self.to_status} by {self.action_by.username}"
        )
