from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse


class RoleAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)

    def login(self, username):
        self.client.login(username=username, password="demo1234")

    def test_groups_created_by_migration(self):
        self.assertEqual(Group.objects.filter(
            name__in=["Quality Engineer", "Inspector", "Supervisor"]).count(), 3)

    def test_post_login_redirect_by_role(self):
        expected = {
            "engineer1": "accounts:engineer_dashboard",
            "inspector1": "accounts:inspector_dashboard",
            "supervisor1": "accounts:supervisor_dashboard",
            "admin": "accounts:plant_manager_dashboard",
        }
        for username, url_name in expected.items():
            resp = self.client.post(reverse("accounts:login"),
                                    {"username": username, "password": "demo1234"}, follow=True)
            self.assertEqual(resp.redirect_chain[-1][0], reverse(url_name), username)
            self.client.post(reverse("accounts:logout"))

    def test_master_data_access(self):
        url = reverse("core:machine_list")
        self.assertEqual(self.client.get(url).status_code, 302)  # anonymous -> login
        for username, status in [("engineer1", 200), ("admin", 200),
                                 ("inspector1", 403), ("supervisor1", 403)]:
            self.login(username)
            for name in ("core:machine_list", "core:part_create", "core:gauge_list"):
                self.assertEqual(self.client.get(reverse(name)).status_code, status, (username, name))
            self.client.logout()

    def test_dashboard_only_for_own_role(self):
        self.login("inspector1")
        self.assertEqual(self.client.get(reverse("accounts:inspector_dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("accounts:engineer_dashboard")).status_code, 403)

    def test_navbar_is_role_based(self):
        self.login("inspector1")
        html = self.client.get(reverse("accounts:inspector_dashboard")).content.decode()
        self.assertNotIn(reverse("core:machine_list"), html)
        self.client.logout()
        self.login("engineer1")
        html = self.client.get(reverse("accounts:engineer_dashboard")).content.decode()
        self.assertIn(reverse("core:machine_list"), html)

    def test_seed_is_repeatable(self):
        call_command("seed_demo", verbosity=0)
        self.assertEqual(User.objects.filter(username__in=["engineer1", "admin"]).count(), 2)


class InspectorDashboardCountTests(TestCase):
    """Each inspector must only see their own checklist count on the dashboard."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)
        from django.contrib.auth.models import Group
        from inspections.models import Checklist, InspectionTemplate
        from core.models import Machine

        cls.inspector1 = User.objects.get(username="inspector1")
        cls.inspector2 = User.objects.create_user("inspector2", password="demo1234")
        Group.objects.get(name="Inspector").user_set.add(cls.inspector2)

        template = InspectionTemplate.objects.get(name="Drive Shaft", revision="Rev A")
        machine = Machine.objects.filter(is_active=True).first()

        # inspector1: 2 checklists, inspector2: 1 checklist
        Checklist.objects.create(
            template=template, machine=machine, job_no="JOB-I1-A",
            inspector=cls.inspector1, status="PENDING_REVIEW",
        )
        Checklist.objects.create(
            template=template, machine=machine, job_no="JOB-I1-B",
            inspector=cls.inspector1, status="PENDING_REVIEW",
        )
        Checklist.objects.create(
            template=template, machine=machine, job_no="JOB-I2-A",
            inspector=cls.inspector2, status="PENDING_REVIEW",
        )

    def test_inspector1_sees_only_own_count(self):
        self.client.login(username="inspector1", password="demo1234")
        resp = self.client.get(reverse("accounts:inspector_dashboard"))
        self.assertEqual(resp.status_code, 200)
        cards = {c["label"]: c["value"] for c in resp.context["cards"]}
        self.assertEqual(cards["My Checklists"], 2)

    def test_inspector2_sees_only_own_count(self):
        self.client.login(username="inspector2", password="demo1234")
        resp = self.client.get(reverse("accounts:inspector_dashboard"))
        self.assertEqual(resp.status_code, 200)
        cards = {c["label"]: c["value"] for c in resp.context["cards"]}
        self.assertEqual(cards["My Checklists"], 1)
