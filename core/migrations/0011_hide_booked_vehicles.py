from django.db import migrations


def hide_booked_vehicles(apps, schema_editor):
    Booking = apps.get_model("core", "Booking")
    Vehicle = apps.get_model("core", "Vehicle")
    booked = Booking.objects.filter(status__in=("confirmed", "active", "returned", "completed", "disputed")).values("vehicle_id")
    Vehicle.objects.filter(status="published", id__in=booked).update(status="unlisted")


class Migration(migrations.Migration):
    dependencies = [("core", "0010_booking_booking_type_booking_end_at_booking_start_at")]
    operations = [migrations.RunPython(hide_booked_vehicles, migrations.RunPython.noop)]
