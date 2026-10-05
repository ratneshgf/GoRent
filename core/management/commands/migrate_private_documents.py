from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Booking, PrivateDocument, User


class Command(BaseCommand):
    help = "Copy existing local owner and renter ID files into private database storage."

    def add_arguments(self, parser):
        parser.add_argument("--execute", action="store_true", help="Write documents after validation")

    def handle(self, *args, **options):
        names = {
            name for name in User.objects.exclude(kyc_document="").values_list("kyc_document", flat=True)
            if name
        }
        names.update(
            name for name in Booking.objects.exclude(id_document="").values_list("id_document", flat=True)
            if name
        )
        root = Path(settings.MEDIA_ROOT).resolve()
        pending = []
        missing = 0
        for name in names:
            if PrivateDocument.objects.filter(path=name).exists():
                continue
            local_file = (root / name).resolve()
            if not local_file.is_relative_to(root) or not local_file.is_file():
                missing += 1
                continue
            data = local_file.read_bytes()
            if len(data) > 5 * 1024 * 1024:
                raise CommandError("An existing ID document exceeds the 5 MB limit.")
            pending.append(PrivateDocument(path=name, content=data, size=len(data)))
        if missing:
            raise CommandError(f"{missing} ID document(s) are missing locally; no files were copied.")
        if options["execute"]:
            with transaction.atomic():
                PrivateDocument.objects.bulk_create(pending)
            self.stdout.write(self.style.SUCCESS(f"Copied {len(pending)} private document(s)."))
        else:
            self.stdout.write(f"Ready to copy {len(pending)} private document(s). Run with --execute.")
