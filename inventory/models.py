from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models


class Item(models.Model):
    """Product / part master: raw materials, components and finished goods."""

    class ItemType(models.TextChoices):
        RAW_MATERIAL = "raw_material", "Raw material"
        COMPONENT = "component", "Component"
        FINISHED_GOOD = "finished_good", "Finished good"

    name = models.CharField(max_length=200)
    sku = models.CharField(max_length=64, unique=True)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=100, blank=True)
    item_type = models.CharField(max_length=20, choices=ItemType.choices, default=ItemType.FINISHED_GOOD)
    quantity = models.PositiveIntegerField(default=0, validators=[MinValueValidator(0)])
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.sku})"


class ItemComponent(models.Model):
    """Bill of materials row: building one `parent` consumes `quantity` of `component`."""

    parent = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="components")
    component = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="used_in")
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["parent__name", "component__name"]
        constraints = [
            models.UniqueConstraint(fields=["parent", "component"], name="unique_bom_row"),
        ]

    def clean(self):
        if self.parent_id and self.parent_id == self.component_id:
            raise ValidationError("An item cannot be a component of itself.")

    def __str__(self):
        return f"{self.parent.sku} <- {self.quantity} x {self.component.sku}"


class Supplier(models.Model):
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=32, unique=True)
    contact_name = models.CharField(max_length=200, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    address = models.TextField(blank=True)
    lead_time_days = models.PositiveIntegerField(default=7)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})"


class Customer(models.Model):
    class CustomerType(models.TextChoices):
        DIRECT = "direct", "Direct customer"
        DEALER = "dealer", "Dealer"

    name = models.CharField(max_length=200)
    code = models.CharField(max_length=32, unique=True)
    customer_type = models.CharField(max_length=10, choices=CustomerType.choices, default=CustomerType.DIRECT)
    contact_name = models.CharField(max_length=200, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    billing_address = models.TextField(blank=True)
    shipping_address = models.TextField(blank=True)
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})"


class PurchaseOrder(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        CONFIRMED = "confirmed", "Confirmed"
        PARTIALLY_RECEIVED = "partially_received", "Partially received"
        RECEIVED = "received", "Received"
        CANCELLED = "cancelled", "Cancelled"

    po_number = models.CharField(max_length=32, unique=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="purchase_orders")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    order_date = models.DateField()
    expected_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-order_date", "-id"]

    @property
    def total(self):
        return sum((line.quantity * line.unit_cost for line in self.lines.all()), Decimal("0"))

    def __str__(self):
        return self.po_number


class PurchaseOrderLine(models.Model):
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="purchase_order_lines")
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2)
    received_quantity = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["id"]

    @property
    def outstanding(self):
        return self.quantity - self.received_quantity

    def __str__(self):
        return f"{self.purchase_order.po_number}: {self.quantity} x {self.item.sku}"


class Order(models.Model):
    """Sales order from a customer or dealer."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        CONFIRMED = "confirmed", "Confirmed"
        IN_PRODUCTION = "in_production", "In production"
        READY_TO_SHIP = "ready_to_ship", "Ready to ship"
        SHIPPED = "shipped", "Shipped"
        DELIVERED = "delivered", "Delivered"
        CANCELLED = "cancelled", "Cancelled"

    order_number = models.CharField(max_length=32, unique=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="orders")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    order_date = models.DateField()
    requested_date = models.DateField(null=True, blank=True)
    shipping_address = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-order_date", "-id"]

    @property
    def total(self):
        return sum((line.quantity * line.unit_price for line in self.lines.all()), Decimal("0"))

    def __str__(self):
        return self.order_number


class OrderLine(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="order_lines")
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.order.order_number}: {self.quantity} x {self.item.sku}"


class ShippingStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SCHEDULED = "scheduled", "Scheduled"
    PICKED = "picked", "Picked"
    IN_TRANSIT = "in_transit", "In transit"
    DELIVERED = "delivered", "Delivered"
    EXCEPTION = "exception", "Exception"
    RETURNED = "returned", "Returned"


class Shipment(models.Model):
    """Outbound shipment of a whole sales order; its scheduled dates form the shipping schedule."""

    shipment_number = models.CharField(max_length=32, unique=True)
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="shipments")
    carrier = models.CharField(max_length=100, blank=True)
    tracking_number = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=ShippingStatus.choices, default=ShippingStatus.PENDING)
    scheduled_ship_date = models.DateField(null=True, blank=True)
    scheduled_delivery_date = models.DateField(null=True, blank=True)
    shipped_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["scheduled_ship_date", "id"]

    def __str__(self):
        return self.shipment_number


class ShipmentStatusEvent(models.Model):
    """Shipping status history entry; creating one moves the shipment to `status`."""

    shipment = models.ForeignKey(Shipment, on_delete=models.CASCADE, related_name="events")
    status = models.CharField(max_length=20, choices=ShippingStatus.choices)
    location = models.CharField(max_length=200, blank=True)
    note = models.TextField(blank=True)
    occurred_at = models.DateTimeField()

    class Meta:
        ordering = ["-occurred_at", "-id"]

    def __str__(self):
        return f"{self.shipment.shipment_number}: {self.status}"
