from django.contrib import admin

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


class ItemComponentInline(admin.TabularInline):
    model = ItemComponent
    fk_name = "parent"
    extra = 0


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ["name", "sku", "item_type", "category", "quantity", "unit_price", "updated_at"]
    search_fields = ["name", "sku", "category"]
    list_filter = ["item_type", "category"]
    inlines = [ItemComponentInline]


@admin.register(ItemComponent)
class ItemComponentAdmin(admin.ModelAdmin):
    list_display = ["parent", "component", "quantity"]
    search_fields = ["parent__sku", "component__sku"]


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "contact_name", "email", "lead_time_days", "is_active"]
    search_fields = ["name", "code"]
    list_filter = ["is_active"]


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "customer_type", "contact_name", "email", "is_active"]
    search_fields = ["name", "code"]
    list_filter = ["customer_type", "is_active"]


class PurchaseOrderLineInline(admin.TabularInline):
    model = PurchaseOrderLine
    extra = 0


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ["po_number", "supplier", "status", "order_date", "expected_date"]
    search_fields = ["po_number", "supplier__name"]
    list_filter = ["status"]
    inlines = [PurchaseOrderLineInline]


class OrderLineInline(admin.TabularInline):
    model = OrderLine
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ["order_number", "customer", "status", "order_date", "requested_date"]
    search_fields = ["order_number", "customer__name"]
    list_filter = ["status"]
    inlines = [OrderLineInline]


class ShipmentStatusEventInline(admin.TabularInline):
    model = ShipmentStatusEvent
    extra = 0


@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = ["shipment_number", "order", "carrier", "status", "scheduled_ship_date", "scheduled_delivery_date"]
    search_fields = ["shipment_number", "tracking_number", "order__order_number"]
    list_filter = ["status", "carrier"]
    inlines = [ShipmentStatusEventInline]
