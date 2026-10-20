from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "username", "action", "model_name", "object_id", "object_repr", "ip_address")
    list_filter = ("action", "model_name", "timestamp")
    search_fields = ("username", "object_repr", "model_name", "object_id")
    readonly_fields = [f.name for f in AuditLog._meta.fields]
    ordering = ("-timestamp",)
    date_hierarchy = "timestamp"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions
