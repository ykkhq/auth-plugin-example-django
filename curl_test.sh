#!/bin/zsh

MCP=https://localhost:11443/mcp/inventory

# 1. initialize -> note the mcp-session-id response header
curl -D curl_test_headers.txt  -k -i -X POST $MCP \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "apikey: test" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize",
       "params":{"protocolVersion":"2025-06-18","capabilities":{},
                 "clientInfo":{"name":"curl","version":"1.0.0"}}}'

SID=$(cat curl_test_headers.txt | grep mcp-session-id  | sed -E 's/mcp-session-id: (.*)/\1/')

# SID=<mcp-session-id>

H=(-H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
   -H "apikey: test" -H "mcp-session-id: $SID")

# 2. initialized notification
curl -k -X POST $MCP "${H[@]}" -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'

# 3. list tools (expect 6)
curl -k -X POST $MCP "${H[@]}" -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'

# 4. call tools
curl -k -X POST $MCP "${H[@]}" -d '{"jsonrpc":"2.0","id":3,"method":"tools/call",
  "params":{"name":"list-items","arguments":{}}}'

curl -k -X POST $MCP "${H[@]}" -d '{"jsonrpc":"2.0","id":4,"method":"tools/call",
  "params":{"name":"create-item","arguments":{"body":{"name":"Widget","sku":"W-001","unit_price":"9.99","quantity":5}}}}'

curl -k -X POST $MCP "${H[@]}" -d '{"jsonrpc":"2.0","id":5,"method":"tools/call",
  "params":{"name":"patch-item","arguments":{"path_id":1,"body":{"quantity":10}}}}'
