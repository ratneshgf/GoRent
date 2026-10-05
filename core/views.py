from django.db import transaction
from django.db.models import Avg, Q
from django.conf import settings
from django.utils import timezone
from django.http import FileResponse
from rest_framework import generics, mixins, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from . import rules
from .models import Booking, Review, Vehicle
from .serializers import *

def auth_payload(u):
    t, _ = Token.objects.get_or_create(user=u); return {"token": t.key, "user": UserSer(u).data}

class RegisterView(generics.CreateAPIView):
    permission_classes = [AllowAny]; serializer_class = RegisterSer
    def create(self, request, *a, **k):
        s = self.get_serializer(data=request.data); s.is_valid(raise_exception=True)
        return Response(auth_payload(s.save()), status=201)

class LoginView(ObtainAuthToken):               # POST {"username": <email>, "password": ...}
    def post(self, request, *a, **k):
        s = self.serializer_class(data=request.data, context={"request": request}); s.is_valid(raise_exception=True)
        u = s.validated_data["user"]
        if u.status != "active": raise PermissionDenied(f"Account is {u.status}.")
        return Response(auth_payload(u))

class LogoutView(APIView):
    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response({"detail": "Signed out."})

class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSer
    def get_object(self): return self.request.user

class OwnerIdentityView(APIView):
    def post(self, request):
        if request.user.role != "owner": raise PermissionDenied("Only owners can submit an identity document.")
        if not settings.OWNER_ID_LOCAL_DEMO:
            raise ValidationError("Government ID verification is not configured. Listing is unavailable until a verification provider is connected.")
        serializer = OwnerIdentitySer(data=request.data)
        serializer.is_valid(raise_exception=True)
        old_document = request.user.kyc_document
        request.user.kyc_document = serializer.validated_data["document"]
        request.user.identity_type = serializer.validated_data["document_type"]
        request.user.identity_status = "demo_checked"
        request.user.identity_submitted_at = timezone.now()
        request.user.save(update_fields=["kyc_document", "identity_type", "identity_status", "identity_submitted_at"])
        if old_document and old_document.name != request.user.kyc_document.name:
            old_document.delete(save=False)
        rules.audit(request.user, "identity_demo_checked", "user", request.user.pk)
        return Response(UserSer(request.user).data)

class VehicleViewSet(viewsets.ModelViewSet):
    serializer_class = VehicleSer; http_method_names = ["get", "post", "patch", "head", "options"]
    def get_permissions(self):
        return [AllowAny()] if self.action in ("list", "retrieve", "reviews") else super().get_permissions()
    def get_queryset(self):
        qs = Vehicle.objects.select_related("owner").annotate(rating=Avg("bookings__review__rating", filter=Q(bookings__review__hidden=False)))
        u, p = self.request.user, self.request.query_params
        if self.action in ("list", "retrieve", "reviews"):
            if self.action == "list" and u.is_authenticated and u.role == "owner":
                qs = qs.filter(owner=u)
            else:
                qs = qs.filter(status="published", owner__status="active")
                if not settings.OWNER_ID_LOCAL_DEMO:
                    qs = qs.filter(owner__identity_status="verified")
            if p.get("q"):
                term = p["q"].strip()
                qs = qs.filter(Q(brand__icontains=term) | Q(name__icontains=term) | Q(city__icontains=term))
            for k in ("city", "fuel", "transmission", "category"):
                if p.get(k): qs = qs.filter(**{f"{k}__iexact": p[k]})
            if p.get("min_price"): qs = qs.filter(price_per_day__gte=p["min_price"])
            if p.get("max_price"): qs = qs.filter(price_per_day__lte=p["max_price"])
            if p.get("seats"): qs = qs.filter(seats__gte=p["seats"])
            if p.get("from") and p.get("to") and not (u.is_authenticated and u.role == "owner"):
                busy = Booking.objects.filter(status__in=rules.BLOCKING, start__lte=p["to"], end__gte=p["from"]).values("vehicle_id")
                qs = qs.exclude(pk__in=busy)
            return qs.order_by({"price": "price_per_day", "newest": "-year"}.get(p.get("sort"), "-rating"), "id")
        return qs.filter(owner=u)
    def perform_create(self, s):
        if self.request.user.role != "owner": raise PermissionDenied("Only owners can save cars.")
        draft = s.validated_data.get("save_as_draft", False)
        if not draft and not UserSer(self.request.user).data["identity_can_list"]:
            raise PermissionDenied("Complete owner ID verification before listing a car.")
        s.save(owner=self.request.user, status="draft" if draft else "published")
    def perform_update(self, s):
        if s.instance.owner_id != self.request.user.pk:
            raise PermissionDenied()
        s.save()
    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        if request.user.role != "owner": raise PermissionDenied("Only the owner can list a car.")
        if not UserSer(request.user).data["identity_can_list"]:
            raise PermissionDenied("Complete the owner ID check before listing a car.")
        with transaction.atomic():
            vehicle = Vehicle.objects.select_for_update().filter(pk=pk, owner=request.user).first()
            if vehicle is None: raise PermissionDenied("This is not your car.")
            if vehicle.status != "draft": raise ValidationError("Only a saved draft can be listed here.")
            vehicle.status = "published"
            vehicle.save(update_fields=["status"])
        return Response(VehicleSer(vehicle, context={"request": request}).data)
    @action(detail=True, methods=["post"])
    def relist(self, request, pk=None):
        if request.user.role != "owner": raise PermissionDenied("Only the owner can relist a car.")
        if not UserSer(request.user).data["identity_can_list"]:
            raise PermissionDenied("Complete the owner ID check before relisting.")
        with transaction.atomic():
            vehicle = Vehicle.objects.select_for_update().filter(pk=pk, owner=request.user).first()
            if vehicle is None: raise PermissionDenied("This is not your car.")
            if vehicle.status != "unlisted": raise ValidationError("This car is already listed.")
            if vehicle.bookings.filter(status__in=("confirmed", "active", "returned", "disputed")).exists():
                raise ValidationError("Finish or cancel the current rental before relisting.")
            vehicle.status = "published"
            vehicle.save(update_fields=["status"])
        return Response(VehicleSer(vehicle, context={"request": request}).data)
    @action(detail=False, methods=["get"], url_path="mine")
    def mine(self, request):
        if request.user.role != "owner": raise PermissionDenied()
        return Response(VehicleSer(self.get_queryset().filter(owner=request.user), many=True, context={"request": request}).data)
    @action(detail=True, methods=["get"])
    def reviews(self, request, pk=None):
        self.get_object()
        r = Review.objects.filter(booking__vehicle_id=pk, hidden=False)
        return Response(ReviewSer(r, many=True).data)

class BookingViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = BookingSer
    def get_queryset(self):
        u = self.request.user
        qs = Booking.objects.select_related("vehicle__owner", "customer", "cancelled_by").prefetch_related("events")
        return qs.filter(Q(customer=u) | Q(vehicle__owner=u))
    def create(self, request):
        if request.user.role != "customer": raise PermissionDenied("Only renters can book.")
        s = BookingCreateSer(data=request.data); s.is_valid(raise_exception=True); d = s.validated_data
        v = d["vehicle"]
        b = Booking.objects.create(vehicle=v, customer=request.user, start=d["start"], end=d["end"],
                                   booking_type=d["booking_type"], start_at=d.get("start_at"), end_at=d.get("end_at"), amount=d["amount"],
                                   id_document=d["id_document"], id_type=d["id_type"])
        b.events.create(actor=request.user, to_status=b.status); rules.audit(request.user, "booking_requested", "booking", b.pk)
        return Response(BookingSer(b).data, status=201)
    @action(detail=True, methods=["post"])
    def transition(self, request, pk=None):
        pickup = None
        if request.data.get("status") == "confirmed":
            s = PickupSer(data=request.data); s.is_valid(raise_exception=True); pickup = s.validated_data
        return Response(BookingSer(rules.transition(self.get_object(), request.data.get("status"), request.user, pickup, request.data.get("reason", ""))).data)
    @action(detail=True, methods=["post"])
    def payment(self, request, pk=None):
        booking = self.get_object()
        return Response(BookingSer(rules.record_cash_payment(booking, request.data.get("action"), request.user)).data)
    @action(detail=True, methods=["get"])
    def receipt(self, request, pk=None):
        booking = self.get_object()
        if booking.payment_status != "paid_at_handover" or not booking.receipt_data:
            raise ValidationError("A receipt is available only after both parties confirm cash handover.")
        return Response(booking.receipt_data)
    @action(detail=True, methods=["get"])
    def document(self, request, pk=None):
        booking = self.get_object()
        if request.user != booking.vehicle.owner: raise PermissionDenied("Only the car owner can view the renter ID.")
        if booking.status in ("rejected", "cancelled"):
            raise PermissionDenied("This ID is no longer available after the request closed.")
        if not booking.id_document: raise ValidationError("The renter has not shared an ID yet.")
        if not booking.id_document.storage.exists(booking.id_document.name):
            raise ValidationError("This ID file is unavailable. Ask the renter to upload it again.")
        booking.id_viewed_by_owner_at = timezone.now()
        booking.save(update_fields=["id_viewed_by_owner_at"])
        rules.audit(request.user, "renter_id_viewed", "booking", booking.pk)
        return FileResponse(booking.id_document.open("rb"))
    @action(detail=True, methods=["post"], url_path="identity")
    def identity(self, request, pk=None):
        booking = self.get_object()
        if booking.customer != request.user: raise PermissionDenied("Only the renter can upload their ID.")
        if booking.status != "requested": raise ValidationError("ID can only be updated before the owner accepts.")
        serializer = BookingIdentitySer(data=request.data)
        serializer.is_valid(raise_exception=True)
        old_document = booking.id_document
        booking.id_document = serializer.validated_data["id_document"]
        booking.id_type = serializer.validated_data["id_type"]
        booking.id_viewed_by_owner_at = None
        booking.save(update_fields=["id_document", "id_type", "id_viewed_by_owner_at"])
        if old_document and old_document.name != booking.id_document.name:
            old_document.delete(save=False)
        rules.audit(request.user, "renter_id_submitted", "booking", booking.pk)
        return Response(BookingSer(booking).data)
    @action(detail=True, methods=["get", "post"])
    def messages(self, request, pk=None):
        b = self.get_object()
        if request.method == "POST":
            s = MessageSer(data=request.data); s.is_valid(raise_exception=True)
            return Response(MessageSer(s.save(booking=b, sender=request.user)).data, status=201)
        return Response(MessageSer(b.messages.select_related("sender"), many=True).data)

class ReviewCreate(generics.CreateAPIView):
    serializer_class = ReviewSer
    def perform_create(self, s):
        b = s.validated_data["booking"]
        if b.customer != self.request.user or b.status != "completed": raise ValidationError("Only completed rentals can be reviewed by the renter.")
        if Review.objects.filter(booking=b).exists(): raise ValidationError("Already reviewed.")
        s.save(reviewer=self.request.user)

