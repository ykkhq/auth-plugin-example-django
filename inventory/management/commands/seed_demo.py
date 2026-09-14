from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from inventory.models import Item

SERVICE_USERNAME = "kong_service"
SERVICE_PASSWORD = "kong-service-demo-pw"  # noqa: S105 - demo credential only

# Regular (non-staff) user for the browser-facing web UI, distinct from the
# kong_service account (used only for the Kong<->Django session bridge) and
# from the Django admin (which has no seeded superuser).
SAMPLE_USERNAME = "user1"
SAMPLE_PASSWORD = "awesome user1"  # noqa: S105 - demo credential only

SAMPLE_ITEMS = [
    {"name": "USB-C Cable", "sku": "SKU-1001", "category": "Accessories", "quantity": 150, "unit_price": "6.99"},
    {"name": "Wireless Mouse", "sku": "SKU-1002", "category": "Accessories", "quantity": 80, "unit_price": "19.99"},
    {"name": "27in Monitor", "sku": "SKU-1003", "category": "Displays", "quantity": 25, "unit_price": "229.00"},
    {"name": "Mechanical Keyboard", "sku": "SKU-1004", "category": "Accessories", "quantity": 40, "unit_price": "89.50"},
    {"name": "Laptop Stand", "sku": "SKU-1005", "category": "Furniture", "quantity": 60, "unit_price": "34.00"},
]


class Command(BaseCommand):
    help = "Create the shared service account Kong uses and seed sample inventory items."

    def handle(self, *args, **options):
        User = get_user_model()
        user, created = User.objects.get_or_create(username=SERVICE_USERNAME)
        if created:
            user.set_password(SERVICE_PASSWORD)
            user.save()
            self.stdout.write(self.style.SUCCESS(
                f"Created service account '{SERVICE_USERNAME}' (password: {SERVICE_PASSWORD})"
            ))
        else:
            self.stdout.write(f"Service account '{SERVICE_USERNAME}' already exists.")

        sample_user, created = User.objects.get_or_create(username=SAMPLE_USERNAME)
        if created:
            sample_user.set_password(SAMPLE_PASSWORD)
            sample_user.save()
            self.stdout.write(self.style.SUCCESS(
                f"Created sample user '{SAMPLE_USERNAME}' (password: {SAMPLE_PASSWORD})"
            ))
        else:
            self.stdout.write(f"Sample user '{SAMPLE_USERNAME}' already exists.")

        created_count = 0
        for data in SAMPLE_ITEMS:
            _, created = Item.objects.get_or_create(sku=data["sku"], defaults=data)
            created_count += int(created)
        self.stdout.write(self.style.SUCCESS(f"Seeded {created_count} new item(s)."))
