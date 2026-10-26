#!/usr/bin/env python
"""Register the AI Gateway MCP servers in the Konnect Catalog (MCP servers).

kongctl doesn't manage Catalog MCP servers yet, so this script does, through
the Konnect API (/v1/mcp-servers). For every server in kong/ai-gateway.yaml it:
  1. creates the Catalog MCP server (same name) if it doesn't exist,
  2. gives it a version with the tools the AI Gateway actually serves
     (tools/list on https://localhost:11443/mcp/mfg/<resource>) and a
     streamable-http remote for that URL. A Catalog MCP server holds one
     immutable version, so when the tools change the entry is recreated,
  3. links it to the AI Gateway MCP server (implementation, once).
The AI Gateway data plane must be running (./start.sh runs this at the end).

    .venv/bin/python kong/catalog_mcp.py           # create / update
    .venv/bin/python kong/catalog_mcp.py --delete  # remove them (./cleanup.sh)
"""
import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
AI_GATEWAY_FILE = ROOT / "kong" / "ai-gateway.yaml"
SPEC_FILE = ROOT / "kong" / "openapi" / "manufacturing-api.yaml"
KONNECT = "https://us.api.konghq.com"
AI_GW_NAME = "django-ai-gw"
PUBLIC_MCP = "https://localhost:11443"
APIKEY = "test"
PAT = Path(os.environ.get("KONNECT_PAT_FILE", Path.home() / ".kong" / "kpat")).read_text().strip()
# The AI Gateway DP serves a self-signed cert on localhost.
INSECURE = ssl._create_unverified_context()


def http(method, url, body=None, headers=None, context=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, context=context, timeout=30) as resp:
            return resp.status, resp.headers, resp.read().decode()
    except urllib.error.HTTPError as err:
        return err.code, err.headers, err.read().decode()


def konnect(method, path, body=None, ok=(200, 201, 204)):
    status, _, text = http(method, KONNECT + path, body, {"Authorization": f"Bearer {PAT}"})
    if status not in ok:
        sys.exit(f"{method} {path} -> {status}: {text}")
    return json.loads(text) if text else None


def live_tools(route_path):
    """tools/list from the AI Gateway MCP server, i.e. exactly what clients see."""
    url = PUBLIC_MCP + route_path
    headers = {"Accept": "application/json, text/event-stream", "apikey": APIKEY,
               "Content-Type": "application/json"}

    def rpc(body, extra=None):
        status, resp_headers, text = http("POST", url, body, {**headers, **(extra or {})}, INSECURE)
        if status >= 400:
            sys.exit(f"MCP {url} -> {status}: {text[:200]} (is the AI Gateway DP running?)")
        return resp_headers, text

    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "catalog_mcp.py", "version": "1.0.0"}}}
    resp_headers, _ = rpc(init)
    session = {"mcp-session-id": resp_headers.get("mcp-session-id", "")}
    rpc({"jsonrpc": "2.0", "method": "notifications/initialized"}, session)
    _, text = rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, session)
    # Streamable HTTP answers either plain JSON or one SSE "data:" line.
    payload = next(line[5:].strip() for line in text.splitlines() if line.startswith("data:")) \
        if "data:" in text else text
    return json.loads(payload)["result"]["tools"]


def catalog_tool(tool):
    """MCP wire format (camelCase) -> Catalog format (snake_case annotations; the
    Catalog rejects a top-level additionalProperties in input_schema)."""
    schema = dict(tool.get("inputSchema") or {"type": "object"})
    schema.pop("additionalProperties", None)
    out = {"name": tool["name"], "description": tool.get("description", ""), "input_schema": schema}
    if tool.get("annotations"):
        snake = lambda k: "".join(f"_{c.lower()}" if c.isupper() else c for c in k)
        out["annotations"] = {snake(k): v for k, v in tool["annotations"].items()}
    return out


def canon(tools):
    """Comparable form: Konnect stores big integers (e.g. maximum: 2**63-1) as floats."""
    return json.dumps(json.loads(json.dumps(sorted(tools, key=lambda t: t["name"])), parse_int=float),
                      sort_keys=True)


def load_servers():
    loader = type("Loader", (yaml.SafeLoader,), {})
    loader.add_constructor("!lookup", lambda load, node: load.construct_mapping(node))
    loader.add_constructor("!env", lambda load, node: load.construct_scalar(node))
    servers = yaml.load(AI_GATEWAY_FILE.read_text(), Loader=loader)["ai_gateway_mcp_servers"]
    # apikey servers only: tools/list here authenticates with the demo key, and the
    # OIDC servers (/mcp-oidc/mfg) offer the same tools behind an Auth0 login
    return [s for s in servers if "mcp-key-auth" in s["access"]["auth_strategies"]]


def list_all(path):
    return konnect("GET", f"{path}?page[size]=100")["data"]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--delete", action="store_true", help="delete the Catalog MCP servers")
    args = ap.parse_args()

    servers = load_servers()
    existing = {s["name"]: s for s in list_all("/v1/mcp-servers")}

    if args.delete:
        for srv in servers:
            if srv["name"] in existing:
                konnect("DELETE", f"/v1/mcp-servers/{existing[srv['name']]['id']}")
                print(f"deleted Catalog MCP server {srv['name']}")
        return

    version = yaml.safe_load(SPEC_FILE.read_text())["info"]["version"]
    ai_gw = next((g for g in list_all("/v1/ai-gateways") if g["name"] == AI_GW_NAME), None)
    if not ai_gw:
        sys.exit(f"AI Gateway {AI_GW_NAME} not found")
    gw_servers = {s["name"]: s["id"] for s in list_all(f"/v1/ai-gateways/{ai_gw['id']}/mcp-servers")}

    for srv in servers:
        name, route = srv["name"], srv["config"]["route"]["paths"][0]
        if name not in gw_servers:
            sys.exit(f"{name} is not on AI Gateway {AI_GW_NAME}; kongctl apply -f kong/ai-gateway.yaml first")
        tools = [catalog_tool(t) for t in live_tools(route)]
        cat, state = existing.get(name), "unchanged"
        if cat:
            versions = list_all(f"/v1/mcp-servers/{cat['id']}/versions")  # includes the tools
            if not versions or canon(versions[0].get("tools") or []) != canon(tools):
                konnect("DELETE", f"/v1/mcp-servers/{cat['id']}")
                cat, state = None, "updated"
        if not cat:
            state = "created" if state == "unchanged" else state
            cat = konnect("POST", "/v1/mcp-servers", {
                "name": name,
                "display_name": srv["display_name"],
                "description": f"{srv['display_name']} REST endpoints as MCP tools ({PUBLIC_MCP}{route}).",
            })
            konnect("POST", f"/v1/mcp-servers/{cat['id']}/versions", {
                "version": version,
                "tools": tools,
                "remotes": [{"type": "streamable-http", "url": PUBLIC_MCP + route}],
                "packages": [], "resources": [], "prompts": [],
            })
        base = f"/v1/mcp-servers/{cat['id']}"

        if not list_all(f"{base}/implementations"):
            konnect("POST", f"{base}/implementations", {"implementation": {
                "type": "ai-gateway",
                "config": {"gateway_control_plane_id": ai_gw["id"], "gateway_mcp_server_id": gw_servers[name]},
            }})
        print(f"{state:9} Catalog MCP server {name}: {len(tools)} tools, version {version}")


if __name__ == "__main__":
    main()
