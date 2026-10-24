from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.forms import inlineformset_factory
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView
from django_filters import rest_framework as filters
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import generics, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import (
    Customer,
    Item,
    ItemComponent,
    Order,
    PurchaseOrder,
    Shipment,
    ShipmentStatusEvent,
    Supplier,
)
from .serializers import (
    BuildRequestSerializer,
    CustomerSerializer,
    DetailResponseSerializer,
    ItemComponentSerializer,
    ItemSerializer,
    LoginRequestSerializer,
    LoginResponseSerializer,
    OrderSerializer,
    PurchaseOrderSerializer,
    ReceiveRequestSerializer,
    ShipmentSerializer,
    ShipmentStatusEventSerializer,
    SupplierSerializer,
)


def crud_docs(singular, plural, extra=""):
    """Summaries/descriptions for a ModelViewSet; they become the MCP tool descriptions."""
    return extend_schema_view(
        list=extend_schema(summary=f"List {plural}.", description=f"List all {plural}.{extra}"),
        retrieve=extend_schema(summary=f"Get a {singular}.", description=f"Retrieve a single {singular} by its id."),
        create=extend_schema(summary=f"Create a {singular}.", description=f"Create a new {singular}."),
        update=extend_schema(summary=f"Replace a {singular}.", description=f"Replace all fields of an existing {singular} (PUT)."),
        partial_update=extend_schema(summary=f"Update a {singular}.", description=f"Update only the given fields of an existing {singular} (PATCH)."),
        destroy=extend_schema(summary=f"Delete a {singular}.", description=f"Permanently delete a {singular} by its id."),
    )


def conflict(exc):
    return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)


@crud_docs("inventory item (product, component or raw material)", "inventory items", " Filter by item_type or category.")
class ItemViewSet(viewsets.ModelViewSet):
    queryset = Item.objects.all()
    serializer_class = ItemSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["item_type", "category"]

    @extend_schema(
        summary="Build (manufacture) an item from its components.",
        description=(
            "Produce `quantity` units of this item by consuming its bill of materials "
            "(item-components) from stock. All-or-nothing: 409 if any component is short."
        ),
        request=BuildRequestSerializer,
        responses={200: ItemSerializer, 409: DetailResponseSerializer},
    )
    @action(detail=True, methods=["post"])
    def build(self, request, pk=None):
        req = BuildRequestSerializer(data=request.data)
        req.is_valid(raise_exception=True)
        try:
            item = services.build_item(self.get_object(), req.validated_data["quantity"])
        except services.StockError as exc:
            return conflict(exc)
        return Response(ItemSerializer(item).data)


@crud_docs(
    "bill-of-materials row (item component)", "bill-of-materials rows (item components)",
    " Filter by parent to get one product's bill of materials, or by component to see where a part is used.",
)
class ItemComponentViewSet(viewsets.ModelViewSet):
    queryset = ItemComponent.objects.select_related("parent", "component")
    serializer_class = ItemComponentSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["parent", "component"]


@crud_docs("supplier", "suppliers", " Filter by is_active.")
class SupplierViewSet(viewsets.ModelViewSet):
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["is_active"]


@crud_docs("customer or dealer", "customers and dealers", " Filter by customer_type (direct or dealer) or is_active.")
class CustomerViewSet(viewsets.ModelViewSet):
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["customer_type", "is_active"]


@crud_docs(
    "purchase order", "purchase orders",
    " Filter by supplier or status. Create/replace with nested lines; sending lines on update replaces them all.",
)
class PurchaseOrderViewSet(viewsets.ModelViewSet):
    queryset = PurchaseOrder.objects.select_related("supplier").prefetch_related("lines__item")
    serializer_class = PurchaseOrderSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["supplier", "status"]

    @extend_schema(
        summary="Receive goods for a purchase order.",
        description=(
            "Add received quantities to inventory stock and update the purchase order status "
            "(partially_received or received). Omit lines to receive everything outstanding. "
            "The PO must be submitted, confirmed or partially_received."
        ),
        request=ReceiveRequestSerializer,
        responses={200: PurchaseOrderSerializer, 409: DetailResponseSerializer},
    )
    @action(detail=True, methods=["post"])
    def receive(self, request, pk=None):
        req = ReceiveRequestSerializer(data=request.data)
        req.is_valid(raise_exception=True)
        try:
            po = services.receive_purchase_order(self.get_object(), req.validated_data.get("lines"))
        except services.StockError as exc:
            return conflict(exc)
        return Response(PurchaseOrderSerializer(po).data)


@crud_docs(
    "sales order", "sales orders",
    " Filter by customer or status. Create/replace with nested lines; line unit_price defaults to the item price.",
)
class OrderViewSet(viewsets.ModelViewSet):
    queryset = Order.objects.select_related("customer").prefetch_related("lines__item")
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["customer", "status"]

    def _transition(self, allowed, new_status):
        order = self.get_object()
        if order.status not in allowed:
            return conflict(f"Cannot move order from '{order.status}' to '{new_status}'.")
        order.status = new_status
        order.save(update_fields=["status", "updated_at"])
        return Response(OrderSerializer(order).data)

    @extend_schema(
        summary="Confirm a draft sales order.",
        request=None,
        responses={200: OrderSerializer, 409: DetailResponseSerializer},
    )
    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        return self._transition([Order.Status.DRAFT], Order.Status.CONFIRMED)

    @extend_schema(
        summary="Cancel a sales order that has not shipped yet.",
        request=None,
        responses={200: OrderSerializer, 409: DetailResponseSerializer},
    )
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        allowed = [
            Order.Status.DRAFT, Order.Status.CONFIRMED,
            Order.Status.IN_PRODUCTION, Order.Status.READY_TO_SHIP,
        ]
        return self._transition(allowed, Order.Status.CANCELLED)


@crud_docs(
    "shipment", "shipments",
    " Filter by order or status. Status is read-only here: change it by creating a shipping status.",
)
class ShipmentViewSet(viewsets.ModelViewSet):
    queryset = Shipment.objects.select_related("order__customer").prefetch_related("events")
    serializer_class = ShipmentSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["order", "status"]


@extend_schema_view(
    list=extend_schema(
        summary="List shipping status events.",
        description="List shipment status history, newest first. Filter by shipment or status.",
    ),
    retrieve=extend_schema(summary="Get a shipping status event.", description="Retrieve one status event by its id."),
    create=extend_schema(
        summary="Record a new shipping status for a shipment.",
        description=(
            "Append a status event and move the shipment to that status. The first in_transit "
            "deducts the order's line quantities from stock (409 if short) and marks the order "
            "shipped; delivered marks the order delivered."
        ),
        responses={201: ShipmentStatusEventSerializer, 409: DetailResponseSerializer},
    ),
)
class ShippingStatusViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    queryset = ShipmentStatusEvent.objects.select_related("shipment")
    serializer_class = ShipmentStatusEventSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["shipment", "status"]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            event = services.record_shipment_status(
                data["shipment"], data["status"], data.get("location", ""),
                data.get("note", ""), data.get("occurred_at"),
            )
        except services.StockError as exc:
            return conflict(exc)
        return Response(self.get_serializer(event).data, status=status.HTTP_201_CREATED)


class ShippingScheduleFilter(filters.FilterSet):
    ship_from = filters.DateFilter(field_name="scheduled_ship_date", lookup_expr="gte",
                                   help_text="Scheduled ship date on or after (YYYY-MM-DD).")
    ship_to = filters.DateFilter(field_name="scheduled_ship_date", lookup_expr="lte",
                                 help_text="Scheduled ship date on or before (YYYY-MM-DD).")

    class Meta:
        model = Shipment
        fields = ["ship_from", "ship_to", "status", "carrier"]


@extend_schema(
    summary="Get the shipping schedule.",
    description=(
        "Shipments ordered by scheduled ship date. Filter with ship_from / ship_to (dates), "
        "status and carrier. Shipments without a scheduled date are excluded."
    ),
)
class ShippingScheduleView(generics.ListAPIView):
    queryset = (
        Shipment.objects.filter(scheduled_ship_date__isnull=False)
        .select_related("order__customer")
        .prefetch_related("events")
    )
    serializer_class = ShipmentSerializer
    permission_classes = [IsAuthenticated]
    filterset_class = ShippingScheduleFilter


class LoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        request=LoginRequestSerializer,
        responses={200: LoginResponseSerializer, 401: DetailResponseSerializer},
    )
    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")
        user = authenticate(request, username=username, password=password)
        if user is None:
            return Response(
                {"detail": "Invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        login(request, user)
        return Response({"detail": "Logged in.", "username": user.username})


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: DetailResponseSerializer})
    def post(self, request):
        logout(request)
        return Response({"detail": "Logged out."})


ITEM_FORM_FIELDS = ["name", "sku", "description", "category", "quantity", "unit_price"]


class ItemListView(LoginRequiredMixin, ListView):
    model = Item
    template_name = "inventory/item_list.html"
    context_object_name = "items"


# Bill of materials (sub components) edited on the item page; "components" is
# the ItemComponent.parent related_name, so it is also the form prefix.
ComponentFormSet = inlineformset_factory(
    Item, ItemComponent, fk_name="parent", fields=["component", "quantity", "notes"], extra=1,
)


class ItemComponentsMixin:
    """Adds the sub-component formset to the item create/update views."""

    model = Item
    fields = ITEM_FORM_FIELDS
    template_name = "inventory/item_form.html"
    success_url = reverse_lazy("item-list")

    def get_formset(self):
        formset = ComponentFormSet(self.request.POST or None, instance=self.object)
        others = Item.objects.exclude(pk=self.object.pk) if self.object and self.object.pk else Item.objects.all()
        for form in formset.forms + [formset.empty_form]:
            form.fields["component"].queryset = others
        return formset

    def get_context_data(self, **kwargs):
        kwargs.setdefault("formset", self.get_formset())
        return super().get_context_data(**kwargs)

    def form_valid(self, form):
        formset = self.get_formset()
        if not formset.is_valid():
            return self.render_to_response(self.get_context_data(form=form, formset=formset))
        with transaction.atomic():
            self.object = form.save()
            formset.instance = self.object
            formset.save()
        return redirect(self.get_success_url())

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form, formset=self.get_formset()))


class ItemCreateView(LoginRequiredMixin, ItemComponentsMixin, CreateView):
    pass


class ItemUpdateView(LoginRequiredMixin, ItemComponentsMixin, UpdateView):
    pass


class ItemDeleteView(LoginRequiredMixin, DeleteView):
    model = Item
    template_name = "inventory/item_confirm_delete.html"
    success_url = reverse_lazy("item-list")
