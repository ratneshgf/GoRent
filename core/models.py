from django.contrib.auth.models import AbstractUser
from django.db import models

class PrivateDocument(models.Model):
    """ID bytes kept in the configured database, never exposed by a file URL."""
    path = models.CharField(max_length=500, unique=True)
    content = models.BinaryField()
    size = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

class User(AbstractUser):
    ROLES = [("customer", "Customer"), ("owner", "Owner"), ("admin", "Admin")]
    role = models.CharField(max_length=10, choices=ROLES, default="customer")
    phone = models.CharField(max_length=15, blank=True)
    status = models.CharField(max_length=10, default="active")            # active, suspended, blocked
    kyc = models.CharField(max_length=14, default="not_submitted")        # not_submitted, under_review, verified, rejected, expired
    company_name = models.CharField(max_length=120, blank=True)
    kyc_document = models.FileField(upload_to="owner_kyc/%Y/%m", blank=True)
    identity_type = models.CharField(max_length=20, blank=True)
    identity_status = models.CharField(max_length=20, default="not_submitted")
    identity_submitted_at = models.DateTimeField(null=True, blank=True)
    renter_id_document = models.FileField(upload_to="renter_ids/%Y/%m", blank=True)
    renter_id_type = models.CharField(max_length=20, blank=True)
    renter_id_submitted_at = models.DateTimeField(null=True, blank=True)
    @property
    def verified(self): return self.kyc == "verified"

class Vehicle(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="vehicles")
    brand = models.CharField(max_length=60); name = models.CharField(max_length=80)
    category = models.CharField(max_length=20); fuel = models.CharField(max_length=12)
    transmission = models.CharField(max_length=10); seats = models.PositiveSmallIntegerField(default=5)
    year = models.PositiveSmallIntegerField(); price_per_day = models.PositiveIntegerField()
    deposit = models.PositiveIntegerField(default=0); city = models.CharField(max_length=60, db_index=True)
    address = models.CharField(max_length=200, blank=True); description = models.TextField(blank=True)
    image_url = models.URLField(max_length=500, blank=True)
    image_public_id = models.CharField(max_length=255, blank=True)
    min_days = models.PositiveSmallIntegerField(default=1); max_days = models.PositiveSmallIntegerField(default=14)
    status = models.CharField(max_length=20, default="published")
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self): return self.name

class Booking(models.Model):
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT, related_name="bookings")
    customer = models.ForeignKey(User, on_delete=models.PROTECT, related_name="bookings")
    start = models.DateField(); end = models.DateField(); amount = models.PositiveIntegerField()
    booking_type = models.CharField(max_length=10, default="daily")
    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=24, default="requested", db_index=True)
    pickup_address = models.CharField(max_length=250, blank=True)
    pickup_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    pickup_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    payment_status = models.CharField(max_length=20, default="unpaid")    # unpaid, renter_marked_paid, paid_at_handover, unverified_legacy
    renter_paid_at = models.DateTimeField(null=True, blank=True)
    owner_received_at = models.DateTimeField(null=True, blank=True)
    receipt_data = models.JSONField(default=dict, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="cancelled_bookings")
    cancellation_reason = models.CharField(max_length=500, blank=True)
    id_document = models.FileField(upload_to="ids/%Y/%m", blank=True)
    id_type = models.CharField(max_length=20, blank=True)
    id_viewed_by_owner_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    @property
    def code(self): return f"GR-{1000 + self.pk}"

class BookingEvent(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    from_status = models.CharField(max_length=24, blank=True); to_status = models.CharField(max_length=24)
    at = models.DateTimeField(auto_now_add=True)

class Message(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(User, on_delete=models.CASCADE)
    body = models.TextField(max_length=1000); created_at = models.DateTimeField(auto_now_add=True)

class Review(models.Model):
    booking = models.OneToOneField(Booking, on_delete=models.CASCADE)
    reviewer = models.ForeignKey(User, on_delete=models.CASCADE)
    rating = models.PositiveSmallIntegerField(); comment = models.TextField(blank=True)
    hidden = models.BooleanField(default=False); created_at = models.DateTimeField(auto_now_add=True)

class AuditLog(models.Model):
    actor = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=40); entity = models.CharField(max_length=30); entity_id = models.PositiveIntegerField()
    at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ["-at"]

class Report(models.Model):
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="reports")
    reporter = models.ForeignKey(User, on_delete=models.CASCADE)
    reason = models.TextField(max_length=1000)
    status = models.CharField(max_length=20, default="open")
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ["-created_at"]
