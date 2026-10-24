---
title: "Manufacturing Developer Portal"
description: "REST APIs and MCP servers for suppliers, production, sales orders and shipping."
---

::page-section
---
full-width: true
---
  ::page-hero
  ---
  full-width: true
  title-tag: "h1"
  title-font-size: "clamp(36px, 5vw, 56px)"
  title-line-height: "clamp(42px, 5vw, 64px)"
  title-font-weight: "600"
  description-font-size: "clamp(16px, 3vw, 22px)"
  description-line-height: "clamp(24px, 3vw, 32px)"
  text-align: "center"
  horizontal-align: "center"
  ---
  #title
  Manufacturing Developer Portal

  #description
  Buy parts from suppliers, build products from their bills of materials, and
  sell and ship to customers and dealers, through one REST API or as MCP tools
  for AI agents.

  #actions
    ::button
    ---
    size: "large"
    to: "/getting-started"
    ---
    Get started
    ::
  ::
::

::page-section
  :::multi-column
  ---
  columns-breakpoints:
    desktop: 3
    laptop: 3
    tablet: 3
    phablet: 1
    mobile: 1
  ---
    ::::card
    #title
    REST API

    #default
    Items and BOMs, suppliers, purchase orders, customers, sales orders,
    shipments and the shipping schedule. OpenAPI reference with try-it.

    #footer
      :::::button
      ---
      to: "/apis"
      appearance: "tertiary"
      padding: "0px"
      ---
      Browse APIs
      :::::
    ::::

    ::::card
    #title
    MCP servers

    #default
    One MCP server per resource on Kong AI Gateway, 50 tools in total, for
    Claude Code and other AI agents.

    #footer
      :::::button
      ---
      to: "/mcp-servers"
      appearance: "tertiary"
      padding: "0px"
      ---
      See MCP servers
      :::::
    ::::

    ::::card
    #title
    Sign up

    #default
    Create a developer account to see the API reference and MCP servers.
    Accounts are approved automatically.

    #footer
      :::::button
      ---
      to: "/register"
      appearance: "tertiary"
      padding: "0px"
      ---
      Create an account
      :::::
    ::::
  :::
::
