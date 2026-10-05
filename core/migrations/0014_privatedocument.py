from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0013_booking_receipt_data")]

    operations = [
        migrations.CreateModel(
            name="PrivateDocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("path", models.CharField(max_length=500, unique=True)),
                ("content", models.BinaryField()),
                ("size", models.PositiveIntegerField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
    ]
