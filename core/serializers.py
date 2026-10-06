from datetime import date, datetime, time, timedelta
from math import ceil
from pathlib import Path
from urllib.parse import urlencode
from PIL import Image, UnidentifiedImageError
from django.conf import settings
from django.utils import timezone
from rest_framework import serializers
from . import rules
from .vehicle_images import delete_vehicle_image, upload_vehicle_image
from .models import Booking, BookingEvent, Message, Review, User, Vehicle

IDENTITY_TYPES = ["aadhaar", "pan", "driving_licence", "passport", "voter_id", "student_id", "employee_id", "other"]

def validate_identity_file(file):
    if file.size > 5 * 1024 * 1024: raise serializers.ValidationError("File must be 5 MB or smaller.")
    suffix = Path(file.name).suffix.lower()
    if suffix not in (".jpg", ".jpeg", ".png", ".pdf"):
        raise serializers.ValidationError("Upload a JPG, PNG or PDF file.")
    if suffix == ".pdf":
        if not file.read(5).startswith(b"%PDF-"):
            raise serializers.ValidationError("This PDF cannot be read.")
    else:
        try:
            with Image.open(file) as image:
                if image.format not in ("JPEG", "PNG") or image.width > 8000 or image.height > 8000:
                    raise serializers.ValidationError("Upload a valid JPG or PNG image up to 8000 pixels per side.")
                image.verify()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            raise serializers.ValidationError("This image cannot be read.")
    file.seek(0)
    return file

class UserSer(serializers.ModelSerializer):
    identity_can_list = serializers.SerializerMethodField()
    identity_local_demo = serializers.SerializerMethodField()
    def get_identity_can_list(self, user):
        return user.identity_status in ("verified", "submitted") or (settings.OWNER_ID_LOCAL_DEMO and user.identity_status == "demo_checked")
    def get_identity_local_demo(self, user): return settings.OWNER_ID_LOCAL_DEMO
    class Meta:
        model = User; fields = ["id", "email", "first_name", "role", "phone", "status", "company_name", "identity_type", "identity_status", "identity_can_list", "identity_local_demo"]
        read_only_fields = ["email", "role", "status", "identity_type", "identity_status", "identity_can_list", "identity_local_demo"]

class OwnerIdentitySer(serializers.Serializer):
    document_type = serializers.ChoiceField(choices=IDENTITY_TYPES)
    document = serializers.FileField()
    consent = serializers.BooleanField()
    masked_aadhaar = serializers.BooleanField(required=False, default=False)
    def validate(self, attrs):
        if attrs["document_type"] == "aadhaar" and not attrs["masked_aadhaar"]:
            raise serializers.ValidationError("Upload only masked Aadhaar with the first eight digits hidden.")
        return attrs
    def validate_consent(self, value):
        if not value: raise serializers.ValidationError("Consent is required to submit an identity document.")
        return value
    def validate_document(self, file):
        return validate_identity_file(file)

class RegisterSer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    role = serializers.ChoiceField(choices=["customer", "owner"])
    class Meta: model = User; fields = ["email", "password", "first_name", "phone", "role", "company_name"]
    def validate_email(self, v):
        v = v.strip().lower()
        if User.objects.filter(username__iexact=v).exists(): raise serializers.ValidationError("Already registered.")
        return v
    def create(self, d):
        return User.objects.create_user(username=d["email"], **d)

class VehicleSer(serializers.ModelSerializer):
    owner_name = serializers.SerializerMethodField()
    rating = serializers.SerializerMethodField()
    image = serializers.FileField(write_only=True, required=False)
    save_as_draft = serializers.BooleanField(write_only=True, required=False, default=False)
    class Meta:
        model = Vehicle
        fields = ["id", "owner", "owner_name", "brand", "name", "category", "fuel", "transmission", "seats",
                  "year", "price_per_day", "deposit", "city", "address", "description", "min_days", "max_days", "status", "rating", "image", "image_url", "save_as_draft"]
        read_only_fields = ["owner", "status", "image_url"]
    def get_owner_name(self, o): return o.owner.company_name or o.owner.first_name
    def get_rating(self, o):
        r = getattr(o, "rating", None); return round(r, 1) if r else None
    def validate_image(self, image):
        if image.size > 10 * 1024 * 1024:
            raise serializers.ValidationError("Choose an image smaller than 10 MB.")
        if Path(image.name).suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
            raise serializers.ValidationError("Upload a JPG, PNG or WebP image.")
        try:
            with Image.open(image) as decoded:
                if decoded.format not in ("JPEG", "PNG", "WEBP"):
                    raise serializers.ValidationError("Upload a JPG, PNG or WebP image.")
                if decoded.width > 8000 or decoded.height > 8000:
                    raise serializers.ValidationError("Image dimensions must be at most 8000 × 8000 pixels.")
                decoded.verify()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            raise serializers.ValidationError("This image could not be read.")
        finally:
            image.seek(0)
        return image
    def create(self, validated_data):
        validated_data.pop("save_as_draft", None)
        image = validated_data.pop("image", None)
        if image:
            public_id, url = upload_vehicle_image(image)
            validated_data.update(image_public_id=public_id, image_url=url)
        try:
            return super().create(validated_data)
        except Exception:
            if image: delete_vehicle_image(public_id)
            raise
    def update(self, instance, validated_data):
        validated_data.pop("save_as_draft", None)
        image = validated_data.pop("image", None)
        old_public_id = instance.image_public_id
        if image:
            public_id, url = upload_vehicle_image(image)
            validated_data.update(image_public_id=public_id, image_url=url)
        try:
            updated = super().update(instance, validated_data)
        except Exception:
            if image: delete_vehicle_image(public_id)
            raise
        if image: delete_vehicle_image(old_public_id)
        return updated
    def validate(self, attrs):
        minimum = attrs.get("min_days", getattr(self.instance, "min_days", 1))
        maximum = attrs.get("max_days", getattr(self.instance, "max_days", 14))
        if minimum < 1 or maximum > 14 or minimum > maximum:
            raise serializers.ValidationError("Rental limits must be between 1 and 14 days.")
        if attrs.get("price_per_day", getattr(self.instance, "price_per_day", 1)) < 1:
            raise serializers.ValidationError("Price must be positive.")
        return attrs
    def to_representation(self, o):
        d, u = super().to_representation(o), self.context["request"].user
        if not (u.is_authenticated and u == o.owner): d.pop("address")
        return d

class EventSer(serializers.ModelSerializer):
    class Meta: model = BookingEvent; fields = ["from_status", "to_status", "at"]

class BookingSer(serializers.ModelSerializer):
    code = serializers.CharField(read_only=True); vehicle_name = serializers.SerializerMethodField()
    def get_vehicle_name(self, booking):
        brand = booking.vehicle.brand.strip()
        model = booking.vehicle.name.strip()
        if not model or (model.isdigit() and len(model) == 4 and 1900 <= int(model) <= 2100) or brand.casefold().endswith(model.casefold()):
            return brand
        return f"{brand} {model}"
    customer_name = serializers.CharField(source="customer.first_name", read_only=True); events = EventSer(many=True, read_only=True)
    pickup_route_url = serializers.SerializerMethodField()
    identity_submitted = serializers.SerializerMethodField()
    def get_identity_submitted(self, booking): return bool(booking.id_document)
    identity_reviewed = serializers.SerializerMethodField()
    def get_identity_reviewed(self, booking): return bool(booking.id_viewed_by_owner_at)
    can_cancel_confirmed = serializers.SerializerMethodField()
    def get_can_cancel_confirmed(self, booking):
        return booking.status == "confirmed" and timezone.now() < rules.interval(booking)[0]
    cancelled_by_name = serializers.SerializerMethodField()
    def get_cancelled_by_name(self, booking):
        if not booking.cancelled_by_id: return None
        return booking.cancelled_by.company_name or booking.cancelled_by.first_name
    def get_pickup_route_url(self, booking):
        if not booking.pickup_address or booking.status in ("requested", "rejected", "cancelled"):
            return None
        destination = f"{booking.pickup_lat},{booking.pickup_lng}" if booking.pickup_lat is not None and booking.pickup_lng is not None else booking.pickup_address
        return "https://www.google.com/maps/dir/?" + urlencode({"api": "1", "destination": destination, "travelmode": "driving"})
    class Meta:
        model = Booking
        fields = ["id", "code", "vehicle", "vehicle_name", "customer_name", "start", "end", "booking_type", "start_at", "end_at", "amount", "status", "id_type", "identity_submitted", "identity_reviewed", "pickup_address", "pickup_route_url", "payment_status", "renter_paid_at", "owner_received_at", "can_cancel_confirmed", "cancelled_at", "cancelled_by_name", "cancellation_reason", "created_at", "events"]

class PickupSer(serializers.Serializer):
    pickup_address = serializers.CharField(max_length=250)
    pickup_lat = serializers.DecimalField(max_digits=9, decimal_places=6, required=False)
    pickup_lng = serializers.DecimalField(max_digits=9, decimal_places=6, required=False)
    def validate(self, attrs):
        if ("pickup_lat" in attrs) != ("pickup_lng" in attrs):
            raise serializers.ValidationError("Both location coordinates are required.")
        if "pickup_lat" in attrs and not (-90 <= attrs["pickup_lat"] <= 90 and -180 <= attrs["pickup_lng"] <= 180):
            raise serializers.ValidationError("Invalid location coordinates.")
        return attrs

class BookingCreateSer(serializers.Serializer):
    vehicle = serializers.PrimaryKeyRelatedField(queryset=Vehicle.objects.select_related("owner"))
    booking_type = serializers.ChoiceField(choices=["daily", "hourly"], default="daily")
    start = serializers.DateField(required=False); end = serializers.DateField(required=False)
    start_at = serializers.DateTimeField(required=False); end_at = serializers.DateTimeField(required=False)
    id_document = serializers.FileField(validators=[validate_identity_file])
    id_type = serializers.ChoiceField(choices=IDENTITY_TYPES)
    consent = serializers.BooleanField()
    masked_aadhaar = serializers.BooleanField(required=False, default=False)
    def validate_consent(self, value):
        if not value: raise serializers.ValidationError("Agree to share your ID privately with the car owner.")
        return value
    def validate(self, a):
        if a["id_type"] == "aadhaar" and not a["masked_aadhaar"]:
            raise serializers.ValidationError("Upload only masked Aadhaar with the first eight digits hidden.")
        v = a["vehicle"]
        allowed_statuses = ("verified", "submitted", "demo_checked") if settings.OWNER_ID_LOCAL_DEMO else ("verified", "submitted")
        if v.status != "published" or v.owner.status != "active" or v.owner.identity_status not in allowed_statuses:
            raise serializers.ValidationError("This car is not available for booking.")
        if a["booking_type"] == "hourly":
            if not a.get("start_at") or not a.get("end_at"):
                raise serializers.ValidationError("Choose pickup and return date and time.")
            start, end = a["start_at"], a["end_at"]
            duration = (end - start).total_seconds() / 3600
            if start < timezone.now() or duration < 1 or duration > v.max_days * 24:
                raise serializers.ValidationError(f"Choose 1 to {v.max_days * 24} hours, starting in the future.")
            a["start"], a["end"] = start.date(), end.date()
            a["amount"] = ceil(v.price_per_day / 24) * ceil(duration)
        else:
            if not a.get("start") or not a.get("end"):
                raise serializers.ValidationError("Choose pickup and return dates.")
            if a["start"] < timezone.localdate() or a["end"] <= a["start"]:
                raise serializers.ValidationError("Return must be after pickup.")
            n = rules.days(a["start"], a["end"])
            if not v.min_days <= n <= v.max_days:
                raise serializers.ValidationError(f"Rental must be {v.min_days} to {v.max_days} days.")
            start = timezone.make_aware(datetime.combine(a["start"], time.min))
            end = timezone.make_aware(datetime.combine(a["end"], time.min))
            a["amount"] = n * v.price_per_day
        if rules.overlaps(v, start, end): raise serializers.ValidationError("Not available for this period.")
        return a

class BookingIdentitySer(serializers.Serializer):
    id_document = serializers.FileField(validators=[validate_identity_file])
    id_type = serializers.ChoiceField(choices=IDENTITY_TYPES)
    consent = serializers.BooleanField()
    masked_aadhaar = serializers.BooleanField(required=False, default=False)
    def validate(self, attrs):
        if attrs["id_type"] == "aadhaar" and not attrs["masked_aadhaar"]:
            raise serializers.ValidationError("Upload only masked Aadhaar with the first eight digits hidden.")
        return attrs
    def validate_consent(self, value):
        if not value: raise serializers.ValidationError("Agree to share your ID privately with the car owner.")
        return value

class MessageSer(serializers.ModelSerializer):
    sender_name = serializers.CharField(source="sender.first_name", read_only=True)
    class Meta: model = Message; fields = ["id", "sender", "sender_name", "body", "created_at"]; read_only_fields = ["sender"]

class ReviewSer(serializers.ModelSerializer):
    rating = serializers.IntegerField(min_value=1, max_value=5)
    class Meta: model = Review; fields = ["id", "booking", "rating", "comment", "created_at"]

