from datetime import timedelta

from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from core.models import Factory, Gauge, Machine, PartNumber
from inspections.models import Checklist, InspectionTemplate

from .mixins import RoleRequiredMixin
from . import roles

EXPIRING_SOON_DAYS = 30  # "expiring soon" window shown on dashboards


class PostLoginRedirectView(LoginRequiredMixin, View):
    """Send the user to the dashboard for their role."""

    def get(self, request):
        role = roles.get_role(request.user)
        if role is None:
            return redirect("accounts:no_role")
        return redirect(roles.DASHBOARD_URL_NAMES[role])


class NoRoleView(LoginRequiredMixin, TemplateView):
    """Shown to logged-in users who have no role group yet."""
    template_name = "accounts/no_role.html"


def gauge_counts():
    today = timezone.localdate()
    valid = Gauge.objects.filter(calibration_expiry__gte=today)
    return {
        "total": Gauge.objects.count(),
        "valid": valid.count(),
        "expired": Gauge.objects.filter(calibration_expiry__lt=today).count(),
        "expiring_soon": valid.filter(
            calibration_expiry__lte=today + timedelta(days=EXPIRING_SOON_DAYS)).count(),
    }


class RoleDashboardView(RoleRequiredMixin, TemplateView):
    """Base dashboard: subclasses set required_role and build their cards."""
    template_name = "accounts/dashboard.html"

    def cards(self):
        raise NotImplementedError

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(role=self.required_role, cards=self.cards())
        return ctx


class EngineerDashboardView(RoleDashboardView):
    required_role = roles.QUALITY_ENGINEER

    def cards(self):
        g = gauge_counts()
        return [
            {"label": "Factories", "value": Factory.objects.count(), "url": "core:factory_list"},
            {"label": "Machines", "value": Machine.objects.count(), "url": "core:machine_list"},
            {"label": "Part numbers", "value": PartNumber.objects.count(), "url": "core:part_list"},
            {"label": "Inspection Templates", "value": InspectionTemplate.objects.count(), "url": "inspections:template_list"},
            {"label": "Approved Templates", "value": InspectionTemplate.objects.filter(status=InspectionTemplate.Status.APPROVED).count(), "style": "success", "url": "inspections:template_list"},
            {"label": "Gauges", "value": g["total"], "url": "core:gauge_list"},
            {"label": "Expired gauges", "value": g["expired"], "style": "danger", "url": "core:gauge_list"},
            {"label": f"Expiring in {EXPIRING_SOON_DAYS} days", "value": g["expiring_soon"], "style": "warning", "url": "core:gauge_list"},
            {"label": "Submitted Checklists", "value": Checklist.objects.count(), "url": "inspections:checklist_list"},
        ]


class InspectorDashboardView(RoleDashboardView):
    required_role = roles.INSPECTOR

    def cards(self):
        g = gauge_counts()
        return [
            {"label": "Approved Templates", "value": InspectionTemplate.objects.filter(status=InspectionTemplate.Status.APPROVED, is_active=True).count(), "url": "inspections:inspection_create"},
            {"label": "Active machines", "value": Machine.objects.filter(is_active=True).count()},
            {"label": "Usable gauges (calibration valid)", "value": g["valid"], "style": "success"},
            {"label": "My Checklists", "value": Checklist.objects.filter(inspector=self.request.user).count(), "url": "inspections:checklist_list"},
        ]


class SupervisorDashboardView(RoleDashboardView):
    required_role = roles.SUPERVISOR

    def cards(self):
        g = gauge_counts()
        return [
            {"label": "Pending Review", "value": Checklist.objects.filter(status=Checklist.Status.PENDING_REVIEW).count(), "style": "warning", "url": "approvals:queue"},
            {"label": "CTQ Failed", "value": Checklist.objects.filter(status=Checklist.Status.CTQ_FAILED).count(), "style": "danger", "url": "approvals:queue"},
            {"label": "Quarantined", "value": Checklist.objects.filter(status=Checklist.Status.QUARANTINED).count(), "style": "secondary", "url": "approvals:quarantine_list"},
            {"label": "Approved", "value": Checklist.objects.filter(status=Checklist.Status.APPROVED).count(), "style": "success"},
            {"label": "Gauges with valid calibration", "value": g["valid"], "style": "success"},
            {"label": "Expired gauges", "value": g["expired"], "style": "danger"},
        ]


class PlantManagerDashboardView(RoleDashboardView):
    required_role = roles.PLANT_MANAGER

    def cards(self):
        g = gauge_counts()
        return [
            {"label": "Factories", "value": Factory.objects.count(), "url": "core:factory_list"},
            {"label": "Active machines", "value": Machine.objects.filter(is_active=True).count()},
            {"label": "Inspection Templates", "value": InspectionTemplate.objects.count(), "url": "inspections:template_list"},
            {"label": "Total Inspections", "value": Checklist.objects.count(), "url": "inspections:checklist_list"},
            {"label": "Gauges", "value": g["total"]},
            {"label": "Expired gauges", "value": g["expired"], "style": "danger"},
        ]
