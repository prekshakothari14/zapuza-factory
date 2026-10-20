from datetime import timedelta
from decimal import Decimal

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import Gauge
from audit.admin import AuditLogAdmin
from audit.middleware import AuditContextMiddleware
from audit.context import set_audit_context, clear_audit_context
from audit.models import AuditLog


class AuditLogCaptureTests(TestCase):
    """Creating/updating tracked models writes correct audit rows."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)
        cls.engineer = User.objects.get(username="engineer1")
        cls.gauge = Gauge.objects.get(serial_no="CAL-001")

    def setUp(self):
        clear_audit_context()
        set_audit_context(user=self.engineer, ip_address="203.0.113.10")

    def tearDown(self):
        clear_audit_context()

    def test_create_gauge_writes_create_log(self):
        # cleared via raw SQL below
        # Use connection to wipe for test isolation without going through manager
        from django.db import connection
        with connection.cursor() as c:
            c.execute("DELETE FROM audit_auditlog")

        g = Gauge.objects.create(
            serial_no="TST-999",
            gauge_type=Gauge.GaugeType.CALIPER,
            calibration_expiry=timezone.localdate() + timedelta(days=90),
        )
        logs = list(AuditLog.objects.filter(model_name="core.Gauge", object_id=str(g.pk), action="CREATE"))
        self.assertEqual(len(logs), 1)
        log = logs[0]
        self.assertEqual(log.username, "engineer1")
        self.assertEqual(log.user_id, self.engineer.id)
        self.assertIsNotNone(log.new_values)
        self.assertIsNone(log.old_values)
        self.assertEqual(log.new_values.get("serial_no"), "TST-999")
        self.assertEqual(log.ip_address, "203.0.113.10")
        self.assertIn("serial_no", log.changed_fields)

    def test_update_gauge_writes_changed_fields_only(self):
        from django.db import connection
        with connection.cursor() as c:
            c.execute("DELETE FROM audit_auditlog")

        g = self.gauge
        old_expiry = g.calibration_expiry
        new_expiry = old_expiry + timedelta(days=30)
        g.calibration_expiry = new_expiry
        g.save()

        logs = list(AuditLog.objects.filter(model_name="core.Gauge", object_id=str(g.pk), action="UPDATE"))
        self.assertEqual(len(logs), 1)
        log = logs[0]
        self.assertEqual(log.username, "engineer1")
        self.assertEqual(log.old_values.get("calibration_expiry"), old_expiry.isoformat())
        self.assertEqual(log.new_values.get("calibration_expiry"), new_expiry.isoformat())
        self.assertEqual(log.changed_fields, ["calibration_expiry"])
        # Unchanged fields must not appear
        self.assertNotIn("serial_no", log.old_values or {})
        self.assertNotIn("serial_no", log.new_values or {})

    def test_system_user_when_no_request(self):
        clear_audit_context()  # no request context
        from django.db import connection
        with connection.cursor() as c:
            c.execute("DELETE FROM audit_auditlog")

        g = Gauge.objects.create(
            serial_no="SYS-001",
            gauge_type=Gauge.GaugeType.CMM,
            calibration_expiry=timezone.localdate() + timedelta(days=10),
        )
        log = AuditLog.objects.filter(object_id=str(g.pk), action="CREATE").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.username, "system")
        self.assertIsNone(log.user)


class AuditLogImmutabilityTests(TestCase):
    """ORM-level immutability for AuditLog."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)

    def setUp(self):
        # Create a real log via tracked model
        set_audit_context(user=User.objects.get(username="engineer1"), ip_address="127.0.0.1")
        g = Gauge.objects.create(
            serial_no="IMM-001",
            gauge_type=Gauge.GaugeType.MICROMETER,
            calibration_expiry=timezone.localdate() + timedelta(days=5),
        )
        clear_audit_context()
        self.log = AuditLog.objects.filter(object_id=str(g.pk), action="CREATE").first()
        self.assertIsNotNone(self.log)

    def test_save_existing_raises(self):
        self.log.username = "hacker"
        with self.assertRaises(PermissionDenied):
            self.log.save()

    def test_delete_instance_raises(self):
        with self.assertRaises(PermissionDenied):
            self.log.delete()

    def test_queryset_update_raises(self):
        with self.assertRaises(PermissionDenied):
            AuditLog.objects.filter(pk=self.log.pk).update(username="hacker")

    def test_queryset_delete_raises(self):
        with self.assertRaises(PermissionDenied):
            AuditLog.objects.filter(pk=self.log.pk).delete()

    def test_bulk_update_raises(self):
        self.log.username = "x"
        with self.assertRaises(PermissionDenied):
            AuditLog.objects.bulk_update([self.log], ["username"])


class AuditLogAdminTests(TestCase):
    def setUp(self):
        self.site = AdminSite()
        self.admin = AuditLogAdmin(AuditLog, self.site)
        self.superuser = User.objects.create_superuser("rootadmin", "a@b.com", "pass")

    def test_admin_permissions_false_even_for_superuser(self):
        req = RequestFactory().get("/admin/")
        req.user = self.superuser
        self.assertFalse(self.admin.has_add_permission(req))
        self.assertFalse(self.admin.has_change_permission(req))
        self.assertFalse(self.admin.has_delete_permission(req))
        self.assertFalse(self.admin.has_change_permission(req, obj=AuditLog()))
        self.assertFalse(self.admin.has_delete_permission(req, obj=AuditLog()))


class AuditLogViewAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)

    def test_inspector_cannot_open_audit_page(self):
        self.client.login(username="inspector1", password="demo1234")
        resp = self.client.get(reverse("audit:log_list"))
        self.assertEqual(resp.status_code, 403)

    def test_engineer_can_open_audit_page(self):
        self.client.login(username="engineer1", password="demo1234")
        resp = self.client.get(reverse("audit:log_list"))
        self.assertEqual(resp.status_code, 200)

    def test_supervisor_can_open_audit_page(self):
        self.client.login(username="supervisor1", password="demo1234")
        resp = self.client.get(reverse("audit:log_list"))
        self.assertEqual(resp.status_code, 200)
