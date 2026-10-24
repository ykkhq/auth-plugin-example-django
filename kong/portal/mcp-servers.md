---
title: "MCP servers"
description: "Every manufacturing API resource as an MCP server for AI agents."
---

::page-section
# MCP servers

Every API resource is also an MCP server on Kong AI Gateway, one server per
resource. Each tool calls the matching REST endpoint, so the
[API reference](/apis) documents its inputs and outputs. Connect with the
same `apikey` header as the REST API (demo key: `test`) over streamable HTTP.

| Server | Endpoint | Tools |
|---|---|---|
| [Manufacturing Customers](#customers) | `https://localhost:11443/mcp/mfg/customers` | 6 |
| [Manufacturing Item Components](#item-components) | `https://localhost:11443/mcp/mfg/item-components` | 6 |
| [Manufacturing Items](#items) | `https://localhost:11443/mcp/mfg/items` | 7 |
| [Manufacturing Orders](#orders) | `https://localhost:11443/mcp/mfg/orders` | 8 |
| [Manufacturing Purchase Orders](#purchase-orders) | `https://localhost:11443/mcp/mfg/purchase-orders` | 7 |
| [Manufacturing Shipments](#shipments) | `https://localhost:11443/mcp/mfg/shipments` | 6 |
| [Manufacturing Shipping Schedule](#shipping-schedule) | `https://localhost:11443/mcp/mfg/shipping-schedule` | 1 |
| [Manufacturing Shipping Statuses](#shipping-statuses) | `https://localhost:11443/mcp/mfg/shipping-statuses` | 3 |
| [Manufacturing Suppliers](#suppliers) | `https://localhost:11443/mcp/mfg/suppliers` | 6 |

Add only the servers an agent needs, to keep its tool list small.

## Manufacturing Customers {#customers}

`https://localhost:11443/mcp/mfg/customers`

```bash
claude mcp add --transport http mfg-customers https://localhost:11443/mcp/mfg/customers --header "apikey: test"
```

| Tool | Description |
|---|---|
| `list-customers` | List all customers and dealers. Filter by customer_type (direct or dealer) or is_active. |
| `create-customer` | Create a new customer or dealer. |
| `get-customer` | Retrieve a single customer or dealer by its id. |
| `update-customer` | Replace all fields of an existing customer or dealer (PUT). |
| `patch-customer` | Update only the given fields of an existing customer or dealer (PATCH). |
| `delete-customer` | Permanently delete a customer or dealer by its id. |

## Manufacturing Item Components {#item-components}

`https://localhost:11443/mcp/mfg/item-components`

```bash
claude mcp add --transport http mfg-item-components https://localhost:11443/mcp/mfg/item-components --header "apikey: test"
```

| Tool | Description |
|---|---|
| `list-item-components` | List all bill-of-materials rows (item components). Filter by parent to get one product's bill of materials, or by component to see where a part is used. |
| `create-item-component` | Create a new bill-of-materials row (item component). |
| `get-item-component` | Retrieve a single bill-of-materials row (item component) by its id. |
| `update-item-component` | Replace all fields of an existing bill-of-materials row (item component) (PUT). |
| `patch-item-component` | Update only the given fields of an existing bill-of-materials row (item component) (PATCH). |
| `delete-item-component` | Permanently delete a bill-of-materials row (item component) by its id. |

## Manufacturing Items {#items}

`https://localhost:11443/mcp/mfg/items`

```bash
claude mcp add --transport http mfg-items https://localhost:11443/mcp/mfg/items --header "apikey: test"
```

| Tool | Description |
|---|---|
| `list-items` | List all inventory items. Filter by item_type or category. |
| `create-item` | Create a new inventory item (product, component or raw material). |
| `get-item` | Retrieve a single inventory item (product, component or raw material) by its id. |
| `update-item` | Replace all fields of an existing inventory item (product, component or raw material) (PUT). |
| `patch-item` | Update only the given fields of an existing inventory item (product, component or raw material) (PATCH). |
| `delete-item` | Permanently delete a inventory item (product, component or raw material) by its id. |
| `build-item` | Produce `quantity` units of this item by consuming its bill of materials (item-components) from stock. All-or-nothing: 409 if any component is short. |

## Manufacturing Orders {#orders}

`https://localhost:11443/mcp/mfg/orders`

```bash
claude mcp add --transport http mfg-orders https://localhost:11443/mcp/mfg/orders --header "apikey: test"
```

| Tool | Description |
|---|---|
| `list-orders` | List all sales orders. Filter by customer or status. Create/replace with nested lines; line unit_price defaults to the item price. |
| `create-order` | Create a new sales order. |
| `get-order` | Retrieve a single sales order by its id. |
| `update-order` | Replace all fields of an existing sales order (PUT). |
| `patch-order` | Update only the given fields of an existing sales order (PATCH). |
| `delete-order` | Permanently delete a sales order by its id. |
| `cancel-order` | Cancel a sales order that has not shipped yet. |
| `confirm-order` | Confirm a draft sales order. |

## Manufacturing Purchase Orders {#purchase-orders}

`https://localhost:11443/mcp/mfg/purchase-orders`

```bash
claude mcp add --transport http mfg-purchase-orders https://localhost:11443/mcp/mfg/purchase-orders --header "apikey: test"
```

| Tool | Description |
|---|---|
| `list-purchase-orders` | List all purchase orders. Filter by supplier or status. Create/replace with nested lines; sending lines on update replaces them all. |
| `create-purchase-order` | Create a new purchase order. |
| `get-purchase-order` | Retrieve a single purchase order by its id. |
| `update-purchase-order` | Replace all fields of an existing purchase order (PUT). |
| `patch-purchase-order` | Update only the given fields of an existing purchase order (PATCH). |
| `delete-purchase-order` | Permanently delete a purchase order by its id. |
| `receive-purchase-order` | Add received quantities to inventory stock and update the purchase order status (partially_received or received). Omit lines to receive everything outstanding. The PO must be submitted, confirmed or partially_received. |

## Manufacturing Shipments {#shipments}

`https://localhost:11443/mcp/mfg/shipments`

```bash
claude mcp add --transport http mfg-shipments https://localhost:11443/mcp/mfg/shipments --header "apikey: test"
```

| Tool | Description |
|---|---|
| `list-shipments` | List all shipments. Filter by order or status. Status is read-only here: change it by creating a shipping status. |
| `create-shipment` | Create a new shipment. |
| `get-shipment` | Retrieve a single shipment by its id. |
| `update-shipment` | Replace all fields of an existing shipment (PUT). |
| `patch-shipment` | Update only the given fields of an existing shipment (PATCH). |
| `delete-shipment` | Permanently delete a shipment by its id. |

## Manufacturing Shipping Schedule {#shipping-schedule}

`https://localhost:11443/mcp/mfg/shipping-schedule`

```bash
claude mcp add --transport http mfg-shipping-schedule https://localhost:11443/mcp/mfg/shipping-schedule --header "apikey: test"
```

| Tool | Description |
|---|---|
| `get-shipping-schedule` | Shipments ordered by scheduled ship date. Filter with ship_from / ship_to (dates), status and carrier. Shipments without a scheduled date are excluded. |

## Manufacturing Shipping Statuses {#shipping-statuses}

`https://localhost:11443/mcp/mfg/shipping-statuses`

```bash
claude mcp add --transport http mfg-shipping-statuses https://localhost:11443/mcp/mfg/shipping-statuses --header "apikey: test"
```

| Tool | Description |
|---|---|
| `list-shipping-statuses` | List shipment status history, newest first. Filter by shipment or status. |
| `create-shipping-status` | Append a status event and move the shipment to that status. The first in_transit deducts the order's line quantities from stock (409 if short) and marks the order shipped; delivered marks the order delivered. |
| `get-shipping-status` | Retrieve one status event by its id. |

## Manufacturing Suppliers {#suppliers}

`https://localhost:11443/mcp/mfg/suppliers`

```bash
claude mcp add --transport http mfg-suppliers https://localhost:11443/mcp/mfg/suppliers --header "apikey: test"
```

| Tool | Description |
|---|---|
| `list-suppliers` | List all suppliers. Filter by is_active. |
| `create-supplier` | Create a new supplier. |
| `get-supplier` | Retrieve a single supplier by its id. |
| `update-supplier` | Replace all fields of an existing supplier (PUT). |
| `patch-supplier` | Update only the given fields of an existing supplier (PATCH). |
| `delete-supplier` | Permanently delete a supplier by its id. |

::
