import io
from decimal import Decimal
from PIL import Image

from django.contrib.auth.models import Group, User
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from django.urls import reverse

from core.models import Factory, Gauge, Machine, PartNumber
from inspections.forms import MeasurementForm, MeasurementFormSet
from inspections.models import Checklist, DefectPhoto, InspectionTemplate, Measurement, TemplateField


def create_test_image(name="defect.jpg", fmt="JPEG", content_type="image/jpeg"):
    file_obj = io.BytesIO()
    image = Image.new("RGB", (100, 100), color=(255, 0, 0))
    image.save(file_obj, fmt)
    file_obj.seek(0)
    return SimpleUploadedFile(name, file_obj.read(), content_type=content_type)


def create_test_text_file(name="notes.txt"):
    return SimpleUploadedFile(name, b"this is not an image", content_type="text/plain")


class ToleranceLogicTests(TestCase):
    """Test TemplateField.evaluate() business logic."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)
        cls.part = PartNumber.objects.get(part_no="DS-100")
        cls.template = InspectionTemplate.objects.get(name="Drive Shaft", revision="Rev A")

    def test_dimension_tolerance(self):
        """DIMENSION passes if nominal+lower_tol <= value <= nominal+upper_tol.
        (25.00, +0.05/-0.02 means 24.98 to 25.05, so 25.03 passes and 25.10 fails)
        """
        field = self.template.fields.get(name="Shaft Diameter")
        # Exact prompt examples:
        self.assertTrue(field.evaluate(value=Decimal("25.03")))
        self.assertTrue(field.evaluate(value="25.03"))
        self.assertFalse(field.evaluate(value=Decimal("25.10")))
        self.assertFalse(field.evaluate(value="25.10"))

        # Boundary checks:
        self.assertTrue(field.evaluate(value="24.980"))
        self.assertFalse(field.evaluate(value="24.979"))
        self.assertTrue(field.evaluate(value="25.050"))
        self.assertFalse(field.evaluate(value="25.051"))

        # Invalid inputs:
        self.assertFalse(field.evaluate(value=None))
        self.assertFalse(field.evaluate(value=""))
        self.assertFalse(field.evaluate(value="abc"))

    def test_dimension_symmetric_tolerance(self):
        """Length 100.00 ±0.10 (99.90 to 100.10)."""
        field = self.template.fields.get(name="Length")
        self.assertTrue(field.evaluate(value="100.00"))
        self.assertTrue(field.evaluate(value="99.900"))
        self.assertTrue(field.evaluate(value="100.100"))
        self.assertFalse(field.evaluate(value="99.899"))
        self.assertFalse(field.evaluate(value="100.101"))

    def test_max_threshold_tolerance(self):
        """MAX_THRESHOLD passes if value <= max_value."""
        field = self.template.fields.get(name="Surface Roughness")
        self.assertTrue(field.evaluate(value="0.8"))
        self.assertTrue(field.evaluate(value="0.800"))
        self.assertTrue(field.evaluate(value="0.5"))
        self.assertTrue(field.evaluate(value="0.0"))
        self.assertFalse(field.evaluate(value="0.801"))
        self.assertFalse(field.evaluate(value="1.2"))
        self.assertFalse(field.evaluate(value=""))
        self.assertFalse(field.evaluate(value=None))

    def test_visual_tolerance(self):
        """VISUAL passes if Yes."""
        field = self.template.fields.get(name="Free of burrs")
        self.assertTrue(field.evaluate(visual_ok=True))
        self.assertTrue(field.evaluate(visual_ok="yes"))
        self.assertTrue(field.evaluate(visual_ok="Yes"))
        self.assertTrue(field.evaluate(visual_ok="YES"))
        self.assertFalse(field.evaluate(visual_ok=False))
        self.assertFalse(field.evaluate(visual_ok="no"))
        self.assertFalse(field.evaluate(visual_ok="No"))
        self.assertFalse(field.evaluate(visual_ok=""))
        self.assertFalse(field.evaluate(visual_ok=None))


class ApprovedTemplateImmutabilityTests(TestCase):
    """Business rule: approved templates cannot be edited."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)
        cls.part = PartNumber.objects.get(part_no="DS-100")
        cls.template = InspectionTemplate.objects.get(name="Drive Shaft", revision="Rev A")

    def test_approved_template_cannot_change_name_or_revision(self):
        self.template.name = "Modified Shaft"
        with self.assertRaises(ValidationError):
            self.template.save()

    def test_cannot_add_field_to_approved_template(self):
        with self.assertRaises(ValidationError):
            TemplateField.objects.create(
                template=self.template,
                order=5,
                name="New Extra Field",
                field_type=TemplateField.FieldType.VISUAL,
            )

    def test_cannot_edit_existing_field_of_approved_template(self):
        field = self.template.fields.first()
        field.name = "Changed Name"
        with self.assertRaises(ValidationError):
            field.save()

    def test_cannot_delete_field_from_approved_template(self):
        field = self.template.fields.first()
        with self.assertRaises(ValidationError):
            field.delete()


class GaugeCalibrationEnforcementTests(TestCase):
    """STAGE 4: Gauge calibration enforcement."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)
        cls.template = InspectionTemplate.objects.get(name="Drive Shaft", revision="Rev A")
        cls.field = cls.template.fields.first()
        cls.valid_gauge = Gauge.objects.get(serial_no="CAL-001")  # Valid calibration
        cls.expired_gauge = Gauge.objects.get(serial_no="MIC-002")  # Expired 10 days ago
        cls.machine = Machine.objects.filter(is_active=True).first()
        cls.inspector = User.objects.get(username="inspector1")

    def test_measurement_clean_with_expired_gauge(self):
        """In Measurement.clean(), if the selected gauge is expired, raise ValidationError."""
        checklist = Checklist.objects.create(
            template=self.template,
            machine=self.machine,
            job_no="JOB-GAUGE-01",
            inspector=self.inspector,
            status=Checklist.Status.PENDING_REVIEW,
        )
        measurement = Measurement(
            checklist=checklist,
            field=self.field,
            value=Decimal("25.02"),
            gauge=self.expired_gauge,
        )
        with self.assertRaises(ValidationError) as ctx:
            measurement.clean()
        self.assertIn("Expired Tool Calibration. Obtain a calibrated tool from the tool crib.", str(ctx.exception))

    def test_measurement_clean_with_valid_gauge(self):
        checklist = Checklist.objects.create(
            template=self.template,
            machine=self.machine,
            job_no="JOB-GAUGE-02",
            inspector=self.inspector,
            status=Checklist.Status.PENDING_REVIEW,
        )
        measurement = Measurement(
            checklist=checklist,
            field=self.field,
            value=Decimal("25.02"),
            gauge=self.valid_gauge,
        )
        # Should not raise
        measurement.clean()
        measurement.save()
        self.assertIsNotNone(measurement.pk)

    def test_measurement_form_and_formset_clean(self):
        """Form and Formset clean() blocks expired gauge."""
        form = MeasurementForm(data={
            "field": self.field.id,
            "value": "25.03",
            "gauge": self.expired_gauge.id,
        })
        self.assertFalse(form.is_valid())
        self.assertIn("Expired Tool Calibration. Obtain a calibrated tool from the tool crib.", form.errors.get("gauge", []))

    def test_dropdown_marks_expired_gauge(self):
        """Mark expired gauges '(EXPIRED)' in the dropdown (via gauges-data JSON)."""
        self.client.login(username="inspector1", password="demo1234")
        resp = self.client.get(reverse("inspections:inspection_create"))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        # Gauge catalog is embedded as JSON (escapejs may encode hyphens as \\u002D).
        # JS appends " (EXPIRED)" when building options for invalid gauges.
        self.assertIn("gauges-data", html)
        self.assertIn('"is_valid": false', html)
        self.assertIn('"is_valid": true', html)
        self.assertIn("(EXPIRED)", html)
        self.assertTrue(
            self.expired_gauge.serial_no in html
            or self.expired_gauge.serial_no.replace("-", "\\u002D") in html
            or "MIC" in html
        )


class DefectPhotoTests(TestCase):
    """STAGE 4B: DefectPhoto model, upload rules, and server-side validation."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)
        cls.template = InspectionTemplate.objects.get(name="Drive Shaft", revision="Rev A")
        cls.machine = Machine.objects.filter(is_active=True).first()
        cls.inspector = User.objects.get(username="inspector1")
        cls.field = cls.template.fields.get(name="Shaft Diameter")
        cls.caliper = Gauge.objects.get(serial_no="CAL-001")

    def login(self, username="inspector1"):
        self.client.login(username=username, password="demo1234")

    def _base_post(self, job_no, shaft_value="25.03", extra=None):
        f_shaft = self.template.fields.get(name="Shaft Diameter")
        f_len = self.template.fields.get(name="Length")
        f_rough = self.template.fields.get(name="Surface Roughness")
        f_burr = self.template.fields.get(name="Free of burrs")
        data = {
            "template": self.template.id,
            "machine": self.machine.id,
            "job_no": job_no,
            f"field_{f_shaft.id}_value": shaft_value,
            f"field_{f_shaft.id}_gauge": self.caliper.id,
            f"field_{f_len.id}_value": "100.00",
            f"field_{f_len.id}_gauge": self.caliper.id,
            f"field_{f_rough.id}_value": "0.5",
            f"field_{f_rough.id}_gauge": self.caliper.id,
            f"field_{f_burr.id}_visual_ok": "yes",
        }
        if extra:
            data.update(extra)
        return data, f_shaft

    def test_defect_photo_model_creation(self):
        checklist = Checklist.objects.create(
            template=self.template,
            machine=self.machine,
            job_no="JOB-PHOTO-01",
            inspector=self.inspector,
            status=Checklist.Status.PENDING_REVIEW,
        )
        m = Measurement.objects.create(
            checklist=checklist,
            field=self.field,
            value=Decimal("25.10"),
            gauge=self.caliper,
            is_within_tolerance=False,
        )
        img = create_test_image("defect_1.jpg")
        photo = DefectPhoto.objects.create(measurement=m, image=img)
        self.assertIsNotNone(photo.pk)
        self.assertEqual(m.photos.count(), 1)
        self.assertEqual(m.defect_photos.count(), 1)
        # upload_to uses defects/%Y/%m/
        self.assertIn("defects/", photo.image.name)

    def test_submit_blocked_with_zero_photos_on_failed_field(self):
        """Submit blocked when a failed field has 0 photos."""
        self.login()
        url = reverse("inspections:inspection_create")
        post_data, f_shaft = self._base_post("JOB-0-PHOTO", shaft_value="25.10")
        resp = self.client.post(url, post_data, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Upload at least 2 photos for")
        self.assertContains(resp, "Shaft Diameter")
        self.assertContains(resp, "0 uploaded")
        self.assertEqual(Checklist.objects.filter(job_no="JOB-0-PHOTO").count(), 0)

    def test_submit_blocked_with_one_photo_on_failed_field(self):
        """Submit blocked when a failed field has only 1 photo."""
        self.login()
        url = reverse("inspections:inspection_create")
        f_shaft = self.template.fields.get(name="Shaft Diameter")
        post_data, _ = self._base_post(
            "JOB-1-PHOTO",
            shaft_value="25.10",
            extra={f"field_{f_shaft.id}_photo_1": create_test_image("only_one.jpg")},
        )
        resp = self.client.post(url, post_data, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Upload at least 2 photos for")
        self.assertContains(resp, "1 uploaded")
        self.assertEqual(Checklist.objects.filter(job_no="JOB-1-PHOTO").count(), 0)

    def test_submit_allowed_with_two_photos_on_failed_field(self):
        """Submit succeeds when failed field has 2 valid photos."""
        self.login()
        url = reverse("inspections:inspection_create")
        f_shaft = self.template.fields.get(name="Shaft Diameter")
        post_data, _ = self._base_post(
            "JOB-2-PHOTO",
            shaft_value="25.10",  # CTQ fail -> CTQ_FAILED
            extra={
                f"field_{f_shaft.id}_photo_1": create_test_image("d1.jpg"),
                f"field_{f_shaft.id}_photo_2": create_test_image("d2.jpg"),
            },
        )
        resp = self.client.post(url, post_data, follow=True)
        self.assertEqual(resp.status_code, 200)
        cl = Checklist.objects.get(job_no="JOB-2-PHOTO")
        self.assertEqual(cl.status, Checklist.Status.CTQ_FAILED)
        m = cl.measurements.get(field=f_shaft)
        self.assertEqual(m.photos.count(), 2)

    def test_passing_fields_need_no_photos(self):
        """All-pass inspection does not require defect photos."""
        self.login()
        url = reverse("inspections:inspection_create")
        post_data, _ = self._base_post("JOB-ALL-PASS", shaft_value="25.03")
        resp = self.client.post(url, post_data, follow=True)
        self.assertEqual(resp.status_code, 200)
        cl = Checklist.objects.get(job_no="JOB-ALL-PASS")
        self.assertEqual(cl.status, Checklist.Status.PENDING_REVIEW)
        self.assertTrue(cl.is_all_passed)
        for m in cl.measurements.all():
            self.assertEqual(m.photos.count(), 0)

    def test_wrong_file_type_rejected(self):
        """Non image files (e.g. .txt) are rejected server-side."""
        self.login()
        url = reverse("inspections:inspection_create")
        f_shaft = self.template.fields.get(name="Shaft Diameter")
        post_data, _ = self._base_post(
            "JOB-BAD-TYPE",
            shaft_value="25.10",
            extra={
                f"field_{f_shaft.id}_photo_1": create_test_text_file("notes.txt"),
                f"field_{f_shaft.id}_photo_2": create_test_image("ok.jpg"),
            },
        )
        resp = self.client.post(url, post_data, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "invalid")
        self.assertEqual(Checklist.objects.filter(job_no="JOB-BAD-TYPE").count(), 0)

    def test_validate_defect_photo_helpers(self):
        from inspections.forms import validate_defect_photo_file, validate_defect_photos_for_field
        self.assertIsNone(validate_defect_photo_file(create_test_image("a.jpg")))
        err = validate_defect_photo_file(create_test_text_file("x.txt"))
        self.assertIsNotNone(err)
        self.assertIn("invalid", err.lower())
        errs = validate_defect_photos_for_field("Shaft Diameter", False, [])
        self.assertTrue(any("Upload at least 2 photos" in e and "0 uploaded" in e for e in errs))
        errs = validate_defect_photos_for_field("Shaft Diameter", True, [])
        self.assertEqual(errs, [])


class InspectorWorkflowTests(TestCase):
    """Test Inspector page, photos requirement, CTQ failure freeze, and email alert."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)
        cls.part = PartNumber.objects.get(part_no="DS-100")
        cls.template = InspectionTemplate.objects.get(name="Drive Shaft", revision="Rev A")
        cls.machine = Machine.objects.filter(is_active=True).first()
        cls.caliper = Gauge.objects.get(serial_no="CAL-001")
        cls.expired_gauge = Gauge.objects.get(serial_no="MIC-002")

    def login(self, username):
        self.client.login(username=username, password="demo1234")

    def test_submission_blocked_with_expired_gauge(self):
        """Selecting an expired gauge raises ValidationError and shows red alert."""
        self.login("inspector1")
        url = reverse("inspections:inspection_create")

        f_shaft = self.template.fields.get(name="Shaft Diameter")
        f_len = self.template.fields.get(name="Length")
        f_rough = self.template.fields.get(name="Surface Roughness")
        f_burr = self.template.fields.get(name="Free of burrs")

        post_data = {
            "template": self.template.id,
            "machine": self.machine.id,
            "job_no": "JOB-EXP-GAUGE",
            f"field_{f_shaft.id}_value": "25.03",
            f"field_{f_shaft.id}_gauge": self.expired_gauge.id,  # Expired gauge!
            f"field_{f_len.id}_value": "100.00",
            f"field_{f_len.id}_gauge": self.caliper.id,
            f"field_{f_rough.id}_value": "0.5",
            f"field_{f_rough.id}_gauge": self.caliper.id,
            f"field_{f_burr.id}_visual_ok": "yes",
        }
        resp = self.client.post(url, post_data, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Expired Tool Calibration. Obtain a calibrated tool from the tool crib.")
        self.assertEqual(Checklist.objects.filter(job_no="JOB-EXP-GAUGE").count(), 0)

    def test_submission_blocked_if_failed_field_lacks_two_photos(self):
        """If any field is out of tolerance, require at least 2 photos for each failed field."""
        self.login("inspector1")
        url = reverse("inspections:inspection_create")

        f_shaft = self.template.fields.get(name="Shaft Diameter")
        f_len = self.template.fields.get(name="Length")
        f_rough = self.template.fields.get(name="Surface Roughness")
        f_burr = self.template.fields.get(name="Free of burrs")

        # Shaft Diameter 25.10 fails tolerance. Only 1 photo attached!
        post_data = {
            "template": self.template.id,
            "machine": self.machine.id,
            "job_no": "JOB-ONE-PHOTO",
            f"field_{f_shaft.id}_value": "25.10",
            f"field_{f_shaft.id}_gauge": self.caliper.id,
            f"field_{f_len.id}_value": "100.00",
            f"field_{f_len.id}_gauge": self.caliper.id,
            f"field_{f_rough.id}_value": "0.5",
            f"field_{f_rough.id}_gauge": self.caliper.id,
            f"field_{f_burr.id}_visual_ok": "yes",
            f"field_{f_shaft.id}_photo_1": create_test_image("only_one.jpg"),
        }
        resp = self.client.post(url, post_data, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Upload at least 2 photos for")
        self.assertEqual(Checklist.objects.filter(job_no="JOB-ONE-PHOTO").count(), 0)

    def test_ctq_failure_sets_ctq_failed_frozen_and_sends_email(self):
        """If a CTQ field fails, set checklist status CTQ_FAILED (frozen) and send an alert email to the Quality Head."""
        mail.outbox.clear()
        self.login("inspector1")
        url = reverse("inspections:inspection_create")

        f_shaft = self.template.fields.get(name="Shaft Diameter")  # CTQ!
        f_len = self.template.fields.get(name="Length")
        f_rough = self.template.fields.get(name="Surface Roughness")
        f_burr = self.template.fields.get(name="Free of burrs")

        # Shaft Diameter 25.10 fails. Provide 2 required defect photos.
        post_data = {
            "template": self.template.id,
            "machine": self.machine.id,
            "job_no": "JOB-CTQ-FAIL",
            f"field_{f_shaft.id}_value": "25.10",
            f"field_{f_shaft.id}_gauge": self.caliper.id,
            f"field_{f_len.id}_value": "100.00",
            f"field_{f_len.id}_gauge": self.caliper.id,
            f"field_{f_rough.id}_value": "0.5",
            f"field_{f_rough.id}_gauge": self.caliper.id,
            f"field_{f_burr.id}_visual_ok": "yes",
            f"field_{f_shaft.id}_photo_1": create_test_image("shaft_defect1.jpg"),
            f"field_{f_shaft.id}_photo_2": create_test_image("shaft_defect2.jpg"),
        }
        resp = self.client.post(url, post_data, follow=True)
        self.assertEqual(resp.status_code, 200)

        checklist = Checklist.objects.get(job_no="JOB-CTQ-FAIL")
        self.assertEqual(checklist.status, Checklist.Status.CTQ_FAILED)
        self.assertTrue(checklist.is_frozen)

        # 2 defect photos attached
        m_shaft = checklist.measurements.get(field=f_shaft)
        self.assertEqual(m_shaft.photos.count(), 2)

        # Email sent to Quality Head
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn("CTQ Inspection Failure", email.subject)
        self.assertIn("Shaft Diameter", email.body)
        self.assertIn("JOB-CTQ-FAIL", email.body)
        self.assertIn("qualityhead@factoryqc.local", email.to)

    def test_passing_inspection_sets_status_pending_review(self):
        """Otherwise, on submit set status PENDING_REVIEW."""
        mail.outbox.clear()
        self.login("inspector1")
        url = reverse("inspections:inspection_create")

        f_shaft = self.template.fields.get(name="Shaft Diameter")
        f_len = self.template.fields.get(name="Length")
        f_rough = self.template.fields.get(name="Surface Roughness")
        f_burr = self.template.fields.get(name="Free of burrs")

        post_data = {
            "template": self.template.id,
            "machine": self.machine.id,
            "job_no": "JOB-ALL-PASS",
            f"field_{f_shaft.id}_value": "25.03",
            f"field_{f_shaft.id}_gauge": self.caliper.id,
            f"field_{f_len.id}_value": "100.05",
            f"field_{f_len.id}_gauge": self.caliper.id,
            f"field_{f_rough.id}_value": "0.6",
            f"field_{f_rough.id}_gauge": self.caliper.id,
            f"field_{f_burr.id}_visual_ok": "yes",
        }
        resp = self.client.post(url, post_data, follow=True)
        self.assertEqual(resp.status_code, 200)

        checklist = Checklist.objects.get(job_no="JOB-ALL-PASS")
        self.assertEqual(checklist.status, Checklist.Status.PENDING_REVIEW)
        self.assertFalse(checklist.is_frozen)
        # No CTQ email sent
        self.assertEqual(len(mail.outbox), 0)

    def test_non_ctq_failure_sets_pending_review_with_photos(self):
        """Non-CTQ failure requires 2 photos and sets status PENDING_REVIEW."""
        mail.outbox.clear()
        self.login("inspector1")
        url = reverse("inspections:inspection_create")

        f_shaft = self.template.fields.get(name="Shaft Diameter")  # 25.03 Passes
        f_len = self.template.fields.get(name="Length")  # 100.00 Passes
        f_rough = self.template.fields.get(name="Surface Roughness")  # 1.2 FAILS (non-CTQ)
        f_burr = self.template.fields.get(name="Free of burrs")

        post_data = {
            "template": self.template.id,
            "machine": self.machine.id,
            "job_no": "JOB-NON-CTQ-FAIL",
            f"field_{f_shaft.id}_value": "25.03",
            f"field_{f_shaft.id}_gauge": self.caliper.id,
            f"field_{f_len.id}_value": "100.00",
            f"field_{f_len.id}_gauge": self.caliper.id,
            f"field_{f_rough.id}_value": "1.2",  # Fails!
            f"field_{f_rough.id}_gauge": self.caliper.id,
            f"field_{f_burr.id}_visual_ok": "yes",
            f"field_{f_rough.id}_photo_1": create_test_image("rough1.jpg"),
            f"field_{f_rough.id}_photo_2": create_test_image("rough2.jpg"),
        }
        resp = self.client.post(url, post_data, follow=True)
        self.assertEqual(resp.status_code, 200)

        checklist = Checklist.objects.get(job_no="JOB-NON-CTQ-FAIL")
        self.assertEqual(checklist.status, Checklist.Status.PENDING_REVIEW)
        self.assertFalse(checklist.is_frozen)
        # CTQ passed, so no email sent
        self.assertEqual(len(mail.outbox), 0)
        # 2 photos attached to rough measurement
        m_rough = checklist.measurements.get(field=f_rough)
        self.assertEqual(m_rough.photos.count(), 2)

    def test_after_submit_checklist_is_readonly(self):
        """After submit, the checklist is read-only for the inspector."""
        checklist = Checklist.objects.create(
            template=self.template,
            machine=self.machine,
            job_no="JOB-READONLY-01",
            inspector=User.objects.get(username="inspector1"),
            status=Checklist.Status.PENDING_REVIEW,
        )
        self.login("inspector1")
        resp = self.client.get(reverse("inspections:checklist_detail", kwargs={"pk": checklist.pk}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Read-Only")


class QualityEngineerWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)
        cls.part = PartNumber.objects.get(part_no="DS-100")

    def login(self, username):
        self.client.login(username=username, password="demo1234")

    def test_access_permissions(self):
        url = reverse("inspections:template_list")
        self.assertEqual(self.client.get(url).status_code, 302)

        self.login("inspector1")
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.get(reverse("inspections:template_create")).status_code, 403)
        self.client.logout()

        for user in ("engineer1", "admin"):
            self.login(user)
            self.assertEqual(self.client.get(url).status_code, 200)
            self.assertEqual(self.client.get(reverse("inspections:template_create")).status_code, 200)
            self.client.logout()

    def test_create_draft_template_and_approve(self):
        self.login("engineer1")
        data = {
            "name": "Bushing Inspection",
            "part": self.part.id,
            "revision": "Rev B",
            "is_active": "on",
            "fields-TOTAL_FORMS": "1",
            "fields-INITIAL_FORMS": "0",
            "fields-MIN_NUM_FORMS": "0",
            "fields-MAX_NUM_FORMS": "1000",
            "fields-0-order": "1",
            "fields-0-name": "Inner Diameter",
            "fields-0-field_type": "DIMENSION",
            "fields-0-nominal": "12.000",
            "fields-0-upper_tol": "0.020",
            "fields-0-lower_tol": "-0.010",
            "fields-0-max_value": "",
            "fields-0-unit": "mm",
            "fields-0-is_ctq": "on",
        }
        resp = self.client.post(reverse("inspections:template_create"), data, follow=True)
        self.assertEqual(resp.status_code, 200)

        template = InspectionTemplate.objects.get(name="Bushing Inspection", revision="Rev B")
        self.assertEqual(template.status, InspectionTemplate.Status.DRAFT)
        self.assertEqual(template.fields.count(), 1)
        self.assertTrue(template.fields.first().is_ctq)

        approve_url = reverse("inspections:template_approve", kwargs={"pk": template.pk})
        resp = self.client.post(approve_url, follow=True)
        self.assertEqual(resp.status_code, 200)
        template.refresh_from_db()
        self.assertEqual(template.status, InspectionTemplate.Status.APPROVED)

        edit_url = reverse("inspections:template_edit", kwargs={"pk": template.pk})
        resp = self.client.get(edit_url, follow=True)
        self.assertContains(resp, "Approved templates cannot be edited.")


class SeedDemoVerificationTests(TestCase):
    def test_seed_demo_creates_drive_shaft_template(self):
        call_command("seed_demo", verbosity=0)
        template = InspectionTemplate.objects.filter(name="Drive Shaft", revision="Rev A").first()
        self.assertIsNotNone(template)
        self.assertEqual(template.status, InspectionTemplate.Status.APPROVED)
        self.assertEqual(template.part.part_no, "DS-100")

        fields = template.fields.all().order_by("order")
        self.assertEqual(fields.count(), 4)

        f1 = fields[0]
        self.assertEqual(f1.name, "Shaft Diameter")
        self.assertTrue(f1.is_ctq)
        self.assertEqual(f1.field_type, TemplateField.FieldType.DIMENSION)
        self.assertEqual(f1.nominal, Decimal("25.000"))
        self.assertEqual(f1.upper_tol, Decimal("0.050"))
        self.assertEqual(f1.lower_tol, Decimal("-0.020"))
        self.assertEqual(f1.unit, "mm")

        f2 = fields[1]
        self.assertEqual(f2.name, "Length")
        self.assertFalse(f2.is_ctq)
        self.assertEqual(f2.field_type, TemplateField.FieldType.DIMENSION)
        self.assertEqual(f2.nominal, Decimal("100.000"))
        self.assertEqual(f2.upper_tol, Decimal("0.100"))
        self.assertEqual(f2.lower_tol, Decimal("-0.100"))

        f3 = fields[2]
        self.assertEqual(f3.name, "Surface Roughness")
        self.assertEqual(f3.field_type, TemplateField.FieldType.MAX_THRESHOLD)
        self.assertEqual(f3.max_value, Decimal("0.800"))

        f4 = fields[3]
        self.assertEqual(f4.name, "Free of burrs")
        self.assertEqual(f4.field_type, TemplateField.FieldType.VISUAL)


# ---------------------------------------------------------------------------
# Fixes suite: gauge required, decimals, access, admin immutability, photos,
# transition locking
# ---------------------------------------------------------------------------
from django.contrib.admin.sites import AdminSite
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import RequestFactory

from inspections.admin import ChecklistAdmin, DefectPhotoAdmin, MeasurementAdmin, TemplateFieldAdmin
from inspections.forms import validate_defect_photo_file


class GaugeMandatoryTests(TestCase):
    """DIMENSION / MAX_THRESHOLD require a gauge; VISUAL does not."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)
        cls.template = InspectionTemplate.objects.get(name="Drive Shaft", revision="Rev A")
        cls.machine = Machine.objects.filter(is_active=True).first()
        cls.caliper = Gauge.objects.get(serial_no="CAL-001")
        cls.inspector = User.objects.get(username="inspector1")

    def login(self):
        self.client.login(username="inspector1", password="demo1234")

    def test_submit_blocked_without_gauge_on_dimension(self):
        self.login()
        f_shaft = self.template.fields.get(name="Shaft Diameter")
        f_len = self.template.fields.get(name="Length")
        f_rough = self.template.fields.get(name="Surface Roughness")
        f_burr = self.template.fields.get(name="Free of burrs")
        post = {
            "template": self.template.id,
            "machine": self.machine.id,
            "job_no": "JOB-NO-GAUGE",
            f"field_{f_shaft.id}_value": "25.03",
            # no gauge for shaft
            f"field_{f_len.id}_value": "100.00",
            f"field_{f_len.id}_gauge": self.caliper.id,
            f"field_{f_rough.id}_value": "0.5",
            f"field_{f_rough.id}_gauge": self.caliper.id,
            f"field_{f_burr.id}_visual_ok": "yes",
        }
        resp = self.client.post(reverse("inspections:inspection_create"), post, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Select the gauge used for")
        self.assertContains(resp, "Shaft Diameter")
        self.assertEqual(Checklist.objects.filter(job_no="JOB-NO-GAUGE").count(), 0)

    def test_measurement_clean_requires_gauge_for_dimension(self):
        cl = Checklist.objects.create(
            template=self.template,
            machine=self.machine,
            job_no="JOB-MCLEAN",
            inspector=self.inspector,
        )
        m = Measurement(
            checklist=cl,
            field=self.template.fields.get(name="Shaft Diameter"),
            value=Decimal("25.00"),
            gauge=None,
        )
        with self.assertRaises(ValidationError) as ctx:
            m.clean()
        self.assertIn("Select the gauge used for", str(ctx.exception))


class DecimalPlacesValidationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)
        cls.template = InspectionTemplate.objects.get(name="Drive Shaft", revision="Rev A")
        cls.machine = Machine.objects.filter(is_active=True).first()
        cls.caliper = Gauge.objects.get(serial_no="CAL-001")

    def test_too_many_decimal_places_blocked(self):
        self.client.login(username="inspector1", password="demo1234")
        f_shaft = self.template.fields.get(name="Shaft Diameter")
        f_len = self.template.fields.get(name="Length")
        f_rough = self.template.fields.get(name="Surface Roughness")
        f_burr = self.template.fields.get(name="Free of burrs")
        post = {
            "template": self.template.id,
            "machine": self.machine.id,
            "job_no": "JOB-DECIMALS",
            f"field_{f_shaft.id}_value": "25.1234",  # 4 decimal places
            f"field_{f_shaft.id}_gauge": self.caliper.id,
            f"field_{f_len.id}_value": "100.00",
            f"field_{f_len.id}_gauge": self.caliper.id,
            f"field_{f_rough.id}_value": "0.5",
            f"field_{f_rough.id}_gauge": self.caliper.id,
            f"field_{f_burr.id}_visual_ok": "yes",
        }
        resp = self.client.post(reverse("inspections:inspection_create"), post, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Enter at most 3 decimal places for")
        self.assertContains(resp, "Shaft Diameter")
        self.assertEqual(Checklist.objects.filter(job_no="JOB-DECIMALS").count(), 0)


class InspectionAccessControlTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)
        cls.template = InspectionTemplate.objects.get(name="Drive Shaft", revision="Rev A")
        cls.machine = Machine.objects.filter(is_active=True).first()
        cls.inspector = User.objects.get(username="inspector1")
        cls.other = User.objects.create_user("inspector2", password="demo1234")
        from django.contrib.auth.models import Group
        Group.objects.get(name="Inspector").user_set.add(cls.other)
        cls.checklist = Checklist.objects.create(
            template=cls.template,
            machine=cls.machine,
            job_no="JOB-OWN",
            inspector=cls.inspector,
            status=Checklist.Status.PENDING_REVIEW,
            submitted_at=timezone.now(),
        )

    def test_engineer_cannot_open_inspection_create(self):
        self.client.login(username="engineer1", password="demo1234")
        resp = self.client.get(reverse("inspections:inspection_create"))
        self.assertEqual(resp.status_code, 403)

    def test_inspector_can_open_inspection_create(self):
        self.client.login(username="inspector1", password="demo1234")
        resp = self.client.get(reverse("inspections:inspection_create"))
        self.assertEqual(resp.status_code, 200)

    def test_inspector_cannot_view_others_checklist(self):
        self.client.login(username="inspector2", password="demo1234")
        resp = self.client.get(reverse("inspections:checklist_detail", kwargs={"pk": self.checklist.pk}))
        self.assertIn(resp.status_code, (403, 404))

    def test_inspector_can_view_own_checklist(self):
        self.client.login(username="inspector1", password="demo1234")
        resp = self.client.get(reverse("inspections:checklist_detail", kwargs={"pk": self.checklist.pk}))
        self.assertEqual(resp.status_code, 200)

    def test_supervisor_can_view_any_checklist(self):
        self.client.login(username="supervisor1", password="demo1234")
        resp = self.client.get(reverse("inspections:checklist_detail", kwargs={"pk": self.checklist.pk}))
        self.assertEqual(resp.status_code, 200)


class SubmittedAdminImmutabilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)
        cls.template = InspectionTemplate.objects.get(name="Drive Shaft", revision="Rev A")
        cls.machine = Machine.objects.filter(is_active=True).first()
        cls.inspector = User.objects.get(username="inspector1")
        cls.checklist = Checklist.objects.create(
            template=cls.template,
            machine=cls.machine,
            job_no="JOB-ADMIN-RO",
            inspector=cls.inspector,
            status=Checklist.Status.PENDING_REVIEW,
            submitted_at=timezone.now(),
        )
        cls.measurement = Measurement.objects.create(
            checklist=cls.checklist,
            field=cls.template.fields.first(),
            value=Decimal("25.00"),
            gauge=Gauge.objects.get(serial_no="CAL-001"),
            is_within_tolerance=True,
        )

    def setUp(self):
        self.site = AdminSite()
        self.superuser = User.objects.create_superuser("su_admin", "su@x.com", "pass")
        self.req = RequestFactory().get("/admin/")
        self.req.user = self.superuser

    def test_checklist_admin_no_change_delete_when_submitted(self):
        admin = ChecklistAdmin(Checklist, self.site)
        self.assertFalse(admin.has_change_permission(self.req, self.checklist))
        self.assertFalse(admin.has_delete_permission(self.req, self.checklist))
        self.assertFalse(admin.has_add_permission(self.req))
        self.assertNotIn("delete_selected", admin.get_actions(self.req))

    def test_measurement_admin_no_change_delete_when_submitted(self):
        admin = MeasurementAdmin(Measurement, self.site)
        self.assertFalse(admin.has_change_permission(self.req, self.measurement))
        self.assertFalse(admin.has_delete_permission(self.req, self.measurement))
        self.assertFalse(admin.has_add_permission(self.req))

    def test_template_field_admin_readonly_when_approved(self):
        field = self.template.fields.first()
        admin = TemplateFieldAdmin(TemplateField, self.site)
        self.assertFalse(admin.has_change_permission(self.req, field))
        self.assertFalse(admin.has_delete_permission(self.req, field))


class PillowPhotoValidationTests(TestCase):
    def test_fake_image_extension_rejected(self):
        # Bytes that are not a real image but have a .jpg name
        fake = SimpleUploadedFile("fake.jpg", b"not-an-image-at-all", content_type="image/jpeg")
        err = validate_defect_photo_file(fake)
        self.assertIsNotNone(err)
        self.assertIn("not a valid image", err.lower())

    def test_real_jpeg_accepted(self):
        err = validate_defect_photo_file(create_test_image("real.jpg"))
        self.assertIsNone(err)


class TransitionAtomicTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)
        cls.template = InspectionTemplate.objects.get(name="Drive Shaft", revision="Rev A")
        cls.machine = Machine.objects.filter(is_active=True).first()
        cls.inspector = User.objects.get(username="inspector1")
        cls.supervisor = User.objects.get(username="supervisor1")

    def test_transition_uses_current_status_and_logs(self):
        from approvals.models import ApprovalLog
        cl = Checklist.objects.create(
            template=self.template,
            machine=self.machine,
            job_no="JOB-TX",
            inspector=self.inspector,
            status=Checklist.Status.PENDING_REVIEW,
            submitted_at=timezone.now(),
        )
        Measurement.objects.create(
            checklist=cl,
            field=self.template.fields.first(),
            value=Decimal("25.00"),
            gauge=Gauge.objects.get(serial_no="CAL-001"),
            is_within_tolerance=True,
        )
        cl.transition(Checklist.Status.APPROVED, self.supervisor)
        cl.refresh_from_db()
        self.assertEqual(cl.status, Checklist.Status.APPROVED)
        self.assertEqual(ApprovalLog.objects.filter(checklist=cl).count(), 1)

    def test_invalid_transition_after_status_change_raises(self):
        cl = Checklist.objects.create(
            template=self.template,
            machine=self.machine,
            job_no="JOB-TX2",
            inspector=self.inspector,
            status=Checklist.Status.APPROVED,
            submitted_at=timezone.now(),
        )
        with self.assertRaises(ValueError):
            cl.transition(Checklist.Status.QUARANTINED, self.supervisor)
