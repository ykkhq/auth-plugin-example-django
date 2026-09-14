from django.contrib import admin

from .models import Item


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ["name", "sku", "category", "quantity", "unit_price", "updated_at"]
    search_fields = ["name", "sku", "category"]
    list_filter = ["category"]
