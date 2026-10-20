from django.contrib import admin

from approvals.models import ApprovalLog
from .models import Checklist, DefectPhoto, InspectionTemplate, Measurement, TemplateField


class TemplateFieldInline(admin.TabularInline):
    model = TemplateField
    extra = 0

    def has_change_permission(self, request, obj=None):
        if obj is not None and getattr(obj, "status", None) == InspectionTemplate.Status.APPROVED:
            return False
        return super().has_change_permission(request, obj)

    def has_add_permission(self, request, obj=None):
        if obj is not None and getattr(obj, "status", None) == InspectionTemplate.Status.APPROVED:
            return False
        return super().has_add_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and getattr(obj, "status", None) == InspectionTemplate.Status.APPROVED:
            return False
        return super().has_delete_permission(request, obj)


@admin.register(InspectionTemplate)
class InspectionTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "part", "revision", "status", "is_active", "created_at")
    list_filter = ("status", "is_active")
    search_fields = ("name", "part__part_no")
    inlines = [TemplateFieldInline]

    def get_readonly_fields(self, request, obj=None):
        if obj is not None and obj.status == InspectionTemplate.Status.APPROVED:
            return [f.name for f in self.model._meta.fields]
        return list(super().get_readonly_fields(request, obj))

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.status == InspectionTemplate.Status.APPROVED:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.status == InspectionTemplate.Status.APPROVED:
            return False
        return super().has_delete_permission(request, obj)


@admin.register(TemplateField)
class TemplateFieldAdmin(admin.ModelAdmin):
    list_display = ("name", "template", "order", "field_type", "nominal", "is_ctq")
    list_filter = ("field_type", "is_ctq", "template")
    search_fields = ("name", "template__name")

    def _template_approved(self, obj):
        return obj is not None and obj.template_id and obj.template.status == InspectionTemplate.Status.APPROVED

    def has_change_permission(self, request, obj=None):
        if self._template_approved(obj):
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if self._template_approved(obj):
            return False
        return super().has_delete_permission(request, obj)

    def has_add_permission(self, request):
        return super().has_add_permission(request)

    def get_readonly_fields(self, request, obj=None):
        if self._template_approved(obj):
            return [f.name for f in self.model._meta.fields]
        return list(super().get_readonly_fields(request, obj))


class DefectPhotoInline(admin.TabularInline):
    model = DefectPhoto
    extra = 0
    readonly_fields = ("uploaded_at", "image")

    def has_add_permission(self, request, obj=None):
        if obj is not None and getattr(obj, "submitted_at", None):
            return False
        if obj is not None and hasattr(obj, "checklist") and obj.checklist.submitted_at:
            return False
        return super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class MeasurementInline(admin.TabularInline):
    model = Measurement
    extra = 0
    readonly_fields = ("field", "value", "visual_ok", "gauge", "is_within_tolerance", "remarks")

    def has_add_permission(self, request, obj=None):
        if obj is not None and obj.submitted_at:
            return False
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ApprovalLogInline(admin.TabularInline):
    model = ApprovalLog
    extra = 0
    readonly_fields = ("from_status", "to_status", "action_by", "reason_code", "justification", "timestamp")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


def _checklist_submitted(obj):
    return obj is not None and bool(obj.submitted_at)


@admin.register(Checklist)
class ChecklistAdmin(admin.ModelAdmin):
    list_display = ("job_no", "template", "machine", "inspector", "status", "created_at", "submitted_at")
    list_filter = ("status", "machine", "template")
    search_fields = ("job_no", "inspector__username")
    inlines = [MeasurementInline, ApprovalLogInline]

    def get_readonly_fields(self, request, obj=None):
        if _checklist_submitted(obj):
            return [f.name for f in self.model._meta.fields]
        return list(super().get_readonly_fields(request, obj))

    def has_change_permission(self, request, obj=None):
        if _checklist_submitted(obj):
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if _checklist_submitted(obj):
            return False
        return super().has_delete_permission(request, obj)

    def has_add_permission(self, request):
        # Checklists are created via the inspection form, not admin
        return False

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions


@admin.register(Measurement)
class MeasurementAdmin(admin.ModelAdmin):
    list_display = ("checklist", "field", "value", "visual_ok", "gauge", "is_within_tolerance")
    list_filter = ("is_within_tolerance", "field__field_type")
    inlines = [DefectPhotoInline]

    def _submitted(self, obj):
        return obj is not None and obj.checklist_id and obj.checklist.submitted_at

    def get_readonly_fields(self, request, obj=None):
        if self._submitted(obj):
            return [f.name for f in self.model._meta.fields]
        return list(super().get_readonly_fields(request, obj))

    def has_change_permission(self, request, obj=None):
        if self._submitted(obj):
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if self._submitted(obj):
            return False
        return super().has_delete_permission(request, obj)

    def has_add_permission(self, request):
        return False

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions


@admin.register(DefectPhoto)
class DefectPhotoAdmin(admin.ModelAdmin):
    list_display = ("id", "measurement", "image", "uploaded_at")
    list_filter = ("uploaded_at",)

    def _submitted(self, obj):
        return (
            obj is not None
            and obj.measurement_id
            and obj.measurement.checklist_id
            and obj.measurement.checklist.submitted_at
        )

    def has_change_permission(self, request, obj=None):
        if self._submitted(obj):
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if self._submitted(obj):
            return False
        return super().has_delete_permission(request, obj)

    def has_add_permission(self, request):
        return False

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions
