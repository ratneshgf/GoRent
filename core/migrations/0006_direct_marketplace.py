from django.db import migrations


def publish_existing(apps, schema_editor):
    Vehicle = apps.get_model("core", "Vehicle")
    Booking = apps.get_model("core", "Booking")
    Vehicle.objects.filter(status="pending_approval").update(status="published")
    Booking.objects.filter(status__in=["verification_pending", "resubmission_required"]).update(status="requested")


class Migration(migrations.Migration):
    dependencies = [("core", "0005_booking_pickup_address_booking_pickup_lat_and_more")]
    operations = [migrations.RunPython(publish_existing, migrations.RunPython.noop)]
