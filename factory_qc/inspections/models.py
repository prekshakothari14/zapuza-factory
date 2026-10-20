from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class InspectionTemplate(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        APPROVED = "APPROVED", "Approved"

    name = models.CharField(max_length=150)
    part = models.ForeignKey("core.PartNumber", on_delete=models.PROTECT, related_name="inspection_templates")
    revision = models.CharField(max_length=20, default="Rev A")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "revision"]
        unique_together = [("part", "revision", "name")]

    def __str__(self):
        return f"{self.name} ({self.revision})"

    @property
    def is_approved(self):
        return self.status == self.Status.APPROVED

    def clean(self):
        super().clean()
        if self.pk:
            original = InspectionTemplate.objects.filter(pk=self.pk).first()
            if original and original.status == self.Status.APPROVED:
                # Business rule: approved templates cannot be edited
                if (
                    self.name != original.name
                    or self.part_id != original.part_id
                    or self.revision != original.revision
                    or self.status != original.status
                    or self.is_active != original.is_active
                ):
                    raise ValidationError("Approved templates cannot be edited.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class TemplateField(models.Model):
    class FieldType(models.TextChoices):
        DIMENSION = "DIMENSION", "Dimension"
        MAX_THRESHOLD = "MAX_THRESHOLD", "Max Threshold"
        VISUAL = "VISUAL", "Visual"

    template = models.ForeignKey(InspectionTemplate, on_delete=models.CASCADE, related_name="fields")
    order = models.PositiveIntegerField(default=1)
    name = models.CharField(max_length=150)
    field_type = models.CharField(max_length=20, choices=FieldType.choices, default=FieldType.DIMENSION)
    nominal = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    upper_tol = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        help_text="Signed upper tolerance e.g. +0.050",
    )
    lower_tol = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        help_text="Signed lower tolerance e.g. -0.020",
    )
    max_value = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    unit = models.CharField(max_length=20, blank=True)
    is_ctq = models.BooleanField(default=False, verbose_name="Critical To Quality (CTQ)")

    class Meta:
        ordering = ["template", "order", "id"]

    def __str__(self):
        return f"{self.name} ({self.field_type})"

    def clean(self):
        super().clean()
        if self.template_id:
            try:
                template = self.template
                if template and template.status == InspectionTemplate.Status.APPROVED:
                    if self.pk:
                        original = TemplateField.objects.filter(pk=self.pk).first()
                        if original:
                            raise ValidationError("Fields of an approved template cannot be edited.")
                    else:
                        raise ValidationError("Cannot add fields to an approved template.")
            except InspectionTemplate.DoesNotExist:
                pass

        if self.field_type == self.FieldType.DIMENSION:
            if self.nominal is None:
                raise ValidationError({"nominal": "Nominal value is required for dimension fields."})
            if self.upper_tol is None:
                raise ValidationError({"upper_tol": "Upper tolerance is required for dimension fields."})
            if self.lower_tol is None:
                raise ValidationError({"lower_tol": "Lower tolerance is required for dimension fields."})
        elif self.field_type == self.FieldType.MAX_THRESHOLD:
            if self.max_value is None:
                raise ValidationError({"max_value": "Max value is required for threshold fields."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.template and self.template.status == InspectionTemplate.Status.APPROVED:
            raise ValidationError("Cannot delete fields from an approved template.")
        super().delete(*args, **kwargs)

    @property
    def expected_range(self):
        """Human-readable expected range."""
        unit_str = f" {self.unit}" if self.unit else ""
        if self.field_type == self.FieldType.DIMENSION:
            if self.nominal is not None and self.lower_tol is not None and self.upper_tol is not None:
                min_v = self.nominal + self.lower_tol
                max_v = self.nominal + self.upper_tol
                return f"{min_v:.3f} to {max_v:.3f}{unit_str}"
            return "-"
        elif self.field_type == self.FieldType.MAX_THRESHOLD:
            return f"<= {self.max_value:.3f}{unit_str}" if self.max_value is not None else "-"
        elif self.field_type == self.FieldType.VISUAL:
            return "Yes"
        return "-"

    def evaluate(self, value=None, visual_ok=None):
        """
        Tolerance evaluation logic:
        - DIMENSION passes if nominal+lower_tol <= value <= nominal+upper_tol
          (e.g. 25.00, +0.05/-0.02 means 24.98 to 25.05, so 25.03 passes and 25.10 fails)
        - MAX_THRESHOLD passes if value <= max_value
        - VISUAL passes if Yes
        """
        if self.field_type == self.FieldType.DIMENSION:
            if value is None or str(value).strip() == "":
                return False
            try:
                val = Decimal(str(value))
            except Exception:
                return False
            min_val = self.nominal + self.lower_tol
            max_val = self.nominal + self.upper_tol
            return min_val <= val <= max_val

        elif self.field_type == self.FieldType.MAX_THRESHOLD:
            if value is None or str(value).strip() == "":
                return False
            try:
                val = Decimal(str(value))
            except Exception:
                return False
            return val <= self.max_value

        elif self.field_type == self.FieldType.VISUAL:
            if visual_ok is True or str(visual_ok).strip().lower() in ["yes", "true", "1"]:
                return True
            return False

        return False


class Checklist(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PENDING_REVIEW = "PENDING_REVIEW", "Pending Review"
        CTQ_FAILED = "CTQ_FAILED", "CTQ Failed"
        APPROVED = "APPROVED", "Approved"
        CONCESSION = "CONCESSION", "Concession"
        QUARANTINED = "QUARANTINED", "Quarantined"

    # Valid transitions: {from_status: [allowed_to statuses]}
    _VALID_TRANSITIONS = {
        Status.PENDING_REVIEW: [Status.APPROVED, Status.CONCESSION, Status.QUARANTINED],
        Status.CTQ_FAILED: [Status.QUARANTINED],
    }

    template = models.ForeignKey(InspectionTemplate, on_delete=models.PROTECT, related_name="checklists")
    machine = models.ForeignKey("core.Machine", on_delete=models.PROTECT, related_name="checklists")
    job_no = models.CharField(max_length=50)
    inspector = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="checklists")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING_REVIEW)
    created_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        local_created = timezone.localtime(self.created_at)
        return f"{self.job_no} - {self.template.name} ({local_created.strftime('%Y-%m-%d %H:%M')})"

    @property
    def is_all_passed(self):
        """Returns True if every measurement in this checklist passed tolerance."""
        measurements = self.measurements.all()
        if not measurements.exists():
            return False
        return all(m.is_within_tolerance for m in measurements)

    @property
    def ctq_passed(self):
        """Returns True if every CTQ measurement passed tolerance."""
        ctq_measurements = self.measurements.filter(field__is_ctq=True)
        if not ctq_measurements.exists():
            return True
        return all(m.is_within_tolerance for m in ctq_measurements)

    @property
    def is_frozen(self):
        """CTQ failure or terminal states freeze the checklist."""
        return self.status in (
            self.Status.CTQ_FAILED,
            self.Status.APPROVED,
            self.Status.CONCESSION,
            self.Status.QUARANTINED,
        )

    @property
    def failed_field_count(self):
        """Count of measurements that failed tolerance."""
        return self.measurements.filter(is_within_tolerance=False).count()

    @property
    def has_any_ctq_failure(self):
        """True if any CTQ measurement failed."""
        return self.measurements.filter(field__is_ctq=True, is_within_tolerance=False).exists()

    @property
    def has_any_failure(self):
        """True if any measurement failed."""
        return self.measurements.filter(is_within_tolerance=False).exists()

    def transition(self, to, user, reason_code=None, justification=None):
        """
        Enforce valid status transitions under a row lock.
        Raises ValueError for invalid moves.
        Creates an ApprovalLog entry on success.
        Returns the updated checklist (saved).
        """
        from django.db import transaction
        from approvals.models import ApprovalLog  # avoid circular import

        with transaction.atomic():
            locked = (
                Checklist.objects.select_for_update()
                .select_related("template")
                .prefetch_related("measurements", "measurements__field")
                .get(pk=self.pk)
            )
            allowed = locked._VALID_TRANSITIONS.get(locked.status, [])
            if to not in allowed:
                raise ValueError(
                    f"Cannot move checklist from '{locked.get_status_display()}' to "
                    f"'{dict(locked.Status.choices).get(to, to)}'."
                )

            # Business rules for CONCESSION
            if to == locked.Status.CONCESSION:
                if not locked.has_any_failure:
                    raise ValueError("Concession is only allowed when some fields have failed.")
                if locked.has_any_ctq_failure:
                    raise ValueError("Concession is not allowed when a CTQ field has failed.")
                if not justification:
                    raise ValueError("A justification is required for a concession decision.")
                if not reason_code:
                    raise ValueError("A reason code is required for a concession decision.")

            old_status = locked.status
            locked.status = to
            locked.save(update_fields=["status"])

            ApprovalLog.objects.create(
                checklist=locked,
                from_status=old_status,
                to_status=to,
                action_by=user,
                reason_code=reason_code or "",
                justification=justification or "",
            )
            self.status = locked.status
            return locked


class Measurement(models.Model):
    checklist = models.ForeignKey(Checklist, on_delete=models.CASCADE, related_name="measurements")
    field = models.ForeignKey(TemplateField, on_delete=models.PROTECT, related_name="measurements")
    value = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    visual_ok = models.BooleanField(null=True, blank=True)
    gauge = models.ForeignKey(
        "core.Gauge",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="measurements",
    )
    is_within_tolerance = models.BooleanField(default=False)
    remarks = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["field__order", "id"]

    def __str__(self):
        return f"{self.checklist.job_no} - {self.field.name}: {'PASS' if self.is_within_tolerance else 'FAIL'}"

    def clean(self):
        super().clean()
        # DIMENSION / MAX_THRESHOLD require a gauge; VISUAL may skip it.
        field_type = getattr(self.field, "field_type", None) if self.field_id else None
        if field_type in (
            TemplateField.FieldType.DIMENSION,
            TemplateField.FieldType.MAX_THRESHOLD,
        ):
            if self.gauge is None:
                name = getattr(self.field, "name", "this field")
                raise ValidationError({"gauge": f"Select the gauge used for '{name}'"})
        if self.gauge and not self.gauge.is_calibration_valid:
            raise ValidationError("Expired Tool Calibration. Obtain a calibrated tool from the tool crib.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def defect_photos(self):
        return self.photos.all()


class DefectPhoto(models.Model):
    measurement = models.ForeignKey(Measurement, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to="defects/%Y/%m/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["uploaded_at", "id"]

    def __str__(self):
        return f"DefectPhoto #{self.id} for Measurement #{self.measurement_id}"
