import html
import json
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Q
from django.views.generic import ListView

from accounts.mixins import RoleRequiredMixin
from accounts import roles

from .models import AuditLog


class AuditLogListView(RoleRequiredMixin, ListView):
    """
    Immutable audit trail viewer.
    Accessible to Quality Engineer, Supervisor, and Admin (Plant Manager / superuser).
    """
    model = AuditLog
    template_name = "audit/log_list.html"
    context_object_name = "logs"
    paginate_by = 25
    # Accept any of these roles (RoleRequiredMixin checks required_role; we override test)
    required_role = roles.QUALITY_ENGINEER

    def test_func(self):
        user = self.request.user
        if not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        role = roles.get_role(user)
        return role in (roles.QUALITY_ENGINEER, roles.SUPERVISOR, roles.PLANT_MANAGER)

    def get_queryset(self):
        qs = AuditLog.objects.select_related("user").all()
        model = self.request.GET.get("model", "").strip()
        user_id = self.request.GET.get("user", "").strip()
        action = self.request.GET.get("action", "").strip()
        date_from = self.request.GET.get("date_from", "").strip()
        date_to = self.request.GET.get("date_to", "").strip()

        if model:
            qs = qs.filter(model_name=model)
        if user_id:
            if user_id == "system":
                qs = qs.filter(Q(user__isnull=True) | Q(username="system"))
            else:
                qs = qs.filter(user_id=user_id)
        if action:
            qs = qs.filter(action=action)
        if date_from:
            qs = qs.filter(timestamp__date__gte=date_from)
        if date_to:
            qs = qs.filter(timestamp__date__lte=date_to)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["model_choices"] = (
            AuditLog.objects.order_by("model_name")
            .values_list("model_name", flat=True)
            .distinct()
        )
        ctx["user_choices"] = User.objects.filter(
            id__in=AuditLog.objects.exclude(user=None).values_list("user_id", flat=True)
        ).order_by("username")
        ctx["action_choices"] = AuditLog.Action.choices
        # Attach JSON strings for the diff modal (escape for HTML attributes)
        for log in ctx.get("logs") or ctx.get("object_list") or []:
            log.old_values_json = html.escape(json.dumps(log.old_values) if log.old_values is not None else "null")
            log.new_values_json = html.escape(json.dumps(log.new_values) if log.new_values is not None else "null")
            log.changed_fields_json = html.escape(json.dumps(log.changed_fields) if log.changed_fields is not None else "[]")
        ctx["filters"] = {
            "model": self.request.GET.get("model", ""),
            "user": self.request.GET.get("user", ""),
            "action": self.request.GET.get("action", ""),
            "date_from": self.request.GET.get("date_from", ""),
            "date_to": self.request.GET.get("date_to", ""),
        }
        return ctx
