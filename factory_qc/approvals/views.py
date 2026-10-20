"""
approvals/views.py

Supervisor review queue and action views.
All views require the 'Supervisor' role (enforced by SupervisorRequiredMixin).
"""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import DetailView, FormView, ListView

from accounts.roles import SUPERVISOR, get_role
from approvals.models import ApprovalLog
from inspections.models import Checklist


class SupervisorRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Block non-supervisors (403)."""

    def test_func(self):
        return get_role(self.request.user) in (SUPERVISOR, "Plant Manager")


# ---------------------------------------------------------------------------
# Queue: checklists awaiting review (PENDING_REVIEW + CTQ_FAILED)
# ---------------------------------------------------------------------------

class ApprovalQueueView(SupervisorRequiredMixin, ListView):
    template_name = "approvals/queue.html"
    context_object_name = "checklists"
    paginate_by = 25

    def get_queryset(self):
        qs = (
            Checklist.objects.filter(
                status__in=[Checklist.Status.PENDING_REVIEW, Checklist.Status.CTQ_FAILED]
            )
            .select_related("template__part", "machine", "inspector")
            .annotate(
                failed_count=Count(
                    "measurements", filter=Q(measurements__is_within_tolerance=False)
                )
            )
            .order_by("-submitted_at")
        )

        # Optional filters
        machine_id = self.request.GET.get("machine")
        date_from = self.request.GET.get("date_from")
        date_to = self.request.GET.get("date_to")

        if machine_id:
            qs = qs.filter(machine_id=machine_id)
        if date_from:
            qs = qs.filter(submitted_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(submitted_at__date__lte=date_to)

        return qs

    def get_context_data(self, **kwargs):
        from core.models import Machine
        ctx = super().get_context_data(**kwargs)
        ctx["machines"] = Machine.objects.filter(is_active=True).order_by("name")
        ctx["selected_machine"] = self.request.GET.get("machine", "")
        ctx["date_from"] = self.request.GET.get("date_from", "")
        ctx["date_to"] = self.request.GET.get("date_to", "")
        return ctx


# ---------------------------------------------------------------------------
# Detail: read-only view of a submitted checklist for the supervisor
# ---------------------------------------------------------------------------

class ApprovalDetailView(SupervisorRequiredMixin, DetailView):
    model = Checklist
    template_name = "approvals/detail.html"
    context_object_name = "checklist"

    def get_queryset(self):
        return Checklist.objects.select_related(
            "template__part", "machine", "inspector"
        ).prefetch_related(
            "measurements__field",
            "measurements__gauge",
            "measurements__photos",
            "approval_logs__action_by",
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        checklist = self.object
        ctx["measurements"] = checklist.measurements.select_related(
            "field", "gauge"
        ).prefetch_related("photos").order_by("field__order")
        ctx["approval_logs"] = checklist.approval_logs.all()
        ctx["reason_codes"] = ApprovalLog.ReasonCode.choices
        ctx["can_approve"] = checklist.status == Checklist.Status.PENDING_REVIEW
        ctx["can_concession"] = (
            checklist.status == Checklist.Status.PENDING_REVIEW
            and checklist.has_any_failure
            and not checklist.has_any_ctq_failure
        )
        ctx["can_quarantine"] = checklist.status in (
            Checklist.Status.PENDING_REVIEW,
            Checklist.Status.CTQ_FAILED,
        )
        return ctx


# ---------------------------------------------------------------------------
# Action: Approve
# ---------------------------------------------------------------------------

class ApproveView(SupervisorRequiredMixin, DetailView):
    model = Checklist

    def post(self, request, *args, **kwargs):
        checklist = self.get_object()
        try:
            checklist.transition(Checklist.Status.APPROVED, user=request.user)
            messages.success(request, f"Checklist {checklist.job_no} has been approved.")
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect(reverse("approvals:detail", kwargs={"pk": checklist.pk}))


# ---------------------------------------------------------------------------
# Action: Quarantine
# ---------------------------------------------------------------------------

class QuarantineView(SupervisorRequiredMixin, DetailView):
    model = Checklist

    def post(self, request, *args, **kwargs):
        checklist = self.get_object()
        try:
            checklist.transition(Checklist.Status.QUARANTINED, user=request.user)
            messages.warning(request, f"Checklist {checklist.job_no} has been quarantined.")
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect(reverse("approvals:detail", kwargs={"pk": checklist.pk}))


# ---------------------------------------------------------------------------
# Action: Concession
# ---------------------------------------------------------------------------

class ConcessionView(SupervisorRequiredMixin, DetailView):
    model = Checklist

    def post(self, request, *args, **kwargs):
        checklist = self.get_object()
        reason_code = request.POST.get("reason_code", "").strip()
        justification = request.POST.get("justification", "").strip()

        # Validate reason_code value
        valid_codes = [c[0] for c in ApprovalLog.ReasonCode.choices]
        if reason_code not in valid_codes:
            messages.error(request, "Please select a valid reason code.")
            return redirect(reverse("approvals:detail", kwargs={"pk": checklist.pk}))

        try:
            checklist.transition(
                Checklist.Status.CONCESSION,
                user=request.user,
                reason_code=reason_code,
                justification=justification,
            )
            messages.success(
                request,
                f"Checklist {checklist.job_no} has been granted a concession ({reason_code})."
            )
        except ValueError as exc:
            messages.error(request, str(exc))

        return redirect(reverse("approvals:detail", kwargs={"pk": checklist.pk}))


# ---------------------------------------------------------------------------
# Quarantine holding area list
# ---------------------------------------------------------------------------

class QuarantineListView(SupervisorRequiredMixin, ListView):
    template_name = "approvals/quarantine_list.html"
    context_object_name = "checklists"
    paginate_by = 25

    def get_queryset(self):
        return (
            Checklist.objects.filter(status=Checklist.Status.QUARANTINED)
            .select_related("template__part", "machine", "inspector")
            .annotate(
                failed_count=Count(
                    "measurements", filter=Q(measurements__is_within_tolerance=False)
                )
            )
            .order_by("-submitted_at")
        )
