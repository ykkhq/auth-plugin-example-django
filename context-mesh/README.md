# Kong Context Mesh: Code Mode vs conventional MCP

[Context Mesh](https://developer.konghq.com/context-mesh/) turns the manufacturing
REST API into one **Code Mode** MCP server. Instead of one tool per endpoint (50
tools on 9 AI Gateway servers), the agent gets 4 tools: `list_tools`, `search`,
`get_schema` and `execute`. With `execute` it writes a short Python block that
calls the API operations in a sandbox and returns only the result.

```
                                  ┌──────────── minikube "context-mesh" ────────────┐
Code Mode client --X-Upstream-Api-Key--> Kong 3.16 DP --> mcpserver-* (Code Mode runtime)
 localhost:18080 (port-forward)   │                            │ http (cluster only)  │
                                  │                       mfg-gateway (nginx)       │
                                  └────────────────────────────│─────────────────────┘
                                         https, verified (private CA, SNI host.docker.internal)
                                                               ▼
                       Docker Kong Gateway :8443 /mfg (key-auth + DataKit) --> Django /api

Conventional client --apikey--> AI Gateway :11000 /mcp/mfg/<resource> (9 servers) --> Kong :8443 /mfg --> Django
```

Interactive version with step-by-step playback:
[docs/context-mesh-flow-v4.html](../docs/context-mesh-flow-v4.html)
(earlier version: [v3](../docs/context-mesh-flow-v3.html)).

## Why it looks like this

- **Kubernetes.** Context Mesh MCP servers run only on a control plane that
  Kong Operator provisions, so this uses a separate minikube profile, Kong
  Operator 2.3 (feature gate `mcp-server`) and a new control plane
  `django-context-mesh` (`k8s.yaml`). The Docker-based `django-apigw` is unchanged.
- **Source.** Context Mesh can't use AI Gateway MCP servers as sources, so its
  source is the same public OpenAPI spec the Dev Portal uses
  (`kong/openapi/manufacturing-api.yaml`), with `base_url` set to the bridge below.
- **TLS bridge.** The Code Mode runtime verifies upstream TLS and can't be given
  our private CA. `mfg-gateway.yaml` runs an nginx that is reachable only inside
  the cluster and calls Kong over verified HTTPS, so `/mfg` stays HTTPS-only.
- **Auth.** The client sends `X-Upstream-Api-Key`, and the runtime forwards it as
  the spec's `apikey` header to Kong key-auth (demo key `test`).
- **Access.** The data plane's ingress is a ClusterIP Service reached through
  `kubectl port-forward` on `localhost:18080`, so no `minikube tunnel` or sudo
  is needed.

## Run it

```bash
./start.sh                                  # main demo (Kong GW, AI GW, Django)
context-mesh/setup.sh                       # Context Mesh + benchmark data (300 orders)
python3 context-mesh/compare_tokens.py      # ~2 min, uses your Claude account (~$0.50)
context-mesh/cleanup.sh                     # remove it again
```

`setup.sh` is safe to re-run, and keeps your current kubectl context. Use the
Code Mode server from Claude Code:

```bash
claude mcp add --transport http mfg-codemode http://localhost:18080/mcp/manufacturing \
  --header "X-Upstream-Api-Key: test"
```

## How the comparison works

`compare_tokens.py` runs each task twice with `claude -p`, once per mode, with
the same model, the same short system prompt and the same task. Each run gets:
no built-in tools, no settings, plugins or skills, and only that mode's MCP
servers. Claude Code's MCP tool search is off, so the conventional run sends
all 50 tool definitions, as a plain MCP client would. Each answer is checked
against values computed directly from the REST API. Results go to
`results/latest.md` and `results/<timestamp>.json`. Use `--runs N` to average
several runs.

| Task | What the agent must do |
|---|---|
| baseline | Answer "OK" without calling a tool: cost of the tool definitions alone |
| lookup | Stock of one item |
| multi_step | Check a product's bill of materials against component stock |
| bulk | Top 3 customers by order value across 301 sales orders |

## Results (Sonnet 5.5, one run, 2026-10-16)

| Task | Input tokens, conventional → Code Mode | Output tokens | Turns | Cost (USD) |
|---|---:|---:|---:|---:|
| baseline | 13,886 → 1,947 (−86%) | 4 → 5 | 1 → 1 | 0.0041 → 0.0017 |
| lookup | 28,537 → 11,307 (−60%) | 39 → 239 | 2 → 3 | 0.0099 → 0.0172 |
| multi_step | 43,487 → 13,031 (−70%) | 326 → 326 | 4 → 3 | 0.0172 → 0.0233 |
| bulk | 139,400 → 45,396 (−67%) | 4,263 → 883 | 14 → 5 | 0.3652 → 0.0538 (−85%) |

All 8 answers were correct.

- **Tool definitions.** The 50 conventional tool definitions cost about 12,000
  input tokens more on every model request. An agent that calls tools re-sends
  them on each turn, so this overhead grows with the number of turns.
- **Small tasks.** Code Mode still sends about 60–70% fewer input tokens. It
  spends an extra turn or two discovering tools (`search` / `get_schema`) and
  writing code, which costs output tokens. Output tokens cost more than input
  tokens, and prompt-cache hits differ between runs, so cost per run was
  roughly even or slightly higher on these tasks.
- **Data-heavy task.** Here the gap is largest. The conventional agent pulled
  every order (about 145 KB of JSON) into its context and took 14 turns. Code
  Mode aggregated in the sandbox and returned three rows: −67% input, −79%
  output and −85% cost.
- **Variance.** These are single runs; run `--runs 3` for averages. Cost also
  depends on cache reads (cheap) versus cache writes across runs, so token
  counts are the cleaner signal.
