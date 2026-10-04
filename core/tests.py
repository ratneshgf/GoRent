from datetime import timedelta
from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient
from .models import Booking, User, Vehicle
from .serializers import BookingSer


@override_settings(SECURE_SSL_REDIRECT=False, DEBUG=True, OWNER_ID_LOCAL_DEMO=True)
class MarketplaceFlowTests(TestCase):
    def setUp(self):
        media = TemporaryDirectory()
        self.addCleanup(media.cleanup)
        settings_override = override_settings(MEDIA_ROOT=media.name)
        settings_override.enable()
        self.addCleanup(settings_override.disable)
        self.client = APIClient()
        self.admin = User.objects.create_superuser(username="admin@test.in", email="admin@test.in", password="password123", role="admin")

    def login(self, email, password="password123"):
        response = self.client.post("/api/auth/login", {"username": email, "password": password})
        self.assertEqual(response.status_code, 200, response.data)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {response.data['token']}")

    def test_direct_listing_request_and_pickup_route(self):
        owner = self.client.post("/api/auth/register", {"email":"owner@test.in", "password":"password123", "first_name":"Owner", "role":"owner"})
        self.assertEqual(owner.status_code, 201, owner.data)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {owner.data['token']}")
        details = {"brand":"Tata", "name":"Punch", "category":"SUV", "fuel":"Petrol", "transmission":"Manual", "seats":5, "year":2024, "price_per_day":1600, "city":"Gwalior"}
        self.assertEqual(self.client.post("/api/vehicles", details).status_code, 403)
        checked = self.client.post("/api/owner/identity", {"document_type":"pan", "document":SimpleUploadedFile("pan.pdf", b"%PDF-1.4 local test", content_type="application/pdf"), "consent":"true"}, format="multipart")
        self.assertEqual(checked.status_code, 200, checked.data)
        self.assertEqual(checked.data["identity_status"], "demo_checked")
        self.assertTrue(checked.data["identity_can_list"])
        self.assertNotIn("kyc_document", checked.data)
        car = self.client.post("/api/vehicles", {"brand":"Tata", "name":"Punch", "category":"SUV", "fuel":"Petrol", "transmission":"Manual", "seats":5, "year":2024, "price_per_day":1600, "city":"Gwalior"})
        self.assertEqual(car.status_code, 201, car.data)
        self.assertEqual(car.data["status"], "published")
        car_id = car.data["id"]
        self.assertEqual(len(self.client.get("/api/vehicles").data), 1)
        self.assertEqual(len(self.client.get("/api/vehicles/mine").data), 1)
        self.assertEqual(self.client.get("/api/admin/queue").status_code, 404)

        renter = self.client.post("/api/auth/register", {"email":"renter@test.in", "password":"password123", "first_name":"Renter", "role":"customer"})
        self.assertEqual(renter.status_code, 201, renter.data)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {renter.data['token']}")
        start = timezone.localdate() + timedelta(days=2)
        end = start + timedelta(days=2)
        self.assertEqual(self.client.post("/api/bookings", {"vehicle":car_id, "start":start.isoformat(), "end":end.isoformat()}).status_code, 400)
        booking = self.client.post("/api/bookings", {"vehicle":car_id, "start":start.isoformat(), "end":end.isoformat(), "id_type":"student_id", "id_document":SimpleUploadedFile("student.pdf", b"%PDF-1.4 student ID", content_type="application/pdf"), "consent":"true"}, format="multipart")
        self.assertEqual(booking.status_code, 201, booking.data)
        self.assertTrue(booking.data["identity_submitted"])
        self.assertEqual(booking.data["id_type"], "student_id")
        self.assertEqual(booking.data["amount"], 3200)
        self.assertEqual(booking.data["status"], "requested")
        self.assertEqual(booking.data["vehicle_name"], "Tata Punch")
        self.assertTrue(booking.data["created_at"])
        self.assertFalse(booking.data["pickup_route_url"])
        self.assertEqual(self.client.get(f"/api/bookings/{booking.data['id']}/document").status_code, 403)

        self.login("owner@test.in")
        self.assertEqual(len(self.client.get("/api/bookings").data), 1)
        identity = self.client.get(f"/api/bookings/{booking.data['id']}/document")
        self.assertEqual(identity.status_code, 200)
        identity.close()
        url = f"/api/bookings/{booking.data['id']}/transition"
        self.assertEqual(self.client.post(url, {"status":"confirmed"}).status_code, 400)
        accepted = self.client.post(url, {"status":"confirmed", "pickup_address":"Gole Ka Mandir, Gwalior", "pickup_lat":"26.256000", "pickup_lng":"78.181000"})
        self.assertEqual(accepted.status_code, 200, accepted.data)
        self.assertEqual(accepted.data["status"], "confirmed")
        self.assertIn("google.com/maps/dir/", accepted.data["pickup_route_url"])
        self.assertEqual(Vehicle.objects.get(pk=car_id).status, "unlisted")
        self.assertEqual(len(self.client.get("/api/vehicles").data), 1)  # owner can manage hidden cars
        self.assertEqual(self.client.post(f"/api/vehicles/{car_id}/relist").status_code, 400)
        self.login("renter@test.in")
        trip = self.client.get(f"/api/bookings/{booking.data['id']}").data
        self.assertEqual(trip["pickup_address"], "Gole Ka Mandir, Gwalior")
        self.assertIn("26.256000", trip["pickup_route_url"])
        self.assertEqual(len(self.client.get("/api/vehicles").data), 0)
        self.assertEqual(self.client.post(f"/api/vehicles/{car_id}/relist").status_code, 403)
        self.login("owner@test.in")
        active = self.client.post(url, {"status":"active"})
        self.assertEqual(active.status_code, 200)
        self.assertEqual(active.data["payment_status"], "unpaid")
        self.assertEqual(self.client.get(f"/api/bookings/{booking.data['id']}/receipt").status_code, 400)
        self.assertEqual(self.client.post(url, {"status":"returned"}).status_code, 400)
        self.assertEqual(self.client.post(f"/api/bookings/{booking.data['id']}/payment", {"action":"confirm_received"}).status_code, 400)
        self.assertEqual(self.client.post(f"/api/bookings/{booking.data['id']}/payment", {"action":"mark_paid"}).status_code, 403)
        self.login("renter@test.in")
        self.assertEqual(self.client.post(f"/api/bookings/{booking.data['id']}/payment", {"action":"confirm_received"}).status_code, 403)
        marked = self.client.post(f"/api/bookings/{booking.data['id']}/payment", {"action":"mark_paid"})
        self.assertEqual(marked.status_code, 200, marked.data)
        self.assertEqual(marked.data["payment_status"], "renter_marked_paid")
        self.assertEqual(self.client.post(f"/api/bookings/{booking.data['id']}/payment", {"action":"mark_paid"}).status_code, 400)
        self.assertEqual(self.client.get(f"/api/bookings/{booking.data['id']}/receipt").status_code, 400)
        self.login("owner@test.in")
        paid = self.client.post(f"/api/bookings/{booking.data['id']}/payment", {"action":"confirm_received"})
        self.assertEqual(paid.status_code, 200, paid.data)
        self.assertEqual(paid.data["payment_status"], "paid_at_handover")
        receipt = self.client.get(f"/api/bookings/{booking.data['id']}/receipt")
        self.assertEqual(receipt.status_code, 200, receipt.data)
        self.assertEqual(receipt.data["rental_amount"], 3200)
        self.assertEqual(receipt.data["payment_method"], "cash_at_handover")
        self.assertEqual(receipt.data["vehicle_name"], "Tata Punch")
        self.client.patch(f"/api/vehicles/{car_id}", {"name":"Updated name"})
        self.assertEqual(self.client.get(f"/api/bookings/{booking.data['id']}/receipt").data["vehicle_name"], "Tata Punch")
        self.login("admin@test.in")
        self.assertEqual(self.client.get(f"/api/bookings/{booking.data['id']}/receipt").status_code, 404)
        self.login("owner@test.in")
        for next_status in ("returned", "completed"):
            self.assertEqual(self.client.post(url, {"status":next_status}).status_code, 200)
        self.assertEqual(Vehicle.objects.get(pk=car_id).status, "unlisted")
        relisted = self.client.post(f"/api/vehicles/{car_id}/relist")
        self.assertEqual(relisted.status_code, 200, relisted.data)
        self.assertEqual(relisted.data["status"], "published")
        self.assertEqual(len(self.client.get("/api/vehicles").data), 1)

    def test_confirmed_booking_cancellation_requires_reason_before_pickup(self):
        owner = User.objects.create_user(username="cancelowner@test.in", email="cancelowner@test.in", password="password123", role="owner")
        renter = User.objects.create_user(username="cancelrenter@test.in", email="cancelrenter@test.in", password="password123", role="customer")
        car = Vehicle.objects.create(owner=owner, brand="Tata", name="Punch", category="SUV", fuel="Petrol", transmission="Manual", seats=5, year=2024, price_per_day=1600, city="Gwalior", status="unlisted")
        start = timezone.localdate() + timedelta(days=2)
        booking = Booking.objects.create(vehicle=car, customer=renter, start=start, end=start+timedelta(days=1), amount=1600, status="confirmed")
        self.login(renter.email)
        url = f"/api/bookings/{booking.pk}/transition"
        self.assertEqual(self.client.post(url, {"status":"cancelled"}).status_code, 400)
        cancelled = self.client.post(url, {"status":"cancelled", "reason":"Plans changed"})
        self.assertEqual(cancelled.status_code, 200, cancelled.data)
        self.assertEqual(cancelled.data["cancellation_reason"], "Plans changed")
        self.assertTrue(cancelled.data["cancelled_at"])
        self.assertEqual(self.client.post(url, {"status":"cancelled", "reason":"Again"}).status_code, 400)
        late = Booking.objects.create(vehicle=car, customer=renter, start=timezone.localdate()-timedelta(days=1), end=timezone.localdate()+timedelta(days=1), amount=1600, status="confirmed")
        self.assertEqual(self.client.post(f"/api/bookings/{late.pk}/transition", {"status":"cancelled", "reason":"Too late"}).status_code, 400)

    def test_identity_upload_validation_and_production_gate(self):
        owner = User.objects.create_user(username="idowner@test.in", email="idowner@test.in", password="password123", role="owner")
        self.login(owner.email)
        bad = self.client.post("/api/owner/identity", {"document_type":"aadhaar", "document":SimpleUploadedFile("id.pdf", b"%PDF-1.4 test", content_type="application/pdf"), "consent":"true"}, format="multipart")
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(User.objects.get(pk=owner.pk).identity_status, "not_submitted")
        checked = self.client.post("/api/owner/identity", {"document_type":"aadhaar", "masked_aadhaar":"true", "document":SimpleUploadedFile("id.pdf", b"%PDF-1.4 test", content_type="application/pdf"), "consent":"true"}, format="multipart")
        self.assertEqual(checked.status_code, 200, checked.data)
        self.assertEqual(checked.data["identity_status"], "demo_checked")
        with override_settings(DEBUG=False, OWNER_ID_LOCAL_DEMO=False):
            self.assertFalse(self.client.get("/api/users/me").data["identity_can_list"])
            details = {"brand":"Tata", "name":"Punch", "category":"SUV", "fuel":"Petrol", "transmission":"Manual", "seats":5, "year":2024, "price_per_day":1600, "city":"Gwalior"}
            self.assertEqual(self.client.post("/api/vehicles", details).status_code, 403)
            self.assertEqual(self.client.post("/api/owner/identity", {"document_type":"pan"}).status_code, 400)

    def test_employee_id_unlocks_owner_and_old_request_needs_renter_id(self):
        owner = User.objects.create_user(username="employee@test.in", email="employee@test.in", password="password123", role="owner")
        renter = User.objects.create_user(username="oldrenter@test.in", email="oldrenter@test.in", password="password123", role="customer")
        self.login(owner.email)
        checked = self.client.post("/api/owner/identity", {"document_type":"employee_id", "document":SimpleUploadedFile("work.pdf", b"%PDF-1.4 employee ID", content_type="application/pdf"), "consent":"true"}, format="multipart")
        self.assertEqual(checked.status_code, 200, checked.data)
        self.assertEqual(checked.data["identity_type"], "employee_id")
        car = Vehicle.objects.create(owner=owner, brand="Tata", name="Punch", category="SUV", fuel="Petrol", transmission="Manual", seats=5, year=2024, price_per_day=1600, city="Gwalior", status="published")
        booking = Booking.objects.create(vehicle=car, customer=renter, start=timezone.localdate()+timedelta(days=1), end=timezone.localdate()+timedelta(days=2), amount=1600)
        url = f"/api/bookings/{booking.pk}/transition"
        self.assertEqual(self.client.post(url, {"status":"confirmed", "pickup_address":"Gwalior"}).status_code, 400)
        self.login(renter.email)
        upload = self.client.post(f"/api/bookings/{booking.pk}/identity", {"id_type":"student_id", "id_document":SimpleUploadedFile("school.pdf", b"%PDF-1.4 student ID", content_type="application/pdf"), "consent":"true"}, format="multipart")
        self.assertEqual(upload.status_code, 200, upload.data)
        self.assertTrue(upload.data["identity_submitted"])
        self.assertFalse(upload.data["identity_reviewed"])
        self.assertEqual(self.client.get(f"/api/bookings/{booking.pk}/document").status_code, 403)
        self.login(owner.email)
        self.assertEqual(self.client.post(url, {"status":"confirmed", "pickup_address":"Gwalior"}).status_code, 400)
        document = self.client.get(f"/api/bookings/{booking.pk}/document")
        self.assertEqual(document.status_code, 200)
        document.close()
        self.login(renter.email)
        replacement = self.client.post(f"/api/bookings/{booking.pk}/identity", {"id_type":"employee_id", "id_document":SimpleUploadedFile("replacement.pdf", b"%PDF-1.4 replacement ID", content_type="application/pdf"), "consent":"true"}, format="multipart")
        self.assertEqual(replacement.status_code, 200, replacement.data)
        self.assertFalse(replacement.data["identity_reviewed"])
        self.login(owner.email)
        self.assertEqual(self.client.post(url, {"status":"confirmed", "pickup_address":"Gwalior"}).status_code, 400)
        document = self.client.get(f"/api/bookings/{booking.pk}/document")
        self.assertEqual(document.status_code, 200)
        document.close()
        self.assertEqual(self.client.post(url, {"status":"confirmed", "pickup_address":"Gwalior"}).status_code, 200)

    def test_trip_title_uses_car_name_when_model_field_is_a_year(self):
        owner = User.objects.create_user(username="yearowner@test.in", email="yearowner@test.in", password="password123", role="owner")
        renter = User.objects.create_user(username="yearrenter@test.in", email="yearrenter@test.in", password="password123", role="customer")
        car = Vehicle.objects.create(owner=owner, brand="mahindra thar", name="2023", category="SUV", fuel="Diesel", transmission="Manual", seats=4, year=2024, price_per_day=3000, city="Gwalior")
        booking = Booking.objects.create(vehicle=car, customer=renter, start=timezone.localdate()+timedelta(days=1), end=timezone.localdate()+timedelta(days=3), amount=6000)
        data = BookingSer(booking).data
        self.assertEqual(data["vehicle_name"], "mahindra thar")
        self.assertTrue(data["created_at"])

    def test_owner_cannot_edit_another_owners_car(self):
        first = User.objects.create_user(username="one@test.in", email="one@test.in", password="password123", role="owner", identity_status="demo_checked")
        User.objects.create_user(username="two@test.in", email="two@test.in", password="password123", role="owner", identity_status="demo_checked")
        car = Vehicle.objects.create(owner=first, brand="Tata", name="Punch", category="SUV", fuel="Petrol", transmission="Manual", seats=5, year=2024, price_per_day=1600, city="Gwalior")
        self.login("two@test.in")
        self.assertEqual(len(self.client.get("/api/vehicles").data), 0)
        self.assertEqual(self.client.patch(f"/api/vehicles/{car.pk}", {"price_per_day":1}).status_code, 404)
        self.login("one@test.in")
        self.assertEqual([item["id"] for item in self.client.get("/api/vehicles").data], [car.pk])

    def test_owner_can_save_draft_then_list_it_later(self):
        owner = User.objects.create_user(username="draftowner@test.in", email="draftowner@test.in", password="password123", role="owner")
        other = User.objects.create_user(username="otherdraft@test.in", email="otherdraft@test.in", password="password123", role="owner", identity_status="demo_checked")
        details = {"brand":"Tata", "name":"Punch", "category":"SUV", "fuel":"Petrol", "transmission":"Manual", "seats":5, "year":2024, "price_per_day":1600, "city":"Gwalior", "save_as_draft":"true"}
        self.login(owner.email)
        saved = self.client.post("/api/vehicles", details)
        self.assertEqual(saved.status_code, 201, saved.data)
        self.assertEqual(saved.data["status"], "draft")
        car_id = saved.data["id"]
        self.assertEqual(self.client.get("/api/vehicles/mine").data[0]["id"], car_id)
        self.client.credentials()
        self.assertEqual(len(self.client.get("/api/vehicles").data), 0)
        self.login(other.email)
        self.assertEqual(self.client.post(f"/api/vehicles/{car_id}/publish").status_code, 403)
        self.login(owner.email)
        self.assertEqual(self.client.post(f"/api/vehicles/{car_id}/publish").status_code, 403)
        checked = self.client.post("/api/owner/identity", {"document_type":"pan", "document":SimpleUploadedFile("pan.pdf", b"%PDF-1.4 local test", content_type="application/pdf"), "consent":"true"}, format="multipart")
        self.assertEqual(checked.status_code, 200, checked.data)
        published = self.client.post(f"/api/vehicles/{car_id}/publish")
        self.assertEqual(published.status_code, 200, published.data)
        self.assertEqual(published.data["status"], "published")
        self.assertEqual(self.client.post(f"/api/vehicles/{car_id}/publish").status_code, 400)
        self.client.credentials()
        self.assertEqual([car["id"] for car in self.client.get("/api/vehicles").data], [car_id])

    def test_message_and_review_are_persisted(self):
        owner = User.objects.create_user(username="owner2@test.in", email="owner2@test.in", password="password123", role="owner", identity_status="demo_checked")
        renter = User.objects.create_user(username="renter2@test.in", email="renter2@test.in", password="password123", role="customer")
        car = Vehicle.objects.create(owner=owner, brand="Tata", name="Punch", category="SUV", fuel="Petrol", transmission="Manual", seats=5, year=2024, price_per_day=1600, city="Gwalior", status="published")
        booking = Booking.objects.create(vehicle=car, customer=renter, start=timezone.localdate()+timedelta(days=1), end=timezone.localdate()+timedelta(days=2), amount=1600, status="completed", id_document="ids/test.pdf")
        self.login("renter2@test.in")
        self.assertEqual(self.client.post(f"/api/bookings/{booking.pk}/messages", {"body":"Where is pickup?"}).status_code, 201)
        self.assertEqual(len(self.client.get(f"/api/bookings/{booking.pk}/messages").data), 1)
        self.assertEqual(self.client.post("/api/reviews", {"booking":booking.pk,"rating":5,"comment":"Great car"}).status_code, 201)
        self.assertEqual(len(self.client.get(f"/api/vehicles/{car.pk}/reviews").data), 1)
    def test_logout_invalidates_token(self):
        self.login("admin@test.in")
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 200)
        self.assertEqual(self.client.get("/api/users/me").status_code, 401)

    def test_public_car_search_matches_name_brand_and_city(self):
        owner = User.objects.create_user(username="searchowner@test.in", email="searchowner@test.in", password="password123", role="owner", identity_status="demo_checked")
        Vehicle.objects.create(owner=owner, brand="Mercedes", name="C Class", category="Sedan", fuel="Petrol", transmission="Automatic", seats=5, year=2024, price_per_day=5500, city="Delhi", status="published")
        for query in ("mercedes", "class", "delhi"):
            response = self.client.get("/api/vehicles", {"q":query})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.data), 1)
        self.assertEqual(len(self.client.get("/api/vehicles", {"q":"Mumbai"}).data), 0)

    def test_hourly_booking_price_and_overlap(self):
        owner = User.objects.create_user(username="hourowner@test.in", email="hourowner@test.in", password="password123", role="owner", identity_status="demo_checked")
        renter = User.objects.create_user(username="hourrenter@test.in", email="hourrenter@test.in", password="password123", role="customer")
        car = Vehicle.objects.create(owner=owner, brand="Tata", name="Punch", category="SUV", fuel="Petrol", transmission="Manual", seats=5, year=2024, price_per_day=2400, city="Gwalior")
        start = timezone.now() + timedelta(days=2)
        start = start.replace(minute=0, second=0, microsecond=0)
        end = start + timedelta(hours=1)
        self.login(renter.email)
        def request(a, b):
            return self.client.post("/api/bookings", {"vehicle":car.pk, "booking_type":"hourly", "start_at":a.isoformat(), "end_at":b.isoformat(), "id_type":"student_id", "id_document":SimpleUploadedFile("student.pdf", b"%PDF-1.4 student ID", content_type="application/pdf"), "consent":"true"}, format="multipart")
        one = request(start, end)
        self.assertEqual(one.status_code, 201, one.data)
        self.assertEqual(one.data["amount"], 100)
        self.assertEqual(one.data["booking_type"], "hourly")
        self.assertEqual(request(start, start + timedelta(minutes=30)).status_code, 400)
        self.login(owner.email)
        document = self.client.get(f"/api/bookings/{one.data['id']}/document")
        document.close()
        accepted = self.client.post(f"/api/bookings/{one.data['id']}/transition", {"status":"confirmed", "pickup_address":"Gwalior"})
        self.assertEqual(accepted.status_code, 200, accepted.data)
        self.login(renter.email)
        self.assertEqual(request(start + timedelta(minutes=30), end + timedelta(minutes=30)).status_code, 400)
        self.assertEqual(request(end, end + timedelta(hours=1)).status_code, 400)

    def test_owner_car_image_upload_and_replacement(self):
        owner = User.objects.create_user(username="photos@test.in", email="photos@test.in", password="password123", role="owner", identity_status="demo_checked")
        self.login(owner.email)
        def image_file():
            content = BytesIO()
            Image.new("RGB", (40, 30), "red").save(content, format="PNG")
            return SimpleUploadedFile("car.png", content.getvalue(), content_type="image/png")
        with override_settings(CLOUDINARY_URL="cloudinary://test:key@example"), \
             patch("core.vehicle_images.cloudinary.uploader.upload") as upload, \
             patch("core.vehicle_images.cloudinary.uploader.destroy") as destroy:
            upload.return_value = {"public_id":"gorent/vehicles/first", "secure_url":"https://res.cloudinary.com/example/image/upload/first.png"}
            response = self.client.post("/api/vehicles", {"brand":"Tata", "name":"Punch", "category":"SUV", "fuel":"Petrol", "transmission":"Manual", "seats":5, "year":2024, "price_per_day":1600, "city":"Gwalior", "image":image_file()}, format="multipart")
            self.assertEqual(response.status_code, 201, response.data)
            car_id = response.data["id"]
            self.assertEqual(response.data["image_url"], upload.return_value["secure_url"])
            self.assertNotIn("image_public_id", response.data)
            upload.return_value = {"public_id":"gorent/vehicles/second", "secure_url":"https://res.cloudinary.com/example/image/upload/second.png"}
            updated = self.client.patch(f"/api/vehicles/{car_id}", {"image":image_file()}, format="multipart")
            self.assertEqual(updated.status_code, 200, updated.data)
            self.assertEqual(updated.data["image_url"], upload.return_value["secure_url"])
            destroy.assert_called_once_with("gorent/vehicles/first", resource_type="image", invalidate=True)

    def test_invalid_car_image_never_uploads(self):
        owner = User.objects.create_user(username="badphoto@test.in", email="badphoto@test.in", password="password123", role="owner", identity_status="demo_checked")
        self.login(owner.email)
        with patch("core.vehicle_images.cloudinary.uploader.upload") as upload:
            response = self.client.post("/api/vehicles", {"brand":"Tata", "name":"Punch", "category":"SUV", "fuel":"Petrol", "transmission":"Manual", "seats":5, "year":2024, "price_per_day":1600, "city":"Gwalior", "image":SimpleUploadedFile("fake.png", b"not an image", content_type="image/png")}, format="multipart")
            self.assertEqual(response.status_code, 400)
            self.assertEqual(Vehicle.objects.count(), 0)
            upload.assert_not_called()

    def test_missing_cloudinary_credentials_keeps_car_unsaved(self):
        owner = User.objects.create_user(username="nocloud@test.in", email="nocloud@test.in", password="password123", role="owner", identity_status="demo_checked")
        self.login(owner.email)
        content = BytesIO()
        Image.new("RGB", (30, 30), "blue").save(content, format="PNG")
        with override_settings(CLOUDINARY_URL=""), patch("core.vehicle_images.cloudinary.uploader.upload") as upload:
            response = self.client.post("/api/vehicles", {"brand":"Tata", "name":"Punch", "category":"SUV", "fuel":"Petrol", "transmission":"Manual", "seats":5, "year":2024, "price_per_day":1600, "city":"Gwalior", "image":SimpleUploadedFile("car.png", content.getvalue(), content_type="image/png")}, format="multipart")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(Vehicle.objects.count(), 0)
            upload.assert_not_called()
