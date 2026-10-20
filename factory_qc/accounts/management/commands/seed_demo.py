from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Factory, Gauge, Machine, PartNumber
from inspections.models import InspectionTemplate, TemplateField

DEMO_PASSWORD = "demo1234"


class Command(BaseCommand):
    help = "Create demo data (safe to run repeatedly)."

    def handle(self, *args, **options):
        today = timezone.localdate()

        factory, _ = Factory.objects.get_or_create(name="Pune Plant", defaults={"location": "Pune"})
        for name in ("CNC Lathe 1", "Grinder 1"):
            Machine.objects.get_or_create(name=name, factory=factory, defaults={"is_active": True})
        part, _ = PartNumber.objects.get_or_create(part_no="DS-100", defaults={"description": "Drive Shaft"})

        # One valid, one expired, one expiring in 5 days.
        gauges = [
            ("CAL-001", Gauge.GaugeType.CALIPER, today + timedelta(days=180)),
            ("MIC-002", Gauge.GaugeType.MICROMETER, today - timedelta(days=10)),
            ("PLG-003", Gauge.GaugeType.PLUG_GAUGE, today + timedelta(days=5)),
        ]
        for serial, gtype, expiry in gauges:
            Gauge.objects.update_or_create(
                serial_no=serial, defaults={"gauge_type": gtype, "calibration_expiry": expiry}
            )

        # Rev A "Drive Shaft" template
        template = InspectionTemplate.objects.filter(name="Drive Shaft", part=part, revision="Rev A").first()
        if not template:
            template = InspectionTemplate.objects.create(
                name="Drive Shaft",
                part=part,
                revision="Rev A",
                status=InspectionTemplate.Status.DRAFT,
                is_active=True,
            )

        fields_data = [
            {
                "order": 1,
                "name": "Shaft Diameter",
                "field_type": TemplateField.FieldType.DIMENSION,
                "nominal": Decimal("25.000"),
                "upper_tol": Decimal("0.050"),
                "lower_tol": Decimal("-0.020"),
                "unit": "mm",
                "is_ctq": True,
            },
            {
                "order": 2,
                "name": "Length",
                "field_type": TemplateField.FieldType.DIMENSION,
                "nominal": Decimal("100.000"),
                "upper_tol": Decimal("0.100"),
                "lower_tol": Decimal("-0.100"),
                "unit": "mm",
                "is_ctq": False,
            },
            {
                "order": 3,
                "name": "Surface Roughness",
                "field_type": TemplateField.FieldType.MAX_THRESHOLD,
                "max_value": Decimal("0.800"),
                "unit": "µm",
                "is_ctq": False,
            },
            {
                "order": 4,
                "name": "Free of burrs",
                "field_type": TemplateField.FieldType.VISUAL,
                "is_ctq": False,
            },
        ]

        # Only add fields if not already populated
        if not template.fields.exists():
            for fdata in fields_data:
                TemplateField.objects.create(template=template, **fdata)

        if template.status != InspectionTemplate.Status.APPROVED:
            template.status = InspectionTemplate.Status.APPROVED
            template.save()

        # (username, group or None, is_superuser)
        users = [
            ("engineer1", "Quality Engineer", False),
            ("inspector1", "Inspector", False),
            ("supervisor1", "Supervisor", False),
            ("admin", None, True),  # superuser = Plant Manager
        ]
        for username, group_name, is_super in users:
            user, _ = User.objects.get_or_create(username=username)
            user.set_password(DEMO_PASSWORD)
            user.is_superuser = is_super
            user.is_staff = is_super  # staff so admin can use /admin/
            user.save()
            if group_name:
                user.groups.set([Group.objects.get(name=group_name)])

        self.stdout.write(
            self.style.SUCCESS(
                f"Demo data ready. Users: engineer1, inspector1, supervisor1, admin (password {DEMO_PASSWORD})."
            )
        )
