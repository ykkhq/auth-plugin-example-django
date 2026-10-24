from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APITestCase

from . import services
from .models import Customer, Item, ItemComponent, Order, Shipment, ShipmentStatusEvent, Supplier


class KongRemoteUserTests(TestCase):
    sub = "auth0|abc123"
    kong = {"x-authenticated-user": sub}

    def test_kong_user_is_logged_in_and_created(self):
        resp = self.client.get("/items/", headers=self.kong)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(get_user_model().objects.filter(username=self.sub).exists())
        self.assertContains(resp, self.sub)
        self.assertContains(resp, 'href="/items/logout"')

    def test_without_header_django_login_is_required(self):
        resp = self.client.get("/items/")
        self.assertRedirects(resp, "/login/?next=/items/", fetch_redirect_response=False)

    def test_header_switches_user(self):
        self.client.get("/items/", headers=self.kong)
        resp = self.client.get("/items/", headers={"x-authenticated-user": "auth0|other"})
        self.assertContains(resp, "auth0|other")

    def csrf_post(self, origin, sku):
        client = self.client_class(enforce_csrf_checks=True)
        client.get("/items/add/", headers=self.kong)
        token = client.cookies["csrftoken"].value
        return client.post(
            "/items/add/",
            {"name": "Widget", "sku": sku, "quantity": 1, "unit_price": "1.00", "csrfmiddlewaretoken": token,
             "components-TOTAL_FORMS": 0, "components-INITIAL_FORMS": 0},
            headers={**self.kong, "origin": origin},
        )

    def test_csrf_accepts_kong_origin(self):
        resp = self.csrf_post("https://localhost:8443", "W-1")
        self.assertRedirects(resp, "/items/", fetch_redirect_response=False)

    def test_csrf_rejects_foreign_origin(self):
        resp = self.csrf_post("https://evil.example", "W-2")
        self.assertEqual(resp.status_code, 403)

    def test_edit_page_adds_edits_and_removes_sub_components(self):
        kit = Item.objects.create(name="Kit", sku="FG-9", unit_price="80.00")
        driver = Item.objects.create(name="Driver", sku="D-1", unit_price="25.00")
        case = Item.objects.create(name="Case", sku="K-1", unit_price="25.00")
        row = ItemComponent.objects.create(parent=kit, component=driver, quantity=1)
        url = f"/items/{kit.pk}/edit/"
        self.assertContains(self.client.get(url, headers=self.kong), "Sub components")
        base = {"name": "Kit", "sku": "FG-9", "quantity": 0, "unit_price": "80.00",
                "components-TOTAL_FORMS": 2, "components-INITIAL_FORMS": 1}
        resp = self.client.post(url, {
            **base,
            "components-0-id": row.pk, "components-0-component": driver.pk, "components-0-quantity": 4,
            "components-1-component": case.pk, "components-1-quantity": 1,
        }, headers=self.kong)
        self.assertRedirects(resp, "/items/", fetch_redirect_response=False)
        self.assertEqual(
            sorted(kit.components.values_list("component__sku", "quantity")), [("D-1", 4), ("K-1", 1)],
        )
        resp = self.client.post(url, {
            **base, "components-TOTAL_FORMS": 1,
            "components-0-id": row.pk, "components-0-component": driver.pk, "components-0-quantity": 4,
            "components-0-DELETE": "on",
        }, headers=self.kong)
        self.assertRedirects(resp, "/items/", fetch_redirect_response=False)
        self.assertFalse(kit.components.filter(component=driver).exists())

    def test_edit_page_rejects_self_as_sub_component(self):
        kit = Item.objects.create(name="Kit", sku="FG-9", unit_price="80.00")
        resp = self.client.post(f"/items/{kit.pk}/edit/", {
            "name": "Kit", "sku": "FG-9", "quantity": 0, "unit_price": "80.00",
            "components-TOTAL_FORMS": 1, "components-INITIAL_FORMS": 0,
            "components-0-component": kit.pk, "components-0-quantity": 1,
        }, headers=self.kong)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(kit.components.exists())


class ManufacturingAPITests(APITestCase):
    def setUp(self):
        self.client.force_authenticate(get_user_model().objects.create_user("api"))
        self.cable = Item.objects.create(name="Cable", sku="C-1", item_type="component", quantity=10, unit_price="2.00")
        self.board = Item.objects.create(name="Board", sku="C-2", item_type="component", quantity=3, unit_price="20.00")
        self.kit = Item.objects.create(name="Kit", sku="FG-1", item_type="finished_good", quantity=0, unit_price="50.00")
        ItemComponent.objects.create(parent=self.kit, component=self.cable, quantity=2)
        ItemComponent.objects.create(parent=self.kit, component=self.board, quantity=1)
        self.supplier = Supplier.objects.create(name="Acme", code="SUP-1")
        self.customer = Customer.objects.create(name="Dealer", code="CUS-1", customer_type="dealer", shipping_address="Tokyo")

    def stock(self, item):
        item.refresh_from_db()
        return item.quantity

    def test_crud_smoke(self):
        for path, payload in [
            ("/api/suppliers/", {"name": "B", "code": "SUP-2"}),
            ("/api/customers/", {"name": "C", "code": "CUS-2", "customer_type": "direct"}),
            ("/api/item-components/", {"parent": self.board.pk, "component": self.cable.pk, "quantity": 4}),
        ]:
            resp = self.client.post(path, payload, format="json")
            self.assertEqual(resp.status_code, 201, resp.data)
            url = f"{path}{resp.data['id']}/"
            self.assertEqual(self.client.patch(url, {}, format="json").status_code, 200)
            self.assertEqual(self.client.get(path).status_code, 200)
            self.assertEqual(self.client.delete(url).status_code, 204)

    def test_bom_rejects_self_reference(self):
        resp = self.client.post("/api/item-components/", {"parent": self.kit.pk, "component": self.kit.pk, "quantity": 1}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_filter_bom_by_parent(self):
        resp = self.client.get(f"/api/item-components/?parent={self.kit.pk}")
        self.assertEqual(len(resp.data), 2)

    def test_build_consumes_components(self):
        resp = self.client.post(f"/api/items/{self.kit.pk}/build/", {"quantity": 3}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["quantity"], 3)
        self.assertEqual((self.stock(self.cable), self.stock(self.board)), (4, 0))

    def test_build_insufficient_stock_changes_nothing(self):
        resp = self.client.post(f"/api/items/{self.kit.pk}/build/", {"quantity": 4}, format="json")
        self.assertEqual(resp.status_code, 409)
        self.assertIn("C-2", resp.data["detail"])
        self.assertEqual((self.stock(self.cable), self.stock(self.board), self.stock(self.kit)), (10, 3, 0))

    def create_po(self):
        resp = self.client.post("/api/purchase-orders/", {
            "po_number": "PO-1", "supplier": self.supplier.pk, "status": "submitted", "order_date": "2026-10-01",
            "lines": [{"item": self.cable.pk, "quantity": 5, "unit_cost": "1.50"},
                      {"item": self.board.pk, "quantity": 2, "unit_cost": "15.00"}],
        }, format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        return resp.data

    def test_purchase_order_nested_and_receive(self):
        po = self.create_po()
        self.assertEqual(po["total"], "37.50")
        first = po["lines"][0]["id"]
        resp = self.client.post(f"/api/purchase-orders/{po['id']}/receive/",
                                {"lines": [{"line_id": first, "quantity": 2}]}, format="json")
        self.assertEqual(resp.data["status"], "partially_received")
        self.assertEqual(self.stock(self.cable), 12)
        resp = self.client.post(f"/api/purchase-orders/{po['id']}/receive/", {}, format="json")
        self.assertEqual(resp.data["status"], "received")
        self.assertEqual((self.stock(self.cable), self.stock(self.board)), (15, 5))
        resp = self.client.post(f"/api/purchase-orders/{po['id']}/receive/", {}, format="json")
        self.assertEqual(resp.status_code, 409)

    def test_receive_over_outstanding_rejected(self):
        po = self.create_po()
        resp = self.client.post(f"/api/purchase-orders/{po['id']}/receive/",
                                {"lines": [{"line_id": po["lines"][0]["id"], "quantity": 6}]}, format="json")
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(self.stock(self.cable), 10)

    def create_order(self, qty):
        resp = self.client.post("/api/orders/", {
            "order_number": "SO-1", "customer": self.customer.pk, "order_date": "2026-10-01",
            "lines": [{"item": self.cable.pk, "quantity": qty}],
        }, format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        return resp.data

    def test_order_defaults_and_line_replace(self):
        order = self.create_order(2)
        self.assertEqual(order["lines"][0]["unit_price"], "2.00")
        self.assertEqual(order["shipping_address"], "Tokyo")
        self.assertEqual(order["total"], "4.00")
        resp = self.client.patch(f"/api/orders/{order['id']}/",
                                 {"lines": [{"item": self.board.pk, "quantity": 1, "unit_price": "18.00"}]}, format="json")
        self.assertEqual([l["item_sku"] for l in resp.data["lines"]], ["C-2"])
        self.assertEqual(resp.data["total"], "18.00")

    def test_order_confirm_and_cancel(self):
        order = self.create_order(1)
        self.assertEqual(self.client.post(f"/api/orders/{order['id']}/confirm/").data["status"], "confirmed")
        self.assertEqual(self.client.post(f"/api/orders/{order['id']}/confirm/").status_code, 409)
        self.assertEqual(self.client.post(f"/api/orders/{order['id']}/cancel/").data["status"], "cancelled")

    def ship(self, order, **extra):
        resp = self.client.post("/api/shipments/", {
            "shipment_number": "SH-1", "order": order["id"], "carrier": "Yamato",
            "scheduled_ship_date": "2026-10-20", **extra}, format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        return resp.data

    def status(self, shipment, value):
        return self.client.post("/api/shipping-statuses/", {"shipment": shipment["id"], "status": value}, format="json")

    def test_shipping_status_moves_stock_and_order(self):
        order = self.create_order(4)
        shipment = self.ship(order, status="delivered")  # status is read-only on shipments
        self.assertEqual(shipment["status"], "pending")
        self.assertEqual(self.status(shipment, "delivered").status_code, 409)
        self.assertEqual(self.status(shipment, "picked").status_code, 201)
        self.assertEqual(self.status(shipment, "in_transit").status_code, 201)
        self.assertEqual(self.stock(self.cable), 6)
        self.assertEqual(self.status(shipment, "in_transit").status_code, 201)  # no double deduction
        self.assertEqual(self.stock(self.cable), 6)
        self.assertEqual(self.client.get(f"/api/orders/{order['id']}/").data["status"], "shipped")
        self.assertEqual(self.status(shipment, "delivered").status_code, 201)
        detail = self.client.get(f"/api/shipments/{shipment['id']}/").data
        self.assertEqual(detail["status"], "delivered")
        self.assertEqual(len(detail["events"]), 4)
        self.assertEqual(self.client.get(f"/api/orders/{order['id']}/").data["status"], "delivered")
        self.assertEqual(len(self.client.get(f"/api/shipping-statuses/?shipment={shipment['id']}").data), 4)

    def test_shipping_insufficient_stock(self):
        shipment = self.ship(self.create_order(11))
        self.assertEqual(self.status(shipment, "in_transit").status_code, 409)
        self.assertEqual(self.stock(self.cable), 10)
        self.assertFalse(ShipmentStatusEvent.objects.exists())

    def test_shipping_schedule_filters(self):
        order = self.create_order(1)
        self.ship(order)
        Shipment.objects.create(shipment_number="SH-2", order=Order.objects.get(pk=order["id"]),
                                scheduled_ship_date="2026-11-05")
        Shipment.objects.create(shipment_number="SH-3", order=Order.objects.get(pk=order["id"]))
        resp = self.client.get("/api/shipping-schedule/")
        self.assertEqual([s["shipment_number"] for s in resp.data], ["SH-1", "SH-2"])
        resp = self.client.get("/api/shipping-schedule/?ship_from=2026-11-01&ship_to=2026-11-30")
        self.assertEqual([s["shipment_number"] for s in resp.data], ["SH-2"])

    def test_requires_authentication(self):
        self.client.force_authenticate(None)
        self.assertIn(self.client.get("/api/orders/").status_code, (401, 403))


class SeedDemoTests(TestCase):
    def test_seed_is_idempotent_and_bundle_is_buildable(self):
        for _ in range(2):
            call_command("seed_demo", stdout=StringIO())
        self.assertEqual(ItemComponent.objects.filter(parent__sku="FG-2001").count(), 5)
        self.assertEqual((Order.objects.count(), Shipment.objects.count()), (1, 1))
        bundle = Item.objects.get(sku="FG-2001")
        self.assertEqual(services.build_item(bundle, 1).quantity, 6)


class KongForwardedTests(TestCase):
    """Kong proxies https://localhost:8443/oidc/mfg/<x> to http://django:3333/api/<x>."""

    def kong(self, public_path, prefix="/oidc/mfg"):
        return {
            "x-forwarded-proto": "https",
            "x-forwarded-host": "localhost",
            "x-forwarded-port": "8443",
            "x-forwarded-prefix": prefix,
            "x-forwarded-path": public_path,
        }

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("api"))

    def test_api_root_links_use_public_url(self):
        resp = self.client.get("/api/", headers=self.kong("/oidc/mfg/"), HTTP_ACCEPT="application/json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["suppliers"], "https://localhost:8443/oidc/mfg/suppliers/")

    def test_append_slash_redirect_keeps_prefix(self):
        resp = self.client.get("/api/orders", headers=self.kong("/oidc/mfg/orders"))
        self.assertRedirects(resp, "/oidc/mfg/orders/", status_code=301, fetch_redirect_response=False)

    def test_prefix_without_trailing_slash_serves_api_root(self):
        resp = self.client.get("/api", headers=self.kong("/oidc/mfg"), HTTP_ACCEPT="application/json")
        self.assertEqual(resp.json()["orders"], "https://localhost:8443/oidc/mfg/orders/")

    def test_apikey_route_and_nested_paths(self):
        Supplier.objects.create(name="Acme", code="SUP-1")
        resp = self.client.get("/api/suppliers/", headers=self.kong("/mfg/suppliers/", prefix="/mfg"),
                               HTTP_ACCEPT="application/json")
        self.assertEqual(resp.json()[0]["code"], "SUP-1")

    def test_browsable_api_breadcrumbs_use_prefix(self):
        resp = self.client.get("/api/suppliers/", headers=self.kong("/oidc/mfg/suppliers/"), HTTP_ACCEPT="text/html")
        self.assertContains(resp, 'href="/oidc/mfg/"')
        self.assertNotContains(resp, 'href="/api/')

    def test_legacy_items_route_untouched(self):
        resp = self.client.get("/api/items/", headers=self.kong("/inventory/", prefix="/inventory"),
                               HTTP_ACCEPT="application/json")
        self.assertEqual(resp.status_code, 200)

    def test_without_kong_headers(self):
        resp = self.client.get("/api/", HTTP_ACCEPT="application/json")
        self.assertEqual(resp.json()["suppliers"], "http://testserver/api/suppliers/")
