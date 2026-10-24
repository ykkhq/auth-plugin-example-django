#!/usr/bin/env python3
"""Compare token usage: conventional MCP (AI Gateway, 9 servers / 50 tools)
vs Code Mode (Context Mesh, 1 server / 4 tools), on the same tasks.

Each run is a headless Claude Code session (`claude -p`, no settings, plugins
or skills) with a tiny system prompt, no built-in tools and only the MCP servers of one mode, so the
token difference comes from the MCP side. MCP tool search is turned off so the
conventional run sends all 50 tool definitions, as a plain MCP client would.

    python3 context-mesh/compare_tokens.py [--model sonnet] [--runs 1] [--tasks baseline,lookup,...]

Needs: the AI Gateway DP (http://localhost:11000/mcp/mfg/<resource>) and the
Context Mesh port-forward (http://localhost:18080/mcp/manufacturing, started by
context-mesh/setup.sh), plus `seed_benchmark` data. Uses your Claude account.
Writes context-mesh/results/<timestamp>.json and context-mesh/results/latest.md.
"""
import argparse
import json
import os
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
RESOURCES = ["items", "item-components", "suppliers", "customers", "purchase-orders",
             "orders", "shipments", "shipping-statuses", "shipping-schedule"]
APIKEY = "test"
REST = "https://localhost:8443/mfg"

MODES = {
    "conventional": {
        "label": "Conventional MCP (AI Gateway, 9 servers / 50 tools)",
        "servers": {f"mfg-{r}": {"type": "http", "url": f"http://localhost:11000/mcp/mfg/{r}",
                                 "headers": {"apikey": APIKEY}} for r in RESOURCES},
    },
    "codemode": {
        "label": "Code Mode (Context Mesh, 1 server / 4 tools)",
        "servers": {"manufacturing": {"type": "http", "url": "http://localhost:18080/mcp/manufacturing",
                                      "headers": {"X-Upstream-Api-Key": APIKEY}}},
    },
}

SYSTEM_PROMPT = (
    "You answer questions about a manufacturing company's data using only the MCP tools "
    "provided. Be concise: give the answer, no explanation of your method."
)

TASKS = {
    "baseline": "Reply with exactly: OK. Do not call any tools.",
    "lookup": "How many units of item SKU-1003 are in stock? Answer with just the number.",
    "multi_step": (
        "Can we build 3 more 'Desk Workstation Bundle' (SKU FG-2001) from current component "
        "stock? Check its bill of materials against component stock. Answer yes or no, and list "
        "any component that is short with the shortfall."
    ),
    "bulk": (
        "Across all sales orders, which 3 customers have the highest total order value "
        "(sum of quantity x unit_price over all order lines)? Give customer name, number of "
        "orders and total value for each."
    ),
}


def rest(path):
    ctx = ssl._create_unverified_context()  # gateway's self-signed cert on localhost
    req = urllib.request.Request(f"{REST}{path}", headers={"apikey": APIKEY, "Accept": "application/json"})
    with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
        return json.load(r)


def expected():
    """Ground truth straight from the REST API, to check each answer."""
    items = {i["id"]: i for i in rest("/items/")}
    by_sku = {i["sku"]: i for i in items.values()}
    bundle = by_sku["FG-2001"]
    short = []
    for row in rest(f"/item-components/?parent={bundle['id']}"):
        need, have = row["quantity"] * 3, items[row["component"]]["quantity"]
        if have < need:
            short.append(f"{row['component_sku']} short {need - have}")
    totals, counts = defaultdict(Decimal), Counter()
    for o in rest("/orders/"):
        counts[o["customer_name"]] += 1
        totals[o["customer_name"]] += Decimal(o["total"])
    top = sorted(totals, key=totals.get, reverse=True)[:3]
    return {
        "baseline": "OK",
        "lookup": str(by_sku["SKU-1003"]["quantity"]),
        "multi_step": "yes" if not short else "no: " + ", ".join(short),
        "bulk": "; ".join(f"{c}: {counts[c]} orders, {totals[c]}" for c in top),
    }


def run(mode, prompt, model, workdir):
    cfg = Path(workdir) / f"mcp-{mode}.json"
    cfg.write_text(json.dumps({"mcpServers": MODES[mode]["servers"]}))
    allowed = [f"mcp__{name}" for name in MODES[mode]["servers"]]
    # not --bare: it ignores the Claude Code login. Settings, plugins and skills are
    # off instead; anything left (e.g. a global CLAUDE.md) is the same for both modes.
    cmd = ["claude", "-p", prompt, "--setting-sources", "", "--disable-slash-commands",
           "--strict-mcp-config", "--mcp-config", str(cfg),
           "--system-prompt", SYSTEM_PROMPT, "--tools", "", "--allowedTools", *allowed,
           "--output-format", "json", "--no-session-persistence", "--max-turns", "30"]
    if model:
        cmd += ["--model", model]
    env = {**os.environ, "ENABLE_TOOL_SEARCH": "false"}  # send every tool definition up front
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=workdir, env=env, timeout=900)
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        sys.exit(f"claude failed ({mode}): {proc.stderr[-2000:] or proc.stdout[-2000:]}")
    u = out.get("usage", {})
    fresh, cw, cr = u.get("input_tokens", 0), u.get("cache_creation_input_tokens", 0), u.get("cache_read_input_tokens", 0)
    return {
        "input_tokens": fresh + cw + cr, "fresh_input": fresh, "cache_write": cw, "cache_read": cr,
        "output_tokens": u.get("output_tokens", 0), "turns": out.get("num_turns"),
        "cost_usd": out.get("total_cost_usd"), "seconds": round(time.time() - t0, 1),
        "is_error": out.get("is_error"), "answer": (out.get("result") or "").strip(),
    }


def report(rows, truth, model):
    lines = [f"# Token usage: conventional MCP vs Code Mode", "",
             f"Run {datetime.now():%Y-%m-%d %H:%M}, model `{model or 'default'}`, "
             "`claude -p` (no settings/plugins/skills, no built-in tools), same system prompt and task per row. Input tokens include cache reads/writes.", "",
             "| Task | Mode | Input tokens | Output tokens | Turns | Cost (USD) | Time (s) |",
             "|---|---|---:|---:|---:|---:|---:|"]
    for r in rows:
        lines.append(f"| {r['task']} | {r['mode']} | {r['input_tokens']:,} | {r['output_tokens']:,} | "
                     f"{r['turns']} | {r['cost_usd'] or 0:.4f} | {r['seconds']} |")
    lines += ["", "## Code Mode vs conventional", "",
              "Conventional → Code Mode; negative % = Code Mode uses less. Cost depends on prompt-cache "
              "hits across runs (cache reads are ~10x cheaper than writes), so token counts are the cleaner signal.", "",
              "| Task | Input tokens | Output tokens | Total tokens | Cost (USD) |", "|---|---:|---:|---:|---:|"]
    by = defaultdict(dict)
    for r in rows:
        by[r["task"]].setdefault(r["mode"], []).append(r)
    avg = lambda rs, k: sum(x[k] or 0 for x in rs) / len(rs)
    for task, modes in by.items():
        if {"conventional", "codemode"} <= modes.keys():
            c, m = modes["conventional"], modes["codemode"]
            pct = lambda k: f"{(avg(m, k) / avg(c, k) - 1) * 100:+.0f}%" if avg(c, k) else "n/a"
            tot = lambda rs: sum(x["input_tokens"] + x["output_tokens"] for x in rs) / len(rs)
            lines.append(f"| {task} | {avg(c, 'input_tokens'):,.0f} → {avg(m, 'input_tokens'):,.0f} ({pct('input_tokens')}) | "
                         f"{avg(c, 'output_tokens'):,.0f} → {avg(m, 'output_tokens'):,.0f} ({pct('output_tokens')}) | "
                         f"{tot(c):,.0f} → {tot(m):,.0f} | {avg(c, 'cost_usd'):.4f} → {avg(m, 'cost_usd'):.4f} ({pct('cost_usd')}) |")
    lines += ["", "## Answers", "", "| Task | Expected (REST API) | Mode | Answer |", "|---|---|---|---|"]
    for r in rows:
        ans = r["answer"].replace("\n", " ").replace("|", "/")[:240]
        lines.append(f"| {r['task']} | {truth[r['task']]} | {r['mode']} | {ans} |")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--tasks", default=",".join(TASKS))
    ap.add_argument("--report", metavar="JSON", help="only rebuild latest.md from a saved results file")
    args = ap.parse_args()
    if args.report:
        saved = json.loads(Path(args.report).read_text())
        (RESULTS / "latest.md").write_text(report(saved["rows"], saved["expected"], saved["model"]))
        print(f"wrote {RESULTS / 'latest.md'}")
        return

    truth = expected()
    rows = []
    with tempfile.TemporaryDirectory(prefix="cm-bench-") as workdir:  # no CLAUDE.md / project settings
        for task in args.tasks.split(","):
            for n in range(args.runs):
                for mode in MODES:
                    r = run(mode, TASKS[task], args.model, workdir)
                    rows.append({"task": task, "mode": mode, "run": n + 1, **r})
                    print(f"{task:10} {mode:12} in={r['input_tokens']:>8,} out={r['output_tokens']:>6,} "
                          f"turns={r['turns']} cost=${r['cost_usd'] or 0:.4f}  {r['answer'][:70]!r}", flush=True)
    RESULTS.mkdir(exist_ok=True)
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    (RESULTS / f"{stamp}.json").write_text(json.dumps({"model": args.model, "expected": truth, "rows": rows}, indent=2))
    (RESULTS / "latest.md").write_text(report(rows, truth, args.model))
    print(f"\nwrote {RESULTS / 'latest.md'}")


if __name__ == "__main__":
    main()
