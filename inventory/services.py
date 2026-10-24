"""Stock-moving business operations. Views call these; each runs in one transaction."""

from collections import defaultdict

from django.db import transaction
from django.utils import timezone

from .models import Item, Order, PurchaseOrder, Shipment, ShipmentStatusEvent, ShippingStatus


class StockError(Exception):
    """Not enough stock, or the operation isn't allowed in the current state."""


def _lock_items(item_ids):
    return {i.pk: i for i in Item.objects.select_for_update().filter(pk__in=item_ids)}


def _consume(needed):
    """Atomically subtract {item_id: qty} from stock, or raise StockError naming every short item."""
    items = _lock_items(needed.keys())
    short = [
        f"{items[pk].sku} (need {qty}, have {items[pk].quantity})"
        for pk, qty in needed.items()
        if items[pk].quantity < qty
    ]
    if short:
        raise StockError("Insufficient stock: " + ", ".join(short))
    for pk, qty in needed.items():
        items[pk].quantity -= qty
        items[pk].save(update_fields=["quantity", "updated_at"])


@transaction.atomic
def build_item(item, quantity):
    """Produce `quantity` of `item` by consuming its bill of materials."""
    bom = list(item.components.all())
    if not bom:
        raise StockError(f"{item.sku} has no components (bill of materials is empty).")
    needed = defaultdict(int)
    for row in bom:
        needed[row.component_id] += row.quantity * quantity
    _consume(needed)
    item = Item.objects.select_for_update().get(pk=item.pk)
    item.quantity += quantity
    item.save(update_fields=["quantity", "updated_at"])
    return item


@transaction.atomic
def receive_purchase_order(po, receipts=None):
    """Add received goods to stock. `receipts` is [{line_id, quantity}]; None receives everything outstanding."""
    po = PurchaseOrder.objects.select_for_update().get(pk=po.pk)
    if po.status in (PurchaseOrder.Status.CANCELLED, PurchaseOrder.Status.RECEIVED, PurchaseOrder.Status.DRAFT):
        raise StockError(f"Cannot receive a purchase order in status '{po.status}'.")
    lines = {line.pk: line for line in po.lines.all()}
    if receipts is None:
        receipts = [{"line_id": pk, "quantity": line.outstanding} for pk, line in lines.items() if line.outstanding]
    for r in receipts:
        line = lines.get(r["line_id"])
        if line is None:
            raise StockError(f"Line {r['line_id']} does not belong to {po.po_number}.")
        if r["quantity"] > line.outstanding:
            raise StockError(f"Line {line.pk}: receiving {r['quantity']} exceeds outstanding {line.outstanding}.")
    items = _lock_items([lines[r["line_id"]].item_id for r in receipts])
    for r in receipts:
        line = lines[r["line_id"]]
        line.received_quantity += r["quantity"]
        line.save(update_fields=["received_quantity"])
        item = items[line.item_id]
        item.quantity += r["quantity"]
        item.save(update_fields=["quantity", "updated_at"])
    fully = all(line.outstanding == 0 for line in lines.values())
    po.status = PurchaseOrder.Status.RECEIVED if fully else PurchaseOrder.Status.PARTIALLY_RECEIVED
    po.save(update_fields=["status", "updated_at"])
    return po


@transaction.atomic
def record_shipment_status(shipment, status, location="", note="", occurred_at=None):
    """Append a status event and move the shipment (and its order) along.

    The first move to in_transit ships the goods: order-line quantities are
    deducted from stock and the order becomes `shipped`.
    """
    shipment = Shipment.objects.select_for_update().select_related("order").get(pk=shipment.pk)
    order = shipment.order
    now = occurred_at or timezone.now()
    if status == ShippingStatus.IN_TRANSIT and shipment.shipped_at is None:
        if order.status == Order.Status.CANCELLED:
            raise StockError(f"Order {order.order_number} is cancelled.")
        needed = defaultdict(int)
        for line in order.lines.all():
            needed[line.item_id] += line.quantity
        _consume(needed)
        shipment.shipped_at = now
        order.status = Order.Status.SHIPPED
    elif status == ShippingStatus.DELIVERED:
        if shipment.shipped_at is None:
            raise StockError("Shipment must be in_transit before it can be delivered.")
        shipment.delivered_at = now
        order.status = Order.Status.DELIVERED
    event = ShipmentStatusEvent.objects.create(
        shipment=shipment, status=status, location=location, note=note, occurred_at=now
    )
    shipment.status = status
    shipment.save()
    order.save(update_fields=["status", "updated_at"])
    return event
