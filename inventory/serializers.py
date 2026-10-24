from django.db import transaction
from rest_framework import serializers

from .models import (
    Customer,
    Item,
    ItemComponent,
    Order,
    OrderLine,
    PurchaseOrder,
    PurchaseOrderLine,
    Shipment,
    ShipmentStatusEvent,
    Supplier,
)

TIMESTAMPS = ["id", "created_at", "updated_at"]


class ItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = Item
        fields = [
            "id",
            "name",
            "sku",
            "description",
            "category",
            "item_type",
            "quantity",
            "unit_price",
            "created_at",
            "updated_at",
        ]
        read_only_fields = TIMESTAMPS


class ItemComponentSerializer(serializers.ModelSerializer):
    parent_sku = serializers.CharField(source="parent.sku", read_only=True)
    component_sku = serializers.CharField(source="component.sku", read_only=True)
    component_name = serializers.CharField(source="component.name", read_only=True)

    class Meta:
        model = ItemComponent
        fields = ["id", "parent", "parent_sku", "component", "component_sku", "component_name", "quantity", "notes"]
        read_only_fields = ["id"]

    def validate(self, attrs):
        parent = attrs.get("parent", getattr(self.instance, "parent", None))
        component = attrs.get("component", getattr(self.instance, "component", None))
        if parent and parent == component:
            raise serializers.ValidationError("An item cannot be a component of itself.")
        return attrs


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = [
            "id", "name", "code", "contact_name", "email", "phone", "address",
            "lead_time_days", "is_active", "created_at", "updated_at",
        ]
        read_only_fields = TIMESTAMPS


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = [
            "id", "name", "code", "customer_type", "contact_name", "email", "phone",
            "billing_address", "shipping_address", "credit_limit", "is_active", "created_at", "updated_at",
        ]
        read_only_fields = TIMESTAMPS


# Writable nested `lines`: created with the header; on update, sending `lines`
# replaces them all. (A comment, not a docstring: drf-spectacular would copy a
# docstring into every subclass's schema description.)
class NestedLinesMixin:

    line_model = None
    line_fk = None

    def create(self, validated_data):
        lines = validated_data.pop("lines", [])
        with transaction.atomic():
            obj = super().create(validated_data)
            self._write_lines(obj, lines)
        return obj

    def update(self, instance, validated_data):
        lines = validated_data.pop("lines", None)
        with transaction.atomic():
            obj = super().update(instance, validated_data)
            if lines is not None:
                getattr(obj, "lines").all().delete()
                self._write_lines(obj, lines)
        return obj

    def _write_lines(self, obj, lines):
        self.line_model.objects.bulk_create(
            [self.line_model(**{self.line_fk: obj}, **self.prepare_line(line)) for line in lines]
        )

    def prepare_line(self, line):
        return line


class PurchaseOrderLineSerializer(serializers.ModelSerializer):
    item_sku = serializers.CharField(source="item.sku", read_only=True)

    class Meta:
        model = PurchaseOrderLine
        fields = ["id", "item", "item_sku", "quantity", "unit_cost", "received_quantity"]
        read_only_fields = ["id", "received_quantity"]


class PurchaseOrderSerializer(NestedLinesMixin, serializers.ModelSerializer):
    line_model = PurchaseOrderLine
    line_fk = "purchase_order"

    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    lines = PurchaseOrderLineSerializer(many=True, required=False)
    total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = PurchaseOrder
        fields = [
            "id", "po_number", "supplier", "supplier_name", "status", "order_date", "expected_date",
            "notes", "lines", "total", "created_at", "updated_at",
        ]
        read_only_fields = TIMESTAMPS


class OrderLineSerializer(serializers.ModelSerializer):
    item_sku = serializers.CharField(source="item.sku", read_only=True)
    unit_price = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False,
        help_text="Defaults to the item's current unit_price.",
    )

    class Meta:
        model = OrderLine
        fields = ["id", "item", "item_sku", "quantity", "unit_price"]
        read_only_fields = ["id"]


class OrderSerializer(NestedLinesMixin, serializers.ModelSerializer):
    line_model = OrderLine
    line_fk = "order"

    customer_name = serializers.CharField(source="customer.name", read_only=True)
    lines = OrderLineSerializer(many=True, required=False)
    total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = Order
        fields = [
            "id", "order_number", "customer", "customer_name", "status", "order_date", "requested_date",
            "shipping_address", "notes", "lines", "total", "created_at", "updated_at",
        ]
        read_only_fields = TIMESTAMPS

    def prepare_line(self, line):
        line.setdefault("unit_price", line["item"].unit_price)
        return line

    def create(self, validated_data):
        if not validated_data.get("shipping_address"):
            validated_data["shipping_address"] = validated_data["customer"].shipping_address
        return super().create(validated_data)


class ShipmentStatusEventSerializer(serializers.ModelSerializer):
    shipment_number = serializers.CharField(source="shipment.shipment_number", read_only=True)
    occurred_at = serializers.DateTimeField(required=False, help_text="Defaults to now.")

    class Meta:
        model = ShipmentStatusEvent
        fields = ["id", "shipment", "shipment_number", "status", "location", "note", "occurred_at"]
        read_only_fields = ["id"]


class ShipmentSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.order_number", read_only=True)
    customer_name = serializers.CharField(source="order.customer.name", read_only=True)
    events = ShipmentStatusEventSerializer(many=True, read_only=True)

    class Meta:
        model = Shipment
        fields = [
            "id", "shipment_number", "order", "order_number", "customer_name", "carrier", "tracking_number",
            "status", "scheduled_ship_date", "scheduled_delivery_date", "shipped_at", "delivered_at",
            "events", "created_at", "updated_at",
        ]
        # Status moves only through shipping-statuses, so stock and order stay consistent.
        read_only_fields = TIMESTAMPS + ["status", "shipped_at", "delivered_at"]


class BuildRequestSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=1)


class ReceiptLineSerializer(serializers.Serializer):
    line_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1)


class ReceiveRequestSerializer(serializers.Serializer):
    lines = ReceiptLineSerializer(
        many=True, required=False,
        help_text="Lines to receive. Omit to receive everything outstanding.",
    )


class LoginRequestSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(style={"input_type": "password"})


class LoginResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()
    username = serializers.CharField()


class DetailResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()

