"""
approvals/tests.py

Tests for Stage 5: Approval workflow, transition() enforcement, ApprovalLog,
supervisor queue, and admin read-only enforcement.
"""
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from approvals.models import ApprovalLog
from core.models import Gauge, Machine
from inspections.models import Checklist, InspectionTemplate, Measurement


def make_passing_checklist(template, machine, inspector):
    """Create a PENDING_REVIEW checklist where ALL fields pass."""
    gauge = Gauge.objects.filter(serial_no="CAL-001").first() or Gauge.objects.first()
    cl = Checklist.objects.create(
        template=template, machine=machine, job_no="PASS-001",
        inspector=inspector, status=Checklist.Status.PENDING_REVIEW,
    )
    for field in template.fields.all():
        if field.field_type == "DIMENSION":
            Measurement.objects.create(
                checklist=cl, field=field, value=field.nominal, gauge=gauge, is_within_tolerance=True
            )
        elif field.field_type == "MAX_THRESHOLD":
            Measurement.objects.create(
                checklist=cl, field=field, value=Decimal("0.500"), gauge=gauge, is_within_tolerance=True
            )
        else:  # VISUAL
            Measurement.objects.create(
                checklist=cl, field=field, visual_ok=True, is_within_tolerance=True
            )
    return cl


def make_failing_checklist(template, machine, inspector, fail_ctq=False):
    """Create a checklist with some failures.  fail_ctq=True fails the CTQ field."""
    gauge = Gauge.objects.filter(serial_no="CAL-001").first() or Gauge.objects.first()
    status = Checklist.Status.CTQ_FAILED if fail_ctq else Checklist.Status.PENDING_REVIEW
    cl = Checklist.objects.create(
        template=template, machine=machine, job_no="FAIL-001",
        inspector=inspector, status=status,
    )
    for field in template.fields.all():
        is_ctq = field.is_ctq
        if field.field_type == "DIMENSION":
            # CTQ field: fail if fail_ctq, else pass
            fail_this = fail_ctq and is_ctq
            value = Decimal("99.000") if fail_this else field.nominal
            Measurement.objects.create(
                checklist=cl, field=field, value=value, gauge=gauge,
                is_within_tolerance=not fail_this,
            )
        elif field.field_type == "MAX_THRESHOLD":
            # Always fail the threshold field (non-CTQ in seed data)
            Measurement.objects.create(
                checklist=cl, field=field, value=Decimal("5.000"), gauge=gauge, is_within_tolerance=False,
            )
        else:  # VISUAL — always pass
            Measurement.objects.create(
                checklist=cl, field=field, visual_ok=True, is_within_tolerance=True
            )
    return cl


class ChecklistTransitionTests(TestCase):
    """Unit tests for Checklist.transition() business logic."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)
        cls.template = InspectionTemplate.objects.get(name="Drive Shaft", revision="Rev A")
        cls.machine = Machine.objects.filter(is_active=True).first()
        cls.supervisor = User.objects.get(username="supervisor1")
        cls.inspector = User.objects.get(username="inspector1")

    def test_approve_from_pending_review(self):
        cl = make_passing_checklist(self.template, self.machine, self.inspector)
        cl.transition(Checklist.Status.APPROVED, self.supervisor)
        cl.refresh_from_db()
        self.assertEqual(cl.status, Checklist.Status.APPROVED)
        self.assertEqual(cl.approval_logs.count(), 1)
        log = cl.approval_logs.first()
        self.assertEqual(log.from_status, Checklist.Status.PENDING_REVIEW)
        self.assertEqual(log.to_status, Checklist.Status.APPROVED)

    def test_quarantine_from_pending_review(self):
        cl = make_passing_checklist(self.template, self.machine, self.inspector)
        cl.transition(Checklist.Status.QUARANTINED, self.supervisor)
        cl.refresh_from_db()
        self.assertEqual(cl.status, Checklist.Status.QUARANTINED)

    def test_quarantine_from_ctq_failed(self):
        cl = make_failing_checklist(self.template, self.machine, self.inspector, fail_ctq=True)
        cl.transition(Checklist.Status.QUARANTINED, self.supervisor)
        cl.refresh_from_db()
        self.assertEqual(cl.status, Checklist.Status.QUARANTINED)

    def test_cannot_approve_from_ctq_failed(self):
        cl = make_failing_checklist(self.template, self.machine, self.inspector, fail_ctq=True)
        with self.assertRaises(ValueError):
            cl.transition(Checklist.Status.APPROVED, self.supervisor)

    def test_concession_from_pending_review_with_non_ctq_failure(self):
        cl = make_failing_checklist(self.template, self.machine, self.inspector, fail_ctq=False)
        cl.transition(
            Checklist.Status.CONCESSION, self.supervisor,
            reason_code=ApprovalLog.ReasonCode.COSMETIC_ONLY,
            justification="Minor cosmetic issue, non-functional.",
        )
        cl.refresh_from_db()
        self.assertEqual(cl.status, Checklist.Status.CONCESSION)
        log = cl.approval_logs.first()
        self.assertEqual(log.reason_code, ApprovalLog.ReasonCode.COSMETIC_ONLY)
        self.assertIn("cosmetic", log.justification.lower())

    def test_concession_blocked_when_ctq_fails(self):
        cl = make_failing_checklist(self.template, self.machine, self.inspector, fail_ctq=True)
        with self.assertRaises(ValueError) as ctx:
            cl.transition(
                Checklist.Status.CONCESSION, self.supervisor,
                reason_code=ApprovalLog.ReasonCode.COSMETIC_ONLY,
                justification="Test",
            )
        self.assertIn("CTQ", str(ctx.exception))

    def test_concession_blocked_when_no_failures(self):
        cl = make_passing_checklist(self.template, self.machine, self.inspector)
        with self.assertRaises(ValueError) as ctx:
            cl.transition(
                Checklist.Status.CONCESSION, self.supervisor,
                reason_code=ApprovalLog.ReasonCode.OTHER,
                justification="Test",
            )
        self.assertIn("failed", str(ctx.exception).lower())

    def test_concession_requires_justification(self):
        cl = make_failing_checklist(self.template, self.machine, self.inspector, fail_ctq=False)
        with self.assertRaises(ValueError) as ctx:
            cl.transition(
                Checklist.Status.CONCESSION, self.supervisor,
                reason_code=ApprovalLog.ReasonCode.OTHER,
                justification="",  # empty
            )
        self.assertIn("justification", str(ctx.exception).lower())

    def test_invalid_transition_raises(self):
        cl = make_passing_checklist(self.template, self.machine, self.inspector)
        cl.status = Checklist.Status.APPROVED
        cl.save(update_fields=["status"])
        with self.assertRaises(ValueError):
            cl.transition(Checklist.Status.PENDING_REVIEW, self.supervisor)

    def test_transition_creates_approval_log(self):
        cl = make_passing_checklist(self.template, self.machine, self.inspector)
        cl.transition(Checklist.Status.APPROVED, self.supervisor)
        self.assertEqual(ApprovalLog.objects.filter(checklist=cl).count(), 1)

    def test_is_frozen_after_approve(self):
        cl = make_passing_checklist(self.template, self.machine, self.inspector)
        cl.transition(Checklist.Status.APPROVED, self.supervisor)
        cl.refresh_from_db()
        self.assertTrue(cl.is_frozen)

    def test_is_frozen_after_quarantine(self):
        cl = make_passing_checklist(self.template, self.machine, self.inspector)
        cl.transition(Checklist.Status.QUARANTINED, self.supervisor)
        cl.refresh_from_db()
        self.assertTrue(cl.is_frozen)

    def test_is_frozen_after_concession(self):
        cl = make_failing_checklist(self.template, self.machine, self.inspector, fail_ctq=False)
        cl.transition(
            Checklist.Status.CONCESSION, self.supervisor,
            reason_code=ApprovalLog.ReasonCode.OTHER,
            justification="Granted.",
        )
        cl.refresh_from_db()
        self.assertTrue(cl.is_frozen)

    def test_failed_field_count(self):
        cl = make_failing_checklist(self.template, self.machine, self.inspector)
        # Surface Roughness always fails; Shaft Diameter passes in non-CTQ scenario
        self.assertGreater(cl.failed_field_count, 0)

    def test_has_any_ctq_failure(self):
        cl_ctq = make_failing_checklist(self.template, self.machine, self.inspector, fail_ctq=True)
        self.assertTrue(cl_ctq.has_any_ctq_failure)
        cl_no_ctq = make_failing_checklist(self.template, self.machine, self.inspector, fail_ctq=False)
        self.assertFalse(cl_no_ctq.has_any_ctq_failure)


class SupervisorQueueViewTests(TestCase):
    """HTTP tests for the supervisor approval queue."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)
        cls.template = InspectionTemplate.objects.get(name="Drive Shaft", revision="Rev A")
        cls.machine = Machine.objects.filter(is_active=True).first()
        cls.supervisor = User.objects.get(username="supervisor1")
        cls.inspector = User.objects.get(username="inspector1")

    def test_queue_accessible_by_supervisor(self):
        self.client.login(username="supervisor1", password="demo1234")
        resp = self.client.get(reverse("approvals:queue"))
        self.assertEqual(resp.status_code, 200)

    def test_queue_forbidden_for_inspector(self):
        self.client.login(username="inspector1", password="demo1234")
        resp = self.client.get(reverse("approvals:queue"))
        self.assertEqual(resp.status_code, 403)

    def test_queue_shows_pending_checklists(self):
        cl = make_passing_checklist(self.template, self.machine, self.inspector)
        self.client.login(username="supervisor1", password="demo1234")
        resp = self.client.get(reverse("approvals:queue"))
        self.assertContains(resp, cl.job_no)

    def test_detail_view_accessible_by_supervisor(self):
        cl = make_passing_checklist(self.template, self.machine, self.inspector)
        self.client.login(username="supervisor1", password="demo1234")
        resp = self.client.get(reverse("approvals:detail", kwargs={"pk": cl.pk}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, cl.job_no)


class SupervisorActionViewTests(TestCase):
    """HTTP POST tests for approve, quarantine, concession actions."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)
        cls.template = InspectionTemplate.objects.get(name="Drive Shaft", revision="Rev A")
        cls.machine = Machine.objects.filter(is_active=True).first()
        cls.supervisor = User.objects.get(username="supervisor1")
        cls.inspector = User.objects.get(username="inspector1")

    def test_approve_action(self):
        cl = make_passing_checklist(self.template, self.machine, self.inspector)
        self.client.login(username="supervisor1", password="demo1234")
        resp = self.client.post(reverse("approvals:approve", kwargs={"pk": cl.pk}), follow=True)
        self.assertEqual(resp.status_code, 200)
        cl.refresh_from_db()
        self.assertEqual(cl.status, Checklist.Status.APPROVED)

    def test_quarantine_action(self):
        cl = make_passing_checklist(self.template, self.machine, self.inspector)
        self.client.login(username="supervisor1", password="demo1234")
        resp = self.client.post(reverse("approvals:quarantine", kwargs={"pk": cl.pk}), follow=True)
        self.assertEqual(resp.status_code, 200)
        cl.refresh_from_db()
        self.assertEqual(cl.status, Checklist.Status.QUARANTINED)
        self.assertTrue(cl in Checklist.objects.filter(status=Checklist.Status.QUARANTINED))

    def test_concession_action_with_valid_data(self):
        cl = make_failing_checklist(self.template, self.machine, self.inspector, fail_ctq=False)
        self.client.login(username="supervisor1", password="demo1234")
        resp = self.client.post(
            reverse("approvals:concession", kwargs={"pk": cl.pk}),
            {"reason_code": "COSMETIC_ONLY", "justification": "Minor surface marks only."},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        cl.refresh_from_db()
        self.assertEqual(cl.status, Checklist.Status.CONCESSION)

    def test_concession_blocked_for_ctq_failed_checklist(self):
        cl = make_failing_checklist(self.template, self.machine, self.inspector, fail_ctq=True)
        # CTQ_FAILED -> concession is not a valid transition
        self.client.login(username="supervisor1", password="demo1234")
        resp = self.client.post(
            reverse("approvals:concession", kwargs={"pk": cl.pk}),
            {"reason_code": "COSMETIC_ONLY", "justification": "Test."},
            follow=True,
        )
        cl.refresh_from_db()
        # Status must not have changed to CONCESSION
        self.assertNotEqual(cl.status, Checklist.Status.CONCESSION)

    def test_concession_requires_valid_reason_code(self):
        cl = make_failing_checklist(self.template, self.machine, self.inspector, fail_ctq=False)
        self.client.login(username="supervisor1", password="demo1234")
        resp = self.client.post(
            reverse("approvals:concession", kwargs={"pk": cl.pk}),
            {"reason_code": "INVALID_CODE", "justification": "Test."},
            follow=True,
        )
        cl.refresh_from_db()
        self.assertNotEqual(cl.status, Checklist.Status.CONCESSION)

    def test_quarantine_list_view(self):
        cl = make_passing_checklist(self.template, self.machine, self.inspector)
        cl.transition(Checklist.Status.QUARANTINED, self.supervisor)
        self.client.login(username="supervisor1", password="demo1234")
        resp = self.client.get(reverse("approvals:quarantine_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, cl.job_no)

    def test_approval_log_shown_in_detail(self):
        cl = make_passing_checklist(self.template, self.machine, self.inspector)
        self.client.login(username="supervisor1", password="demo1234")
        self.client.post(reverse("approvals:approve", kwargs={"pk": cl.pk}))
        resp = self.client.get(reverse("approvals:detail", kwargs={"pk": cl.pk}))
        self.assertContains(resp, "APPROVED")

    def test_concession_badge_shown_in_detail(self):
        cl = make_failing_checklist(self.template, self.machine, self.inspector, fail_ctq=False)
        cl.transition(
            Checklist.Status.CONCESSION, self.supervisor,
            reason_code=ApprovalLog.ReasonCode.CUSTOMER_WAIVER,
            justification="Customer has accepted this deviation.",
        )
        self.client.login(username="supervisor1", password="demo1234")
        resp = self.client.get(reverse("approvals:detail", kwargs={"pk": cl.pk}))
        self.assertContains(resp, "Concession")
