from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from core.models import Factory


class FactoryMasterDataTests(TestCase):
    """Factories list/create are Quality Engineer / Admin only."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)

    def test_engineer_can_add_factory(self):
        self.client.login(username="engineer1", password="demo1234")
        resp = self.client.get(reverse("core:factory_list"))
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post(
            reverse("core:factory_create"),
            {"name": "North Plant", "location": "Pune"},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Factory.objects.filter(name="North Plant", location="Pune").exists())

    def test_inspector_gets_403_on_factory_pages(self):
        self.client.login(username="inspector1", password="demo1234")
        for name in ("core:factory_list", "core:factory_create"):
            resp = self.client.get(reverse(name))
            self.assertEqual(resp.status_code, 403, name)
