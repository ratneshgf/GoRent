from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Disabled: demo listings must not appear in the real marketplace"

    def handle(self, *args, **options):
        raise CommandError("Demo seeding is disabled. Register an owner and list a car through the app.")
