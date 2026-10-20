from django.contrib import admin
from django.utils.html import format_html

from .models import Factory, Gauge, Machine, PartNumber


@admin.register(Factory)
class FactoryAdmin(admin.ModelAdmin):
    list_display = ("name", "location")
    search_fields = ("name", "location")


@admin.register(Machine)
class MachineAdmin(admin.ModelAdmin):
    list_display = ("name", "factory", "is_active")
    list_filter = ("factory", "is_active")
    search_fields = ("name", "factory__name")


@admin.register(PartNumber)
class PartNumberAdmin(admin.ModelAdmin):
    list_display = ("part_no", "description")
    search_fields = ("part_no", "description")


class CalibrationStatusFilter(admin.SimpleListFilter):
    """Filter gauges by calibration status (computed from calibration_expiry)."""
    title = "calibration status"
    parameter_name = "calibration"

    def lookups(self, request, model_admin):
        return [("valid", "Valid"), ("expired", "Expired")]

    def queryset(self, request, queryset):
        from django.utils import timezone
        today = timezone.localdate()
        if self.value() == "valid":
            return queryset.filter(calibration_expiry__gte=today)
        if self.value() == "expired":
            return queryset.filter(calibration_expiry__lt=today)
        return queryset


@admin.register(Gauge)
class GaugeAdmin(admin.ModelAdmin):
    list_display = ("serial_no", "gauge_type", "calibration_expiry", "days_left", "calibration_status")
    list_filter = ("gauge_type", CalibrationStatusFilter)
    search_fields = ("serial_no",)

    @admin.display(description="Status")
    def calibration_status(self, obj):
        if obj.is_calibration_valid:
            return format_html('<b style="color:green;">VALID</b>')
        return format_html('<b style="color:red;">EXPIRED</b>')
