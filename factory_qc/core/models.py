from django.db import models
from django.utils import timezone


class Factory(models.Model):
    name = models.CharField(max_length=100)
    location = models.CharField(max_length=150)

    class Meta:
        verbose_name_plural = "factories"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Machine(models.Model):
    name = models.CharField(max_length=100)
    factory = models.ForeignKey(Factory, on_delete=models.PROTECT, related_name="machines")
    # Inactive machines are kept for history but should not be used for new work.
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["factory__name", "name"]

    def __str__(self):
        return f"{self.name} ({self.factory})"


class PartNumber(models.Model):
    part_no = models.CharField(max_length=50, unique=True)
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["part_no"]

    def __str__(self):
        return self.part_no


class Gauge(models.Model):
    class GaugeType(models.TextChoices):
        CALIPER = "Caliper", "Caliper"
        MICROMETER = "Micrometer", "Micrometer"
        HEIGHT_GAUGE = "Height Gauge", "Height Gauge"
        PLUG_GAUGE = "Plug Gauge", "Plug Gauge"
        CMM = "CMM", "CMM"

    serial_no = models.CharField(max_length=50, unique=True)
    gauge_type = models.CharField(max_length=20, choices=GaugeType.choices)
    calibration_expiry = models.DateField()

    class Meta:
        ordering = ["serial_no"]

    def __str__(self):
        return f"{self.serial_no} ({self.gauge_type})"

    @property
    def days_left(self):
        """Days until calibration expires. Zero or negative once expired."""
        return (self.calibration_expiry - timezone.localdate()).days

    @property
    def is_calibration_valid(self):
        """
        Business rule: a gauge is valid through its expiry date (inclusive).
        It becomes EXPIRED the day after calibration_expiry.
        """
        return self.days_left >= 0
