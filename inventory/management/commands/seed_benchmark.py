import random
from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction

from inventory.models import Customer, Item, Order, OrderLine

DEALERS = [
    "Osaka Office Supply", "Nagoya Workspace", "Fukuoka Desk Center", "Sapporo IT Mart",
    "Sendai Business Gear", "Hiroshima Office Pro", "Kobe Tech Dealer", "Yokohama Desk Shop",
]


class Command(BaseCommand):
    help = (
        "Add bulk sample data for the Code Mode token benchmark (context-mesh/): "
        "8 dealers and 300 sales orders BENCH-0001..0300. Deterministic and idempotent."
    )

    def add_arguments(self, parser):
        parser.add_argument("--orders", type=int, default=300)

    @transaction.atomic
    def handle(self, *args, orders, **options):
        rng = random.Random(42)
        customers = list(Customer.objects.filter(code__in=["CUS-001", "CUS-002"]))
        for i, name in enumerate(DEALERS, start=1):
            customer, _ = Customer.objects.get_or_create(
                code=f"BENCH-C{i:02d}",
                defaults={"name": name, "customer_type": Customer.CustomerType.DEALER,
                          "shipping_address": f"{name}, Japan"},
            )
            customers.append(customer)
        items = list(Item.objects.order_by("sku"))
        if not customers or not items:
            self.stderr.write("Run seed_demo first.")
            return

        statuses = [Order.Status.CONFIRMED, Order.Status.IN_PRODUCTION, Order.Status.SHIPPED, Order.Status.DELIVERED]
        created = 0
        for n in range(1, orders + 1):
            number = f"BENCH-{n:04d}"
            # draw every random value even for existing orders, so reruns stay identical
            customer, status = rng.choice(customers), rng.choice(statuses)
            order_date = date(2026, 1, 1) + timedelta(days=rng.randrange(270))
            lines = [(item, rng.randint(1, 20)) for item in rng.sample(items, rng.randint(1, 3))]
            if Order.objects.filter(order_number=number).exists():
                continue
            order = Order.objects.create(
                order_number=number, customer=customer, status=status, order_date=order_date,
                shipping_address=customer.shipping_address,
            )
            OrderLine.objects.bulk_create(
                [OrderLine(order=order, item=item, quantity=qty, unit_price=item.unit_price) for item, qty in lines]
            )
            created += 1
        self.stdout.write(self.style.SUCCESS(f"Created {created} benchmark order(s) ({orders} total BENCH-*)."))
