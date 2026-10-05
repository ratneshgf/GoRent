from django.core.files.base import ContentFile
from django.test import TestCase
from django.test import override_settings

from .models import PrivateDocument, User, Vehicle
from .private_storage import DatabasePrivateStorage


class PrivateStorageTests(TestCase):
    def test_private_file_survives_storage_instance_and_has_no_public_url(self):
        storage = DatabasePrivateStorage()
        name = storage.save("ids/test.pdf", ContentFile(b"%PDF-1.4 test"))
        self.assertEqual(PrivateDocument.objects.count(), 1)
        self.assertEqual(DatabasePrivateStorage().open(name).read(), b"%PDF-1.4 test")
        self.assertEqual(storage.size(name), len(b"%PDF-1.4 test"))
        with self.assertRaises(ValueError):
            storage.url(name)
        storage.delete(name)
        self.assertFalse(storage.exists(name))


class ProductionListingGateTests(TestCase):
    @override_settings(OWNER_ID_LOCAL_DEMO=False)
    def test_demo_checked_owner_car_is_not_public_in_production(self):
        owner = User.objects.create_user(
            username="demo-owner@example.com", email="demo-owner@example.com",
            password="example-password", role="owner", identity_status="demo_checked",
        )
        Vehicle.objects.create(
            owner=owner, brand="Tata", name="Punch", category="SUV", fuel="Petrol",
            transmission="Manual", seats=5, year=2024, price_per_day=2000,
            city="Gwalior", status="published",
        )
        self.assertEqual(self.client.get("/api/vehicles").json(), [])
