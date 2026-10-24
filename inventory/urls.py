from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)
from rest_framework.routers import DefaultRouter

from .views import (
    CustomerViewSet,
    ItemComponentViewSet,
    ItemViewSet,
    LoginView,
    LogoutView,
    OrderViewSet,
    PurchaseOrderViewSet,
    ShipmentViewSet,
    ShippingScheduleView,
    ShippingStatusViewSet,
    SupplierViewSet,
)

router = DefaultRouter()
router.register("items", ItemViewSet, basename="item")
router.register("item-components", ItemComponentViewSet, basename="item-component")
router.register("suppliers", SupplierViewSet, basename="supplier")
router.register("customers", CustomerViewSet, basename="customer")
router.register("purchase-orders", PurchaseOrderViewSet, basename="purchase-order")
router.register("orders", OrderViewSet, basename="order")
router.register("shipments", ShipmentViewSet, basename="shipment")
router.register("shipping-statuses", ShippingStatusViewSet, basename="shipping-status")

urlpatterns = [
    path("auth/login/", LoginView.as_view(), name="api-login"),
    path("auth/logout/", LogoutView.as_view(), name="api-logout"),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("schema/swagger-ui/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("schema/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    path("shipping-schedule/", ShippingScheduleView.as_view(), name="shipping-schedule"),
    path("", include(router.urls)),
]
