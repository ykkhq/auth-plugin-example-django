from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from inventory.models import (
    Customer,
    Item,
    ItemComponent,
    Order,
    OrderLine,
    PurchaseOrder,
    PurchaseOrderLine,
    Shipment,
    ShippingStatus,
    Supplier,
)

SERVICE_USERNAME = "kong_service"
SERVICE_PASSWORD = "kong-service-demo-pw"  # noqa: S105 - demo credential only

# Regular (non-staff) user for the browser-facing web UI, distinct from the
# kong_service account (used only for the Kong<->Django session bridge) and
# from the Django admin (which has no seeded superuser).
SAMPLE_USERNAME = "user1"
SAMPLE_PASSWORD = "awesome user1"  # noqa: S105 - demo credential only

C, F = Item.ItemType.COMPONENT, Item.ItemType.FINISHED_GOOD
SAMPLE_ITEMS = [
    {"name": "USB-C Cable", "sku": "SKU-1001", "category": "Accessories", "item_type": C, "quantity": 150, "unit_price": "6.99"},
    {"name": "Wireless Mouse", "sku": "SKU-1002", "category": "Accessories", "item_type": C, "quantity": 80, "unit_price": "19.99"},
    {"name": "27in Monitor", "sku": "SKU-1003", "category": "Displays", "item_type": C, "quantity": 25, "unit_price": "229.00"},
    {"name": "Mechanical Keyboard", "sku": "SKU-1004", "category": "Accessories", "item_type": C, "quantity": 40, "unit_price": "89.50"},
    {"name": "Laptop Stand", "sku": "SKU-1005", "category": "Furniture", "item_type": C, "quantity": 60, "unit_price": "34.00"},
    {"name": "Desk Workstation Bundle", "sku": "FG-2001", "category": "Bundles", "item_type": F, "quantity": 5, "unit_price": "449.00"},
]

# Bill of materials for FG-2001: (component sku, quantity per bundle)
SAMPLE_BOM = [("SKU-1003", 1), ("SKU-1004", 1), ("SKU-1002", 1), ("SKU-1001", 2), ("SKU-1005", 1)]

SAMPLE_SUPPLIERS = [
    {"code": "SUP-001", "name": "Acme Electronics", "contact_name": "Jane Park", "email": "orders@acme.example", "lead_time_days": 10},
    {"code": "SUP-002", "name": "Nippon Furniture Parts", "contact_name": "Ken Sato", "email": "sales@nfp.example", "lead_time_days": 21},
]

SAMPLE_CUSTOMERS = [
    {"code": "CUS-001", "name": "Tokyo Office Dealer", "customer_type": Customer.CustomerType.DEALER,
     "email": "buy@tod.example", "shipping_address": "1-1 Marunouchi, Chiyoda, Tokyo", "credit_limit": "50000.00"},
    {"code": "CUS-002", "name": "Startup Inc.", "customer_type": Customer.CustomerType.DIRECT,
     "email": "it@startup.example", "shipping_address": "2-2 Shibuya, Tokyo", "credit_limit": "5000.00"},
]


class Command(BaseCommand):
    help = "Create the shared service account Kong uses and seed sample manufacturing data."

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
        self.seed_manufacturing()

    def seed_manufacturing(self):
        items = {i.sku: i for i in Item.objects.filter(sku__in=[d["sku"] for d in SAMPLE_ITEMS])}
        bundle = items["FG-2001"]
        for sku, qty in SAMPLE_BOM:
            ItemComponent.objects.get_or_create(parent=bundle, component=items[sku], defaults={"quantity": qty})

        suppliers = {
            d["code"]: Supplier.objects.get_or_create(code=d["code"], defaults=d)[0] for d in SAMPLE_SUPPLIERS
        }
        customers = {
            d["code"]: Customer.objects.get_or_create(code=d["code"], defaults=d)[0] for d in SAMPLE_CUSTOMERS
        }

        today = date.today()
        po, created = PurchaseOrder.objects.get_or_create(
            po_number="PO-0001",
            defaults={"supplier": suppliers["SUP-001"], "status": PurchaseOrder.Status.SUBMITTED,
                      "order_date": today, "expected_date": today + timedelta(days=10)},
        )
        if created:
            PurchaseOrderLine.objects.create(purchase_order=po, item=items["SKU-1003"], quantity=20, unit_cost="150.00")
            PurchaseOrderLine.objects.create(purchase_order=po, item=items["SKU-1004"], quantity=30, unit_cost="55.00")

        dealer = customers["CUS-001"]
        order, created = Order.objects.get_or_create(
            order_number="SO-0001",
            defaults={"customer": dealer, "status": Order.Status.CONFIRMED, "order_date": today,
                      "requested_date": today + timedelta(days=7), "shipping_address": dealer.shipping_address},
        )
        if created:
            OrderLine.objects.create(order=order, item=bundle, quantity=3, unit_price=bundle.unit_price)
        Shipment.objects.get_or_create(
            shipment_number="SH-0001",
            defaults={"order": order, "carrier": "Yamato", "status": ShippingStatus.SCHEDULED,
                      "scheduled_ship_date": today + timedelta(days=3),
                      "scheduled_delivery_date": today + timedelta(days=5)},
        )
        self.stdout.write(self.style.SUCCESS("Seeded manufacturing sample data (BOM, suppliers, customers, PO, order, shipment)."))
