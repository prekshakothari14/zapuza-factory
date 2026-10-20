from django.contrib import admin
from .models import ApprovalLog


@admin.register(ApprovalLog)
class ApprovalLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "checklist", "from_status", "to_status", "action_by", "reason_code")
    list_filter = ("to_status", "from_status", "reason_code")
    search_fields = ("checklist__job_no", "action_by__username", "justification")
    readonly_fields = (
        "checklist", "from_status", "to_status", "action_by",
        "reason_code", "justification", "timestamp",
    )
    ordering = ["-timestamp"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
