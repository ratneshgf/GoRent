"""Business rules: booking state machine, overlap prevention, audit trail."""
from django.db import transaction
from datetime import datetime, time, timedelta
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from .models import AuditLog, Booking, BookingEvent, Vehicle

NEXT = {
    "requested": ["confirmed", "rejected", "cancelled"],
    "confirmed": ["active", "cancelled"],
    "active": ["returned", "disputed"],
    "returned": ["completed", "disputed"],
}
OWNER_MOVES = {"confirmed", "rejected", "active", "returned", "completed", "disputed", "cancelled"}
CUSTOMER_MOVES = {"cancelled"}
BLOCKING = ("confirmed", "active")

def days(start, end): return max(1, (end - start).days)

def interval(booking):
    if booking.start_at and booking.end_at:
        return booking.start_at, booking.end_at
    return (timezone.make_aware(datetime.combine(booking.start, time.min)),
            timezone.make_aware(datetime.combine(booking.end, time.min)))

def overlaps(vehicle, start, end, exclude=None):
    q = Booking.objects.filter(vehicle=vehicle, status__in=BLOCKING, start__lt=end.date() + timedelta(days=1), end__gte=start.date())
    if exclude: q = q.exclude(pk=exclude)
    return any(existing_start < end and start < existing_end for existing_start, existing_end in map(interval, q))

def audit(actor, action, entity, entity_id):
    AuditLog.objects.create(actor=actor, action=action, entity=entity, entity_id=entity_id)

@transaction.atomic
def transition(booking, to, actor, pickup=None, cancellation_reason=""):
    b = Booking.objects.select_for_update().select_related("vehicle__owner").get(pk=booking.pk)
    if to not in NEXT.get(b.status, []):
        raise ValidationError(f"Cannot move from {b.status} to {to}.")
    owner = actor == b.vehicle.owner
    if not ((actor == b.customer and to in CUSTOMER_MOVES) or (owner and to in OWNER_MOVES)):
        raise PermissionDenied("You cannot make this change.")
    if to == "confirmed":
        if not b.id_document:
            raise ValidationError("Ask the renter to upload an ID before accepting.")
        if not b.id_viewed_by_owner_at:
            raise ValidationError("Open the renter ID before accepting this request.")
        if not pickup or not pickup.get("pickup_address"):
            raise ValidationError("Add a pickup location before accepting.")
        if b.vehicle.owner.status != "active": raise ValidationError("Suspended owners cannot accept bookings.")
        vehicle = Vehicle.objects.select_for_update().get(pk=b.vehicle_id)  # serialise confirmations and relisting
        if vehicle.status != "published":
            raise ValidationError("This car is no longer listed. The owner must relist it after the rental ends.")
        start, end = interval(b)
        if overlaps(b.vehicle, start, end, exclude=b.pk): raise ValidationError("Overlaps a confirmed booking.")
        vehicle.status = "unlisted"
        vehicle.save(update_fields=["status"])
        b.pickup_address = pickup["pickup_address"]
        b.pickup_lat = pickup.get("pickup_lat")
        b.pickup_lng = pickup.get("pickup_lng")
    if to == "cancelled":
        reason = str(cancellation_reason or "").strip()
        if b.status == "confirmed":
            if timezone.now() >= interval(b)[0]:
                raise ValidationError("A confirmed booking can only be cancelled before pickup starts. Contact the other party for help.")
            if not reason:
                raise ValidationError("Give a reason when cancelling a confirmed booking.")
        b.cancelled_at = timezone.now()
        b.cancelled_by = actor
        b.cancellation_reason = reason[:500]
    if to in ("returned", "completed") and b.payment_status != "paid_at_handover":
        raise ValidationError("Both renter and owner must confirm the cash handover before finishing the rental.")
    BookingEvent.objects.create(booking=b, actor=actor, from_status=b.status, to_status=to)
    b.status = to; b.save()
    audit(actor, f"booking_{to}", "booking", b.pk)
    return b

@transaction.atomic
def record_cash_payment(booking, action, actor):
    b = Booking.objects.select_for_update().select_related("vehicle__owner", "customer").get(pk=booking.pk)
    if b.status not in ("active", "returned", "completed"):
        raise ValidationError("Cash handover can only be recorded after the rental starts.")
    if action == "mark_paid":
        if actor != b.customer: raise PermissionDenied("Only the renter can mark cash as paid.")
        if b.renter_paid_at: raise ValidationError("You already marked this payment as paid.")
        b.renter_paid_at = timezone.now()
        b.payment_status = "renter_marked_paid"
        b.save(update_fields=["renter_paid_at", "payment_status"])
        audit(actor, "cash_marked_paid", "booking", b.pk)
    elif action == "confirm_received":
        if actor != b.vehicle.owner: raise PermissionDenied("Only the car owner can confirm receipt of cash.")
        if not b.renter_paid_at: raise ValidationError("The renter must mark cash as paid first.")
        if b.owner_received_at: raise ValidationError("Cash receipt is already confirmed.")
        b.owner_received_at = timezone.now()
        b.payment_status = "paid_at_handover"
        brand = b.vehicle.brand.strip()
        model = b.vehicle.name.strip()
        vehicle_name = brand if not model or (model.isdigit() and len(model) == 4 and 1900 <= int(model) <= 2100) or brand.casefold().endswith(model.casefold()) else f"{brand} {model}"
        b.receipt_data = {
            "receipt_number": f"{b.code}-CASH", "booking_code": b.code,
            "vehicle_name": vehicle_name,
            "owner_name": b.vehicle.owner.company_name or b.vehicle.owner.first_name,
            "renter_name": b.customer.first_name,
            "booking_type": b.booking_type, "start": b.start.isoformat(), "end": b.end.isoformat(),
            "start_at": b.start_at.isoformat() if b.start_at else None,
            "end_at": b.end_at.isoformat() if b.end_at else None,
            "pickup_address": b.pickup_address, "rental_amount": b.amount,
            "payment_method": "cash_at_handover",
            "renter_marked_paid_at": b.renter_paid_at.isoformat(),
            "owner_confirmed_at": b.owner_received_at.isoformat(),
        }
        b.save(update_fields=["owner_received_at", "payment_status", "receipt_data"])
        audit(actor, "cash_received", "booking", b.pk)
    else:
        raise ValidationError("Choose mark_paid or confirm_received.")
    return b
