---
title: "Getting started"
description: "Make your first call to the manufacturing API and connect an AI agent."
---

::page-section
# Getting started

## 1. Sign up and log in

[Create an account](/register) and log in. The API reference and the MCP
server list are visible only to logged-in developers.

## 2. Call the REST API

All requests go through Kong at `https://localhost:8443/mfg` with an
`apikey` header. This demo uses the shared key `test`.

```bash
curl -k https://localhost:8443/mfg/items/ -H "apikey: test"
```

Resources: `items`, `item-components` (bills of materials), `suppliers`,
`customers`, `purchase-orders`, `orders`, `shipments`, `shipping-statuses`
and `shipping-schedule`. See the [API reference](/apis) for every operation.
Its **Try it** panel calls the same URL from your browser, so open
`https://localhost:8443` once and accept its self-signed certificate first.

## 3. Typical flow

1. `POST /purchase-orders/` with `lines`, then `POST /purchase-orders/{id}/receive/` to add parts to stock.
2. `POST /items/{id}/build/` to build a product from its bill of materials.
3. `POST /orders/` with `lines` for a customer or dealer, then `POST /orders/{id}/confirm/`.
4. `POST /shipments/`, then `POST /shipping-statuses/` with `in_transit` to ship it (takes the items out of stock) and `delivered` when it arrives.

Stock-moving calls return `409` and change nothing when stock is short.

## 4. Connect an AI agent

Each resource is an MCP server at `https://localhost:11443/mcp/mfg/<resource>`.

```bash
claude mcp add --transport http mfg-orders https://localhost:11443/mcp/mfg/orders --header "apikey: test"
```

See [MCP servers](/mcp-servers) for every server and tool.
::
